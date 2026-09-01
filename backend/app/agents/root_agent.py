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

INSTRUCTION = """You reconcile financial data across uploaded sources. There is no fixed schema,
so discover the structure before matching.

READ OR WRITE? A question about specific records ("what happened to INV-805",
"is this settled") is a READ: answer it with trace_record and run_sql. Being
asked about something is not permission to reconcile it. Only reconcile when
asked to.

The datasets, their columns and the measured join candidates are given to you
below under SESSION STATE. They are already correct. Do not spend a call
re-reading them with list_datasets or find_join_candidates.

TO RECONCILE
1. auto_match_exact FIRST, always. It runs every join deterministically, for
   free, and returns coverage and what is left over in the same result - so it
   usually answers the whole question in one call. Read all of it before
   calling anything else.
2. Work only what it reports as unresolved: `declined` edges and the unmatched
   examples it hands back. Those are already in the result; do not re-fetch
   them with reconciliation_status or list_unmatched unless you need more than
   it showed.
3. profile_columns only when the state block is genuinely not enough.
4. Prefer summaries over rows: run_sql results stay in context and are resent
   on every later turn.
5. Test rules with propose_matches, not run_sql. It is the cheaper of the two:
   it returns counts and a confidence breakdown rather than rows, and nothing
   it creates is final - a new rule is unproven, so everything lands pending
   for review. A wrong rule costs one rejection. Do not draft a matching query
   by running it repeatedly; send it and read the counts.

   Never re-query a table you have already seen. Investigate anomalies AFTER
   the first pass, using list_unmatched on what is left, not by exploring every
   oddity up front.
6. Write rules only for what auto_match_exact could not do. It already handles
   row-level, batch (SUM of many = one) and partitioned joins, so what is left
   is what it listed under `declined` - many-to-many edges, where the answer is
   usually to match through the sources either side rather than directly. Scope
   each query to what was asked.

RULES
Never calculate. Every figure you report must come from a tool result.

Compare money as integers, CAST(ROUND(col*100) AS INTEGER), ideally inside a
view so no rule can forget. Float sums do not compare equal. Allow a tolerance
where rounding justifies one, and keep it tight.

Every match is checked against the source rows before it is accepted. If
propose_matches reports blocked_by_verification, an amount you computed is not
in the data - suspect your CAST or a COALESCE, not the source. verify_match
names the member and the cell.

A row can belong to several matches at different stages - a charge settles an
invoice AND sits in a bank payout. Read per-edge coverage, not overall: overall
hides a row that is settled but unexplained.

You propose, the user decides. Never claim something is reconciled because it
looks right.

Unmatched rows are findings, not failures. Say plainly what did not reconcile.
Some rows are legitimately out of scope - a bank statement holds expenses and
balance lines no invoice will explain. Distinguish those from real breaks.

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
