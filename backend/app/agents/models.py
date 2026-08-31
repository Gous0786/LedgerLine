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
    s = get_settings()
    if s.openrouter_api_key:
        os.environ.setdefault("OPENROUTER_API_KEY", s.openrouter_api_key)
    os.environ.setdefault("OPENROUTER_API_BASE", s.openrouter_base_url)


@lru_cache
def model(model_id: str) -> LiteLlm:
    """Wrap an OpenRouter model id (``openrouter/<vendor>/<name>``) for ADK."""
    configure_litellm()
    settings = get_settings()

    extra: dict = {}
    if settings.enable_prompt_cache:
        # Ask OpenRouter to report cache hit/write counts. Caching itself does
        # not currently engage: OpenRouter puts tool schemas after the system
        # breakpoint, so only the ~420-token system prompt is cacheable, which
        # is under the provider minimum (2048 on Haiku). Kept because the
        # accounting is free and shows the moment that changes.
        extra["extra_body"] = {"usage": {"include": True}}

    return LiteLlm(model=model_id, **extra)


def orchestrator_model() -> LiteLlm:
    return model(get_settings().model_orchestrator)


def worker_model() -> LiteLlm:
    return model(get_settings().model_worker)
