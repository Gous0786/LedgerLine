"""What a turn did, recorded while it does it.

`run`, `run_event` and `run_metric` were designed in migration 0001 and then
never written to, which left the system able to say what exists but not what
produced it: `match_proposal.run_id` was always NULL, the Activity replay path
always returned nothing, and cost history died with the browser tab.

A run here is **one agent turn**. That is the unit a person actually asks about
-- "what did that do?" -- and it is what `run_event.seq` was designed to
address, since a reconnecting client resumes from a cursor within one turn.

The id travels in a ContextVar rather than through every signature. Tools are
called deep inside ADK's own call stack, and threading a run id down through the
model's tool schema would put it in front of the model, which has no business
knowing it. `contextvars` copy into `asyncio.to_thread`, so a sync tool sees it
too.
"""

from __future__ import annotations

import contextvars
import json
import logging
import time
import uuid
from typing import Any

from app.db import connection as db

log = logging.getLogger(__name__)

_current_run: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "recon_run_id", default=None
)

# Set by before_model, read by after_model, to turn two callbacks into one
# latency. Same reasoning as above: no signature threading.
_model_started: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "recon_model_started", default=None
)


def current() -> str | None:
    """The run this code is executing inside, if any."""
    return _current_run.get()


def start(title: str, session_id: str | None = None) -> str:
    run_id = uuid.uuid4().hex[:12]
    try:
        db.execute(
            "INSERT INTO run (id, title, status, adk_session_id, started_at)"
            " VALUES (?, ?, 'running', ?, datetime('now'))",
            (run_id, title[:200], session_id),
        )
    except Exception:
        log.warning("could not open run row", exc_info=True)
    _current_run.set(run_id)
    return run_id


def finish(run_id: str | None, status: str = "done", error: str | None = None) -> None:
    if not run_id:
        return
    try:
        db.execute(
            "UPDATE run SET status = ?, error = ?, finished_at = datetime('now')"
            " WHERE id = ?",
            (status, error, run_id),
        )
    except Exception:
        log.warning("could not close run %s", run_id, exc_info=True)
    finally:
        _current_run.set(None)


def event(kind: str, payload: Any, agent: str | None = None,
          run_id: str | None = None) -> None:
    """Append one activity record.

    `seq` is assigned inside the INSERT so it stays gap-free and monotonic
    without a read-then-write race. Recording must never be able to break the
    turn it is recording, so every failure here is swallowed and logged.
    """
    rid = run_id or current()
    if not rid:
        return
    try:
        db.execute(
            "INSERT INTO run_event (run_id, seq, kind, agent, payload_json)"
            " VALUES (?, (SELECT COALESCE(MAX(seq), 0) + 1 FROM run_event"
            "             WHERE run_id = ?), ?, ?, ?)",
            (rid, rid, kind, agent, json.dumps(payload, default=str)),
        )
    except Exception:
        log.debug("could not record run_event %s", kind, exc_info=True)


def model_call_started() -> None:
    _model_started.set(time.perf_counter())


def metric(
    *,
    model: str | None,
    agent: str | None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cached_tokens: int = 0,
    reasoning_tokens: int = 0,
    cost_usd: float = 0.0,
    tool_name: str | None = None,
    latency_ms: int | None = None,
    run_id: str | None = None,
) -> None:
    """One row per model call, which is what makes the cost panel a history."""
    rid = run_id or current()
    if not rid:
        return
    if latency_ms is None:
        started = _model_started.get()
        latency_ms = int((time.perf_counter() - started) * 1000) if started else 0
    try:
        db.execute(
            "INSERT INTO run_metric (run_id, agent, model, tool_name, prompt_tokens,"
            " completion_tokens, cached_tokens, reasoning_tokens, cost_usd, latency_ms)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (rid, agent, model, tool_name, prompt_tokens, completion_tokens,
             cached_tokens, reasoning_tokens, cost_usd, latency_ms),
        )
    except Exception:
        log.debug("could not record run_metric", exc_info=True)
    finally:
        _model_started.set(None)


def totals(run_id: str) -> dict[str, Any]:
    row = db.query_one(
        "SELECT COUNT(*) AS calls,"
        " COALESCE(SUM(prompt_tokens),0) AS prompt_tokens,"
        " COALESCE(SUM(completion_tokens),0) AS completion_tokens,"
        " COALESCE(SUM(cached_tokens),0) AS cached_tokens,"
        " COALESCE(SUM(cost_usd),0) AS cost_usd,"
        " COALESCE(SUM(latency_ms),0) AS latency_ms"
        " FROM run_metric WHERE run_id = ?",
        (run_id,),
    )
    return row or {}
