"""Model factory: every agent gets its LLM through LiteLLM -> OpenRouter.

Keeping construction behind a factory means the model for any role is an env
var, not a code change -- useful when a cheap model is enough for mechanical
steps and only the judgement calls need a strong one.
"""

from __future__ import annotations

import os
from functools import lru_cache

from google.adk.models.lite_llm import LiteLlm

from app.config import get_settings


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
    return LiteLlm(model=model_id)


def orchestrator_model() -> LiteLlm:
    return model(get_settings().model_orchestrator)


def worker_model() -> LiteLlm:
    return model(get_settings().model_worker)
