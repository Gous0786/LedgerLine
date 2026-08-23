"""Reconciliation run endpoints.

Listing and event replay work today; starting a run arrives with the agent.
`GET /runs/{id}/events` is the replay path -- the frontend reconnects with its
last `seq` and gets everything it missed, since every streamed chunk is
persisted to `run_event` before it goes out over the wire.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.db import connection as db

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("")
async def list_runs() -> list[dict]:
    return await db.run(
        db.query,
        "SELECT id, title, status, created_at, started_at, finished_at "
        "FROM run ORDER BY created_at DESC",
    )


@router.get("/{run_id}/events")
async def run_events(run_id: str, after_seq: int = 0, limit: int = 500) -> list[dict]:
    return await db.run(
        db.query,
        "SELECT seq, ts, kind, agent, payload_json FROM run_event "
        "WHERE run_id = ? AND seq > ? ORDER BY seq LIMIT ?",
        (run_id, after_seq, limit),
    )
