"""Which source starts a transaction.

Reconciliation chains hang off an anchor -- the spine -- and the right anchor is
where a transaction *begins*: the order, not the bank credit that eventually
settles it.

**Time decides, but only within a match.** A transaction moves forward through
the sources, so the source whose row is earlier *for the same transaction* is
upstream. Orders precede captures, captures precede settlements, and that holds
whatever the columns are called.

Comparing whole sources instead -- each one's median timestamp -- looks
equivalent and is not, because it compares different populations. On a sampled
dataset the bank rows fell in an earlier fortnight than the orders, so the
median said settlements start a transaction and every chain read backwards.
Joining first makes both sides the same transactions, and the signal stops
being a lean and becomes a fact: 261 of 261 matched rows, then 250 of 250.

Containment direction (if A's values are a subset of B's, B is referenced) is
kept only as a fallback, because it answers a different question. It says which
source is a *lookup*, not which is *first*, and the two diverge: with a payment
processor referenced by both the ledger and the bank, containment crowns the
processor even though nothing starts there. It also goes silent whenever two
sources share a key symmetrically, which is the common case.

Exclusions learned by testing:

*   Only identifier columns count for containment. `expected_payment_date` is a
    subset of `txn_date` in real data -- a calendar coincidence, not a key.
*   Uniqueness and reach are useless -- every table has a unique primary key,
    and in a fully-joined set every source reaches every other.
*   Only ISO-shaped timestamps are compared, since those sort correctly as
    text. A DD/MM/YYYY column would rank by day-of-month.
"""

from __future__ import annotations

import collections
import logging
import re
from typing import Any

from app.config import get_settings
from app.core import discovery, sqlguard
from app.db import connection as db

log = logging.getLogger(__name__)

SETTING_KEY = "spine_dataset_id"

# A value is treated as contained when essentially all of it appears on the
# other side; real foreign keys are rarely perfectly clean.
CONTAINMENT = 0.99

# How consistently one side must be earlier, across matched rows, before it is
# called upstream. Deliberately strict: the comparison is apples-to-apples so a
# real flow agrees on nearly every row, and anything close to a coin toss means
# the two sources are not ordered by these timestamps at all.
PRECEDENCE_AGREEMENT = 0.8
MIN_PAIR_ROWS = 5


def _identifier_types(dataset_id: str) -> dict[str, str]:
    return {
        c["column_name"]: c["inferred_type"]
        for c in db.query(
            "SELECT column_name, inferred_type FROM dataset_column WHERE dataset_id = ?",
            (dataset_id,),
        )
    }


_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _earliest_event(dataset_id: str, table_name: str) -> str | None:
    """Median timestamp of this source, or None if it has no usable one.

    Median rather than minimum: one backdated row should not make a source look
    like the origin.
    """
    cols = db.query(
        "SELECT column_name FROM dataset_column"
        " WHERE dataset_id = ? AND inferred_type IN ('DATE','TIMESTAMP')"
        " ORDER BY ordinal",
        (dataset_id,),
    )
    best: str | None = None
    for c in cols:
        col = c["column_name"].replace('"', '""')
        try:
            rows = sqlguard.select_all(
                get_settings().db_path,
                f'SELECT "{col}" AS v FROM "{table_name}" WHERE "{col}" IS NOT NULL'
                f' ORDER BY "{col}"'
                f' LIMIT 1 OFFSET (SELECT COUNT("{col}")/2 FROM "{table_name}")',
            )
        except Exception:
            continue
        if not rows or rows[0]["v"] is None:
            continue
        value = str(rows[0]["v"])
        if not _ISO.match(value):
            continue
        # a source may carry several dates; its position is the earliest of them
        if best is None or value < best:
            best = value
    return best


def precedence() -> list[tuple[str, str, int, int]]:
    """Which source's rows come first, compared *within a match*.

    The earlier version took each source's median timestamp and ranked them.
    That compares different populations, and on a sampled dataset it inverts:
    the bank rows happened to cluster in an earlier fortnight than the orders,
    so the statement landed on "settlements start a transaction", and every
    chain read backwards.

    Joining first fixes it, because then both sides are the *same*
    transactions. Measured on that dataset the signal is not merely better, it
    is unambiguous: internal precedes processor in 261 of 261 matched rows, and
    processor precedes bank in 250 of 250.

    Returns `(earlier_id, later_id, agreeing_rows, compared_rows)`.
    """
    datasets = {d["name"]: d for d in db.query(
        "SELECT id, name, table_name FROM dataset WHERE status = 'ready'"
    )}
    stamps = {
        d["id"]: [
            c["column_name"] for c in db.query(
                "SELECT column_name FROM dataset_column WHERE dataset_id = ?"
                " AND inferred_type IN ('DATE','TIMESTAMP') ORDER BY ordinal",
                (d["id"],),
            )
        ]
        for d in datasets.values()
    }

    p = get_settings().db_path
    edges: list[tuple[str, str, int, int]] = []
    for pair in discovery.find_join_candidates()["pairs"]:
        left, right = datasets.get(pair["left_dataset"]), datasets.get(pair["right_dataset"])
        if not left or not right:
            continue
        best: tuple[int, int] | None = None
        for lts in stamps.get(left["id"], []):
            for rts in stamps.get(right["id"], []):
                sql = (
                    f'SELECT COUNT(*) AS n,'
                    f' SUM(CASE WHEN l."{lts}" < r."{rts}" THEN 1 ELSE 0 END) AS earlier'
                    f' FROM "{left["table_name"]}" l'
                    f' JOIN "{right["table_name"]}" r'
                    f'   ON r."{pair["right_column"]}" = l."{pair["left_column"]}"'
                    # Only ISO-shaped values: anything else does not sort as text,
                    # and a DD/MM column would rank by day of month.
                    f' WHERE l."{lts}" GLOB \'[0-9][0-9][0-9][0-9]-*\''
                    f'   AND r."{rts}" GLOB \'[0-9][0-9][0-9][0-9]-*\''
                )
                try:
                    row = sqlguard.select_all(p, sql)[0]
                except Exception:
                    continue
                n = row["n"] or 0
                if n < MIN_PAIR_ROWS:
                    continue
                if best is None or n > best[1]:
                    best = (row["earlier"] or 0, n)
        if best is None:
            continue
        earlier, n = best
        if earlier / n >= PRECEDENCE_AGREEMENT:
            edges.append((left["id"], right["id"], earlier, n))
        elif (n - earlier) / n >= PRECEDENCE_AGREEMENT:
            edges.append((right["id"], left["id"], n - earlier, n))
    return edges


def _ordered_by_precedence(edges: list[tuple[str, str, int, int]]) -> list[str] | None:
    """Sources in flow order: fewest things preceding them first."""
    if not edges:
        return None
    before: dict[str, set[str]] = {}
    for earlier, later, _, _ in edges:
        before.setdefault(later, set()).add(earlier)
        before.setdefault(earlier, set())
    # Transitive closure, so a three-stage chain orders correctly rather than
    # relying on the two edges happening to be discovered in order.
    for _ in range(len(before)):
        for node, preds in before.items():
            for p in list(preds):
                preds |= before.get(p, set()) - {node}
    return sorted(before, key=lambda n: (len(before[n]), n))


def infer_spine() -> dict[str, Any]:
    """Pick the source where transactions begin."""
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

    # --- primary signal: which side is earlier within a match ---
    edges = precedence()
    order = _ordered_by_precedence(edges)
    if order:
        names = {d["id"]: d["name"] for d in datasets}
        first = order[0]
        followers = [names.get(x, x) for x in order[1:]]
        return {
            "dataset_id": first,
            "name": names.get(first, first),
            "reason": (
                "earliest within every match"
                + (f", ahead of {', '.join(followers)}" if followers else "")
            ),
            "scores": [
                {"earlier": names.get(a, a), "later": names.get(b, b),
                 "agreeing_rows": k, "compared_rows": n}
                for a, b, k, n in edges
            ],
            "origin": "inferred",
        }

    # --- fallback: whole-source medians ---
    # Only reached when no two sources share both a key and comparable
    # timestamps. It compares different populations, so it is a guess.
    timing = {
        d["id"]: _earliest_event(d["id"], d["table_name"])
        for d in db.query(
            "SELECT id, table_name FROM dataset WHERE status = 'ready'"
        )
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
    for s_ in scores:
        s_["earliest_event"] = timing.get(s_["dataset_id"])

    dated = [s_ for s_ in scores if s_["earliest_event"]]
    if len(dated) >= 2:
        dated.sort(key=lambda s_: s_["earliest_event"])
        first = dated[0]
        return {
            "dataset_id": first["dataset_id"],
            "name": first["name"],
            "reason": (
                f"earliest events ({first['earliest_event'][:10]}), so transactions"
                " start here"
            ),
            "scores": dated,
            "foreign_keys": keys,
            "origin": "inferred",
        }

    # No comparable timestamps: fall back to who is referenced most.
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
            f"no comparable timestamps; {best['referenced_by']} source(s)"
            f" reference it, it depends on {best['depends_on']}"
        ),
        "scores": scores,
        "foreign_keys": keys,
        "origin": "inferred",
    }


def stage_order() -> list[dict[str, Any]]:
    """Sources in the order a transaction moves through them.

    Same signal as the spine itself, so the chain and its origin cannot
    disagree. Sources that take part in no measured precedence are appended in
    upload order rather than dropped.
    """
    datasets = db.query(
        "SELECT id, name, table_name FROM dataset WHERE status = 'ready'"
        " ORDER BY created_at"
    )
    names = {d["id"]: d["name"] for d in datasets}

    order = _ordered_by_precedence(precedence())
    if order:
        ranked = [{"dataset_id": i, "name": names[i]} for i in order if i in names]
        rest = [
            {"dataset_id": d["id"], "name": d["name"]}
            for d in datasets
            if d["id"] not in set(order)
        ]
        return ranked + rest

    dated, undated = [], []
    for d in datasets:
        when = _earliest_event(d["id"], d["table_name"])
        entry = {"dataset_id": d["id"], "name": d["name"], "earliest_event": when}
        (dated if when else undated).append(entry)
    dated.sort(key=lambda e: e["earliest_event"])
    return dated + undated


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
