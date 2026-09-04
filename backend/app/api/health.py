from __future__ import annotations

from fastapi import APIRouter

from app.config import get_settings
from app.db import connection as db

router = APIRouter(tags=["system"])


@router.get("/health")
async def health() -> dict:
    s = get_settings()
    versions = await db.run(db.query_one, "SELECT max(version) AS v FROM schema_migrations")
    return {
        "status": "ok",
        "db": str(s.db_path),
        "schema_version": (versions or {}).get("v"),
        "openrouter_key_present": bool(s.openrouter_api_key),
        "model": s.model_orchestrator,
    }
