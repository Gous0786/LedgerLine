"""What the agent would otherwise spend its first few calls finding out.

Measured on a real turn: the prompt starts at ~2,150 tokens and grows to ~8,500
by the thirteenth call, because every model call resends the whole conversation.
Total cost therefore grows with the *square* of the number of calls, which makes
call count the dominant lever and the size of any single message a secondary
one. Removing a round trip is worth far more than shortening a result.

The first calls of every reconciliation asked for things that are (a) already
known to the backend, (b) free to compute, and (c) unchanged for the duration
of the turn -- which datasets exist, what columns they have, which columns
overlap. Answering those in the instruction costs a few hundred tokens once and
removes two round trips whose real price is every later call that had to carry
them in history.

Snapshotted **once per turn**, deliberately. An instruction provider is called
before every model call, so recomputing would let the text drift as proposals
are created mid-turn, and a prefix that changes between calls is a prefix that
never caches.
"""

from __future__ import annotations

import contextvars
import logging

log = logging.getLogger(__name__)

_turn_state: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "recon_turn_state", default=None
)

# Enough pairs to reason about structure, few enough not to become the thing
# being resent forever.
MAX_PAIRS = 8


def render() -> str:
    """A compact picture of the session, or an empty string if nothing is loaded."""
    from app.core import discovery
    from app.db import connection as db

    try:
        datasets = db.query(
            "SELECT id, name, row_count FROM dataset WHERE status = 'ready'"
            " ORDER BY created_at"
        )
    except Exception:
        return ""
    if not datasets:
        return "\nSESSION STATE\nNo datasets uploaded yet.\n"

    lines = ["", "SESSION STATE (already measured; do not re-query it)", "datasets:"]
    for d in datasets:
        cols = db.query(
            "SELECT column_name, inferred_type FROM dataset_column"
            " WHERE dataset_id = ? ORDER BY ordinal",
            (d["id"],),
        )
        rendered = " ".join(f"{c['column_name']}:{c['inferred_type']}" for c in cols)
        lines.append(f"  {d['name']} ({d['row_count']} rows) {rendered}")

    views = db.query("SELECT name FROM dataset_view ORDER BY name")
    if views:
        lines.append("views: " + ", ".join(v["name"] for v in views))

    try:
        pairs = discovery.find_join_candidates()["pairs"][:MAX_PAIRS]
    except Exception:
        pairs = []
    if pairs:
        lines.append("join candidates (measured value overlap, strongest first):")
        for p in pairs:
            lines.append(
                f"  {p['left_dataset']}.{p['left_column']}"
                f" = {p['right_dataset']}.{p['right_column']}"
                f"  overlap {p['overlap']}"
                f" coverage {p['left_coverage']}/{p['right_coverage']}"
            )

    counts = db.query(
        "SELECT status, COUNT(*) n FROM match_proposal GROUP BY status"
    )
    if counts:
        summary = ", ".join(f"{c['n']} {c['status']}" for c in counts)
        lines.append(f"proposals so far: {summary}")
    else:
        lines.append("proposals so far: none -- nothing has been reconciled yet")
    return "\n".join(lines) + "\n"


def begin_turn() -> None:
    """Snapshot the state for this turn. Called once, before the agent runs."""
    try:
        _turn_state.set(render())
    except Exception:
        log.warning("could not render session state", exc_info=True)
        _turn_state.set("")


def current() -> str:
    return _turn_state.get() or ""
