"""Chat endpoint consumed by `useChat` on the frontend.

Drives the ADK agent and translates its events into the AI SDK UI Message
Stream. Each request is one turn and one run: `agents.runner.run` opens the run
row before the first event, so everything the turn produces -- tool calls,
proposals, cost -- is attributable to it.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.agents import runner as agent_runner
from app.config import get_settings
from app.core import demo
from app.streaming import protocol as p
from app.streaming.sse import ui_message_stream
from app.streaming.translator import translate

log = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    """Body `useChat` POSTs. `messages` are UIMessages with a `parts` array."""

    id: str | None = None
    messages: list[dict[str, Any]] = []
    trigger: str | None = None
    messageId: str | None = None


def _last_user_text(messages: list[dict[str, Any]]) -> str:
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        return "".join(
            part.get("text", "")
            for part in msg.get("parts", [])
            if part.get("type") == "text"
        ).strip()
    return ""


async def _refuse(message: str):
    yield p.start()
    yield p.error(message)
    yield p.finish(reason="error")


def _visitor(request: Request) -> str:
    # Behind a hosting proxy every request comes from the proxy; the visitor is
    # the first address it forwarded for.
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.post("/chat")
async def chat(body: ChatRequest, request: Request):
    prompt = _last_user_text(body.messages)
    if not prompt:
        return ui_message_stream(_refuse("No message text received."), request)

    # Refused as a stream, not an HTTP error, so the chat panel shows the
    # reason in place of a generic failure.
    if get_settings().demo_mode:
        refused = demo.limiter().check(_visitor(request))
        if refused:
            return ui_message_stream(_refuse(refused), request)

    # The chat id keys the ADK session, so history survives across turns.
    session_id = body.id or "default"

    events = agent_runner.run(session_id, prompt)
    chunks = translate(events, model=agent_runner.active_model())
    return ui_message_stream(chunks, request)
