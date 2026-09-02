"""ADK `Event` -> AI SDK UI Message Stream chunks.

    ADK event                            UI Message Stream chunk
    -----------------------------------  ---------------------------------------
    content.parts[].text (partial)       text-start / text-delta / text-end
    content.parts[].thought              reasoning-start / reasoning-delta / -end
    content.parts[].function_call        tool-input-start -> tool-input-available
    content.parts[].function_response    tool-output-available
    author                               data-activity
    usage_metadata (+ litellm cost)      data-metrics  (transient)
    error_code / error_message           error

Two details that bite:

*   ADK emits a run of ``partial=True`` events carrying deltas, then a final
    aggregated event holding the *whole* turn. Emitting text from both duplicates
    the reply, so text is streamed only from partials -- and the final event is
    used as a fallback when the model did not stream at all.
*   Block ids must be stable across deltas or the client opens a new bubble per
    chunk, so one id is held open per text/reasoning block and closed at the end.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from app.core import pricing, runlog
from app.streaming import protocol as p

log = logging.getLogger(__name__)


def _explain(exc: BaseException) -> str:
    """Say what happened in words, and say what survived.

    A turn dies with `litellm.MidStreamFallbackError: litellm.Timeout: ...
    OpenrouterException` and the reader concludes the reconciliation failed. It
    did not: matching writes to the database as it goes, so everything the run
    reached is already recorded and only the summary is lost. Saying so is the
    difference between a scare and a retry.
    """
    text = f"{type(exc).__name__}: {exc}"
    lowered = text.lower()
    if "timeout" in lowered or "aborted" in lowered:
        return (
            "The model stopped responding, so this answer is incomplete."
            " Any matching that had already run is saved -- reload the"
            " reconciled panel to see it, or ask again for a summary."
        )
    if "rate" in lowered and "limit" in lowered:
        return "The model provider is rate limiting. Wait a moment and ask again."
    if "api key" in lowered or "401" in lowered or "auth" in lowered:
        return "The model rejected the credentials. Check OPENROUTER_API_KEY."
    return text


async def translate(
    events: AsyncIterator[Any],
    *,
    model: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    started = time.perf_counter()

    text_id: str | None = None
    reasoning_id: str | None = None
    reasoning_open = False
    streamed_text = False
    streamed_reasoning = False
    final_text = ""
    final_reasoning = ""

    # Accumulated so the run log can keep one row per block rather than one per
    # delta. Replaying a turn does not need to re-animate it, and a long reply
    # is hundreds of deltas -- persisting each would make the audit trail cost
    # more than the work it records.
    text_buf: list[str] = []
    reasoning_buf: list[str] = []

    prompt_tokens = 0
    completion_tokens = 0
    model_calls = 0
    counted_events: set[str] = set()
    cached_tokens = 0
    reasoning_tokens = 0
    seen_model = model
    last_author: str | None = None

    yield p.start(message_id=uuid.uuid4().hex)
    yield p.start_step()

    try:
        async for event in events:
            author = getattr(event, "author", None)
            if author and author != last_author:
                last_author = author
                yield p.activity(
                    agent=author, state="thinking", label="generating", id=f"act:{author}"
                )

            if getattr(event, "error_message", None) or getattr(event, "error_code", None):
                detail = str(event.error_message or event.error_code)
                runlog.event("error", {"message": detail}, agent=author)
                yield p.error(detail)
                continue

            usage = getattr(event, "usage_metadata", None)
            # One agent turn makes many model calls -- one per tool round trip --
            # and each reports its own usage. These must be SUMMED: taking the
            # latest reports only the final call and hides the true spend, which
            # is where the cost actually is.
            event_id = str(getattr(event, "id", "") or "")
            if usage is not None and event_id not in counted_events:
                counted_events.add(event_id)
                model_calls += 1
                prompt_tokens += getattr(usage, "prompt_token_count", None) or 0
                completion_tokens += (
                    getattr(usage, "candidates_token_count", None) or 0
                )
                cached_tokens += (
                    getattr(usage, "cached_content_token_count", None) or 0
                )
                reasoning_tokens += (
                    getattr(usage, "thoughts_token_count", None) or 0
                )

            seen_model = getattr(event, "model_version", None) or seen_model

            content = getattr(event, "content", None)
            parts = getattr(content, "parts", None) if content else None
            if not parts:
                continue

            is_partial = bool(getattr(event, "partial", False))

            for part in parts:
                # --- tool calls ---
                call = getattr(part, "function_call", None)
                if call is not None:
                    call_id = getattr(call, "id", None) or uuid.uuid4().hex
                    yield p.tool_input_start(call_id, call.name)
                    yield p.tool_input_available(call_id, call.name, dict(call.args or {}))
                    continue

                response = getattr(part, "function_response", None)
                if response is not None:
                    resp_id = getattr(response, "id", None) or uuid.uuid4().hex
                    yield p.tool_output_available(resp_id, response.response)
                    continue

                text = getattr(part, "text", None)
                if not text:
                    continue

                # --- reasoning ---
                # Same partial-only rule as prose: the final aggregated event
                # repeats the whole thought, which would replay it verbatim.
                if getattr(part, "thought", False):
                    if is_partial:
                        if reasoning_id is None:
                            reasoning_id = uuid.uuid4().hex
                            reasoning_open = True
                            yield p.reasoning_start(reasoning_id)
                        yield p.reasoning_delta(reasoning_id, text)
                        reasoning_buf.append(text)
                        streamed_reasoning = True
                    else:
                        final_reasoning = text
                    continue

                # --- prose ---
                if is_partial:
                    # Thinking is done once prose starts; close it so the UI
                    # settles the block instead of leaving it spinning.
                    if reasoning_open and reasoning_id is not None:
                        yield p.reasoning_end(reasoning_id)
                        runlog.event(
                            "reasoning", {"text": "".join(reasoning_buf)}, agent=author
                        )
                        reasoning_buf.clear()
                        reasoning_open = False
                    if text_id is None:
                        text_id = uuid.uuid4().hex
                        yield p.text_start(text_id)
                    yield p.text_delta(text_id, text)
                    text_buf.append(text)
                    streamed_text = True
                else:
                    # Aggregated final event -- keep it only as a fallback.
                    final_text = text

        # Model returned everything at once: emit the aggregates we held back.
        if not streamed_reasoning and final_reasoning:
            reasoning_id = uuid.uuid4().hex
            yield p.reasoning_start(reasoning_id)
            yield p.reasoning_delta(reasoning_id, final_reasoning)
            yield p.reasoning_end(reasoning_id)
            runlog.event("reasoning", {"text": final_reasoning}, agent=last_author)
            reasoning_open = False
            reasoning_id = None

        if not streamed_text and final_text:
            text_id = uuid.uuid4().hex
            yield p.text_start(text_id)
            yield p.text_delta(text_id, final_text)
            text_buf.append(final_text)

    except Exception as exc:
        log.exception("agent run failed")
        # The raw exception goes to the run log for diagnosis; the reader gets
        # the sentence.
        runlog.event("error", {"message": f"{type(exc).__name__}: {exc}"})
        yield p.error(_explain(exc))

    finally:
        if reasoning_open and reasoning_id is not None:
            yield p.reasoning_end(reasoning_id)
            runlog.event("reasoning", {"text": "".join(reasoning_buf)}, agent=last_author)
        if text_id is not None:
            yield p.text_end(text_id)
            runlog.event("text", {"text": "".join(text_buf)}, agent=last_author)

        if last_author:
            yield p.activity(
                agent=last_author, state="done", label="complete", id=f"act:{last_author}"
            )

        yield p.metrics(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
            reasoning_tokens=reasoning_tokens,
            cost_usd=pricing.cost_usd(
                # configured id first (carries the openrouter/ prefix), then
                # whatever the event reported.
                pricing.candidates(model, seen_model),
                prompt_tokens,
                completion_tokens,
            ),
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            model=seen_model,
            agent=last_author,
            model_calls=model_calls,
        )
        runlog.event(
            "data-metrics",
            {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cached_tokens": cached_tokens,
                "reasoning_tokens": reasoning_tokens,
                "model_calls": model_calls,
                "model": seen_model,
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
            },
            agent=last_author,
        )
        yield p.finish_step()
        yield p.finish(reason="stop")
