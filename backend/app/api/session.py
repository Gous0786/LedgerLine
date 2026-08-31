"""Session reset."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.core import reset as reset_core
from app.db import connection as db

router = APIRouter(prefix="/session", tags=["session"])


@router.post("/reset")
async def reset_session() -> dict[str, Any]:
    """Delete all uploaded data, reconciliation state and agent memory."""
    result = await db.run(reset_core.reset_session)
    result["agent_sessions_cleared"] = await reset_core.clear_agent_sessions()
    return result
