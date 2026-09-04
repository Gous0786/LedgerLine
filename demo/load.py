"""Put the app into the exact state the demo script expects.

    cd backend
    uv run python ../demo/load.py              # clean slate, files loaded, nothing matched
    uv run python ../demo/load.py --reconcile  # ...and already reconciled

Wipes every uploaded file, match and message first, so take twelve looks like
take one. Run it through the backend's environment -- it needs those
dependencies -- but from whichever directory you like: `backend/` goes on the
import path below, and settings resolve from an absolute root regardless of
where you started.

Leaving reconciliation *unrun* is the default on purpose: the demo shows the
agent doing it. Use `--reconcile` only to check the end state, or to re-record a
later section without sitting through the turn again.

Refresh the browser afterwards — the frontend caches datasets per session.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

DEMO = Path(__file__).parent / "data"
SOURCES = ("erp_ledger", "gateway_transactions", "bank_statement")

# Running `python ../demo/load.py` puts *this* directory on sys.path, not the
# one you were standing in, so `app` is not importable without saying so.
BACKEND = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


async def main(reconcile: bool) -> int:
    from app.config import get_settings
    from app.core import ingest, reset
    from app.db import connection as db
    from app.db.migrate import migrate

    settings = get_settings()
    db.configure(settings.db_path)
    migrate()

    missing = [n for n in SOURCES if not (DEMO / f"{n}.csv").exists()]
    if missing:
        print(f"missing demo files: {missing}\nrun: python demo/generate.py")
        return 1

    cleared = await db.run(reset.reset_session)
    await reset.clear_agent_sessions()
    print(f"cleared {cleared}")

    def load() -> None:
        for name in SOURCES:
            path = DEMO / f"{name}.csv"
            out = ingest.ingest_csv(path, name=name, original_name=path.name)
            marks = ""
            if out.get("near_duplicate_rows") or out.get("duplicate_rows"):
                marks = (f"  ({out.get('duplicate_rows', 0)} identical,"
                         f" {out.get('near_duplicate_rows', 0)} same-event repeats)")
            print(f"  {name:<24} {out['row_count']:>3} rows"
                  f" x {out['column_count']} cols{marks}")

    await db.run(load)

    if reconcile:
        from app.core import automatch
        out = await db.run(automatch.auto_match_exact)
        print(f"\nreconciled: {out['rules_run']} rules, {out['groups_proposed']} groups")
        for e in out.get("embedded_keys", []):
            print(f"  embedded key: {e['found']}")
        for r in out["results"]:
            print(f"  {r['join']}  ->  {r.get('by_confidence')}")

    print("\nready. refresh the browser.")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--reconcile", action="store_true",
                    help="also run the deterministic pass (the demo normally "
                         "shows the agent doing this)")
    sys.exit(asyncio.run(main(ap.parse_args().reconcile)))
