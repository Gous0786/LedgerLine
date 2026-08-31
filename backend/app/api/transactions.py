"""End-to-end transaction view.

Grouped by the source that starts a transaction (the spine), which is inferred
rather than configured -- see app/core/spine.py.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.core import spine as spine_mod
from app.core import transactions as tx
from app.db import connection as db

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("")
async def list_transactions() -> dict[str, Any]:
    resolved = await db.run(spine_mod.resolve_spine)
    if not resolved.get("dataset_id"):
        return {"spine": resolved, "transactions": [], "leftovers": [], "counts": {}}
    try:
        result = await db.run(tx.build, resolved["dataset_id"])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    result["spine"] = {**result["spine"], **{k: resolved[k] for k in ("reason", "origin")
                                             if k in resolved}}
    result["counts"] = dict(result["counts"])
    return result


@router.get("/spine")
async def get_spine() -> dict[str, Any]:
    return await db.run(spine_mod.resolve_spine)
