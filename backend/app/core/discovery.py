"""Structure discovery over raw datasets.

Everything here is deterministic. Join keys are found by *measuring value
overlap* between columns, not by reasoning about column names -- names lie
(`external_txn_ref` vs `charge_id`) while values do not.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any

from app.config import get_settings
from app.core import sqlguard
from app.db import connection as db

log = logging.getLogger(__name__)

# Per-column distinct values pulled into memory for the overlap pass.
DISTINCT_CAP = 50_000

# A column with very few distinct values (status, currency, txn_type) overlaps
# with everything and means nothing as a join key.
MIN_DISTINCT = 2
ENUM_MAX_DISTINCT = 12

# Only surface pairs where one side is meaningfully covered by the other.
MIN_COVERAGE = 0.25


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _signature(value: str) -> str:
    """Shape of a value: ch_3M01 -> aa_9A99, INV-2026-801 -> AAA-9999-999."""
    out = []
    for ch in value[:40]:
        if ch.isdigit():
            out.append("9")
        elif ch.isupper():
            out.append("A")
        elif ch.islower():
            out.append("a")
        else:
            out.append(ch)
    return re.sub(r"(.)\1{2,}", lambda m: m.group(1) * 3, "".join(out))


def _datasets() -> list[dict[str, Any]]:
    return db.query(
        "SELECT id, name, table_name, row_count FROM dataset"
        " WHERE status = 'ready' ORDER BY created_at"
    )


def _columns(dataset_id: str) -> list[dict[str, Any]]:
    return db.query(
        "SELECT ordinal, source_name, column_name, inferred_type"
        " FROM dataset_column WHERE dataset_id = ? ORDER BY ordinal",
        (dataset_id,),
    )


def profile_columns(dataset_id: str) -> dict[str, Any]:
    """Per-column statistics for one dataset."""
    ds = db.query_one("SELECT * FROM dataset WHERE id = ?", (dataset_id,))
    if not ds:
        raise ValueError(f"unknown dataset {dataset_id!r}")

    table = _quote(ds["table_name"])
    settings = get_settings()
    out: list[dict[str, Any]] = []

    for col in _columns(dataset_id):
        c = _quote(col["column_name"])
        stats = sqlguard.select_all(
            settings.db_path,
            f"SELECT COUNT(*) AS n,"
            f" COUNT({c}) AS non_null,"
            f" COUNT(DISTINCT {c}) AS distinct_count,"
            f" MIN({c}) AS min_value, MAX({c}) AS max_value"
            f" FROM {table}",
        )[0]

        tops = sqlguard.select_all(
            settings.db_path,
            f"SELECT {c} AS v, COUNT(*) AS n FROM {table}"
            f" WHERE {c} IS NOT NULL GROUP BY {c} ORDER BY n DESC LIMIT 5",
        )

        sample = sqlguard.select_all(
            settings.db_path,
            f"SELECT DISTINCT {c} AS v FROM {table} WHERE {c} IS NOT NULL LIMIT 200",
        )
        sigs = Counter(_signature(str(r["v"])) for r in sample)
        top_sig, top_sig_n = (sigs.most_common(1)[0] if sigs else ("", 0))

        n = stats["n"] or 0
        out.append(
            {
                "column": col["column_name"],
                "source_name": col["source_name"],
                "type": col["inferred_type"],
                "rows": n,
                "nulls": n - (stats["non_null"] or 0),
                "distinct": stats["distinct_count"] or 0,
                "unique": (stats["distinct_count"] or 0) == (stats["non_null"] or 0) and n > 0,
                "min": stats["min_value"],
                "max": stats["max_value"],
                "top_values": [{"value": r["v"], "count": r["n"]} for r in tops],
                "pattern": top_sig,
                "pattern_coverage": round(top_sig_n / len(sample), 3) if sample else 0.0,
            }
        )

    return {
        "dataset_id": dataset_id,
        "name": ds["name"],
        "rows": ds["row_count"],
        "columns": out,
    }


def _distinct_values(table: str, column: str) -> set[str]:
    rows = sqlguard.select_all(
        get_settings().db_path,
        f"SELECT DISTINCT {_quote(column)} AS v FROM {_quote(table)}"
        f" WHERE {_quote(column)} IS NOT NULL LIMIT {DISTINCT_CAP}",
    )
    return {str(r["v"]).strip() for r in rows if str(r["v"]).strip() != ""}


def find_join_candidates(dataset_ids: list[str] | None = None) -> dict[str, Any]:
    """Value-overlap matrix across every column pair from different datasets.

    This is what discovers that `internal_invoices.external_txn_ref` and
    `stripe_payout.charge_id` are the same identifier, without anyone guessing
    from the names.
    """
    datasets = _datasets()
    if dataset_ids:
        wanted = set(dataset_ids)
        datasets = [d for d in datasets if d["id"] in wanted]
    if len(datasets) < 2:
        return {"pairs": [], "note": "need at least two ready datasets"}

    # Collect candidate columns and their value sets once.
    loaded: list[dict[str, Any]] = []
    for ds in datasets:
        for col in _columns(ds["id"]):
            values = _distinct_values(ds["table_name"], col["column_name"])
            if len(values) < MIN_DISTINCT:
                continue
            loaded.append(
                {
                    "dataset_id": ds["id"],
                    "dataset": ds["name"],
                    "column": col["column_name"],
                    "type": col["inferred_type"],
                    "values": values,
                    # Few distinct values, repeated across many rows. On its own
                    # this says nothing: `status` looks like this and so does a
                    # foreign key into a small parent table. Which one it is
                    # depends on the other side -- see below.
                    "repetitive": (
                        len(values) <= ENUM_MAX_DISTINCT
                        and (ds["row_count"] or 0) > len(values) * 2
                    ),
                }
            )

    pairs: list[dict[str, Any]] = []
    for i, left in enumerate(loaded):
        for right in loaded[i + 1 :]:
            if left["dataset_id"] == right["dataset_id"]:
                continue
            # Being enum-like is a property of the *pair*, not of a column.
            # `settlement_batch_id` on a processor table is seven values across
            # a hundred rows -- indistinguishable from a status column until you
            # look at the other side, where those same seven values are one row
            # each. That is a foreign key into a small parent, and dropping it
            # loses the entire settlement edge. Only a pair that repeats on
            # *both* sides is an enum.
            if left["repetitive"] and right["repetitive"]:
                continue
            shared = left["values"] & right["values"]
            if not shared:
                continue
            lcov = len(shared) / len(left["values"])
            rcov = len(shared) / len(right["values"])
            if max(lcov, rcov) < MIN_COVERAGE:
                continue
            union = len(left["values"] | right["values"])
            pairs.append(
                {
                    "left_dataset": left["dataset"],
                    "left_dataset_id": left["dataset_id"],
                    "left_column": left["column"],
                    "right_dataset": right["dataset"],
                    "right_dataset_id": right["dataset_id"],
                    "right_column": right["column"],
                    "overlap": len(shared),
                    "left_coverage": round(lcov, 3),
                    "right_coverage": round(rcov, 3),
                    "jaccard": round(len(shared) / union, 3) if union else 0.0,
                    "examples": sorted(shared)[:3],
                }
            )

    pairs.sort(key=lambda p: (max(p["left_coverage"], p["right_coverage"]), p["overlap"]),
               reverse=True)
    return {"pairs": pairs[:40], "columns_compared": len(loaded)}


def _identifier_columns(dataset_id: str, table: str) -> set[str]:
    """Columns whose values are worth following.

    A status column ("PAID") is not an identifier: following it drags in every
    other row sharing that status. Same enum hazard as the join matrix, so the
    same threshold applies -- a column must be high-cardinality to be followed.
    """
    out: set[str] = set()
    for col in _columns(dataset_id):
        if col["inferred_type"] not in ("TEXT", "INTEGER"):
            continue
        c = _quote(col["column_name"])
        try:
            stats = sqlguard.select_all(
                get_settings().db_path,
                f"SELECT COUNT(DISTINCT {c}) AS d, COUNT({c}) AS n FROM {_quote(table)}",
            )[0]
        except Exception:
            continue
        distinct, non_null = stats["d"] or 0, stats["n"] or 0
        if distinct <= ENUM_MAX_DISTINCT and non_null > distinct * 2:
            continue  # enum-like
        out.add(col["column_name"])
    return out


def trace_record(value: str, max_hops: int = 2) -> dict[str, Any]:
    """Follow one identifier across every dataset.

    Answers "what happened to this record" without reconciling anything. Hop 0
    finds rows holding the value directly; each further hop follows identifiers
    found in those rows into other datasets, which is how an invoice reaches its
    charge and the charge reaches its bank settlement.

    Read-only. It records nothing and matches nothing.
    """
    value = (value or "").strip()
    if not value:
        return {"value": value, "hits": [], "note": "empty value"}

    datasets = _datasets()
    settings = get_settings()
    columns_by_ds = {d["id"]: _columns(d["id"]) for d in datasets}
    followable = {d["id"]: _identifier_columns(d["id"], d["table_name"]) for d in datasets}

    seen_rows: set[tuple[str, int]] = set()
    hits: list[dict[str, Any]] = []
    frontier = {value}
    followed: set[str] = set()

    for hop in range(max_hops + 1):
        if not frontier:
            break
        next_frontier: set[str] = set()

        for token in sorted(frontier):
            if token in followed:
                continue
            followed.add(token)
            safe = token.replace("'", "''")

            for ds in datasets:
                table = _quote(ds["table_name"])
                for col in columns_by_ds[ds["id"]]:
                    # only search identifier-like columns, and never match a
                    # value against a status/enum column
                    if col["column_name"] not in followable[ds["id"]]:
                        continue
                    c = _quote(col["column_name"])
                    try:
                        rows = sqlguard.select_all(
                            settings.db_path,
                            f"SELECT * FROM {table} WHERE {c} = '{safe}' LIMIT 20",
                        )
                    except Exception:
                        continue
                    for r in rows:
                        key = (ds["id"], int(r["__row"]))
                        if key in seen_rows:
                            continue
                        seen_rows.add(key)
                        hits.append(
                            {
                                "hop": hop,
                                "dataset": ds["name"],
                                "dataset_id": ds["id"],
                                "row": int(r["__row"]),
                                "matched_column": col["column_name"],
                                "matched_value": token,
                                "data": {k: v for k, v in r.items() if k != "__row"},
                            }
                        )
                        for k, v in r.items():
                            if k == "__row" or v is None:
                                continue
                            if k not in followable[ds["id"]]:
                                continue
                            sv = str(v).strip()
                            if 3 <= len(sv) <= 64 and " " not in sv and sv not in followed:
                                next_frontier.add(sv)

        frontier = next_frontier

    hits.sort(key=lambda h: (h["hop"], h["dataset"], h["row"]))
    return {
        "value": value,
        "datasets_touched": sorted({h["dataset"] for h in hits}),
        "hits": hits,
    }
