"""FastAPI application host.

The ADK agent runs *in this process* rather than behind a separate
`adk api_server`: one event bus, one SQLite handle, and no cross-process
plumbing between the agent and the stream the UI is reading.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.config import get_settings
from app.db import connection as db
from app.db.migrate import migrate

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    db.configure(settings.db_path)
    applied = migrate()
    log.info("db ready at %s (applied: %s)", settings.db_path, applied or "none")

    if not settings.openrouter_api_key:
        log.warning("OPENROUTER_API_KEY is not set - model calls will fail")

    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Agentic Reconciliation API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        # so the browser can read the stream-protocol marker
        expose_headers=["x-vercel-ai-ui-message-stream"],
    )
    app.include_router(api_router)
    return app


app = create_app()


def main() -> None:
    import uvicorn

    s = get_settings()
    uvicorn.run("app.main:app", host=s.host, port=s.port, reload=True, log_level=s.log_level)


if __name__ == "__main__":
    main()
