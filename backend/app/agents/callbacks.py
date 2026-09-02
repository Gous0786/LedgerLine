"""Cross-cutting guardrails, hung off ADK's callback seam.

Everything the agent is structurally prevented from doing lives inside the tool
bodies, which is the right place for a rule about *that tool*. These are the
rules that are not about any one tool:

*   every tool call and every model call is recorded against the run, which is
    what makes `match_proposal.run_id`, the Activity replay path and the cost
    history real rather than designed;
*   no single tool result may flood the context.

The size cap is the one that changes behaviour, so it is worth being precise
about why it exists. A tool result is not paid for once. It stays in the
conversation and is re-sent on every later turn, so an oversized result is a
recurring charge for the rest of the session -- the cost of a session grows with
the square of how much its tools returned. `run_sql` already caps itself for
exactly this reason; this applies the same discipline to the tools that were
written before the lesson.
"""

from __future__ import annotations

import contextvars
import json
import logging
from typing import Any

from app.core import pricing, runlog

log = logging.getLogger(__name__)

# How many *exploratory* calls one turn may make. Not a cost cap for its own
# sake -- a bound on variance, which is what makes the cost unquotable. The
# same prompt on the same data has spent 9 calls and 14, 43k tokens and 79k,
# because "reconcile it" has no natural end and the model keeps probing after
# the deterministic pass has already answered. The prompt asks it not to; two
# measured runs show it does anyway, which is the same reason confidence is
# computed here rather than requested from the model.
#
# Generous on purpose: auto_match_exact now returns coverage and leftovers in
# one result, so what remains is a handful of questions about specific breaks.
EXPLORE_BUDGET = 6

# Tools that look. `run_reconciliation` is never budgeted, in either mode,
# because running out of budget must never mean leaving the job half done.
EXPLORATORY = frozenset({
    "query_data", "describe_dataset", "list_datasets",
    "get_exceptions", "get_transaction_chain",
})

# ~1.5k tokens. Chosen against measured results: the heaviest tool results came
# in around 7.5k characters, carrying long lists whose tail adds nothing a
# summary would not.
MAX_TOOL_RESULT_CHARS = 6_000

# Never trim below this many items -- a truncated list that shows nothing is
# worse than one that shows a few.
MIN_KEPT_ITEMS = 3

_explored: contextvars.ContextVar[int] = contextvars.ContextVar(
    "recon_explore_calls", default=0
)


def begin_turn() -> None:
    """Reset the per-turn exploration budget."""
    _explored.set(0)


def _size(payload: Any) -> int:
    try:
        return len(json.dumps(payload, default=str))
    except Exception:
        return 0


def cap_result(payload: Any) -> tuple[Any, dict[str, int] | None]:
    """Trim the longest list fields until the whole thing fits.

    Lists are trimmed rather than the JSON being cut, so what comes back is
    still valid and still shaped the way the tool documented. Longest-first
    means the bulk (`pairs`, `results`, `rows`) gives way before the short
    fields that carry the finding -- `declined`, `error`, counts.
    """
    if not isinstance(payload, dict):
        return payload, None
    if _size(payload) <= MAX_TOOL_RESULT_CHARS:
        return payload, None

    trimmed = dict(payload)
    dropped: dict[str, int] = {}
    lists = sorted(
        (k for k, v in trimmed.items() if isinstance(v, list) and len(v) > MIN_KEPT_ITEMS),
        key=lambda k: _size(trimmed[k]),
        reverse=True,
    )
    for key in lists:
        # Trim by how much is actually over, not by halving: the lists are
        # ordered best-first, so every item dropped past the budget is evidence
        # thrown away for nothing.
        while (
            _size(trimmed) > MAX_TOOL_RESULT_CHARS
            and len(trimmed[key]) > MIN_KEPT_ITEMS
        ):
            items = trimmed[key]
            over = _size(trimmed) - MAX_TOOL_RESULT_CHARS
            per_item = max(1, _size(items) // len(items))
            remove = max(1, min(len(items) - MIN_KEPT_ITEMS, over // per_item + 1))
            dropped[key] = dropped.get(key, 0) + remove
            trimmed[key] = items[: len(items) - remove]
        if _size(trimmed) <= MAX_TOOL_RESULT_CHARS:
            break

    if dropped:
        # Said plainly, because a silently shortened list is a lie the model
        # will reason from: it would conclude there were only three join
        # candidates and stop looking.
        trimmed["_truncated"] = {
            "dropped": dropped,
            "note": (
                "Result was too large to return in full and lists were shortened."
                " Counts and totals elsewhere in this result are complete."
                " Narrow the question rather than repeating this call."
            ),
        }
    return trimmed, dropped or None


def after_tool(
    *,
    tool: Any,
    args: dict[str, Any],
    tool_context: Any,
    tool_response: dict[str, Any],
) -> dict[str, Any] | None:
    """Record the call, then cap what goes back to the model.

    Keyword-only, and the names are ADK's. Its own source notes that the
    callback type aliases are declared positionally but the framework has
    always invoked them by keyword, so a signature that merely has the right
    arity fails at the first tool call with a TypeError -- which is exactly how
    this was found.
    """
    name = getattr(tool, "name", None) or getattr(tool, "__name__", "tool")
    capped, dropped = cap_result(tool_response)

    runlog.event(
        "tool-output-available",
        {
            "tool": name,
            "args": args,
            "result_chars": _size(tool_response),
            "returned_chars": _size(capped),
            "truncated": dropped or None,
            # The full result is kept here even when the model gets less: the
            # Activity tab and any later audit should see what the tool
            # actually said, not what fitted.
            "result": tool_response,
        },
        agent=getattr(tool_context, "agent_name", None),
    )

    if dropped:
        log.info("capped %s result: %s -> %s chars", name,
                 _size(tool_response), _size(capped))
        return capped
    return None  # unchanged


def before_tool(
    *, tool: Any, args: dict[str, Any], tool_context: Any
) -> dict[str, Any] | None:
    """Spend the exploration budget, and say so when it runs out.

    Returning a dict short-circuits the tool, so this is a real bound rather
    than advice. The message is written to be *actionable* -- it tells the model
    to answer with what it has, because a refusal it cannot act on just becomes
    another wasted round trip.
    """
    name = getattr(tool, "name", None) or getattr(tool, "__name__", "tool")
    if name not in EXPLORATORY:
        return None

    spent = _explored.get() + 1
    _explored.set(spent)
    if spent <= EXPLORE_BUDGET:
        return None

    log.info("exploration budget spent; refused %s", name)
    runlog.event("tool-budget-exceeded", {"tool": name, "args": args, "spent": spent})
    return {
        "error": "exploration budget for this turn is spent",
        "spent": spent,
        "budget": EXPLORE_BUDGET,
        "note": (
            "Stop investigating and answer now with what you already have."
            " auto_match_exact's result already carries coverage and the"
            " unmatched examples. Reporting what is unresolved is a complete"
            " answer; it does not need to be explained row by row."
        ),
    }


def before_model(*, callback_context: Any, llm_request: Any) -> None:
    runlog.model_call_started()
    return None


def after_model(*, callback_context: Any, llm_response: Any) -> None:
    """One `run_metric` row per completed model call.

    Streaming delivers many partial responses and one final; only the final
    carries usage, so partials are skipped rather than counted as zero-token
    calls that would inflate the call count.
    """
    if getattr(llm_response, "partial", False):
        return None
    usage = getattr(llm_response, "usage_metadata", None)
    if usage is None:
        return None

    prompt = getattr(usage, "prompt_token_count", None) or 0
    completion = getattr(usage, "candidates_token_count", None) or 0
    model = getattr(llm_response, "model_version", None)

    from app.agents import runner as agent_runner

    runlog.metric(
        model=model,
        agent=getattr(callback_context, "agent_name", None),
        prompt_tokens=prompt,
        completion_tokens=completion,
        cached_tokens=getattr(usage, "cached_content_token_count", None) or 0,
        reasoning_tokens=getattr(usage, "thoughts_token_count", None) or 0,
        cost_usd=pricing.cost_usd(
            pricing.candidates(agent_runner.active_model(), model), prompt, completion
        ),
    )
    return None
