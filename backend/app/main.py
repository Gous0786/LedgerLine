"""FastAPI application host.

The ADK agent runs *in this process* rather than behind a separate
`adk api_server`: one event bus, one SQLite handle, and no cross-process
plumbing between the agent and the stream the UI is reading.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.api import api_router
from app.config import get_settings
from app.core import demo, duplicates
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

    # Files uploaded before duplicate marking existed carry no marks. Backfill
    # them once here rather than making every later read wonder whether the
    # answer is "none" or "never looked".
    await db.run(duplicates.scan_missing)

    if not settings.openrouter_api_key:
        log.warning("OPENROUTER_API_KEY is not set - model calls will fail")

    if settings.demo_mode:
        await db.run(demo.ensure_loaded)

    yield


def _serve_frontend(app: FastAPI, dist: Path) -> None:
    """Serve the built single-page app, sending unknown paths to index.html.

    The app routes on the client (`/upload`, `/report`), so a refresh on one of
    those paths has to return the page, not a 404. Paths under /api never fall
    through to it: a mistyped API call should fail as an API call.
    """
    index = dist / "index.html"
    root = dist.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404)
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(index)


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
    # Registered last: its catch-all route must not shadow the API.
    if (settings.frontend_dist / "index.html").is_file():
        _serve_frontend(app, settings.frontend_dist)
    return app


app = create_app()


def main() -> None:
    import uvicorn

    s = get_settings()
    uvicorn.run("app.main:app", host=s.host, port=s.port, reload=True, log_level=s.log_level)


if __name__ == "__main__":
    main()
