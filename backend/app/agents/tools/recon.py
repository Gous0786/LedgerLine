"""Tools exposed to the reconciliation agent.

Docstrings here are the agent's interface -- they are what the model reads to
decide what to call, so they carry the contract, not just a label. They are also
re-sent on every model call, so they are written to be complete and no longer.

Six tools, each answering one question a person would actually ask: what is
here, what is in it, show me the data, do the reconciliation, what went wrong,
and what happened to this one transaction.

Deliberately absent: anything that accepts or rejects a proposal, writes to a
`ds_*` table, or lets the agent supply its own confidence. Proposing and
approving are different jobs, and confidence is computed from evidence in
`core/matching.py` rather than asserted.

`config` and `filters` arrive as free-form objects -- ADK generates no property
schema for a dict parameter, so the model has only the docstring to go on. Both
therefore validate their keys and answer a bad shape by naming the valid ones,
the same teach-at-failure-time approach the matching contract already uses.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.config import get_settings
from app.core import automatch, discovery, duplicates, matching, spine, sqlguard
from app.db import connection as db

log = logging.getLogger(__name__)

# Every result stays in the conversation and is re-sent on each later call, so
# the cost of an oversized result is paid many times over.
SAMPLE_ROWS = 10
MAX_EXCEPTIONS = 15
# Two reasons is enough to act on; a group listing every invariant it
# failed crowds out the other groups that also need looking at.
MAX_FAILURES_PER_GROUP = 2


def _resolve(dataset: str) -> str:
    """Accept a dataset name where an id is expected."""
    value = (dataset or "").strip()
    if not value:
        return value
    row = db.query_one(
        "SELECT id FROM dataset WHERE id = ? OR name = ? OR table_name = ?",
        (value, value, value),
    )
    return row["id"] if row else value


def _unknown(given: dict[str, Any], allowed: set[str]) -> list[str]:
    return sorted(k for k in given if k not in allowed)


# ------------------------------------------------------------------ what is --

def list_datasets() -> dict[str, Any]:
    """Every uploaded dataset with its columns, types, row count and any views."""
    out = []
    for d in db.query(
        "SELECT id, name, row_count FROM dataset"
        " WHERE status = 'ready' ORDER BY created_at"
    ):
        cols = db.query(
            "SELECT column_name, inferred_type FROM dataset_column"
            " WHERE dataset_id = ? ORDER BY ordinal",
            (d["id"],),
        )
        out.append({
            "dataset": d["name"],
            "dataset_id": d["id"],
            "rows": d["row_count"],
            "columns": [f"{c['column_name']}:{c['inferred_type']}" for c in cols],
        })
    views = [v["name"] for v in db.query("SELECT name FROM dataset_view ORDER BY name")]
    return {"datasets": out, **({"views": views} if views else {})}


def describe_dataset(dataset: str) -> dict[str, Any]:
    """Per-column statistics for one dataset: distinct count, nulls, min/max,
    top values, whether the column is unique, and a pattern signature.

    Use it to tell an identifier from an amount when the names do not make that
    obvious. `dataset` accepts the name or the id.
    """
    try:
        return discovery.profile_columns(_resolve(dataset))
    except ValueError as exc:
        return {"error": str(exc)}


def query_data(sql: str) -> dict[str, Any]:
    """Run one read-only SELECT (or WITH) and return its columns and first rows.

    For looking at data, not for matching it -- matching goes through
    run_reconciliation, which records what it finds instead of printing it.
    Results stay in the conversation and are re-sent on every later call, so
    prefer an aggregate over a page of rows.
    """
    try:
        return sqlguard.select(get_settings().db_path, sql, limit=SAMPLE_ROWS)
    except sqlguard.SqlError as exc:
        return {"error": str(exc)}


# -------------------------------------------------------------- reconciling --

_RECON_KEYS = {"mode", "rule", "sql", "description", "tolerance_minor", "tier", "spine"}


def run_reconciliation(config: dict[str, Any]) -> dict[str, Any]:
    """Reconcile. Two modes, and the first is almost always the whole answer.

    {"mode": "auto"} -- START HERE, and usually stop here. Runs every join
    deterministically for zero tokens: classifies each shared key as one-to-one,
    one-to-many or many-to-many, then matches row-for-row, by the aggregate
    identity SUM(many)=one, or by the single class of rows that corresponds --
    discovering amount columns by measured agreement rather than by name.
    Returns the rules it ran, the `declined` edges it refused and why, and
    `coverage`: what is matched and what is left, per dataset and per
    relationship. Read all of it before calling anything else. Everything in it
    is current, so it does not need confirming.

    {"mode": "rule", "rule": "...", "sql": "...", "description": "...",
     "tolerance_minor": 0} -- for what auto declined, chiefly many-to-many
    edges. The SQL returns one row per group member, with columns:
      group_key     identifies the match group
      dataset       the dataset name the row comes from
      row           that row's __row value
      role          optional label
      amount_minor  optional signed integer in minor units, signed so a
                    balancing group sums to zero (invoice +25000, charge -25000)
    YOUR QUERY DEFINES THE SCOPE -- everything it returns gets reconciled, so
    filter to what was asked. Confidence is computed from the evidence, never
    supplied by you, and a new rule is unproven so nothing it creates is final.
    tolerance_minor is the residual allowed per group; keep it tight, because
    absorbed residual is still unexplained money and is reported back.

    Optional in either mode: {"spine": "<dataset>"} names the source a
    transaction starts from, when the request implies one.
    """
    if not isinstance(config, dict):
        return {"error": "config must be an object", "valid_keys": sorted(_RECON_KEYS)}
    unknown = _unknown(config, _RECON_KEYS)
    if unknown:
        return {"error": f"unknown config key(s): {unknown}",
                "valid_keys": sorted(_RECON_KEYS)}

    if config.get("spine"):
        try:
            spine.set_spine(_resolve(str(config["spine"])),
                            "named in the request", actor="agent")
        except ValueError as exc:
            return {"error": str(exc)}

    mode = str(config.get("mode") or "auto").lower()
    if mode == "auto":
        return automatch.auto_match_exact()
    if mode != "rule":
        return {"error": f"unknown mode {mode!r}", "valid_modes": ["auto", "rule"]}

    missing = [k for k in ("rule", "sql") if not config.get(k)]
    if missing:
        return {"error": f"mode 'rule' needs {missing}",
                "valid_keys": sorted(_RECON_KEYS)}
    try:
        return matching.propose_matches(
            rule=str(config["rule"]),
            tier=int(config.get("tier") or 1),
            sql=str(config["sql"]),
            description=str(config.get("description") or ""),
            tolerance_minor=int(config.get("tolerance_minor") or 0),
        )
    except (matching.MatchError, sqlguard.SqlError) as exc:
        return {"error": str(exc)}


# --------------------------------------------------------------- what broke --

_FILTER_KEYS = {"kind", "dataset", "limit"}
_KINDS = ("all", "unbalanced", "ambiguous", "verification_failed", "unmatched")

_GROUP_COLUMNS = (
    "SELECT p.id, p.rule, p.group_key, p.confidence, p.status,"
    " p.balance_minor,"
    " (SELECT v.status FROM verification v WHERE v.proposal_id = p.id"
    "    ORDER BY v.id DESC LIMIT 1) AS verified,"
    " (SELECT v.invariants FROM verification v WHERE v.proposal_id = p.id"
    "    ORDER BY v.id DESC LIMIT 1) AS invariants"
    " FROM match_proposal p WHERE "
)
_FAILED_LATEST = (
    "(SELECT v.status FROM verification v WHERE v.proposal_id = p.id"
    " ORDER BY v.id DESC LIMIT 1) = 'fail'"
)


def _failures(row: dict[str, Any]) -> list[str]:
    if row.pop("verified", None) != "fail":
        row.pop("invariants", None)
        return []
    raw = row.pop("invariants", None) or "[]"
    try:
        failed = [f"{i['code']}: {i['detail']}" for i in json.loads(raw)
                  if i.get("passed") is False]
    except Exception:
        return []
    return failed[:MAX_FAILURES_PER_GROUP]


def get_exceptions(filters: dict[str, Any]) -> dict[str, Any]:
    """Everything that needs a person, in one call.

    Pass {} for all of it, or narrow with:
      kind     all (default) | unbalanced | ambiguous | verification_failed
               | unmatched
      dataset  restrict the unmatched rows to one source
      limit    how many of each to return (default 15)

    `groups` are matches with something wrong: amounts that do not tie, rows
    that could join two ways, or a group its own verification refused -- mixed
    currency, an amount that appears in no cell of the row it claims to come
    from, a settlement far outside the normal lag for its rule. `unmatched` are
    rows in no accepted match at all.

    Both are findings, not failures. Some rows are legitimately out of scope: a
    bank statement holds fees and balance lines no order will explain. Say
    plainly what did not reconcile and distinguish those from real breaks.
    """
    if not isinstance(filters, dict):
        return {"error": "filters must be an object", "valid_keys": sorted(_FILTER_KEYS)}
    unknown = _unknown(filters, _FILTER_KEYS)
    if unknown:
        return {"error": f"unknown filter key(s): {unknown}",
                "valid_keys": sorted(_FILTER_KEYS)}

    kind = str(filters.get("kind") or "all").lower()
    if kind not in _KINDS:
        return {"error": f"unknown kind {kind!r}", "valid_kinds": list(_KINDS)}
    limit = max(1, min(int(filters.get("limit") or MAX_EXCEPTIONS), 100))

    out: dict[str, Any] = {
        "summary": db.query(
            "SELECT status, confidence, COUNT(*) AS n FROM match_proposal"
            " GROUP BY status, confidence"
        )
    }

    if kind != "unmatched":
        params: tuple = ()
        if kind in ("unbalanced", "ambiguous"):
            where = "p.confidence = ?"
            params = (kind,)
        elif kind == "verification_failed":
            where = _FAILED_LATEST
        else:
            where = f"(p.confidence IN ('unbalanced','ambiguous') OR {_FAILED_LATEST})"
        rows = db.query(_GROUP_COLUMNS + where + " ORDER BY p.id LIMIT ?",
                        (*params, limit))
        groups = []
        for r in rows:
            failed = _failures(r)
            groups.append({**r, **({"verification_failures": failed} if failed else {})})
        out["groups"] = groups

    if kind in ("all", "unmatched"):
        wanted = _resolve(str(filters["dataset"])) if filters.get("dataset") else None
        unmatched = []
        for d in db.query(
            "SELECT id, name, table_name FROM dataset WHERE status = 'ready'"
            " ORDER BY created_at"
        ):
            if wanted and d["id"] != wanted:
                continue
            unmatched.append(_unattached(d))
        out["unmatched"] = [u for u in unmatched if u and u["unmatched"]]

    if kind == "all":
        # A duplicated source row is a finding in its own right, not just a
        # reason some batch looked wrong.
        dupes = [
            duplicates.summary(d["id"])
            for d in db.query("SELECT id FROM dataset WHERE status = 'ready'")
        ]
        dupes = [d for d in dupes if d.get("duplicate_rows")]
        if dupes:
            out["duplicated_rows"] = dupes

    return out


# Rows in no proposal at all -- deliberately *not* `matching.list_unmatched`,
# which counts rows outside an **accepted** match. Nothing is accepted until a
# rule is approved, so in the agent's flow that reports every row in every
# source as unmatched: true, useless, and alarming. What a reviewer wants to
# know is which rows nothing even proposed a home for.
UNATTACHED_EXAMPLES = 3
EXAMPLE_COLUMNS = 5


def _unattached(dataset: dict[str, Any]) -> dict[str, Any] | None:
    table = dataset["table_name"].replace('"', '""')
    where = (
        f'FROM "{table}" WHERE __row NOT IN ('
        " SELECT m.row FROM match_member m"
        " JOIN match_proposal p ON p.id = m.proposal_id"
        " WHERE m.dataset_id = ? AND p.status != 'rejected')"
    )
    try:
        total = db.query_one(f"SELECT COUNT(*) AS n {where}", (dataset["id"],))["n"]
        rows = db.query(
            f"SELECT * {where} ORDER BY __row LIMIT {UNATTACHED_EXAMPLES}",
            (dataset["id"],),
        )
    except Exception:
        return None
    return {
        "dataset": dataset["name"],
        "unmatched": total,
        # A handful of columns is enough to recognise a row; the rest is bulk
        # that would push the other findings out of the result.
        "examples": [dict(list(r.items())[:EXAMPLE_COLUMNS]) for r in rows],
    }


# ---------------------------------------------------------- one transaction --

def get_transaction_chain(transaction_id: str) -> dict[str, Any]:
    """Follow one identifier end to end. READ ONLY, records nothing.

    The right tool for a question about a specific record -- "what happened to
    ORDER-1042", "did this settle". Finds every row holding the value, follows
    the identifiers in those rows into the other sources, and reports the
    matches those rows belong to with their event history in order.

    Being asked about something is not permission to reconcile it.
    """
    traced = discovery.trace_record(transaction_id)
    rows = [(h["dataset_id"], h["row"]) for h in traced.get("hits", [])]
    if not rows:
        return {**traced, "matches": []}

    pairs = " OR ".join("(m.dataset_id = ? AND m.row = ?)" for _ in rows)
    params: list[Any] = []
    for ds_id, row in rows:
        params.extend((ds_id, int(row)))
    matches = db.query(
        "SELECT DISTINCT p.id, p.rule, p.group_key, p.confidence, p.status,"
        " p.datasets, p.balance_minor FROM match_proposal p"
        f" JOIN match_member m ON m.proposal_id = p.id WHERE {pairs}"
        " ORDER BY p.id",
        params,
    )
    for m in matches:
        m["events"] = db.query(
            "SELECT ts, kind, actor FROM match_event WHERE proposal_id = ?"
            " ORDER BY id",
            (m["id"],),
        )
    return {**traced, "matches": matches}


ALL_TOOLS = [
    list_datasets,
    describe_dataset,
    query_data,
    run_reconciliation,
    get_exceptions,
    get_transaction_chain,
]
