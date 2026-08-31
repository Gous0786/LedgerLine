"""Which source starts a transaction.

Reconciliation chains have to hang off something. That anchor -- the spine -- is
whichever source the others reference: orders, not the bank statement, because
the gateway and ledger both carry `order_id` while nothing carries a gateway id.

Inferred from **containment direction**. If A's values are a subset of B's, then
B is the referenced side and A depends on it; the source that the most others
depend on, and that depends on fewest itself, is the root.

Two exclusions matter, both learned by testing:

*   Only identifier columns count. `expected_payment_date` is a subset of
    `txn_date` in real data, which is a calendar coincidence, not a key.
*   Uniqueness and reach are useless as signals -- every table has a unique
    primary key, and in a fully-joined set every source reaches every other.
    Neither discriminates.
"""

from __future__ import annotations

import collections
import logging
from typing import Any

from app.core import discovery
from app.db import connection as db

log = logging.getLogger(__name__)

SETTING_KEY = "spine_dataset_id"

# A value is treated as contained when essentially all of it appears on the
# other side; real foreign keys are rarely perfectly clean.
CONTAINMENT = 0.99


def _identifier_types(dataset_id: str) -> dict[str, str]:
    return {
        c["column_name"]: c["inferred_type"]
        for c in db.query(
            "SELECT column_name, inferred_type FROM dataset_column WHERE dataset_id = ?",
            (dataset_id,),
        )
    }


def infer_spine() -> dict[str, Any]:
    """Rank sources by how many others depend on them."""
    datasets = db.query(
        "SELECT id, name FROM dataset WHERE status = 'ready' ORDER BY created_at"
    )
    if not datasets:
        return {"dataset_id": None, "reason": "no datasets", "scores": []}
    if len(datasets) == 1:
        d = datasets[0]
        return {
            "dataset_id": d["id"],
            "name": d["name"],
            "reason": "only source",
            "scores": [],
            "origin": "inferred",
        }

    types = {d["name"]: _identifier_types(d["id"]) for d in datasets}

    def is_identifier(ds_name: str, col: str) -> bool:
        # amounts and dates overlap by coincidence; keys are labels
        return types.get(ds_name, {}).get(col) == "TEXT"

    parent: collections.Counter = collections.Counter()
    child: collections.Counter = collections.Counter()
    keys: list[dict[str, Any]] = []

    for p in discovery.find_join_candidates()["pairs"]:
        left, right = p["left_dataset"], p["right_dataset"]
        if not (
            is_identifier(left, p["left_column"]) and is_identifier(right, p["right_column"])
        ):
            continue
        lc, rc = p["left_coverage"], p["right_coverage"]
        if lc >= CONTAINMENT and rc < CONTAINMENT:
            parent[right] += 1
            child[left] += 1
            keys.append({"from": f"{left}.{p['left_column']}",
                         "to": f"{right}.{p['right_column']}"})
        elif rc >= CONTAINMENT and lc < CONTAINMENT:
            parent[left] += 1
            child[right] += 1
            keys.append({"from": f"{right}.{p['right_column']}",
                         "to": f"{left}.{p['left_column']}"})

    scores = [
        {
            "dataset_id": d["id"],
            "name": d["name"],
            "referenced_by": parent[d["name"]],
            "depends_on": child[d["name"]],
            "score": parent[d["name"]] - child[d["name"]],
        }
        for d in datasets
    ]
    scores.sort(key=lambda s: (s["score"], s["referenced_by"]), reverse=True)
    best = scores[0]

    # No containment anywhere means no structure to read; first upload is as
    # good a guess as any, and saying so is better than inventing a reason.
    if best["referenced_by"] == 0 and best["depends_on"] == 0:
        first = datasets[0]
        return {
            "dataset_id": first["id"],
            "name": first["name"],
            "reason": "no foreign keys found; defaulted to first source uploaded",
            "scores": scores,
            "foreign_keys": keys,
            "origin": "fallback",
        }

    return {
        "dataset_id": best["dataset_id"],
        "name": best["name"],
        "reason": (
            f"{best['referenced_by']} source(s) reference it, it depends on"
            f" {best['depends_on']}"
        ),
        "scores": scores,
        "foreign_keys": keys,
        "origin": "inferred",
    }


def declared_spine() -> dict[str, Any] | None:
    row = db.query_one(
        "SELECT value, reason, set_by FROM app_setting WHERE key = ?", (SETTING_KEY,)
    )
    if not row:
        return None
    ds = db.query_one("SELECT id, name FROM dataset WHERE id = ?", (row["value"],))
    if not ds:
        return None  # the declared source was deleted; fall back to inference
    return {
        "dataset_id": ds["id"],
        "name": ds["name"],
        "reason": row["reason"],
        "origin": "declared",
    }


def set_spine(dataset_id: str, reason: str, actor: str = "agent") -> dict[str, Any]:
    ds = db.query_one("SELECT id, name FROM dataset WHERE id = ?", (dataset_id,))
    if not ds:
        raise ValueError(f"unknown dataset {dataset_id!r}")
    db.execute(
        "INSERT INTO app_setting (key, value, reason, set_by) VALUES (?,?,?,?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value,"
        "   reason = excluded.reason, set_by = excluded.set_by,"
        "   updated_at = datetime('now')",
        (SETTING_KEY, dataset_id, reason, actor),
    )
    return {"dataset_id": ds["id"], "name": ds["name"], "reason": reason,
            "origin": "declared"}


def resolve_spine() -> dict[str, Any]:
    """What the agent declared, else what the structure implies."""
    return declared_spine() or infer_spine()
