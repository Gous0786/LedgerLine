"""Deterministic first pass: match everything that joins on a shared identifier.

Most of a reconciliation is not interesting. Rows that carry the same reference
and the same amount need no judgement, and having a model reason its way to them
one query at a time is the expensive way to learn nothing.

So this does the obvious pass without an LLM: take the identifier pairs the
overlap matrix already found, join on each, verify amounts where a matching
numeric column exists, and record the groups. What survives is the part that
actually needs attention.

The amount column is discovered rather than declared: for the rows that join,
each numeric pair is tested and the one that agrees on nearly all of them is
used. Without that the groups can only be scored `high` -- unique and
cross-source, but with nothing to verify -- and would never auto-accept.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings
from app.core import discovery, matching, sqlguard
from app.db import connection as db

log = logging.getLogger(__name__)

MIN_COVERAGE = 0.5
# Floor for treating a numeric column pair as the same quantity. Deliberately
# low: on a set that is a third exceptions the correct pair only agreed on 91%
# of rows, while every wrong pair agreed on 0%. The gap is enormous, so rank
# the candidates and take the best rather than demanding near-perfection.
AMOUNT_AGREEMENT = 0.60
MIN_AMOUNT_ROWS = 3


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _columns(dataset_id: str) -> list[dict[str, Any]]:
    return db.query(
        "SELECT column_name, inferred_type FROM dataset_column"
        " WHERE dataset_id = ? ORDER BY ordinal",
        (dataset_id,),
    )


def _find_amount_pair(
    left: dict[str, Any], right: dict[str, Any], lcol: str, rcol: str
) -> tuple[str, str] | None:
    """Which numeric column means the same thing on both sides?"""
    p = get_settings().db_path
    lnum = [c["column_name"] for c in _columns(left["id"])
            if c["inferred_type"] in ("REAL", "INTEGER")]
    rnum = [c["column_name"] for c in _columns(right["id"])
            if c["inferred_type"] in ("REAL", "INTEGER")]
    if not lnum or not rnum:
        return None

    scored: list[tuple[float, int, str, str]] = []
    for lc in lnum:
        for rc in rnum:
            try:
                row = sqlguard.select_all(
                    p,
                    f"SELECT COUNT(*) AS n,"
                    f" SUM(CASE WHEN ABS(COALESCE(l.{_quote(lc)},0)"
                    f"   - COALESCE(r.{_quote(rc)},0)) < 0.005 THEN 1 ELSE 0 END) AS agree"
                    f" FROM {_quote(left['table_name'])} l"
                    f" JOIN {_quote(right['table_name'])} r"
                    f"   ON l.{_quote(lcol)} = r.{_quote(rcol)}",
                )[0]
            except Exception:
                continue
            n = row["n"] or 0
            agree = row["agree"] or 0
            if n >= MIN_AMOUNT_ROWS:
                ratio = agree / n
                if ratio >= AMOUNT_AGREEMENT:
                    # Identical names break ties only; agreement still decides.
                    scored.append((ratio, 1 if lc == rc else 0, lc, rc))

    if not scored:
        return None
    scored.sort(reverse=True)
    return (scored[0][2], scored[0][3])


def auto_match_exact(min_coverage: float = MIN_COVERAGE) -> dict[str, Any]:
    """Run the exact-identifier pass across every discovered join key."""
    datasets = {d["name"]: d for d in db.query(
        "SELECT id, name, table_name FROM dataset WHERE status = 'ready'"
    )}
    types = {}
    for d in datasets.values():
        for c in _columns(d["id"]):
            types[(d["name"], c["column_name"])] = c["inferred_type"]

    pairs = discovery.find_join_candidates()["pairs"]

    # one rule per dataset pair -- the strongest key wins
    strongest: dict[tuple[str, str], dict[str, Any]] = {}
    for p in pairs:
        left, right = p["left_dataset"], p["right_dataset"]
        if types.get((left, p["left_column"])) != "TEXT":
            continue
        if types.get((right, p["right_column"])) != "TEXT":
            continue
        score = max(p["left_coverage"], p["right_coverage"])
        if score < min_coverage:
            continue
        key = tuple(sorted((left, right)))
        if key not in strongest or score > strongest[key]["_score"]:
            strongest[key] = {**p, "_score": score}

    results = []
    for p in strongest.values():
        left, right = datasets.get(p["left_dataset"]), datasets.get(p["right_dataset"])
        if not left or not right:
            continue
        lcol, rcol = p["left_column"], p["right_column"]
        amounts = _find_amount_pair(left, right, lcol, rcol)

        lt, rt = _quote(left["table_name"]), _quote(right["table_name"])
        if amounts:
            la, ra = amounts
            lamt = f"CAST(ROUND(COALESCE(l.{_quote(la)},0)*100) AS INTEGER)"
            ramt = f"-CAST(ROUND(COALESCE(r.{_quote(ra)},0)*100) AS INTEGER)"
        else:
            lamt = ramt = "NULL"

        sql = (
            f"SELECT l.{_quote(lcol)} AS group_key, '{left['name']}' AS dataset,"
            f" l.__row AS row, 'left' AS role, {lamt} AS amount_minor"
            f" FROM {lt} l JOIN {rt} r ON r.{_quote(rcol)} = l.{_quote(lcol)}"
            f" UNION ALL "
            f"SELECT r.{_quote(rcol)}, '{right['name']}', r.__row, 'right', {ramt}"
            f" FROM {lt} l JOIN {rt} r ON r.{_quote(rcol)} = l.{_quote(lcol)}"
        )

        rule = f"auto_exact__{left['name']}__{right['name']}"
        try:
            outcome = matching.propose_matches(
                rule=rule, tier=1, sql=sql,
                description=(
                    f"Exact identifier match {left['name']}.{lcol}"
                    f" = {right['name']}.{rcol}"
                    + (f", amounts {amounts[0]}/{amounts[1]}" if amounts else
                       ", no comparable amount column found")
                ),
                tolerance_minor=0,
            )
        except Exception as exc:
            results.append({"rule": rule, "error": f"{type(exc).__name__}: {exc}"})
            continue

        results.append({
            "rule": rule,
            "join": f"{left['name']}.{lcol} = {right['name']}.{rcol}",
            "amount_columns": list(amounts) if amounts else None,
            "proposed": outcome.get("proposed", 0),
            "by_confidence": outcome.get("by_confidence", {}),
            "skipped_already_matched": outcome.get("skipped_already_matched", 0),
        })

    total = sum(r.get("proposed", 0) for r in results)
    return {
        "rules_run": len(results),
        "groups_proposed": total,
        "results": results,
        "next": "Use reconciliation_status and list_unmatched to work the remainder.",
    }
