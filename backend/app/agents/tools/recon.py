"""Tools exposed to the reconciliation agent.

Docstrings here are the agent's interface -- they are what the model reads to
decide what to call, so they carry the contract, not just a label.

Deliberately absent: anything that accepts or rejects a proposal, writes to a
`ds_*` table, or lets the agent supply its own confidence. Proposing and
approving are different jobs.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings
from app.core import automatch, discovery, matching, spine, sqlguard
from app.db import connection as db

log = logging.getLogger(__name__)


# --------------------------------------------------------- understanding --

def list_datasets() -> dict[str, Any]:
    """Every dataset with its columns, types, row count and any views. Start here."""
    out = []
    for d in db.query(
        "SELECT id, name, row_count, table_name FROM dataset"
        " WHERE status = 'ready' ORDER BY created_at"
    ):
        cols = db.query(
            "SELECT column_name, inferred_type FROM dataset_column"
            " WHERE dataset_id = ? ORDER BY ordinal",
            (d["id"],),
        )
        views = db.query(
            "SELECT name FROM dataset_view WHERE dataset_id = ?", (d["id"],)
        )
        out.append(
            {
                "dataset_id": d["id"],
                "name": d["name"],
                "table": d["table_name"],
                "rows": d["row_count"],
                "columns": [f"{c['column_name']}:{c['inferred_type']}" for c in cols],
                "views": [v["name"] for v in views],
            }
        )
    return {"datasets": out}


def profile_columns(dataset_id: str) -> dict[str, Any]:
    """Per-column stats: distinct count, nulls, min/max, top values, uniqueness
    and a pattern signature. Use it to tell identifiers from amounts.
    """
    return discovery.profile_columns(dataset_id)


def find_join_candidates() -> dict[str, Any]:
    """Find columns across datasets holding the same values.

    Measures real value overlap, so it finds join keys whose names differ.
    Returns overlap counts, per-side coverage and examples. Coverage below
    1.0 means some values have no counterpart -- usually where breaks are.
    """
    return discovery.find_join_candidates()


def trace_record(value: str) -> dict[str, Any]:
    """Follow one identifier across every dataset. READ ONLY, records nothing.

    The right tool for questions about specific records ("what happened to
    INV-805"). Finds rows holding the value, then follows identifiers in
    those rows into other sources. Never reconcile just to answer a question.
    """
    return discovery.trace_record(value)


def set_spine(dataset_id: str, reason: str) -> dict[str, Any]:
    """Declare which source starts a transaction, for the end-to-end view.

    Call only when the request names it -- "reconcile all orders" makes
    orders the spine. Otherwise it is inferred from foreign keys.
    """
    try:
        return spine.set_spine(dataset_id, reason, actor="agent")
    except ValueError as exc:
        return {"error": str(exc)}


# ----------------------------------------------------------------- query --

def run_sql(sql: str, limit: int) -> dict[str, Any]:
    """Run one read-only SELECT (or WITH). Returns columns and `limit` rows.

    Every result stays in context and is resent on every later turn, so keep
    limit small -- 5 to 10 is enough to understand shape. Do not re-query a
    table you have already seen.

    For structure use profile_columns and find_join_candidates instead: they
    return summaries, not rows, and cost a fraction as much.
    """
    try:
        return sqlguard.select(get_settings().db_path, sql, limit=limit or 10)
    except sqlguard.SqlError as exc:
        return {"error": str(exc)}


def create_view(name: str, sql: str) -> dict[str, Any]:
    """Create or replace a named SQL view (name must start with `v_`).

    Normalise once here instead of in every rule: money to integer minor
    units via CAST(ROUND(col*100) AS INTEGER), separate debit/credit columns
    into one signed amount, reference namespaces, non-transaction rows.

    Float sums do not compare equal, so always match on the integer form.
    """
    if not name.startswith("v_") or not name.replace("_", "").isalnum():
        return {"error": "view name must start with 'v_' and be alphanumeric/underscore"}
    try:
        body = sqlguard.validate(sql)
    except sqlguard.SqlError as exc:
        return {"error": str(exc)}

    try:
        with db.cursor() as conn:
            conn.execute(f'DROP VIEW IF EXISTS "{name}"')
            conn.execute(f'CREATE VIEW "{name}" AS {body}')
        probe = sqlguard.select(get_settings().db_path, f'SELECT * FROM "{name}"', limit=3)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}

    db.execute(
        "INSERT INTO dataset_view (name, dataset_id, sql) VALUES (?, NULL, ?)"
        " ON CONFLICT(name) DO UPDATE SET sql = excluded.sql",
        (name, body),
    )
    return {"created": name, "columns": probe["columns"], "sample": probe["rows"]}


# ------------------------------------------------------------ reconciling --

def auto_match_exact() -> dict[str, Any]:
    """Run the obvious pass first. Deterministic, no reasoning required.

    Joins every identifier pair the overlap matrix found, discovers the
    matching amount column on each, and records the groups. Clears the bulk of
    a reconciliation in one call for zero tokens.

    ALWAYS CALL THIS FIRST. Then work only on what it leaves behind: read
    reconciliation_status and list_unmatched, and investigate the remainder.
    Do not hand-write rules for joins this already covers.

    It only does row-level equality. Batch settlements, where one credit covers
    many rows, still need an aggregate rule from you.
    """
    return automatch.auto_match_exact()



def propose_matches(
    rule: str, tier: int, sql: str, description: str, tolerance_minor: int
) -> dict[str, Any]:
    """Propose matches by running a matching query. Pass SQL, never rows.

    This is the cheap way to test a rule: it returns counts, never rows, and a
    new rule name is unproven so nothing it creates is final. Send a query and
    read the result rather than rehearsing it with run_sql.
    Required columns: group_key, dataset, row (plus optional role,
    amount_minor). A bad shape returns an error spelling out the contract.

    Sign amount_minor so a balancing group sums to zero -- invoice +25000,
    charge -25000. Wrong signs make correct matches look like breaks.

    YOUR QUERY DEFINES THE SCOPE. Everything it returns gets reconciled, so
    filter to what was asked. Check `group_keys` in the result against the
    request; wider means the rule was not scoped.

    tolerance_minor: residual allowed per group in minor units (100 = 1.00,
    0 = exact tie). Keep it tight -- absorbed residual is still unexplained
    money and is reported back.

    Confidence is computed here, never supplied by you. Earlier tiers are
    excluded automatically.
    """
    try:
        return matching.propose_matches(
            rule=rule, tier=tier, sql=sql, description=description,
            tolerance_minor=tolerance_minor,
        )
    except (matching.MatchError, sqlguard.SqlError) as exc:
        return {"error": str(exc)}


def list_proposals(status: str, limit: int) -> dict[str, Any]:
    """List recorded match proposals. `status` is pending, accepted, rejected,
    or an empty string for all. Returns summaries, not member rows."""
    return {"proposals": matching.list_proposals(status or None, limit or 25)}


def get_proposal(proposal_id: int) -> dict[str, Any]:
    """Full detail for one proposal: its member rows with source data, and its
    event history in order. Use it to explain a match or a break."""
    try:
        return matching.get_proposal(proposal_id)
    except matching.MatchError as exc:
        return {"error": str(exc)}


def reconciliation_status() -> dict[str, Any]:
    """Coverage per dataset and per relationship.

    Read the per-edge numbers: a charge that settles into the bank counts as
    matched overall even when no invoice explains it. Only the edge
    breakdown reveals that gap.
    """
    return matching.reconciliation_status()


def list_unmatched(dataset_id: str, counterpart_dataset_id: str, limit: int) -> dict[str, Any]:
    """Rows with no accepted match.

    Pass counterpart_dataset_id to scope to one relationship ("which charges
    have no invoice?"), or "" for rows in no match at all. Prefer the scoped
    form when hunting breaks in a multi-hop flow.
    """
    try:
        return matching.list_unmatched(
            dataset_id, counterpart_dataset_id or None, limit or 25
        )
    except matching.MatchError as exc:
        return {"error": str(exc)}


def get_row_history(dataset_id: str, row: int) -> dict[str, Any]:
    """Every match a specific source row participates in, with its event
    history in order. This is the audit trail for one transaction."""
    props = db.query(
        "SELECT p.id, p.rule, p.tier, p.group_key, p.confidence, p.status, p.datasets"
        " FROM match_proposal p JOIN match_member m ON m.proposal_id = p.id"
        " WHERE m.dataset_id = ? AND m.row = ? ORDER BY p.id",
        (dataset_id, row),
    )
    for p in props:
        p["events"] = db.query(
            "SELECT ts, kind, actor, detail FROM match_event"
            " WHERE proposal_id = ? ORDER BY id",
            (p["id"],),
        )
    return {"dataset_id": dataset_id, "row": row, "matches": props}


ALL_TOOLS = [
    list_datasets,
    auto_match_exact,
    trace_record,
    set_spine,
    profile_columns,
    find_join_candidates,
    run_sql,
    create_view,
    propose_matches,
    list_proposals,
    get_proposal,
    reconciliation_status,
    list_unmatched,
    get_row_history,
]
