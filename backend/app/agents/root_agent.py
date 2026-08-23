"""Root reconciliation agent.

Placeholder wiring only. The sub-agent tree (schema mapping, matching, break
analysis, reporting) lands once the transaction-flow model is defined -- until
then this proves the model factory resolves and gives `adk web` something to
attach to.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent

from app.agents.models import orchestrator_model

INSTRUCTION = """\
You are the orchestrator of a multi-source reconciliation system.

Sources are arbitrary CSVs with no fixed schema, reconciled in whatever
direction the transaction flow demands. You never compute matches, sums, or
balances yourself -- you call tools that run SQL, and you interpret what comes
back. If a number did not come from a tool result, do not state it.
"""


def build_root_agent() -> LlmAgent:
    return LlmAgent(
        name="orchestrator",
        model=orchestrator_model(),
        description="Plans and drives a multi-source reconciliation run.",
        instruction=INSTRUCTION,
        tools=[],  # populated as recon tools land
    )
