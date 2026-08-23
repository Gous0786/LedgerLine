"""Cost / token / latency aggregates for the metrics panel."""

from __future__ import annotations

from fastapi import APIRouter

from app.db import connection as db

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/runs/{run_id}")
async def run_totals(run_id: str) -> dict:
    row = await db.run(
        db.query_one,
        "SELECT COUNT(*) AS calls,"
        "  COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,"
        "  COALESCE(SUM(completion_tokens), 0) AS completion_tokens,"
        "  COALESCE(SUM(cached_tokens), 0) AS cached_tokens,"
        "  COALESCE(SUM(cost_usd), 0) AS cost_usd,"
        "  COALESCE(SUM(latency_ms), 0) AS latency_ms"
        " FROM run_metric WHERE run_id = ?",
        (run_id,),
    )
    return row or {}


@router.get("/runs/{run_id}/by-model")
async def run_by_model(run_id: str) -> list[dict]:
    return await db.run(
        db.query,
        "SELECT model, COUNT(*) AS calls,"
        "  SUM(prompt_tokens) AS prompt_tokens,"
        "  SUM(completion_tokens) AS completion_tokens,"
        "  SUM(cost_usd) AS cost_usd,"
        "  SUM(latency_ms) AS latency_ms"
        " FROM run_metric WHERE run_id = ? GROUP BY model ORDER BY cost_usd DESC",
        (run_id,),
    )
