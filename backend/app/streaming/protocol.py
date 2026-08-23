"""Vercel AI SDK **UI Message Stream** protocol (v1), server side.

Verified against `ai@7.0.77` / `@ai-sdk/react@4.0.80`.

Wire format is SSE: every chunk is one `data: <json>\n\n` frame, and the stream
is terminated by a literal `data: [DONE]\n\n`. The response MUST carry
`x-vercel-ai-ui-message-stream: v1` or the client refuses to parse it.

Two families of chunk matter to us:

*   **native** -- `text-*`, `reasoning-*`, `tool-*`. `useChat` renders these into
    `message.parts` with first-class semantics, so agent prose, chain-of-thought
    and tool calls should use these rather than bespoke events.
*   **custom data** -- `data-<name>`, carrying an arbitrary JSON `data` payload.
    This is where anything the SDK has no concept of goes: which ADK sub-agent
    is active, run progress, and the cost/token/latency meter.

    A data part with `transient=True` is delivered to `onData` but is *not*
    appended to the message -- correct for high-frequency meter ticks that
    should not bloat conversation history. Reusing an `id` on a non-transient
    data part overwrites that part instead of appending, which is how a single
    live-updating status row is done.
"""

from __future__ import annotations

import json
from typing import Any, Literal

# Exact header set the SDK itself sends (ui-message-stream-headers.ts).
UI_MESSAGE_STREAM_HEADERS: dict[str, str] = {
    "content-type": "text/event-stream",
    "cache-control": "no-cache",
    "connection": "keep-alive",
    "x-vercel-ai-ui-message-stream": "v1",
    "x-accel-buffering": "no",  # stop nginx from buffering the stream
}

DONE = "data: [DONE]\n\n"


def encode(chunk: dict[str, Any]) -> str:
    """Serialise one chunk as an SSE frame."""
    return f"data: {json.dumps(chunk, separators=(',', ':'), default=str)}\n\n"


# --------------------------------------------------------------- lifecycle --

def start(message_id: str | None = None, metadata: Any = None) -> dict[str, Any]:
    c: dict[str, Any] = {"type": "start"}
    if message_id is not None:
        c["messageId"] = message_id
    if metadata is not None:
        c["messageMetadata"] = metadata
    return c


def finish(reason: str | None = None, metadata: Any = None) -> dict[str, Any]:
    c: dict[str, Any] = {"type": "finish"}
    if reason is not None:
        c["finishReason"] = reason
    if metadata is not None:
        c["messageMetadata"] = metadata
    return c


def start_step() -> dict[str, Any]:
    return {"type": "start-step"}


def finish_step() -> dict[str, Any]:
    return {"type": "finish-step"}


def abort() -> dict[str, Any]:
    return {"type": "abort"}


def error(text: str) -> dict[str, Any]:
    return {"type": "error", "errorText": text}


# -------------------------------------------------------------------- text --

def text_start(id: str) -> dict[str, Any]:
    return {"type": "text-start", "id": id}


def text_delta(id: str, delta: str) -> dict[str, Any]:
    return {"type": "text-delta", "id": id, "delta": delta}


def text_end(id: str) -> dict[str, Any]:
    return {"type": "text-end", "id": id}


# --------------------------------------------------------------- reasoning --

def reasoning_start(id: str) -> dict[str, Any]:
    return {"type": "reasoning-start", "id": id}


def reasoning_delta(id: str, delta: str) -> dict[str, Any]:
    return {"type": "reasoning-delta", "id": id, "delta": delta}


def reasoning_end(id: str) -> dict[str, Any]:
    return {"type": "reasoning-end", "id": id}


# ------------------------------------------------------------------- tools --

def tool_input_start(tool_call_id: str, tool_name: str, title: str | None = None) -> dict[str, Any]:
    c: dict[str, Any] = {
        "type": "tool-input-start",
        "toolCallId": tool_call_id,
        "toolName": tool_name,
    }
    if title:
        c["title"] = title
    return c


def tool_input_delta(tool_call_id: str, delta: str) -> dict[str, Any]:
    return {"type": "tool-input-delta", "toolCallId": tool_call_id, "inputTextDelta": delta}


def tool_input_available(
    tool_call_id: str, tool_name: str, input: Any, title: str | None = None
) -> dict[str, Any]:
    c: dict[str, Any] = {
        "type": "tool-input-available",
        "toolCallId": tool_call_id,
        "toolName": tool_name,
        "input": input,
    }
    if title:
        c["title"] = title
    return c


def tool_output_available(
    tool_call_id: str, output: Any, preliminary: bool = False
) -> dict[str, Any]:
    c: dict[str, Any] = {
        "type": "tool-output-available",
        "toolCallId": tool_call_id,
        "output": output,
    }
    if preliminary:
        c["preliminary"] = True
    return c


def tool_output_error(tool_call_id: str, error_text: str) -> dict[str, Any]:
    return {"type": "tool-output-error", "toolCallId": tool_call_id, "errorText": error_text}


# ------------------------------------------------------- custom data parts --
#
# Names below are the contract with the frontend -- keep them in sync with
# `frontend/src/types/stream.ts`. A `data-<name>` chunk arrives client-side as
# a part of type `data-<name>` (and in `onData`).

DataName = Literal["activity", "metrics", "run", "dataset"]


def data(name: DataName | str, payload: Any, *, id: str | None = None,
         transient: bool = False) -> dict[str, Any]:
    c: dict[str, Any] = {"type": f"data-{name}", "data": payload}
    if id is not None:
        c["id"] = id
    if transient:
        c["transient"] = True
    return c


def activity(
    *,
    agent: str,
    state: Literal["started", "thinking", "calling-tool", "waiting", "done", "failed"],
    label: str,
    detail: Any = None,
    id: str | None = None,
) -> dict[str, Any]:
    """Which agent is doing what, right now. Drives the Activity feed."""
    return data(
        "activity",
        {"agent": agent, "state": state, "label": label, "detail": detail},
        id=id,
    )


def metrics(
    *,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cached_tokens: int = 0,
    reasoning_tokens: int = 0,
    cost_usd: float = 0.0,
    elapsed_ms: int = 0,
    model: str | None = None,
    agent: str | None = None,
    transient: bool = True,
) -> dict[str, Any]:
    """Cost / tokens / time. Transient by default -- meter ticks are not history."""
    return data(
        "metrics",
        {
            "promptTokens": prompt_tokens,
            "completionTokens": completion_tokens,
            "cachedTokens": cached_tokens,
            "reasoningTokens": reasoning_tokens,
            "totalTokens": prompt_tokens + completion_tokens,
            "costUsd": cost_usd,
            "elapsedMs": elapsed_ms,
            "model": model,
            "agent": agent,
        },
        transient=transient,
    )


def run_progress(
    *, run_id: str, stage: str, pct: float | None = None, status: str = "running"
) -> dict[str, Any]:
    return data(
        "run",
        {"runId": run_id, "stage": stage, "pct": pct, "status": status},
        id=f"run:{run_id}",  # stable id -> the part updates in place
    )
