"""Match proposal engine.

The agent never passes rows -- it passes SQL. This module runs that SQL,
groups the result, scores each group from *evidence*, and records proposals.
Bulk rows stay in SQLite; the agent gets counts and a small sample.

Three invariants live here rather than in the prompt, because a prompt
instruction the model forgets once produces silent false matches:

1.  Rows already inside an accepted match are excluded, so tier ordering is
    safe by construction and nothing is matched twice.
2.  Confidence is computed, never supplied. A row that could join two ways is
    `ambiguous` by structure regardless of how plausible it looks.
3.  Only `exact` auto-accepts. Everything else waits for a human.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.config import get_settings
from app.core import sqlguard
from app.db import connection as db

log = logging.getLogger(__name__)

REQUIRED_COLUMNS = {"group_key", "dataset", "row"}
MAX_GROUPS = 5_000

# confidence values
EXACT = "exact"
HIGH = "high"
AMBIGUOUS = "ambiguous"
UNBALANCED = "unbalanced"


class MatchError(Exception):
    pass


def _dataset_lookup() -> dict[str, str]:
    """Accept either dataset id or name in the agent's SQL output."""
    out: dict[str, str] = {}
    for r in db.query("SELECT id, name, table_name FROM dataset"):
        out[r["id"]] = r["id"]
        out[r["name"]] = r["id"]
        out[r["table_name"]] = r["id"]
    return out


def _claimed_rows() -> dict[str, set[tuple[str, int]]]:
    """Rows already inside an accepted match, keyed by *edge*.

    Exclusion must be per-relationship, not global. A Stripe charge legitimately
    belongs to two matches -- it settles an invoice, and it is part of a bank
    payout. Keying on the group's dataset signature lets a row be claimed once
    per relationship while still preventing it being matched twice within one.
    """
    rows = db.query(
        "SELECT m.dataset_id, m.row, p.datasets FROM match_member m"
        " JOIN match_proposal p ON p.id = m.proposal_id"
        " WHERE p.status = 'accepted'"
    )
    out: dict[str, set[tuple[str, int]]] = {}
    for r in rows:
        out.setdefault(r["datasets"] or "", set()).add((r["dataset_id"], int(r["row"])))
    return out


def _existing_group_keys(rule: str) -> set[str]:
    rows = db.query(
        "SELECT group_key FROM match_proposal WHERE rule = ? AND status != 'rejected'",
        (rule,),
    )
    return {r["group_key"] for r in rows}


def rule_status(rule: str) -> str:
    row = db.query_one("SELECT status FROM rule_trust WHERE rule = ?", (rule,))
    return row["status"] if row else "unproven"


def _register_rule(rule: str) -> None:
    db.execute(
        "INSERT INTO rule_trust (rule, status) VALUES (?, 'unproven')"
        " ON CONFLICT(rule) DO NOTHING",
        (rule,),
    )


def list_rules() -> list[dict[str, Any]]:
    return db.query(
        "SELECT r.rule, r.status, r.first_seen, r.approved_at, r.approved_by,"
        "  (SELECT COUNT(*) FROM match_proposal p WHERE p.rule = r.rule) AS proposals,"
        "  (SELECT COUNT(*) FROM match_proposal p WHERE p.rule = r.rule"
        "     AND p.status = 'pending') AS pending"
        " FROM rule_trust r ORDER BY r.first_seen DESC"
    )


def trust_rule(rule: str, actor: str = "human", note: str | None = None) -> dict[str, Any]:
    """Approve a rule, and accept the exact matches it is already holding.

    Only `exact` proposals are released. Ambiguous and unbalanced ones still
    need individual judgement -- approving the rule says the rule is right, not
    that every group it produced is.
    """
    if not db.query_one("SELECT rule FROM rule_trust WHERE rule = ?", (rule,)):
        raise MatchError(f"unknown rule {rule!r}")

    pending = db.query(
        "SELECT id FROM match_proposal"
        " WHERE rule = ? AND status = 'pending' AND confidence = ?",
        (rule, EXACT),
    )
    with db.cursor() as conn:
        conn.execute("BEGIN")
        try:
            conn.execute(
                "UPDATE rule_trust SET status = 'trusted', approved_at = datetime('now'),"
                " approved_by = ?, note = ? WHERE rule = ?",
                (actor, note, rule),
            )
            for r in pending:
                conn.execute(
                    "UPDATE match_proposal SET status = 'accepted' WHERE id = ?", (r["id"],)
                )
                conn.execute(
                    "INSERT INTO match_event (proposal_id, kind, actor, detail)"
                    " VALUES (?, 'accepted', ?, ?)",
                    (r["id"], actor, json.dumps({"via": "rule approved", "rule": rule})),
                )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return {"rule": rule, "status": "trusted", "released": len(pending)}


def propose_matches(
    *,
    rule: str,
    tier: int,
    sql: str,
    description: str = "",
    run_id: str | None = None,
) -> dict[str, Any]:
    """Execute the agent's matching SQL and record the resulting groups."""
    raw = sqlguard.select_all(get_settings().db_path, sql)
    if not raw:
        return {
            "rule": rule,
            "tier": tier,
            "proposed": 0,
            "auto_accepted": 0,
            "pending": 0,
            "note": "query returned no rows",
        }

    missing = REQUIRED_COLUMNS - set(raw[0].keys())
    if missing:
        raise MatchError(
            f"query must return columns {sorted(REQUIRED_COLUMNS)};"
            f" missing {sorted(missing)}"
        )

    _register_rule(rule)
    trusted = rule_status(rule) == "trusted"

    lookup = _dataset_lookup()
    claimed = _claimed_rows()
    seen_keys = _existing_group_keys(rule)

    # --- assemble groups -------------------------------------------------
    groups: dict[str, dict[tuple[str, int], dict[str, Any]]] = {}
    unknown_datasets: set[str] = set()
    for r in raw:
        key = str(r["group_key"])
        ds_raw = str(r["dataset"])
        ds_id = lookup.get(ds_raw)
        if ds_id is None:
            unknown_datasets.add(ds_raw)
            continue
        # A join that fans out (many gateway rows against one bank row) repeats
        # that bank row per match. It is one member either way -- collapsing it
        # avoids both a PK violation and, worse, double-counting its amount.
        member_key = (ds_id, int(r["row"]))
        bucket = groups.setdefault(key, {})
        if member_key not in bucket:
            bucket[member_key] = {
                "dataset_id": ds_id,
                "row": int(r["row"]),
                "role": r.get("role"),
                "amount_minor": r.get("amount_minor"),
            }

    if unknown_datasets:
        raise MatchError(
            f"unknown dataset(s) in results: {sorted(unknown_datasets)};"
            " use the dataset id or name"
        )
    if len(groups) > MAX_GROUPS:
        raise MatchError(f"{len(groups)} groups exceeds the {MAX_GROUPS} cap; narrow the rule")

    # --- ambiguity: does any row belong to more than one group? ----------
    collapsed: dict[str, list[dict[str, Any]]] = {
        key: list(bucket.values()) for key, bucket in groups.items()
    }
    duplicates_collapsed = sum(len(b) for b in groups.values())

    row_groups: dict[tuple[str, int], set[str]] = {}
    for key, members in collapsed.items():
        for m in members:
            row_groups.setdefault((m["dataset_id"], m["row"]), set()).add(key)
    contested = {k for k, keys in row_groups.items() if len(keys) > 1}

    counts = {
        "proposed": 0,
        "auto_accepted": 0,
        "pending": 0,
        "skipped_already_matched": 0,
        "skipped_duplicate": 0,
        "skipped_single_member": 0,
    }
    by_confidence: dict[str, int] = {}
    sample: list[dict[str, Any]] = []

    for key, members in collapsed.items():
        if key in seen_keys:
            counts["skipped_duplicate"] += 1
            continue
        if len(members) < 2:
            counts["skipped_single_member"] += 1
            continue

        datasets = sorted({m["dataset_id"] for m in members})
        edge = ",".join(datasets)
        # only rows already matched *within this same relationship* are excluded
        if any((m["dataset_id"], m["row"]) in claimed.get(edge, ()) for m in members):
            counts["skipped_already_matched"] += 1
            continue
        amounts = [m["amount_minor"] for m in members]
        has_amounts = all(a is not None for a in amounts)
        balance = int(sum(int(a) for a in amounts)) if has_amounts else None

        if any((m["dataset_id"], m["row"]) in contested for m in members):
            confidence = AMBIGUOUS
        elif has_amounts and balance != 0:
            confidence = UNBALANCED
        elif len(datasets) < 2:
            confidence = AMBIGUOUS  # a "match" inside one source is not a match
        elif has_amounts:
            confidence = EXACT
        else:
            confidence = HIGH

        # `exact` is necessary but not sufficient: an unscoped rule produces
        # flawless matches for rows nobody asked about. A rule earns
        # auto-accept by being approved once.
        status = "accepted" if (confidence == EXACT and trusted) else "pending"

        with db.cursor() as conn:
            conn.execute("BEGIN")
            try:
                cur = conn.execute(
                    "INSERT INTO match_proposal"
                    " (run_id, rule, tier, group_key, confidence, status,"
                    "  member_count, datasets, balance_minor, description)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        run_id, rule, tier, key, confidence, status,
                        len(members), edge, balance, description,
                    ),
                )
                pid = cur.lastrowid
                conn.executemany(
                    "INSERT INTO match_member"
                    " (proposal_id, dataset_id, row, role, amount_minor)"
                    " VALUES (?,?,?,?,?)",
                    [
                        (pid, m["dataset_id"], m["row"], m["role"], m["amount_minor"])
                        for m in members
                    ],
                )
                conn.execute(
                    "INSERT INTO match_event (proposal_id, kind, actor, detail)"
                    " VALUES (?, 'proposed', 'agent', ?)",
                    (pid, json.dumps({"rule": rule, "tier": tier, "confidence": confidence})),
                )
                if status == "accepted":
                    conn.execute(
                        "INSERT INTO match_event (proposal_id, kind, actor, detail)"
                        " VALUES (?, 'auto_accepted', 'system', ?)",
                        (pid, json.dumps({
                            "reason": "exact, and rule previously approved",
                            "rule": rule,
                        })),
                    )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

        counts["proposed"] += 1
        by_confidence[confidence] = by_confidence.get(confidence, 0) + 1
        if status == "accepted":
            counts["auto_accepted"] += 1
            claimed.setdefault(edge, set()).update(
                (m["dataset_id"], m["row"]) for m in members
            )
        else:
            counts["pending"] += 1

        if len(sample) < 12:
            sample.append(
                {
                    "proposal_id": pid,
                    "group_key": key,
                    "confidence": confidence,
                    "members": len(members),
                    "balance_minor": balance,
                }
            )

    created_keys = [g["group_key"] for g in sample]
    return {
        "rule": rule,
        "tier": tier,
        "rule_status": "trusted" if trusted else "unproven",
        **counts,
        "unique_members": duplicates_collapsed,
        "by_confidence": by_confidence,
        # The groups actually created -- if this is wider than what was asked
        # about, the rule was not scoped.
        "group_keys": created_keys,
        "sample": sample,
    }


# ------------------------------------------------------------------ reads --

def list_proposals(status: str | None = None, limit: int = 25) -> list[dict[str, Any]]:
    sql = (
        "SELECT id, rule, tier, group_key, confidence, status, member_count,"
        " datasets, balance_minor, created_at FROM match_proposal"
    )
    params: tuple = ()
    if status:
        sql += " WHERE status = ?"
        params = (status,)
    sql += " ORDER BY id DESC LIMIT ?"
    return db.query(sql, (*params, max(1, min(limit, 200))))


def get_proposal(proposal_id: int) -> dict[str, Any]:
    p = db.query_one("SELECT * FROM match_proposal WHERE id = ?", (proposal_id,))
    if not p:
        raise MatchError(f"no proposal {proposal_id}")

    members = db.query(
        "SELECT m.dataset_id, d.name AS dataset, m.row, m.role, m.amount_minor"
        " FROM match_member m JOIN dataset d ON d.id = m.dataset_id"
        " WHERE m.proposal_id = ? ORDER BY d.name, m.row",
        (proposal_id,),
    )
    # pull the actual source rows so evidence is inspectable
    for m in members:
        ds = db.query_one("SELECT table_name FROM dataset WHERE id = ?", (m["dataset_id"],))
        if ds:
            found = sqlguard.select_all(
                get_settings().db_path,
                f'SELECT * FROM "{ds["table_name"]}" WHERE __row = {int(m["row"])}',
            )
            m["data"] = found[0] if found else None

    events = db.query(
        "SELECT ts, kind, actor, detail FROM match_event"
        " WHERE proposal_id = ? ORDER BY id",
        (proposal_id,),
    )
    return {**p, "members": members, "events": events}


def _identifying_columns(dataset_id: str, limit: int = 3) -> list[str]:
    """Columns most useful for naming a row: unique-ish text identifiers."""
    cols = db.query(
        "SELECT column_name, inferred_type FROM dataset_column"
        " WHERE dataset_id = ? ORDER BY ordinal",
        (dataset_id,),
    )
    text_cols = [c["column_name"] for c in cols if c["inferred_type"] == "TEXT"]
    return (text_cols or [c["column_name"] for c in cols])[:limit]


def _unmatched_examples(dataset_id: str, matched_rows: set[int], limit: int = 3
                        ) -> list[dict[str, Any]]:
    ds = db.query_one("SELECT table_name FROM dataset WHERE id = ?", (dataset_id,))
    if not ds:
        return []
    cols = _identifying_columns(dataset_id)
    if not cols:
        return []
    picked = ", ".join(f'"{c}"' for c in cols)
    exclude = ""
    if matched_rows:
        exclude = " WHERE __row NOT IN (" + ",".join(str(int(r)) for r in matched_rows) + ")"
    try:
        return sqlguard.select_all(
            get_settings().db_path,
            f'SELECT __row, {picked} FROM "{ds["table_name"]}"{exclude}'
            f" ORDER BY __row LIMIT {limit}",
        )
    except Exception:
        return []


def reconciliation_status() -> dict[str, Any]:
    """Coverage per dataset and, more usefully, per *edge*.

    Global coverage lies in a multi-hop flow: a gateway charge that settles into
    the bank counts as "matched" even when no invoice explains it. Per-edge
    coverage is what actually surfaces that break.
    """
    datasets = db.query(
        "SELECT id, name, row_count FROM dataset WHERE status = 'ready' ORDER BY created_at"
    )
    names = {d["id"]: d["name"] for d in datasets}
    by_edge = _claimed_rows()
    all_claimed = {row for rows in by_edge.values() for row in rows}

    per_dataset = []
    for d in datasets:
        matched_rows = {r for (ds, r) in all_claimed if ds == d["id"]}
        entry = {
            "dataset": d["name"],
            "dataset_id": d["id"],
            "rows": d["row_count"],
            "matched_in_any_edge": len(matched_rows),
            "matched_in_no_edge": (d["row_count"] or 0) - len(matched_rows),
        }
        # Never report a count without the rows behind it: a bare number with no
        # identity is an invitation to invent one.
        if entry["matched_in_no_edge"]:
            entry["examples"] = _unmatched_examples(d["id"], matched_rows, limit=5)
        per_dataset.append(entry)

    edges = []
    for edge, rows in sorted(by_edge.items()):
        members = edge.split(",")
        detail = []
        for ds_id in members:
            total = next((d["row_count"] for d in datasets if d["id"] == ds_id), 0) or 0
            matched_rows = {r for (d, r) in rows if d == ds_id}
            side = {
                "dataset": names.get(ds_id, ds_id),
                "dataset_id": ds_id,
                "rows": total,
                "matched": len(matched_rows),
                "unmatched": total - len(matched_rows),
            }
            # A bare count is easy to skim past; concrete rows are not. This is
            # where a row that is settled downstream but unexplained upstream
            # actually becomes visible.
            if side["unmatched"]:
                side["unmatched_examples"] = _unmatched_examples(ds_id, matched_rows)
            detail.append(side)
        edges.append({"edge": " <-> ".join(names.get(m, m) for m in members), "sides": detail})

    totals = db.query(
        "SELECT status, confidence, COUNT(*) AS n FROM match_proposal"
        " GROUP BY status, confidence"
    )
    return {"datasets": per_dataset, "edges": edges, "proposals": totals}


def list_unmatched(
    dataset_id: str,
    counterpart_dataset_id: str | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """Rows with no accepted match.

    Pass `counterpart_dataset_id` to scope the question to one relationship --
    "which charges have no invoice?" -- rather than "which rows are in no match
    at all?", which hides breaks in a multi-hop flow.
    """
    ds = db.query_one("SELECT * FROM dataset WHERE id = ?", (dataset_id,))
    if not ds:
        raise MatchError(f"unknown dataset {dataset_id!r}")

    by_edge = _claimed_rows()
    if counterpart_dataset_id:
        other = db.query_one(
            "SELECT name FROM dataset WHERE id = ?", (counterpart_dataset_id,)
        )
        if not other:
            raise MatchError(f"unknown dataset {counterpart_dataset_id!r}")
        relevant = {
            row
            for edge, rows in by_edge.items()
            if counterpart_dataset_id in edge.split(",") and dataset_id in edge.split(",")
            for row in rows
        }
        scope = f"unmatched against {other['name']}"
    else:
        relevant = {row for rows in by_edge.values() for row in rows}
        scope = "unmatched in any relationship"

    claimed = sorted(r for (d, r) in relevant if d == dataset_id)
    table = ds["table_name"]
    exclude = ""
    if claimed:
        exclude = " WHERE __row NOT IN (" + ",".join(str(int(r)) for r in claimed) + ")"

    total = sqlguard.select_all(
        get_settings().db_path, f'SELECT COUNT(*) AS n FROM "{table}"{exclude}'
    )[0]["n"]
    rows = sqlguard.select_all(
        get_settings().db_path,
        f'SELECT * FROM "{table}"{exclude} ORDER BY __row LIMIT {max(1, min(limit, 100))}',
    )
    return {"dataset": ds["name"], "scope": scope, "unmatched": total, "rows": rows}


# ----------------------------------------------------------------- writes --
# Called by the API on human action -- deliberately not exposed to the agent.

def set_status(proposal_id: int, status: str, actor: str = "human",
               note: str | None = None) -> dict[str, Any]:
    if status not in ("accepted", "rejected", "pending", "review_later"):
        raise MatchError(f"bad status {status!r}")
    p = db.query_one("SELECT id FROM match_proposal WHERE id = ?", (proposal_id,))
    if not p:
        raise MatchError(f"no proposal {proposal_id}")

    with db.cursor() as conn:
        conn.execute("BEGIN")
        try:
            conn.execute(
                "UPDATE match_proposal SET status = ? WHERE id = ?", (status, proposal_id)
            )
            conn.execute(
                "INSERT INTO match_event (proposal_id, kind, actor, detail) VALUES (?,?,?,?)",
                (proposal_id, status, actor, json.dumps({"note": note}) if note else None),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return {"proposal_id": proposal_id, "status": status}
