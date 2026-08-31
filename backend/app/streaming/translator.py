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

from app.streaming import protocol as p

log = logging.getLogger(__name__)


_OPENROUTER_PRICES: dict[str, tuple[float, float]] | None = None


def _openrouter_prices() -> dict[str, tuple[float, float]]:
    """OpenRouter's own price sheet, fetched once per process.

    ADK's usage_metadata carries token counts only -- the cost OpenRouter
    reports is dropped in the LiteLLM mapping -- and LiteLLM's bundled sheet
    lags new models, so anything recent prices at zero. Reading the live sheet
    keeps the meter honest for models LiteLLM has never heard of.
    """
    global _OPENROUTER_PRICES
    if _OPENROUTER_PRICES is not None:
        return _OPENROUTER_PRICES
    prices: dict[str, tuple[float, float]] = {}
    try:
        import json
        import urllib.request

        with urllib.request.urlopen(
            "https://openrouter.ai/api/v1/models", timeout=15
        ) as fh:
            for m in json.load(fh).get("data", []):
                pricing = m.get("pricing") or {}
                try:
                    prices[m["id"]] = (
                        float(pricing.get("prompt") or 0),
                        float(pricing.get("completion") or 0),
                    )
                except (TypeError, ValueError):
                    continue
    except Exception:
        log.debug("could not fetch OpenRouter prices", exc_info=True)
    _OPENROUTER_PRICES = prices
    return prices


def _cost_usd(candidates: list[str], prompt_tokens: int, completion_tokens: int) -> float:
    """Best effort pricing, first candidate that LiteLLM knows wins.

    Events report a bare model_version ("stealth/ox-alpha") while LiteLLM prices
    by routed id ("openrouter/stealth/ox-alpha"), so both are tried. OpenRouter
    also carries models with no price sheet at all -- those cost 0 rather than
    failing the stream.
    """
    if prompt_tokens == 0 and completion_tokens == 0:
        return 0.0

    import litellm

    for model in candidates:
        if not model:
            continue
        try:
            prompt_cost, completion_cost = litellm.cost_per_token(
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
            total = float(prompt_cost + completion_cost)
            if total > 0:
                return total
        except Exception:
            continue

    # LiteLLM did not know it; try OpenRouter's live sheet, which is where the
    # model actually ran.
    sheet = _openrouter_prices()
    for model in candidates:
        if not model:
            continue
        key = model[len("openrouter/"):] if model.startswith("openrouter/") else model
        rate = sheet.get(key)
        if rate:
            return prompt_tokens * rate[0] + completion_tokens * rate[1]

    log.debug("no pricing for any of %s", candidates)
    return 0.0


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
                yield p.error(str(event.error_message or event.error_code))
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
                # --- tool calls (no tools are registered yet; mapped anyway) ---
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
                        reasoning_open = False
                    if text_id is None:
                        text_id = uuid.uuid4().hex
                        yield p.text_start(text_id)
                    yield p.text_delta(text_id, text)
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
            reasoning_open = False
            reasoning_id = None

        if not streamed_text and final_text:
            text_id = uuid.uuid4().hex
            yield p.text_start(text_id)
            yield p.text_delta(text_id, final_text)

    except Exception as exc:
        log.exception("agent run failed")
        yield p.error(f"{type(exc).__name__}: {exc}")

    finally:
        if reasoning_open and reasoning_id is not None:
            yield p.reasoning_end(reasoning_id)
        if text_id is not None:
            yield p.text_end(text_id)

        if last_author:
            yield p.activity(
                agent=last_author, state="done", label="complete", id=f"act:{last_author}"
            )

        yield p.metrics(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
            reasoning_tokens=reasoning_tokens,
            cost_usd=_cost_usd(
                # configured id first (carries the openrouter/ prefix), then
                # whatever the event reported.
                [model or "", seen_model or "", f"openrouter/{seen_model}" if seen_model else ""],
                prompt_tokens,
                completion_tokens,
            ),
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            model=seen_model,
            agent=last_author,
            model_calls=model_calls,
        )
        yield p.finish_step()
        yield p.finish(reason="stop")
