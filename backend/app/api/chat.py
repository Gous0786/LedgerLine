"""Chat endpoint consumed by `useChat` on the frontend.

Phase 0: emits a scripted stream that exercises every chunk family the real
agent will use -- prose, reasoning, a tool call, agent activity, and a metrics
tick. It is a wiring proof, not a feature; `_scripted_stream` gets replaced by
`translator.translate(runner.run_async(...))` once the ADK tree exists.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.streaming import protocol as p
from app.streaming.sse import ui_message_stream

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


async def _scripted_stream(prompt: str) -> AsyncIterator[dict[str, Any]]:
    started = time.perf_counter()
    text_id = uuid.uuid4().hex
    tool_id = uuid.uuid4().hex

    yield p.start(message_id=uuid.uuid4().hex)
    yield p.start_step()

    yield p.activity(agent="orchestrator", state="started", label="Scaffold check", id="act:0")

    # Reasoning block -- renders as a collapsible thought in the UI.
    reason_id = uuid.uuid4().hex
    yield p.reasoning_start(reason_id)
    for piece in ("No agent is wired yet, ", "so this response is scripted ",
                  "to prove the stream protocol end to end."):
        yield p.reasoning_delta(reason_id, piece)
        await asyncio.sleep(0.05)
    yield p.reasoning_end(reason_id)

    # Tool call -- the shape every real recon tool will use.
    yield p.activity(agent="orchestrator", state="calling-tool", label="ping", id="act:0")
    yield p.tool_input_start(tool_id, "ping")
    yield p.tool_input_available(tool_id, "ping", {"echo": prompt or "(empty)"})
    await asyncio.sleep(0.1)
    yield p.tool_output_available(tool_id, {"ok": True, "echo": prompt or "(empty)"})

    # Prose.
    yield p.text_start(text_id)
    for piece in (
        "Backend, stream protocol and SQLite are up. ",
        "No reconciliation agent is connected yet — ",
        "this reply is scripted.",
    ):
        yield p.text_delta(text_id, piece)
        await asyncio.sleep(0.05)
    yield p.text_end(text_id)

    yield p.activity(agent="orchestrator", state="done", label="Scaffold check", id="act:0")
    yield p.metrics(
        prompt_tokens=0,
        completion_tokens=0,
        cost_usd=0.0,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        model="(none - scaffold)",
        agent="orchestrator",
    )

    yield p.finish_step()
    yield p.finish(reason="stop")


@router.post("/chat")
async def chat(body: ChatRequest, request: Request):
    return ui_message_stream(_scripted_stream(_last_user_text(body.messages)), request)
