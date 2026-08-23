"""Forward-only migration runner: applies app/db/migrations/*.sql in order."""

from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path

from app.db import connection as db

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
VERSION_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def migrate() -> list[str]:
    applied: list[str] = []
    with db.cursor() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "  version TEXT PRIMARY KEY,"
            "  applied_at TEXT NOT NULL DEFAULT (datetime('now'))"
            ")"
        )
        done = {r["version"] for r in conn.execute("SELECT version FROM schema_migrations")}

        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = path.stem
            if version in done:
                continue
            if not VERSION_RE.match(version):
                raise ValueError(f"unsafe migration filename: {path.name}")

            # executescript() commits any open transaction before it runs, so
            # BEGIN/COMMIT must live inside the script rather than around it.
            # Recording the version in the same script keeps DDL and bookkeeping
            # atomic.
            script = (
                "BEGIN;\n"
                f"{path.read_text(encoding='utf-8')}\n"
                f"INSERT INTO schema_migrations (version) VALUES ('{version}');\n"
                "COMMIT;"
            )
            try:
                conn.executescript(script)
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.OperationalError:
                    pass  # already rolled back
                log.error("migration %s failed", version)
                raise

            applied.append(version)
            log.info("applied migration %s", version)

    return applied
