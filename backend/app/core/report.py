"""The close report: everything a reconciliation can be asked to account for.

Assembled here rather than in the interface because a report is evidence, and
evidence should not be arithmetic performed by a renderer. Every figure below
comes from a row, a decision event, or a verification record.

Two things this adds that nothing else in the system computed:

*   **Value.** Coverage was only ever counted in rows, and "542 of 621 rows"
    is an engineering number. The person signing a close asks how much money
    tied. Value is therefore summed per currency and never across them -- the
    matcher refuses to compare currencies, so the report must not add them up
    either.
*   **A checksum.** A hash over the decision set, so two runs can be compared
    without reading them. Same data and same rules give the same digest; a
    single re-decided group changes it.
"""

from __future__ import annotations

import collections
import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any

from app.config import get_settings
from app.core import matching, spine, sqlguard, transactions, verify
from app.db import connection as db

log = logging.getLogger(__name__)

# Verification codes, in the words a reviewer would use, with the note that
# says what the finding actually means.
CAUSE_WORDS: dict[str, tuple[str, str]] = {
    "timing_consistent": (
        "Settled outside the normal window",
        "Far outside the lag this dataset itself exhibits. Learned from the"
        " data, not from a contract.",
    ),
    "currency_uniform": (
        "Mixed currency in one group",
        "A group spanning two currencies. Refused outright rather than scored.",
    ),
    "no_residual_evidence": (
        "Row left beside a match",
        "A row carrying the group's own key that the rule did not take -- a"
        " refund against a matched order, typically.",
    ),
    "amounts_traceable": (
        "Amount is not in the source row",
        "A figure that appears in no cell of the row it claims to come from.",
    ),
    "single_claim_per_edge": (
        "Row claimed by two matches",
        "The same row already sits in another accepted match on this edge.",
    ),
    "balance_recomputed": (
        "Does not tie on recomputation",
        "The group claims to balance and does not when re-derived.",
    ),
}

LIMITS = [
    (
        "Fee amounts",
        "A group whose gross ties reads as exact even when the fee is wrong."
        " No fee policy is known to the system, so fee errors pass silently.",
    ),
    (
        "Timing against a contract",
        "“Late” means far outside the lag this dataset exhibits, not a"
        " breach of any agreed settlement window.",
    ),
    (
        "Value for non-amount exceptions",
        "Late and mixed-currency groups are counted, not priced; their value"
        " sits inside the open figures.",
    ),
    (
        "Anything outside these files",
        "Rows with no counterpart may be legitimately out of scope -- a"
        " statement holds fees and balance lines no order will explain.",
    ),
]


def _duplicates() -> dict[str, Any]:
    """What each file repeated, and whether those rows were counted.

    Reported per source rather than as one total: "nine rows repeated" is not
    actionable, and which file did the repeating is the first thing anyone
    asks. The policy is stated beside the count because the same number means
    opposite things depending on it -- rows set aside, or rows still in the
    figures above and waiting for someone.
    """
    rows = db.query(
        "SELECT name, row_count, duplicate_rows, near_duplicate_rows,"
        " exclude_duplicates FROM dataset WHERE status = 'ready'"
        " AND (duplicate_rows > 0 OR near_duplicate_rows > 0) ORDER BY name"
    )
    per_source = [
        {
            "dataset": r["name"],
            "rows": r["row_count"],
            "identical": r["duplicate_rows"] or 0,
            "same_event_different_id": r["near_duplicate_rows"] or 0,
            "excluded": bool(r["exclude_duplicates"]),
        }
        for r in rows
    ]
    return {
        "sources": per_source,
        "rows_marked": sum(
            s["identical"] + s["same_event_different_id"] for s in per_source
        ),
        "rows_excluded": sum(
            s["identical"] + s["same_event_different_id"]
            for s in per_source if s["excluded"]
        ),
    }


def _limits() -> list[tuple[str, str]]:
    """The standing limits, plus any this particular close earned.

    A limitation that does not apply is noise, and noise is how a limits
    section stops being read. The inferred-key caveat is only worth a reader's
    attention when a key really was read out of free text.
    """
    limits = list(LIMITS)

    counted = db.query_one(
        "SELECT COUNT(*) n FROM dataset WHERE status = 'ready'"
        " AND exclude_duplicates = 0"
        " AND (duplicate_rows > 0 OR near_duplicate_rows > 0)"
    )
    if (counted or {}).get("n"):
        limits.insert(0, (
            "Repeated rows are still counted",
            "At least one source records the same event more than once, and"
            " those rows remain in every figure above. They are marked, and the"
            " groups holding them read as breaks rather than as matches --"
            " which is the intended outcome: a file disagreeing with itself is"
            " a finding, not an arithmetic error to net out.",
        ))

    inferred = db.query(
        "SELECT DISTINCT description FROM match_proposal"
        " WHERE description LIKE '%(read from %'"
    )
    if inferred:
        limits.insert(0, (
            "Keys read out of free text",
            "At least one leg was joined on a reference found inside a"
            " narration rather than in a column of its own. Rows naming two"
            " references were left unmatched rather than guessed at, and every"
            " such leg had to be corroborated by the amounts -- but the join"
            " itself is inferred, and the method table says which one.",
        ))
    return limits


def _period_and_sources() -> tuple[dict[str, str | None], list[dict[str, Any]]]:
    p = get_settings().db_path
    sources: list[dict[str, Any]] = []
    seen: list[str] = []
    for d in db.query(
        "SELECT id, name, table_name, row_count, byte_size, duplicate_rows,"
        " near_duplicate_rows, exclude_duplicates FROM dataset"
        " WHERE status = 'ready' ORDER BY created_at"
    ):
        cols = db.query(
            "SELECT column_name FROM dataset_column WHERE dataset_id = ?"
            " AND inferred_type IN ('DATE','TIMESTAMP')",
            (d["id"],),
        )
        lo = hi = None
        for c in cols:
            name = c["column_name"].replace('"', '""')
            try:
                r = sqlguard.select_all(
                    p,
                    f'SELECT MIN("{name}") a, MAX("{name}") b FROM "{d["table_name"]}"',
                )[0]
            except Exception:
                continue
            a, b = str(r["a"] or ""), str(r["b"] or "")
            if a[:4].isdigit():
                lo = min(lo, a) if lo else a
                hi = max(hi, b) if hi else b
        if lo:
            seen += [lo, hi or lo]
        ncols = db.query_one(
            "SELECT COUNT(*) n FROM dataset_column WHERE dataset_id = ?", (d["id"],)
        )["n"]
        sources.append({
            "name": d["name"], "rows": d["row_count"], "columns": ncols,
            "bytes": d["byte_size"], "from": lo, "to": hi,
        })
    period = {
        "from": min(seen)[:10] if seen else None,
        "to": max(seen)[:10] if seen else None,
    }
    return period, sources


def _value_by_currency(ctx: verify.Context) -> dict[str, dict[str, int]]:
    """Money reconciled, still open, and not tying -- per currency.

    The gross of a group is one side of it: members are signed so a balancing
    group sums to zero, so adding every member would report nothing. The
    positive side is the value the match accounts for.
    """
    out: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for p in db.query(
        "SELECT id, status, confidence, balance_minor FROM match_proposal"
    ):
        members = db.query(
            "SELECT dataset_id, row, amount_minor FROM match_member"
            " WHERE proposal_id = ?",
            (p["id"],),
        )
        if not members:
            continue
        ctx.prefetch([(m["dataset_id"], int(m["row"])) for m in members])
        code = "unknown"
        for m in members:
            col = ctx.currency.get(m["dataset_id"])
            row = ctx.row(m["dataset_id"], m["row"])
            if col and row and row.get(col):
                code = str(row[col]).strip().upper()
                break
        gross = sum(
            int(m["amount_minor"] or 0) for m in members if (m["amount_minor"] or 0) > 0
        )
        out[code]["reconciled" if p["status"] == "accepted" else "open"] += gross
        if p["confidence"] == matching.UNBALANCED:
            out[code]["residual"] += abs(int(p["balance_minor"] or 0))
    return {c: dict(v) for c, v in sorted(out.items())}


def _exceptions() -> list[dict[str, Any]]:
    """Findings grouped by cause, because that is what a person acts on.

    "Thirty settlements arrived late" is a job. "Rule auto_batch produced
    thirty exceptions" is a rule name.
    """
    reasons: collections.Counter = collections.Counter()
    for r in db.query(
        "SELECT invariants FROM verification v"
        " WHERE v.id = (SELECT MAX(id) FROM verification WHERE proposal_id = v.proposal_id)"
        "   AND v.status = 'fail'"
    ):
        try:
            for inv in json.loads(r["invariants"]):
                if inv.get("passed") is False:
                    reasons[inv["code"]] += 1
        except Exception:
            continue

    out: list[dict[str, Any]] = []
    for code, n in reasons.most_common():
        title, note = CAUSE_WORDS.get(code, (code.replace("_", " "), ""))
        out.append({"cause": title, "code": code, "groups": n, "value_minor": None,
                    "note": note})

    off = db.query_one(
        "SELECT COUNT(*) n, COALESCE(SUM(ABS(balance_minor)), 0) v"
        " FROM match_proposal WHERE confidence = ?",
        (matching.UNBALANCED,),
    )
    if off and off["n"]:
        out.append({
            "cause": "Amounts do not tie", "code": "unbalanced",
            "groups": off["n"], "value_minor": off["v"],
            "note": "The two sides disagree by the amount shown.",
        })

    amb = db.query_one(
        "SELECT COUNT(*) n FROM match_proposal WHERE confidence = ?",
        (matching.AMBIGUOUS,),
    )
    if amb and amb["n"]:
        out.append({
            "cause": "More than one candidate", "code": "ambiguous",
            "groups": amb["n"], "value_minor": None,
            "note": "A row that could join two ways, so no join was claimed.",
        })

    loose = matching.reconciliation_status()["datasets"]
    rows = sum(d["matched_in_no_edge"] or 0 for d in loose)
    if rows:
        detail = ", ".join(
            f"{d['matched_in_no_edge']} {d['dataset']}"
            for d in sorted(loose, key=lambda d: -(d["matched_in_no_edge"] or 0))
            if d["matched_in_no_edge"]
        )
        out.append({
            "cause": "In no match at all", "code": "unmatched",
            "groups": None, "rows": rows, "value_minor": None,
            "note": f"{detail}. Some are legitimately out of scope.",
        })
    return out


def _decisions() -> dict[str, int]:
    kinds = {
        (r["kind"], r["actor"]): r["n"]
        for r in db.query(
            "SELECT kind, actor, COUNT(*) n FROM match_event GROUP BY 1, 2"
        )
    }
    status = {
        r["status"]: r["n"]
        for r in db.query("SELECT status, COUNT(*) n FROM match_proposal GROUP BY 1")
    }
    return {
        "proposed": sum(v for (k, _), v in kinds.items() if k == "proposed"),
        "auto_released": sum(v for (k, _), v in kinds.items() if k == "auto_accepted"),
        "human_accepted": kinds.get(("accepted", "human"), 0),
        "rejected": kinds.get(("rejected", "human"), 0),
        # The audit line. Never hidden, never merged into the accepted count.
        "overridden": sum(
            v for (k, _), v in kinds.items() if k == "verification_overridden"
        ),
        "held": sum(v for (k, _), v in kinds.items() if k == "verification_failed"),
        "open": status.get("pending", 0) + status.get("review_later", 0),
        "accepted_total": status.get("accepted", 0),
    }


def _checksum() -> str:
    """A digest over the decisions, not the data.

    Same sources and same rules give the same string; one group re-decided
    changes it. It answers "is this the report I read on Tuesday" without
    reading it again.
    """
    rows = db.query(
        "SELECT p.id, p.rule, p.group_key, p.confidence, p.status,"
        " GROUP_CONCAT(m.dataset_id || ':' || m.row) AS members"
        " FROM match_proposal p LEFT JOIN match_member m ON m.proposal_id = p.id"
        " GROUP BY p.id ORDER BY p.rule, p.group_key"
    )
    h = hashlib.sha256()
    for r in rows:
        members = ",".join(sorted((r["members"] or "").split(",")))
        h.update(
            f"{r['rule']}|{r['group_key']}|{r['confidence']}|{r['status']}|{members}\n"
            .encode()
        )
    return h.hexdigest()


def build() -> dict[str, Any]:
    """Everything the close report shows, in one read."""
    ctx = verify.Context()
    period, sources = _period_and_sources()

    status = matching.reconciliation_status()
    datasets = [{k: v for k, v in d.items() if k != "examples"} for d in status["datasets"]]
    edges = [
        {"edge": e["edge"],
         "sides": [{k: v for k, v in s.items() if k != "unmatched_examples"}
                   for s in e["sides"]]}
        for e in status["edges"]
    ]
    total_rows = sum(d["rows"] or 0 for d in datasets)
    total_matched = sum(d["matched_in_any_edge"] or 0 for d in datasets)

    resolved = spine.resolve_spine()
    tx: dict[str, Any] = {"spine": None, "stages": [], "counts": {}, "total": 0,
                          "examples": []}
    if resolved.get("dataset_id"):
        try:
            view = transactions.build(resolved["dataset_id"])
            tx = {
                "spine": view["spine"]["name"],
                "spine_reason": resolved.get("reason"),
                "stages": view["stages"],
                "counts": dict(view["counts"]),
                "total": len(view["transactions"]),
                "examples": [
                    {"key": t["key"], "state": t["state"], "reason": t["reason"]}
                    for t in view["transactions"]
                    if t["state"] in ("exception", "incomplete", "unmatched")
                ][:8],
            }
        except Exception:
            log.warning("could not assemble transactions for the report", exc_info=True)

    verified = db.query_one(
        "SELECT COUNT(*) n, SUM(status = 'pass') p FROM verification"
    ) or {}
    run = db.query_one(
        "SELECT id, title, started_at, finished_at FROM run"
        " ORDER BY started_at DESC, rowid DESC LIMIT 1"
    )

    return {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "checksum": _checksum()[:24],
        "run": run,
        "model": get_settings().model_orchestrator,
        "period": period,
        "sources": sources,
        "duplicates": _duplicates(),
        "value": _value_by_currency(ctx),
        "coverage": {
            "datasets": datasets,
            "edges": edges,
            "totals": {"rows": total_rows, "matched": total_matched,
                       "unmatched": total_rows - total_matched},
        },
        "transactions": tx,
        "exceptions": _exceptions(),
        "decisions": _decisions(),
        "verification": {
            "verified": verified.get("n", 0) or 0,
            "passed": verified.get("p", 0) or 0,
            "failed": (verified.get("n", 0) or 0) - (verified.get("p", 0) or 0),
        },
        "rules": db.query(
            "SELECT r.rule, r.status, r.approved_by,"
            " (SELECT COUNT(*) FROM match_proposal p WHERE p.rule = r.rule) proposals,"
            " (SELECT description FROM match_proposal p WHERE p.rule = r.rule LIMIT 1)"
            "   AS description"
            " FROM rule_trust r ORDER BY proposals DESC"
        ),
        "limits": [{"title": t, "note": n} for t, n in _limits()],
    }
