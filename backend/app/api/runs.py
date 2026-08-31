"""Reconciliation run endpoints.

A run is one agent turn. It is opened by `agents/runner.run` and recorded by
`core/runlog`, so listing a run and replaying what it did both work off the same
rows the turn wrote as it went.

`GET /runs/{id}/events` is the replay path: the frontend reconnects with its
last `seq` and gets everything after it. What is persisted is one row per
*semantic* event -- each tool call with its arguments and full result, each
prose or reasoning block, errors, and the turn's metrics -- not one row per
streamed delta. Replay reconstructs what happened; it does not re-animate the
typing.
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
