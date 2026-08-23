"""CSV dataset endpoints.

Listing works against the real schema. Upload/preview land with the ingest
pipeline -- each CSV will be sniffed, typed, and written to its own SQLite
table so no fixed reconciliation schema is imposed.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.db import connection as db

router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.get("")
async def list_datasets() -> list[dict]:
    return await db.run(
        db.query,
        "SELECT id, name, original_name, role, row_count, byte_size, status, created_at "
        "FROM dataset ORDER BY created_at DESC",
    )
