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
from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_db_path: Path | None = None


def configure(db_path: Path) -> None:
    global _db_path
    _db_path = db_path


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


@contextmanager
def cursor():
    """Synchronous connection scope. Use `run()` from async code."""
    conn = _connect()
    try:
        yield conn
    finally:
        conn.close()


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
