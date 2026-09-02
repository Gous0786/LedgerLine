"""Model factory: every agent gets its LLM through LiteLLM -> OpenRouter.

Keeping construction behind a factory means the model for any role is an env
var, not a code change -- useful when a cheap model is enough for mechanical
steps and only the judgement calls need a strong one.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache

from google.adk.models.lite_llm import LiteLlm

from app.config import get_settings

log = logging.getLogger(__name__)


def configure_litellm() -> None:
    """Push credentials into the env LiteLLM reads. Call once at startup."""
    import litellm

    s = get_settings()
    # `num_retries` reaches completion() through **kwargs, which is easy to
    # lose in a wrapper. The module default is read directly, so setting both
    # means a retry happens whichever path the call takes.
    litellm.num_retries = s.model_retries
    if s.openrouter_api_key:
        os.environ.setdefault("OPENROUTER_API_KEY", s.openrouter_api_key)
    os.environ.setdefault("OPENROUTER_API_BASE", s.openrouter_base_url)


@lru_cache
def model(model_id: str) -> LiteLlm:
    """Wrap an OpenRouter model id (``openrouter/<vendor>/<name>``) for ADK."""
    configure_litellm()
    settings = get_settings()

    body: dict = {}
    if settings.enable_prompt_cache:
        # Ask OpenRouter to report cache hit/write counts. Measured on a real
        # turn: 97k of 180k prompt tokens came back as cache reads, so caching
        # does engage -- the accounting is what proves it, and would show the
        # moment it stops.
        body["usage"] = {"include": True}
    if settings.prefer_fast_provider:
        body["provider"] = {"sort": "throughput"}

    return LiteLlm(
        model=model_id,
        # A named parameter litellm honours directly. Without it the turn
        # inherits whatever default is in play and a stall takes the whole
        # answer with it.
        timeout=settings.model_timeout_seconds,
        num_retries=settings.model_retries,
        **({"fallbacks": list(settings.model_fallbacks)}
           if settings.model_fallbacks else {}),
        **({"extra_body": body} if body else {}),
    )


def orchestrator_model() -> LiteLlm:
    return model(get_settings().model_orchestrator)


def worker_model() -> LiteLlm:
    return model(get_settings().model_worker)
