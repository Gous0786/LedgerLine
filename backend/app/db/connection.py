"""SQLite access layer.

Deliberately no ORM: reconciliation is a SQL-shaped problem and agent tools
will eventually want to issue (guarded) SQL directly against uploaded data.
A thin wrapper keeps that path open.

Every uploaded CSV becomes its own table, so the reconciliation schema stays
open-ended -- sources can be joined in whatever direction a given transaction
flow requires.
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_db_path: Path | None = None

# One connection per thread, reused. Opening a connection is not free -- it
# costs a file open plus four PRAGMA round trips -- and the reconciliation path
# issues thousands of small queries, so per-call connections dominated the
# runtime: 6,168 queries took 34 seconds, almost none of it spent querying.
# Threads are the right scope because FastAPI runs these helpers through
# `asyncio.to_thread` and sqlite3 objects are not safely shared across threads.
_local = threading.local()


def configure(db_path: Path) -> None:
    global _db_path
    _db_path = db_path
    _close_local()


def _close_local() -> None:
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
    _local.conn = None
    _local.path = None


def _connect() -> sqlite3.Connection:
    if _db_path is None:
        raise RuntimeError("db.configure() must be called during app startup")
    conn = sqlite3.connect(_db_path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")       # concurrent readers + one writer
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _connection() -> sqlite3.Connection:
    """This thread's connection, opened once.

    Keyed on the configured path so a reconfigure -- a session reset, or the
    eval harness pointing at a sandbox -- retires the old handle instead of
    quietly reading a database nobody meant to touch.
    """
    conn = getattr(_local, "conn", None)
    if conn is not None and getattr(_local, "path", None) == _db_path:
        return conn
    _close_local()
    conn = _connect()
    _local.conn = conn
    _local.path = _db_path
    return conn


@contextmanager
def cursor():
    """Synchronous connection scope. Use `run()` from async code.

    The connection outlives the block; callers that open a transaction are
    responsible for ending it, as they already were.
    """
    yield _connection()


def query(sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    with cursor() as conn:
        return [dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]


def query_one(sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: Iterable[Any] = ()) -> int:
    with cursor() as conn:
        cur = conn.execute(sql, tuple(params))
        return cur.rowcount


async def run(fn, *args, **kwargs):
    """Run a blocking db helper off the event loop."""
    return await asyncio.to_thread(fn, *args, **kwargs)
