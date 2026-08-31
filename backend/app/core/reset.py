"""Wipe everything and start over.

Deliberately thorough: a "fresh session" that leaves stale rows behind is worse
than no reset at all, because the leftovers are invisible until they contaminate
the next run. So this clears reconciliation state, the uploaded data itself, the
generated views, the inferred spine, the stored files, and the agent's own
conversation memory.

Schema and migrations survive -- there is nothing to rebuild.
"""

from __future__ import annotations

import logging
import shutil
from typing import Any

from app.config import get_settings
from app.db import connection as db

log = logging.getLogger(__name__)

# Order matters only for readability; foreign keys cascade the rest.
_TABLES = (
    "verification",
    "match_proposal",   # cascades match_member and match_event
    "rule_trust",
    "pattern",
    "dataset_view",
    "app_setting",      # the declared spine
    "dataset",          # cascades dataset_column
    "run_event",
    "run_metric",
    "run",
)


def reset_session() -> dict[str, Any]:
    """Delete all user data. Returns counts of what was removed."""
    settings = get_settings()

    before = {}
    for t in _TABLES + ("match_member", "match_event", "dataset_column"):
        try:
            before[t] = db.query_one(f"SELECT COUNT(*) AS n FROM {t}")["n"]
        except Exception:
            before[t] = 0

    dropped_tables = 0
    dropped_views = 0
    with db.cursor() as conn:
        conn.execute("BEGIN")
        try:
            for (name,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'view'"
            ).fetchall():
                conn.execute(f'DROP VIEW IF EXISTS "{name}"')
                dropped_views += 1
            for (name,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
                " AND name LIKE 'ds\\_%' ESCAPE '\\'"
            ).fetchall():
                conn.execute(f'DROP TABLE IF EXISTS "{name}"')
                dropped_tables += 1
            for t in _TABLES:
                conn.execute(f"DELETE FROM {t}")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    # The raw uploads are kept for re-ingest and audit, so a reset must take
    # them too or the next upload of the same file collides conceptually.
    files_removed = 0
    upload_dir = settings.upload_dir
    if upload_dir.exists():
        files_removed = sum(1 for p in upload_dir.iterdir() if p.is_file())
        shutil.rmtree(upload_dir, ignore_errors=True)
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Session clearing is async and happens in the API layer.

    log.info(
        "session reset: %d datasets, %d proposals, %d tables, %d views, %d files",
        before.get("dataset", 0), before.get("match_proposal", 0),
        dropped_tables, dropped_views, files_removed,
    )
    return {
        "datasets": before.get("dataset", 0),
        "proposals": before.get("match_proposal", 0),
        "members": before.get("match_member", 0),
        "events": before.get("match_event", 0),
        "rules": before.get("rule_trust", 0),
        "tables_dropped": dropped_tables,
        "views_dropped": dropped_views,
        "files_removed": files_removed,
    }


async def clear_agent_sessions() -> int:
    """Drop the agent's conversation memory.

    Without this the chat still 'remembers' datasets that no longer exist and
    will happily reason about them. Both ADK session methods are coroutines
    despite their annotations.
    """
    try:
        from app.agents import runner as agent_runner

        service = agent_runner._session_service()
        listed = await service.list_sessions(
            app_name=agent_runner.APP_NAME, user_id=agent_runner.USER_ID
        )
        sessions = getattr(listed, "sessions", None) or []
        for s in sessions:
            await service.delete_session(
                app_name=agent_runner.APP_NAME,
                user_id=agent_runner.USER_ID,
                session_id=s.id,
            )
        return len(sessions)
    except Exception:
        log.warning("could not clear agent sessions", exc_info=True)
        return 0
