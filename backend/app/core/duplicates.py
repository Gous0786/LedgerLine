"""Rows a source file records twice, decided once at ingest.

A duplicated line is not a second event. When an export carries the same
capture twice, there was one capture and the file says so twice -- and any sum
over that file is wrong by exactly the duplicated amount.

Marking the row at ingest rather than noticing it during matching is what makes
the correction free. A redundant row is simply not selected, so a group holding
one balances by construction; nothing downstream needs to know that a
correction happened, because none did.

Two classes, and the difference is not cosmetic:

`exact`
    Every column equal, byte for byte. This needs no key discovery, no
    threshold and no guess about which column is the natural key, and it cannot
    produce a false positive. One event, recorded twice.

`near`
    Equal on everything that describes the event -- the reference, the amount,
    the currency -- while carrying its own id and its own timestamp. The
    labelled data is explicit that this is not the same finding: it calls the
    shape AMBIGUOUS_MATCH, "the merchant order ID maps to multiple distinct
    candidate records and requires operator review".

Neither class is excluded by default, and that is measured rather than
cautious. Removing a duplicated row makes its group tie, and a group that ties
releases itself without a person: on the labelled fixtures that turned real
exceptions into silent auto-matches, 100% accuracy down to 81.7% and false
auto-matches from 0% to 19.3%. A settlement line recorded twice is a
disagreement between that file and the bank, not an arithmetic slip.

So both classes are marked, counted and visible, and a per-dataset switch says
"in this file a repeat is a recording artefact". Only someone who knows the
file can make that claim, which is why it is a switch and not a constant.

The weaker relative -- same identifier, *different* amounts -- is a conflict
rather than a duplicate, and there is no safe way to pick which of the two is
true. It stays an exception.
"""

from __future__ import annotations

import logging
from typing import Any

from app.db import connection as db

log = logging.getLogger(__name__)

EXACT = "exact"
NEAR = "near"

MARK_COL = "__duplicate_of"
KIND_COL = "__duplicate_kind"

# What makes a column the row's own identifier is not an absolute score but
# being the *most* distinct column in the file, and every absolute cut-off tried
# here failed on some file just below it. Two duplicates in a twelve-row export
# drag a genuine id column to 0.92; a clean file's reference sits at 1.00 and
# would be mistaken for one. So identity is whichever columns tie for the most
# distinct values -- the same relative test the cardinality classifier uses --
# with a floor so a file of nothing but enums claims no identifier at all.
IDENTITY_FLOOR = 0.5

# ...and the columns left over have to include something that actually names
# the event. Without this, a clean file whose reference *is* perfectly unique
# gets that reference treated as row identity, leaving amount, currency and
# status to agree -- and two genuine payments of the same size on the same day
# read as one recorded twice. A reference repeats far less than a status does.
MIN_REFERENCE_RATIO = 0.5

# A near-duplicate claim rests on the rows agreeing about the money. Without a
# numeric column among the agreeing ones, "identical apart from the id" can be
# satisfied by a status and a currency, which says nothing at all.
NUMERIC_TYPES = ("REAL", "INTEGER")


# Does a duplicated row that reached matching still count toward its balance?
#
# Yes, and the module docstring says why: on a dataset nobody has opted in for,
# a duplicate is a finding rather than an error in the arithmetic, and the
# break has to stay visible. On a dataset that has opted in, the row never
# reaches matching at all, so this question does not arise for it.
EXCLUDE_DUPLICATE_AMOUNTS = False


def counts_toward_balance(member: dict[str, Any]) -> bool:
    """Should this member's amount be added to the group's sum?"""
    return not (EXCLUDE_DUPLICATE_AMOUNTS and member.get("duplicate_of") is not None)


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _columns(dataset_id: str) -> list[dict[str, Any]]:
    return db.query(
        "SELECT column_name, inferred_type FROM dataset_column"
        " WHERE dataset_id = ? ORDER BY ordinal",
        (dataset_id,),
    )


def ensure_marks(table: str) -> None:
    """Add the mark columns to a source table that predates them."""
    have = {r["name"] for r in db.query(f"PRAGMA table_info({_quote(table)})")}
    for col, decl in ((MARK_COL, "INTEGER"), (KIND_COL, "TEXT")):
        if col not in have:
            db.execute(f"ALTER TABLE {_quote(table)} ADD COLUMN {_quote(col)} {decl}")


def _mark(table: str, groups: list[dict[str, Any]], kind: str) -> int:
    """Point every redundant row at the canonical one. Returns how many.

    The lowest `__row` of a set is kept -- arbitrary, but stable, so the same
    file always yields the same answer.
    """
    marked = 0
    for g in groups:
        rows = [int(x) for x in str(g["members"] or "").split(",") if x]
        canonical = min(rows) if rows else None
        if canonical is None:
            continue
        redundant = [r for r in rows if r != canonical]
        if not redundant:
            continue
        placeholders = ",".join("?" for _ in redundant)
        db.execute(
            f"UPDATE {_quote(table)} SET {_quote(MARK_COL)} = ?, {_quote(KIND_COL)} = ?"
            f" WHERE __row IN ({placeholders})",
            (canonical, kind, *redundant),
        )
        marked += len(redundant)
    return marked


def _group_by(table: str, cols: list[str], unmarked_only: bool = False) -> list[dict[str, Any]]:
    grouped = ",".join(_quote(c) for c in cols)
    where = f" WHERE {_quote(MARK_COL)} IS NULL" if unmarked_only else ""
    return db.query(
        f"SELECT GROUP_CONCAT(__row) AS members FROM {_quote(table)}{where}"
        f" GROUP BY {grouped} HAVING COUNT(*) > 1"
    )


def _event_columns(dataset_id: str, table: str, rows: int) -> list[str] | None:
    """Columns describing the event rather than identifying the row.

    Returns None when the split is not meaningful -- nothing looks like an id,
    or nothing left describes an amount -- in which case `near` detection would
    only restate what `exact` already found, or worse, group on a status.
    """
    cols = _columns(dataset_id)
    if not cols or rows <= 0:
        return None

    distinct: dict[str, int] = {}
    for c in cols:
        name = c["column_name"]
        try:
            distinct[name] = db.query_one(
                f"SELECT COUNT(DISTINCT {_quote(name)}) d FROM {_quote(table)}"
            )["d"] or 0
        except Exception:
            continue
    if not distinct:
        return None

    most = max(distinct.values())
    if most / rows < IDENTITY_FLOOR:
        return None  # nothing in this file identifies a row; `near` is meaningless
    identity = {n for n, d in distinct.items() if d == most}

    event = [c for c in cols if c["column_name"] not in identity]
    if len(event) < 2:
        return None
    if not any(c["inferred_type"] in NUMERIC_TYPES for c in event):
        return None  # nothing about the money agrees; not a duplicate claim
    if not any(
        c["inferred_type"] == "TEXT"
        and distinct.get(c["column_name"], 0) / rows >= MIN_REFERENCE_RATIO
        for c in event
    ):
        return None  # only statuses agree, which names no event
    return [c["column_name"] for c in event]


def scan(dataset_id: str) -> dict[str, int]:
    """Classify and mark every duplicated row in one dataset.

    Two passes over the table, both plain `GROUP BY`: exact first so that a
    byte-identical row is never also counted as a near one.
    """
    ds = db.query_one(
        "SELECT table_name, row_count FROM dataset WHERE id = ?", (dataset_id,)
    )
    if not ds:
        return {"duplicate_rows": 0, "near_duplicate_rows": 0}

    table = ds["table_name"]
    rows = ds["row_count"] or 0
    ensure_marks(table)
    db.execute(
        f"UPDATE {_quote(table)} SET {_quote(MARK_COL)} = NULL, {_quote(KIND_COL)} = NULL"
    )

    source = [c["column_name"] for c in _columns(dataset_id)]
    exact = near = 0
    if source:
        try:
            exact = _mark(table, _group_by(table, source), EXACT)
        except Exception:
            log.warning("exact duplicate scan failed for %s", dataset_id, exc_info=True)

        event = _event_columns(dataset_id, table, rows)
        if event:
            try:
                near = _mark(
                    table, _group_by(table, event, unmarked_only=True), NEAR
                )
            except Exception:
                log.warning("near duplicate scan failed for %s", dataset_id,
                            exc_info=True)

    db.execute(
        "UPDATE dataset SET duplicate_rows = ?, near_duplicate_rows = ? WHERE id = ?",
        (exact, near, dataset_id),
    )
    if exact or near:
        log.info("duplicates in %s: %d exact, %d near", table, exact, near)
    return {"duplicate_rows": exact, "near_duplicate_rows": near}


def scan_all() -> dict[str, dict[str, int]]:
    return {
        d["id"]: scan(d["id"])
        for d in db.query("SELECT id FROM dataset WHERE status = 'ready'")
    }


def excluded_kinds(dataset: dict[str, Any]) -> tuple[str, ...]:
    """Which classes this dataset keeps out of matching.

    Nothing, unless someone said so for this file. See the module docstring:
    excluding by default lets a deduplicated group release itself, and a
    duplicated row is the finding, not an error in the arithmetic.
    """
    if dataset.get("exclude_duplicates"):
        return (EXACT, NEAR)
    return ()


def filtered_source(dataset: dict[str, Any], source: str) -> str:
    """`source`, wrapped so excluded rows are never selected from it.

    A derived table rather than a condition callers must remember to add: the
    whole point of marking at ingest is that no query downstream has to know
    duplicates exist.
    """
    kinds = excluded_kinds(dataset)
    quoted = ",".join(f"'{k}'" for k in kinds)
    return (
        f"(SELECT * FROM {source} WHERE {_quote(KIND_COL)} IS NULL"
        f" OR {_quote(KIND_COL)} NOT IN ({quoted}))"
    )


def redundant_rows(dataset_id: str) -> dict[int, int]:
    """`{redundant __row: the row it duplicates}`, read from the marks.

    Every class, not only the excluded ones -- matching uses this to badge a
    member as a repeat, and a near duplicate that reached a group is exactly
    the case a reviewer needs pointed out.
    """
    ds = db.query_one("SELECT table_name FROM dataset WHERE id = ?", (dataset_id,))
    if not ds:
        return {}
    try:
        rows = db.query(
            f"SELECT __row, {_quote(MARK_COL)} AS canonical FROM {_quote(ds['table_name'])}"
            f" WHERE {_quote(MARK_COL)} IS NOT NULL"
        )
    except Exception:
        return {}
    return {int(r["__row"]): int(r["canonical"]) for r in rows}


def summary(dataset_id: str) -> dict[str, Any]:
    """Counts and a few examples, for reporting rather than matching."""
    ds = db.query_one(
        "SELECT name, table_name, duplicate_rows, near_duplicate_rows,"
        " exclude_duplicates FROM dataset WHERE id = ?",
        (dataset_id,),
    )
    if not ds:
        return {"dataset": None, "duplicate_rows": 0, "near_duplicate_rows": 0}

    out: dict[str, Any] = {
        "dataset": ds["name"],
        "duplicate_rows": ds["duplicate_rows"] or 0,
        "near_duplicate_rows": ds["near_duplicate_rows"] or 0,
        "excluded_kinds": list(excluded_kinds(dict(ds))),
    }
    if not (out["duplicate_rows"] or out["near_duplicate_rows"]):
        return out

    cols = [c["column_name"] for c in _columns(dataset_id)][:4]
    if cols:
        picked = ", ".join(_quote(c) for c in cols)
        try:
            out["examples"] = db.query(
                f"SELECT __row, {_quote(MARK_COL)} AS duplicate_of,"
                f" {_quote(KIND_COL)} AS kind, {picked}"
                f" FROM {_quote(ds['table_name'])}"
                f" WHERE {_quote(MARK_COL)} IS NOT NULL LIMIT 5"
            )
        except Exception:
            pass
    return out


def all_redundant() -> dict[str, dict[int, int]]:
    """Every ready dataset's redundant rows, keyed by dataset id."""
    return {
        d["id"]: redundant_rows(d["id"])
        for d in db.query("SELECT id FROM dataset WHERE status = 'ready'")
    }
