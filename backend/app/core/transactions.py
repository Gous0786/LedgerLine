"""End-to-end transaction chains, assembled from match proposals.

A proposal covers one edge; a transaction is the whole path -- order to gateway
to bank to ledger. Rebuilding that path means walking the match graph outward
from a spine row.

The walk has to stop somewhere, and the place it stops is the whole trick. A
settlement batch legitimately holds rows from several transactions, so walking
*through* one fuses every order that shares it into a single blob. Batches are
therefore included as legs but never traversed: they appear in each chain that
uses them, labelled, rather than merging those chains together.
"""

from __future__ import annotations

import collections
import logging
from typing import Any

from app.config import get_settings
from app.core import sqlguard
from app.db import connection as db

log = logging.getLogger(__name__)

OPEN_STATUSES = ("pending", "accepted", "review_later")

# Confidence values that represent a settled leg.
SETTLED = ("exact", "within_tolerance", "high")


def _label_column(dataset_id: str) -> str | None:
    """The column that names a transaction across sources.

    Not simply the first text column: a source usually carries both its own
    primary key and the shared reference, and only the shared one identifies the
    same transaction elsewhere. `internal_payment_id` is unique per row, but
    `merchant_order_id` is what the processor and bank also carry -- and what a
    duplicate-payment break has two rows of.

    So pick the column with the widest measured overlap into other datasets.
    """
    from app.core import discovery

    name_row = db.query_one("SELECT name FROM dataset WHERE id = ?", (dataset_id,))
    if not name_row:
        return None
    name = name_row["name"]

    best: tuple[float, str] | None = None
    for pair in discovery.find_join_candidates()["pairs"]:
        for side in ("left", "right"):
            if pair[f"{side}_dataset"] != name:
                continue
            col = pair[f"{side}_column"]
            cov = pair[f"{side}_coverage"]
            if best is None or cov > best[0]:
                best = (cov, col)
    if best:
        return best[1]

    cols = db.query(
        "SELECT column_name, inferred_type FROM dataset_column"
        " WHERE dataset_id = ? ORDER BY ordinal",
        (dataset_id,),
    )
    text = [c["column_name"] for c in cols if c["inferred_type"] == "TEXT"]
    return (text or [c["column_name"] for c in cols] or [None])[0]


def build(spine_dataset_id: str, statuses: tuple[str, ...] = OPEN_STATUSES) -> dict[str, Any]:
    """Group every proposal into per-transaction chains, plus what is left over."""
    spine_ds = db.query_one("SELECT * FROM dataset WHERE id = ?", (spine_dataset_id,))
    if not spine_ds:
        raise ValueError(f"unknown dataset {spine_dataset_id!r}")

    datasets = {d["id"]: d for d in db.query("SELECT * FROM dataset")}
    placeholders = ",".join("?" for _ in statuses)
    members = db.query(
        "SELECT m.proposal_id, m.dataset_id, m.row, m.role, m.amount_minor,"
        "       p.group_key, p.rule, p.tier, p.confidence, p.status,"
        "       p.balance_minor, p.tolerance_minor"
        f" FROM match_member m JOIN match_proposal p ON p.id = m.proposal_id"
        f" WHERE p.status IN ({placeholders})",
        statuses,
    )

    prop_rows: dict[int, list[tuple[str, int]]] = collections.defaultdict(list)
    prop_meta: dict[int, dict[str, Any]] = {}
    row_props: dict[tuple[str, int], list[int]] = collections.defaultdict(list)
    for m in members:
        key = (m["dataset_id"], m["row"])
        prop_rows[m["proposal_id"]].append(key)
        row_props[key].append(m["proposal_id"])
        prop_meta.setdefault(
            m["proposal_id"],
            {
                "proposal_id": m["proposal_id"],
                "group_key": m["group_key"],
                "rule": m["rule"],
                "tier": m["tier"],
                "confidence": m["confidence"],
                "status": m["status"],
                "balance_minor": m["balance_minor"],
                "tolerance_minor": m["tolerance_minor"],
            },
        )

    # --- pass 1: every spine row claims the rows it is directly matched with
    spine_label: dict[tuple[str, int], str] = {}
    spine_rows = sqlguard.select_all(
        get_settings().db_path, f'SELECT * FROM "{spine_ds["table_name"]}" ORDER BY __row'
    )
    label_col = _label_column(spine_dataset_id)
    labels: dict[str, dict[str, Any]] = {}
    for r in spine_rows:
        key = (spine_dataset_id, int(r["__row"]))
        label = str(r.get(label_col)) if label_col else f"row {r['__row']}"
        spine_label[key] = label
        labels[label] = {"row": int(r["__row"]), "data": r}

    for key, label in list(spine_label.items()):
        for pid in row_props.get(key, []):
            for other in prop_rows[pid]:
                spine_label.setdefault(other, label)

    # --- pass 2: a proposal spanning several spine entities is a shared batch
    shared: set[int] = set()
    for pid, rows in prop_rows.items():
        owners = {spine_label.get(r) for r in rows if spine_label.get(r)}
        if len(owners) > 1:
            shared.add(pid)

    # --- pass 3: assemble
    chains: dict[str, set[int]] = collections.defaultdict(set)
    for pid, rows in prop_rows.items():
        for owner in {spine_label.get(r) for r in rows if spine_label.get(r)}:
            if owner:
                chains[owner].add(pid)

    leg_counts = [len(v) for v in chains.values()]
    modal_legs = (
        collections.Counter(leg_counts).most_common(1)[0][0] if leg_counts else 0
    )

    transactions = []
    for label, info in labels.items():
        pids = sorted(chains.get(label, set()))
        legs = []
        for pid in pids:
            meta = dict(prop_meta[pid])
            meta["is_batch"] = pid in shared
            meta["batch_size"] = (
                len({spine_label.get(r) for r in prop_rows[pid] if spine_label.get(r)})
                if pid in shared
                else 1
            )
            meta["members"] = [
                {
                    "dataset": datasets[d]["name"] if d in datasets else d,
                    "dataset_id": d,
                    "row": r,
                }
                for (d, r) in sorted(prop_rows[pid])
            ]
            legs.append(meta)

        if not legs:
            state = "unmatched"
        elif any(x["confidence"] in ("unbalanced", "ambiguous") for x in legs):
            state = "exception"
        elif len(legs) < modal_legs:
            state = "incomplete"
        elif any(x["status"] != "accepted" for x in legs):
            state = "pending"
        else:
            state = "reconciled"

        transactions.append(
            {
                "key": label,
                "spine_row": info["row"],
                "data": info["data"],
                "state": state,
                "leg_count": len(legs),
                "expected_legs": modal_legs,
                "legs": legs,
            }
        )

    order = {"exception": 0, "incomplete": 1, "unmatched": 2, "pending": 3, "reconciled": 4}
    transactions.sort(key=lambda t: (order.get(t["state"], 9), t["key"]))

    # A row is attached if it appears in any leg of any chain. Labelling alone
    # is not enough: pass 1 only reaches one hop, so a bank row sitting in a
    # settlement leg is never labelled even though its chain includes it.
    attached: set[tuple[str, int]] = {
        (m["dataset_id"], m["row"])
        for t in transactions
        for leg in t["legs"]
        for m in leg["members"]
    }
    attached |= {k for k in spine_label}

    return {
        "spine": {"dataset_id": spine_dataset_id, "name": spine_ds["name"]},
        "modal_legs": modal_legs,
        "transactions": transactions,
        "leftovers": _leftovers(datasets, attached, spine_dataset_id),
        "counts": collections.Counter(t["state"] for t in transactions),
    }


def _leftovers(
    datasets: dict[str, dict[str, Any]],
    attached: set[tuple[str, int]],
    spine_dataset_id: str,
) -> list[dict[str, Any]]:
    """Rows belonging to no transaction at all -- orphan credits, phantom
    journal entries, non-order-linked fees."""
    out = []
    for ds_id, ds in datasets.items():
        if ds_id == spine_dataset_id or ds["status"] != "ready":
            continue
        claimed = {r for (d, r) in attached if d == ds_id}
        exclude = ""
        if claimed:
            exclude = " WHERE __row NOT IN (" + ",".join(str(int(r)) for r in claimed) + ")"
        try:
            rows = sqlguard.select_all(
                get_settings().db_path,
                f'SELECT * FROM "{ds["table_name"]}"{exclude} ORDER BY __row LIMIT 100',
            )
        except Exception:
            continue
        if rows:
            out.append({"dataset": ds["name"], "dataset_id": ds_id,
                        "count": len(rows), "rows": rows})
    return out
