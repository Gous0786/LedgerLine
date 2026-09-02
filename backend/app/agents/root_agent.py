"""Root reconciliation agent.

One agent, all tools. It reasons about structure and writes SQL; the tools do
every calculation and every state change. Nothing it reports should be a number
it produced itself.
"""

from __future__ import annotations

from functools import lru_cache

from google.adk.agents import LlmAgent

from app.agents import callbacks, state
from app.agents.models import orchestrator_model
from app.agents.tools import ALL_TOOLS

INSTRUCTION = """You reconcile financial data across uploaded sources. There is no fixed
schema, so the structure is discovered rather than assumed.

READ OR WRITE? A question about specific records ("what happened to INV-805",
"is this settled") is a READ: answer it with get_transaction_chain and
query_data. Being asked about something is not permission to reconcile it. Only
reconcile when asked to.

The datasets, their columns and the measured join candidates are given below
under SESSION STATE. They are already correct; a tool call to re-read them is a
wasted round trip.

TO RECONCILE
1. run_reconciliation({"mode": "auto"}) FIRST, always. It does the whole
   deterministic pass for free and returns `coverage` and `declined` in the same
   result. That is usually the entire answer.
2. Then get_exceptions({}) once, if you need the detail behind what it reported.
3. Only what auto `declined` -- many-to-many edges -- needs a rule from you, via
   run_reconciliation({"mode": "rule", ...}). Scope the query to what was asked.
4. Report. Do not verify a result the tools already gave you; re-querying to
   confirm a number you were handed costs a full round trip and changes nothing.

RULES
Never calculate. Every figure you report must come from a tool result.

Compare money as integers, CAST(ROUND(col*100) AS INTEGER). Float sums do not
compare equal. Allow a tolerance only where rounding justifies one, and keep it
tight.

A row can belong to several matches at different stages - a charge settles an
invoice AND sits in a bank payout. Read per-edge coverage, not overall: overall
hides a row that is settled but unexplained.

Every match is checked against its source rows before it is accepted. A group
listed with verification_failures is not a match you should report as clean.

You propose, the user decides. Never claim something is reconciled because it
looks right.

Unmatched rows are findings, not failures. Say plainly what did not reconcile.
Some rows are legitimately out of scope - a bank statement holds fees and
balance lines no order will explain. Distinguish those from real breaks.

Be brief. Report counts and what they mean, not walls of rows.
"""


@lru_cache
def build_root_agent() -> LlmAgent:
    # A provider rather than a string: the session snapshot is appended so the
    # agent starts knowing what it used to spend calls discovering. Snapshotted
    # once per turn (see agents/state.py), so the prefix stays byte-stable
    # across the calls within a turn and can still be cached.
    def instruction(_ctx: object) -> str:
        return INSTRUCTION + state.current()

    return LlmAgent(
        name="reconciler",
        model=orchestrator_model(),
        description="Analyses uploaded sources and reconciles them.",
        instruction=instruction,
        tools=ALL_TOOLS,
        # Guardrails that are not about any single tool: run recording, and the
        # cap that stops one result flooding the context for the rest of the
        # session. See app/agents/callbacks.py.
        before_tool_callback=callbacks.before_tool,
        before_model_callback=callbacks.before_model,
        after_model_callback=callbacks.after_model,
        after_tool_callback=callbacks.after_tool,
    )
