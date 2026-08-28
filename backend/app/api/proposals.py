"""Match proposal endpoints.

Accepting and rejecting live here rather than in the agent's toolset: the
agent proposes, a person decides.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core import matching
from app.db import connection as db

router = APIRouter(prefix="/proposals", tags=["proposals"])
# Separate prefix: /proposals/rules would be swallowed by /proposals/{id}.
rules_router = APIRouter(prefix="/rules", tags=["rules"])

VALID_STATUS = ("pending", "accepted", "rejected", "review_later")


class StatusUpdate(BaseModel):
    status: str
    note: str | None = None


@router.get("/summary")
async def summary() -> dict[str, Any]:
    rows = await db.run(
        db.query,
        "SELECT status, confidence, COUNT(*) AS n FROM match_proposal"
        " GROUP BY status, confidence",
    )
    by_status: dict[str, int] = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + r["n"]
    return {
        "by_status": by_status,
        "detail": rows,
        "needs_review": by_status.get("pending", 0) + by_status.get("review_later", 0),
    }


@router.get("")
async def list_proposals(status: str = "", limit: int = 100) -> list[dict[str, Any]]:
    sql = (
        "SELECT p.id, p.rule, p.tier, p.group_key, p.confidence, p.status,"
        " p.member_count, p.datasets, p.balance_minor, p.description, p.created_at"
        " FROM match_proposal p"
    )
    params: tuple = ()
    if status:
        if status not in VALID_STATUS:
            raise HTTPException(400, f"status must be one of {VALID_STATUS}")
        sql += " WHERE p.status = ?"
        params = (status,)
    sql += " ORDER BY p.id DESC LIMIT ?"

    rows = await db.run(db.query, sql, (*params, max(1, min(limit, 500))))

    names = {
        r["id"]: r["name"] for r in await db.run(db.query, "SELECT id, name FROM dataset")
    }
    for r in rows:
        r["dataset_names"] = [
            names.get(x, x) for x in (r["datasets"] or "").split(",") if x
        ]
    return rows


@router.get("/{proposal_id}")
async def get_proposal(proposal_id: int) -> dict[str, Any]:
    try:
        return await db.run(matching.get_proposal, proposal_id)
    except matching.MatchError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/{proposal_id}/status")
async def set_status(proposal_id: int, body: StatusUpdate) -> dict[str, Any]:
    if body.status not in VALID_STATUS:
        raise HTTPException(400, f"status must be one of {VALID_STATUS}")
    try:
        return await db.run(
            matching.set_status, proposal_id, body.status, "human", body.note
        )
    except matching.MatchError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/{proposal_id}/events")
async def get_events(proposal_id: int) -> list[dict[str, Any]]:
    return await db.run(
        db.query,
        "SELECT ts, kind, actor, detail FROM match_event"
        " WHERE proposal_id = ? ORDER BY id",
        (proposal_id,),
    )


class TrustUpdate(BaseModel):
    note: str | None = None


@rules_router.get("")
async def list_rules() -> list[dict[str, Any]]:
    """Rules the agent has used, and whether they are approved."""
    return await db.run(matching.list_rules)


@rules_router.post("/{rule}/trust")
async def trust_rule(rule: str, body: TrustUpdate) -> dict[str, Any]:
    """Approve a rule. Releases the exact matches it is holding; ambiguous and
    unbalanced ones still need individual review."""
    try:
        return await db.run(matching.trust_rule, rule, "human", body.note)
    except matching.MatchError as exc:
        raise HTTPException(404, str(exc)) from exc
