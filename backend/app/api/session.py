"""Session reset."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.config import get_settings
from app.core import demo
from app.core import reset as reset_core
from app.db import connection as db

router = APIRouter(prefix="/session", tags=["session"])


@router.post("/reset")
async def reset_session() -> dict[str, Any]:
    """Delete all uploaded data, reconciliation state and agent memory."""
    result = await db.run(reset_core.reset_session)
    result["agent_sessions_cleared"] = await reset_core.clear_agent_sessions()
    # A public demo must never be left empty for the next visitor.
    if get_settings().demo_mode:
        result["demo_files_loaded"] = await db.run(demo.ensure_loaded)
    return result
