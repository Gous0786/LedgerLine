"""FastAPI plumbing for UI Message Streams."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Request
from fastapi.responses import StreamingResponse

from app.streaming import protocol

log = logging.getLogger(__name__)


async def _wrap(
    chunks: AsyncIterator[dict[str, Any]],
    request: Request | None,
) -> AsyncIterator[str]:
    try:
        async for chunk in chunks:
            if request is not None and await request.is_disconnected():
                log.info("client disconnected, aborting stream")
                break
            yield protocol.encode(chunk)
    except Exception as exc:  # never let a traceback kill the socket silently
        log.exception("stream failed")
        yield protocol.encode(protocol.error(str(exc)))
    finally:
        yield protocol.DONE


def ui_message_stream(
    chunks: AsyncIterator[dict[str, Any]],
    request: Request | None = None,
) -> StreamingResponse:
    """Serve an async chunk iterator as a Vercel AI SDK UI Message Stream."""
    return StreamingResponse(
        _wrap(chunks, request),
        media_type="text/event-stream",
        headers=protocol.UI_MESSAGE_STREAM_HEADERS,
    )
