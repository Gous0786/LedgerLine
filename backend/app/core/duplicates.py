"""Rows a source file records twice.

A duplicated line is not a second event. When a processor export carries
`SYNTH-PROC-000169` twice, byte for byte, there was one capture and the file
says so twice -- and any sum over that file is wrong by exactly the duplicated
amount.

Detection is byte-identical only: every source column equal. That needs no key
discovery, no threshold and no guess about which column is the natural key, and
it cannot produce a false positive. The weaker relative -- same identifier,
*different* values -- is a conflict rather than a duplicate and is reported
separately, because there is no safe way to pick which of the two is true.

Nothing here decides what to do about a duplicate. `matching` excludes the
redundant copy from an aggregate sum, where double counting is unambiguous;
elsewhere a duplicate is the finding itself and is left alone.
"""

from __future__ import annotations

import logging
from typing import Any

from app.db import connection as db

log = logging.getLogger(__name__)


# Does a duplicated row stop counting toward its group's balance?
#
# It is always *marked*, and the UI always explains it -- that is what a
# reviewer needs to see two rows as one event recorded twice. Whether the
# amount also stops counting is a separate, load-bearing question, and the
# labelled fixtures answer it: a duplicated settlement line means the file and
# the bank genuinely disagree, so the batch is a real break and someone must
# decide which is right. Excluding it makes the batch tie and costs 1.7-11.7
# points of accuracy, raising false auto-matches from ~1-3% to 5-13%.
#
# So: off. The break stays visible; the explanation says why it is there.
EXCLUDE_DUPLICATE_AMOUNTS = False


def counts_toward_balance(member: dict[str, Any]) -> bool:
    """Should this member's amount be added to the group's sum?"""
    return not (EXCLUDE_DUPLICATE_AMOUNTS and member.get("duplicate_of") is not None)


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _source_columns(dataset_id: str) -> list[str]:
    return [
        c["column_name"]
        for c in db.query(
            "SELECT column_name FROM dataset_column WHERE dataset_id = ?"
            " ORDER BY ordinal",
            (dataset_id,),
        )
    ]


def redundant_rows(dataset_id: str) -> dict[int, int]:
    """`{redundant __row: the row it duplicates}` for one dataset.

    The lowest `__row` of an identical set is kept as the canonical one -- an
    arbitrary but stable choice, so the same file always yields the same answer.
    """
    ds = db.query_one(
        "SELECT table_name FROM dataset WHERE id = ?", (dataset_id,)
    )
    cols = _source_columns(dataset_id)
    if not ds or not cols:
        return {}

    grouped = ",".join(_quote(c) for c in cols)
    try:
        rows = db.query(
            f"SELECT MIN(__row) AS canonical, GROUP_CONCAT(__row) AS members"
            f" FROM {_quote(ds['table_name'])}"
            f" GROUP BY {grouped} HAVING COUNT(*) > 1"
        )
    except Exception:
        log.warning("duplicate scan failed for %s", dataset_id, exc_info=True)
        return {}

    out: dict[int, int] = {}
    for r in rows:
        canonical = int(r["canonical"])
        for member in str(r["members"] or "").split(","):
            if not member:
                continue
            row = int(member)
            if row != canonical:
                out[row] = canonical
    return out


def summary(dataset_id: str) -> dict[str, Any]:
    """Counts and a few examples, for reporting rather than matching."""
    redundant = redundant_rows(dataset_id)
    ds = db.query_one("SELECT name, table_name FROM dataset WHERE id = ?", (dataset_id,))
    if not ds or not redundant:
        return {
            "dataset": (ds or {}).get("name"),
            "duplicate_rows": 0,
            "duplicate_sets": 0,
        }
    canonical = sorted(set(redundant.values()))
    examples = []
    cols = _source_columns(dataset_id)[:4]
    if cols:
        picked = ", ".join(_quote(c) for c in cols)
        keep = ",".join(str(r) for r in canonical[:3])
        try:
            examples = db.query(
                f"SELECT __row, {picked} FROM {_quote(ds['table_name'])}"
                f" WHERE __row IN ({keep})"
            )
        except Exception:
            examples = []
    return {
        "dataset": ds["name"],
        "duplicate_rows": len(redundant),
        "duplicate_sets": len(canonical),
        "examples": examples,
    }


def all_redundant() -> dict[str, dict[int, int]]:
    """Every ready dataset's redundant rows, keyed by dataset id."""
    return {
        d["id"]: redundant_rows(d["id"])
        for d in db.query("SELECT id FROM dataset WHERE status = 'ready'")
    }
