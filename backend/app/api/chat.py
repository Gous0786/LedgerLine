"""Chat endpoint consumed by `useChat` on the frontend.

Drives the ADK agent and translates its events into the AI SDK UI Message
Stream. No tools are registered yet -- this is plain conversation.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.agents import runner as agent_runner
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


async def _empty_prompt():
    yield p.start()
    yield p.error("No message text received.")
    yield p.finish(reason="error")


@router.post("/chat")
async def chat(body: ChatRequest, request: Request):
    prompt = _last_user_text(body.messages)
    if not prompt:
        return ui_message_stream(_empty_prompt(), request)

    # The chat id keys the ADK session, so history survives across turns.
    session_id = body.id or "default"

    events = agent_runner.run(session_id, prompt)
    chunks = translate(events, model=agent_runner.active_model())
    return ui_message_stream(chunks, request)
