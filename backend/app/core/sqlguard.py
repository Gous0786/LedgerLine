"""Guarded read-only SQL for the agent.

The agent writes real SQL -- that is the whole point, since tiered set-based
matching cannot be expressed through fixed parameters. So the safety has to be
structural rather than a prompt instruction:

*   a genuinely read-only connection (``mode=ro``), so a write is refused by
    SQLite itself even if every check below were bypassed;
*   one statement only, and it must be a SELECT/WITH;
*   a wall-clock interrupt, so a runaway cartesian join cannot hang the server;
*   a hard row cap, so a bad join cannot flood the response.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

MAX_ROWS = 50          # rows returned inline to the agent
HARD_ROW_CAP = 10_000  # rows we will even read from a cursor
TIMEOUT_S = 15.0

_COMMENT_RE = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|pragma|"
    r"vacuum|reindex|analyze|begin|commit|rollback)\b",
    re.IGNORECASE,
)


class SqlError(Exception):
    pass


def _strip(sql: str) -> str:
    return _COMMENT_RE.sub(" ", sql).strip().rstrip(";").strip()


def validate(sql: str) -> str:
    """Return the cleaned statement, or raise SqlError."""
    bare = _strip(sql)
    if not bare:
        raise SqlError("empty query")
    if ";" in bare:
        raise SqlError("only one statement is allowed")
    if not re.match(r"^(select|with)\b", bare, re.IGNORECASE):
        raise SqlError("only SELECT / WITH queries are allowed")
    hit = _FORBIDDEN.search(bare)
    if hit:
        raise SqlError(f"'{hit.group(0)}' is not allowed in a read-only query")
    return bare


def _readonly_connection(db_path: Path) -> sqlite3.Connection:
    # as_uri() handles spaces in the path (this repo has one).
    uri = f"{db_path.as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _arm_timeout(conn: sqlite3.Connection, seconds: float) -> None:
    deadline = time.monotonic() + seconds

    def handler() -> int:
        return 1 if time.monotonic() > deadline else 0

    # called every N vm steps; small enough to interrupt tight loops
    conn.set_progress_handler(handler, 2000)


def select(
    db_path: Path,
    sql: str,
    *,
    limit: int = MAX_ROWS,
    timeout: float = TIMEOUT_S,
) -> dict[str, Any]:
    """Run a validated read-only SELECT.

    Returns columns, up to `limit` rows, and whether more exist. Never returns
    the full result set -- bulk rows belong in the UI, not in the agent's
    context.
    """
    bare = validate(sql)
    limit = max(1, min(limit, MAX_ROWS))

    conn = _readonly_connection(db_path)
    try:
        _arm_timeout(conn, timeout)
        started = time.perf_counter()
        try:
            cur = conn.execute(bare)
        except sqlite3.OperationalError as exc:
            if "interrupted" in str(exc).lower():
                raise SqlError(f"query exceeded {timeout:.0f}s and was cancelled") from exc
            raise SqlError(str(exc)) from exc

        columns = [d[0] for d in cur.description] if cur.description else []
        rows: list[dict[str, Any]] = []
        truncated = False
        for i, row in enumerate(cur):
            if i >= HARD_ROW_CAP:
                truncated = True
                break
            if i < limit:
                rows.append(dict(row))
            else:
                truncated = True
                # keep counting a little to report scale, but stop early
                if i > limit + 5000:
                    break
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        return {
            "columns": columns,
            "rows": rows,
            "returned": len(rows),
            "more_rows_exist": truncated,
            "elapsed_ms": elapsed_ms,
        }
    finally:
        conn.close()


def select_all(
    db_path: Path,
    sql: str,
    *,
    timeout: float = TIMEOUT_S,
    cap: int = HARD_ROW_CAP,
) -> list[dict[str, Any]]:
    """Full result set, for internal engines (never handed to the agent)."""
    bare = validate(sql)
    conn = _readonly_connection(db_path)
    try:
        _arm_timeout(conn, timeout)
        try:
            cur = conn.execute(bare)
        except sqlite3.OperationalError as exc:
            if "interrupted" in str(exc).lower():
                raise SqlError(f"query exceeded {timeout:.0f}s and was cancelled") from exc
            raise SqlError(str(exc)) from exc

        out = []
        for i, row in enumerate(cur):
            if i >= cap:
                raise SqlError(f"query returned more than {cap} rows; narrow it")
            out.append(dict(row))
        return out
    finally:
        conn.close()
