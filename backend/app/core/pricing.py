"""What a model call cost.

Lifted out of the translator because two callers now need the same number: the
live meter the UI reads, and the `run_metric` row the callbacks persist. A cost
that differs between the two would be worse than no cost at all.

ADK's `usage_metadata` carries token counts only -- the cost OpenRouter reports
is dropped in the LiteLLM mapping -- and LiteLLM's bundled price sheet lags new
models, so anything recent prices at zero. The live sheet is the fallback.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

_OPENROUTER_PRICES: dict[str, tuple[float, float]] | None = None


def openrouter_prices() -> dict[str, tuple[float, float]]:
    """OpenRouter's own price sheet, fetched once per process."""
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


def cost_usd(candidates: list[str], prompt_tokens: int, completion_tokens: int) -> float:
    """Best effort pricing; the first candidate LiteLLM knows wins.

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
    sheet = openrouter_prices()
    for model in candidates:
        if not model:
            continue
        key = model[len("openrouter/"):] if model.startswith("openrouter/") else model
        rate = sheet.get(key)
        if rate:
            return prompt_tokens * rate[0] + completion_tokens * rate[1]

    log.debug("no pricing for any of %s", candidates)
    return 0.0


def candidates(configured: str | None, reported: str | None) -> list[str]:
    """The model ids worth trying, most specific first."""
    return [
        configured or "",
        reported or "",
        f"openrouter/{reported}" if reported else "",
    ]
