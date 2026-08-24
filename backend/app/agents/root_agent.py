"""Root agent.

Plain conversational agent for now: no tools, and no reconciliation direction.
The no-arithmetic contract and the sub-agent tree land with the first real
recon tools.
"""

from __future__ import annotations

from functools import lru_cache

from google.adk.agents import LlmAgent

from app.agents.models import orchestrator_model

INSTRUCTION = "You are a helpful assistant. Answer the user's questions directly."


@lru_cache
def build_root_agent() -> LlmAgent:
    return LlmAgent(
        name="orchestrator",
        model=orchestrator_model(),
        description="Answers questions.",
        instruction=INSTRUCTION,
        tools=[],
    )
