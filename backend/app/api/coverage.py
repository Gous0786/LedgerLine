"""How much of each source is reconciled.

Its own router rather than a path under `/proposals`, because `GET
/proposals/{proposal_id}` is declared with an int and would claim
`/proposals/coverage` first, answering 422 instead of the numbers.

The counts already existed -- `matching.reconciliation_status` computes them for
the agent -- but nothing served them to the interface, so the only figures on
screen were proposal tallies. "272 settled" does not answer "how much of the
bank statement is explained".
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.core import matching
from app.db import connection as db

router = APIRouter(prefix="/coverage", tags=["coverage"])


@router.get("")
async def coverage() -> dict[str, Any]:
    """Rows matched per dataset, and per relationship.

    Per-edge is the honest reading in a multi-hop flow: a processor row that
    settles into the bank counts as matched overall even when no order explains
    it, and only the edge breakdown shows that gap.
    """
    status = await db.run(matching.reconciliation_status)

    # The example rows are for an agent reading a tool result, not for a panel
    # drawing a bar. Dropping them keeps this small enough to poll.
    datasets = [
        {k: v for k, v in d.items() if k != "examples"} for d in status["datasets"]
    ]
    edges = [
        {
            "edge": e["edge"],
            "sides": [
                {k: v for k, v in s.items() if k != "unmatched_examples"}
                for s in e["sides"]
            ],
        }
        for e in status["edges"]
    ]

    total_rows = sum(d["rows"] or 0 for d in datasets)
    total_matched = sum(d["matched_in_any_edge"] or 0 for d in datasets)
    return {
        "datasets": datasets,
        "edges": edges,
        "totals": {
            "rows": total_rows,
            "matched": total_matched,
            "unmatched": total_rows - total_matched,
        },
    }
