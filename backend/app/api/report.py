"""The close report."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.core import report as report_core
from app.db import connection as db

router = APIRouter(prefix="/report", tags=["report"])


@router.get("")
async def close_report() -> dict[str, Any]:
    """Everything the report shows, assembled in one read.

    Not cached: it is asked for rarely and must never be stale, because the
    figure a person signs off has to be the figure that is true now.
    """
    return await db.run(report_core.build)
