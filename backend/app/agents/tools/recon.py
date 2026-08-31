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
from app.core import discovery, matching, spine, sqlguard
from app.db import connection as db

log = logging.getLogger(__name__)


# --------------------------------------------------------- understanding --

def list_datasets() -> dict[str, Any]:
    """List every uploaded dataset with its columns and inferred types.

    Start here. Returns each dataset's id, name, row count, and the columns
    available to query, plus any normalisation views defined over it.
    """
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
    """Per-column statistics for one dataset.

    Returns distinct count, nulls, min/max, most common values, whether the
    column is unique, and a pattern signature (e.g. `ch_3M01` -> `aa_9A99`).
    Use it to tell identifiers from amounts, and to spot enum-like columns.
    """
    return discovery.profile_columns(dataset_id)


def find_join_candidates() -> dict[str, Any]:
    """Find which columns across different datasets hold the same values.

    Measures actual value overlap between every column pair, so it discovers
    join keys even when the column names differ completely. Returns pairs with
    `overlap` (shared distinct values), `left_coverage` / `right_coverage`
    (fraction of each side covered), and example values.

    Coverage below 1.0 is meaningful: it means some values on that side have no
    counterpart, which is usually where the breaks are.
    """
    return discovery.find_join_candidates()


def trace_record(value: str) -> dict[str, Any]:
    """Follow one identifier across every dataset. READ ONLY -- records nothing.

    Use this to answer questions about specific records: "what happened to
    INV-2026-805", "where did this charge settle", "is this paid". It finds
    every row holding the value, then follows the identifiers in those rows
    into other sources, so an invoice reaches its charge and the charge reaches
    its bank settlement.

    This is the right tool for a question about particular records. Do not
    reconcile in order to answer one -- reconciling writes state, and a question
    is not a request to write.
    """
    return discovery.trace_record(value)


def set_spine(dataset_id: str, reason: str) -> dict[str, Any]:
    """Declare which source starts a transaction, for the end-to-end view.

    Call this when the user's request names the thing being reconciled --
    "reconcile all orders" makes the orders source the spine, "trace every
    payout" makes the payout source the spine. Give the reason in the user's
    terms.

    Without a declaration the spine is inferred from foreign-key structure,
    which is usually right, so only call this when the request actually implies
    a different starting point.
    """
    try:
        return spine.set_spine(dataset_id, reason, actor="agent")
    except ValueError as exc:
        return {"error": str(exc)}


# ----------------------------------------------------------------- query --

def run_sql(sql: str) -> dict[str, Any]:
    """Run a read-only SELECT against the datasets and views.

    Only a single SELECT or WITH statement is allowed. Returns the column names
    and at most 50 rows. Use it to inspect data and to develop a matching query
    before handing it to propose_matches.

    Table names are the `table` field from list_datasets (e.g. ds_ab12cd34ef56),
    or any view you created. Quote identifiers with double quotes.
    """
    try:
        return sqlguard.select(get_settings().db_path, sql)
    except sqlguard.SqlError as exc:
        return {"error": str(exc)}


def create_view(name: str, sql: str) -> dict[str, Any]:
    """Create (or replace) a named SQL view over a raw dataset.

    Use views to do normalisation once instead of repeating it in every rule:
    convert money to integer minor units, collapse separate debit/credit
    columns into one signed amount, tag reference namespaces, and classify
    non-transaction rows.

    Money must be compared as integers. Floating point sums do not compare
    equal -- 242.45 + 1164.90 != 1407.35 in float arithmetic -- so express
    amounts as `CAST(ROUND(col * 100) AS INTEGER)` in the view and match on
    that, never on the raw decimal.

    `name` must start with `v_`. `sql` is the SELECT body of the view.
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

def propose_matches(
    rule: str, tier: int, sql: str, description: str, tolerance_minor: int
) -> dict[str, Any]:
    """Propose reconciliation matches by running a matching query.

    You pass SQL, never rows. The query is executed, its rows are grouped, each
    group is scored from evidence, and the results are recorded and shown to the
    user. Only counts and a small sample come back to you.

    The query MUST return these columns, one row per group member:
      group_key    identifies the match group (e.g. the invoice id or payout id)
      dataset      the dataset name or id the member row comes from
      row          the member's __row value
      role         optional label, e.g. 'invoice', 'charge', 'settlement'
      amount_minor optional signed integer amount in minor units (cents)

    A group is any set of rows that reconcile together, so 1-to-1 and
    many-to-1 use the same shape. A group needs at least two members spanning
    at least two datasets.

    Sign convention: `amount_minor` must be signed so that a balancing group
    sums to zero. Put one side positive and the other negative -- e.g. the
    invoice +25000 and the charge -25000. Groups that do not sum to zero are
    recorded as `unbalanced` and held for review; that is usually a real break,
    not a mistake in your query.

    `tolerance_minor` is the residual you will accept, in minor units, per
    group. Systems round differently, so a bank batch landing 2 cents from the
    computed net is reconciled, not broken -- pass 100 to allow up to 1.00.
    Pass 0 to demand an exact tie. Set it from what the data justifies, never
    wide enough to make a real difference disappear: the residual it absorbs is
    reported back and is still unexplained money.

    Confidence is computed here, not by you:
      exact             balanced to zero
      within_tolerance  residual non-zero but inside tolerance_minor
      high              unique and cross-dataset, but no amounts to verify
      unbalanced        residual exceeds tolerance -> held for review
      ambiguous         a row could belong to more than one group -> reviewed

    YOUR QUERY DEFINES THE SCOPE. Everything it returns gets reconciled. If the
    user asked about particular records, the query must filter to them -- an
    unfiltered join reconciles the whole dataset, which is not what was asked.
    The result includes `group_keys` so you can check what was actually created.

    A new rule name is unproven: its matches wait for approval however confident
    they look. Once the user approves the rule, later runs of it auto-accept.

    Rows already matched within the same relationship are skipped, so you do not
    need to exclude earlier tiers yourself. The same row may still be matched in
    a different relationship -- a charge settles an invoice AND belongs to a
    bank payout.
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
    """Coverage so far, per dataset and per relationship.

    Read the per-edge numbers, not the per-dataset ones: a gateway charge that
    settles into the bank counts as matched overall even when no invoice
    explains it. Only the edge breakdown reveals that gap.
    """
    return matching.reconciliation_status()


def list_unmatched(dataset_id: str, counterpart_dataset_id: str, limit: int) -> dict[str, Any]:
    """Rows in `dataset_id` that have no accepted match.

    Pass `counterpart_dataset_id` to ask about one relationship -- "which
    charges have no invoice?" -- or an empty string to ask which rows are in no
    match at all. Prefer the scoped form when hunting breaks in a multi-hop
    flow.
    """
    try:
        return matching.list_unmatched(
            dataset_id, counterpart_dataset_id or None, limit or 25
        )
    except matching.MatchError as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------- memory --

def save_pattern(kind: str, name: str, content: str, evidence: str) -> dict[str, Any]:
    """Record something learned about this data for later batches.

    `kind` is one of: join_key, transform, exclusion, namespace, tolerance.
    `content` is the reusable fact (a join condition, a normalisation
    expression, a filter). `evidence` is why you believe it -- ideally counts
    from a tool result, e.g. "covers 5/6 charges".

    Patterns are saved as `candidate`. They are suggestions for later runs, not
    licence to auto-apply, and a human can confirm or retire them.
    """
    allowed = {"join_key", "transform", "exclusion", "namespace", "tolerance"}
    if kind not in allowed:
        return {"error": f"kind must be one of {sorted(allowed)}"}
    db.execute(
        "INSERT INTO pattern (kind, name, content, evidence) VALUES (?,?,?,?)"
        " ON CONFLICT(kind, name) DO UPDATE SET"
        "   content = excluded.content, evidence = excluded.evidence",
        (kind, name, content, evidence),
    )
    return {"saved": {"kind": kind, "name": name, "status": "candidate"}}


def get_patterns(kind: str) -> dict[str, Any]:
    """Recall previously saved patterns. `kind` filters by type, or pass an
    empty string for all. Check this before analysing from scratch."""
    if kind:
        rows = db.query(
            "SELECT kind, name, content, status, evidence FROM pattern"
            " WHERE kind = ? AND status != 'retired' ORDER BY id",
            (kind,),
        )
    else:
        rows = db.query(
            "SELECT kind, name, content, status, evidence FROM pattern"
            " WHERE status != 'retired' ORDER BY id"
        )
    return {"patterns": rows}


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
    save_pattern,
    get_patterns,
    get_row_history,
]
