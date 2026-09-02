"""Deterministic first pass: match everything that joins on a shared identifier.

Most of a reconciliation is not interesting. Rows that carry the same reference
and the same amount need no judgement, and having a model reason its way to them
one query at a time is the expensive way to learn nothing.

So this does the obvious pass without an LLM: take the identifier pairs the
overlap matrix already found, work out what kind of relationship each one is,
verify the money accordingly, and record the groups. What survives is the part
that actually needs attention.

**A shared key is not a relationship.** That is the thing this module learned the
hard way. Two sources overlapping on `order_id` may be one row to one row, one
row to many, or many to many, and only the first is a match in the sense of
"these two rows are the same event". So the key is classified before anything is
proposed:

    1:1   both sides unique on the key   -> row-level equality, as before
    N:1   one side unique                -> the aggregate identity,
                                            SUM(many) = one
    1:N   ...and if that fails           -> a partition of the many side,
                                            where only one class of row
                                            corresponds (a ledger's revenue
                                            lines, not its fee lines)
    N:M   neither side unique            -> declined

Declining matters as much as matching. An N:M join produces beautiful
identifier-only groups that no amount can ever verify, and they read as progress
while explaining nothing. Saying "this is not a matchable edge, here is why" is
the more useful answer, and it is the one a reviewer can act on.

Amount columns are discovered rather than declared throughout: candidate
expressions are ranked by how often they actually agree across the join, and the
best is taken. Names are never consulted.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from typing import Any

from app.config import get_settings
from app.core import discovery, matching, sqlguard
from app.db import connection as db

log = logging.getLogger(__name__)

MIN_COVERAGE = 0.5

# Floor for treating a numeric expression pair as the same quantity.
# Deliberately low: on a set that is a third exceptions the correct pair only
# agreed on 91% of rows, while every wrong pair agreed on 0%. The gap is
# enormous, so rank the candidates and take the best rather than demanding
# near-perfection.
AMOUNT_AGREEMENT = 0.60
MIN_AMOUNT_ROWS = 3

# A side counts as the "one" of a one-to-many when its key is essentially
# unique. Not exactly 1.0: a single duplicated reference in real data should
# not reclassify the whole relationship.
UNIQUE_KEY = 0.98

# ...but an absolute threshold alone is wrong, and measurably so. A bank
# statement that is meant to hold one row per settlement, and holds duplicate
# deposits -- the very defect being reconciled -- scores anywhere from 0.88 down
# to 0.77 depending on how many. Every absolute cut-off placed here failed on
# some dataset just below it, because "how many duplicates" is not a constant.
#
# So the real test is relative: the `one` side is the one whose key is
# substantially more distinct than the other's. The floor that remains is
# meaningful rather than tuned -- more than half its rows carry a key of their
# own, so calling it the one-per-key side is defensible at all.
NEARLY_UNIQUE = 0.5
DOMINANCE = 1.5

# Fraction of a TEXT column's values that must look like numbers before it is
# treated as an amount. Ingest types a column TEXT the moment a single row
# carries junk, and five 'NOT_A_NUMBER' rows in two hundred are enough to hide
# an entire amount column from a search that trusts the declared type.
NUMERIC_TEXT = 0.80

# Columns with few enough distinct values to partition on (entry_type,
# txn_type), and how hard we will look.
PARTITION_MAX_DISTINCT = 12
MAX_PARTITION_PROBES = 240

# The largest per-group residual an aggregate rule may absorb as rounding, in
# major units. A batch that lands 0.02 from its computed net is reconciled; one
# that lands 86,000 away is a finding, and no tolerance should hide it.
MAX_RESIDUAL = 1.00


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _columns(dataset_id: str) -> list[dict[str, Any]]:
    return db.query(
        "SELECT column_name, inferred_type FROM dataset_column"
        " WHERE dataset_id = ? ORDER BY ordinal",
        (dataset_id,),
    )


def _minor(expr: str) -> str:
    """Money as an integer, stated in exactly one place."""
    return f"CAST(ROUND(COALESCE({expr},0)*100) AS INTEGER)"


# ------------------------------------------------------------ normalisation --

def _signed_pair(dataset: dict[str, Any]) -> tuple[str, str] | None:
    """Two numeric columns that are never both populated in the same row.

    That is one signed quantity split in half -- a bank statement's credit and
    debit. Neither column alone can be compared with anything, which is why a
    statement looks amount-less to a pairwise search.
    """
    cols = [
        c["column_name"] for c in _columns(dataset["id"])
        if c["inferred_type"] in ("REAL", "INTEGER")
    ]
    p = get_settings().db_path
    table = _quote(dataset["table_name"])
    for i, a in enumerate(cols):
        for b in cols[i + 1:]:
            qa, qb = _quote(a), _quote(b)
            try:
                r = sqlguard.select_all(
                    p,
                    f"SELECT SUM(CASE WHEN {qa} IS NOT NULL AND {qb} IS NOT NULL"
                    f"  THEN 1 ELSE 0 END) both,"
                    f" SUM(CASE WHEN {qa} IS NOT NULL THEN 1 ELSE 0 END) na,"
                    f" SUM(CASE WHEN {qb} IS NOT NULL THEN 1 ELSE 0 END) nb"
                    f" FROM {table}",
                )[0]
            except Exception:
                continue
            if (
                (r["both"] or 0) == 0
                and (r["na"] or 0) >= MIN_AMOUNT_ROWS
                and (r["nb"] or 0) >= MIN_AMOUNT_ROWS
            ):
                return (a, b)
    return None


def normalised_view(dataset: dict[str, Any]) -> str | None:
    """Publish a split credit/debit pair as one signed column, as a view.

    A view rather than an inline expression on purpose: `list_datasets` shows
    views to the agent, so a rule written later inherits the normalisation
    instead of rediscovering it -- which is the difference between the fix
    holding and it holding until the next hand-written query.
    """
    pair = _signed_pair(dataset)
    if not pair:
        return None
    a, b = pair
    name = "v_" + re.sub(r"\W+", "_", dataset["name"]).strip("_").lower() + "_norm"
    expr = f"COALESCE({_quote(a)},0) - COALESCE({_quote(b)},0)"
    body = f'SELECT *, {expr} AS signed_amount FROM {_quote(dataset["table_name"])}'
    try:
        with db.cursor() as conn:
            conn.execute(f'DROP VIEW IF EXISTS "{name}"')
            conn.execute(f'CREATE VIEW "{name}" AS {body}')
        db.execute(
            "INSERT INTO dataset_view (name, dataset_id, sql) VALUES (?,?,?)"
            " ON CONFLICT(name) DO UPDATE SET sql = excluded.sql,"
            "   dataset_id = excluded.dataset_id",
            (name, dataset["id"], body),
        )
    except Exception:
        log.warning("could not build normalised view for %s", dataset["name"], exc_info=True)
        return None
    log.info("normalised %s: %s - %s -> %s.signed_amount", dataset["name"], a, b, name)
    return name


# ------------------------------------------------------------- classifying --

def _alias(template: str, alias: str) -> str:
    """Bind a candidate expression to a table alias.

    Expressions are carried as templates (`CAST({a}."gross_amount" AS REAL)`)
    rather than bare column names, because a numeric-looking TEXT column has to
    be cast, and `l.` cannot simply be glued to the front of a CAST.
    """
    return template.format(a=alias)


@dataclass
class Side:
    """One end of a candidate join, with everything needed to query it."""

    dataset: dict[str, Any]
    key: str
    source: str                   # table or normalised view, already quoted
    exprs: list[tuple[str, str]]  # (label, sql template using {a} for the alias)
    rows: int
    distinct: int

    @property
    def name(self) -> str:
        return self.dataset["name"]

    @property
    def ratio(self) -> float:
        return (self.distinct / self.rows) if self.rows else 0.0

    @property
    def unique(self) -> bool:
        return self.rows > 0 and self.ratio >= UNIQUE_KEY

    def is_one_against(self, other: Side) -> bool:
        """Unique enough to be the `one` side of a one-to-many.

        Absolute uniqueness is the clean case. The common messy one is a table
        meant to hold one row per key that carries a few duplicates -- often the
        exact defect being reconciled -- so it also qualifies by being mostly
        unique and clearly more unique than the other side.
        """
        if self.unique:
            return True
        return self.ratio >= NEARLY_UNIQUE and self.ratio >= other.ratio * DOMINANCE


def _numeric_text_columns(dataset_id: str, source: str) -> list[str]:
    """TEXT columns whose values are overwhelmingly numbers.

    Measured, not declared. The type in `dataset_column` reflects the worst row
    in the file; what matters here is whether the column is where the money is.
    """
    p = get_settings().db_path
    out: list[str] = []
    for c in _columns(dataset_id):
        if c["inferred_type"] != "TEXT":
            continue
        q = _quote(c["column_name"])
        try:
            r = sqlguard.select_all(
                p,
                f"SELECT COUNT(*) n,"
                f" SUM(CASE WHEN TRIM({q}) <> ''"
                f"   AND TRIM({q}) NOT GLOB '*[^0-9.eE+-]*' THEN 1 ELSE 0 END) numeric_like"
                f" FROM {source} WHERE {q} IS NOT NULL",
            )[0]
        except Exception:
            continue
        n = r["n"] or 0
        if n >= MIN_AMOUNT_ROWS and (r["numeric_like"] or 0) / n >= NUMERIC_TEXT:
            out.append(c["column_name"])
    return out


def _side(dataset: dict[str, Any], key: str, view: str | None) -> Side | None:
    source = _quote(view) if view else _quote(dataset["table_name"])
    p = get_settings().db_path
    try:
        stat = sqlguard.select_all(
            p,
            f"SELECT COUNT({_quote(key)}) n, COUNT(DISTINCT {_quote(key)}) d"
            f" FROM {source} WHERE {_quote(key)} IS NOT NULL",
        )[0]
    except Exception:
        return None

    exprs = [
        (c["column_name"], '{a}.' + _quote(c["column_name"]))
        for c in _columns(dataset["id"])
        if c["inferred_type"] in ("REAL", "INTEGER")
    ]
    # A junk row must not cost the whole column. CAST turns the junk into 0.0,
    # which simply fails to agree with anything -- the right outcome, since
    # those rows are not reconcilable anyway.
    for name in _numeric_text_columns(dataset["id"], source):
        exprs.append((name, 'CAST({a}.' + _quote(name) + " AS REAL)"))
    if view:
        exprs.append(("signed_amount", '{a}.' + _quote("signed_amount")))
    return Side(
        dataset=dataset, key=key, source=source, exprs=exprs,
        rows=stat["n"] or 0, distinct=stat["d"] or 0,
    )


def _partition_columns(side: Side) -> list[tuple[str, list[str]]]:
    """Low-cardinality columns on this side, with their values."""
    p = get_settings().db_path
    out: list[tuple[str, list[str]]] = []
    for c in _columns(side.dataset["id"]):
        if c["inferred_type"] != "TEXT":
            continue
        col = _quote(c["column_name"])
        try:
            # The *total* distinct count decides, not how many values happen to
            # be common. Filtering by frequency first lets an identifier column
            # through whenever a handful of its values repeat -- and a partition
            # on one settlement batch id is not a class of row, it is a single
            # batch that happens to agree with itself.
            spread = sqlguard.select_all(
                p, f"SELECT COUNT(DISTINCT {col}) d FROM {side.source}"
                   f" WHERE {col} IS NOT NULL",
            )[0]["d"] or 0
            if not 2 <= spread <= PARTITION_MAX_DISTINCT:
                continue
            vals = sqlguard.select_all(
                p,
                f"SELECT {col} AS v, COUNT(*) n FROM {side.source}"
                f" WHERE {col} IS NOT NULL GROUP BY {col}"
                f" HAVING COUNT(*) >= {MIN_AMOUNT_ROWS}"
                f" ORDER BY n DESC LIMIT {PARTITION_MAX_DISTINCT}",
            )
        except Exception:
            continue
        if len(vals) >= 1:
            out.append((c["column_name"], [str(v["v"]) for v in vals]))
    return out


# ----------------------------------------------------------------- pairing --

@dataclass
class Amounts:
    kind: str                      # row | aggregate | partitioned
    left_expr: str                 # SQL on the alias `l`
    right_expr: str                # SQL on the alias `r`
    agreement: float
    # How many rows or groups this candidate actually accounted for. Strategies
    # are chosen on this, never on `agreement` alone.
    covered: int = 0
    tolerance_minor: int = 0
    partition: tuple[str, str] | None = None
    detail: str = ""


def _measure(sql: str) -> dict[str, Any] | None:
    try:
        return sqlguard.select_all(get_settings().db_path, sql)[0]
    except Exception:
        return None


def _score(row: dict[str, Any] | None) -> tuple[float, int, int, int] | None:
    """(agreement, exact groups, tolerance, groups explained) from a probe.

    The last element is the one that decides between strategies. Agreement is a
    ratio, and a ratio is free to be perfect over almost nothing.
    """
    if not row:
        return None
    n = row["n"] or 0
    if n < MIN_AMOUNT_ROWS:
        return None
    near = row["near_n"] or 0
    agreement = near / n
    if agreement < AMOUNT_AGREEMENT:
        return None
    worst = float(row["worst"] or 0)
    tolerance = math.ceil(round(worst, 4) * 100) if worst > 0 else 0
    return (agreement, row["exact_n"] or 0, tolerance, near)


def _probe_row_level(left: Side, right: Side, le: str, re_: str, extra: str = "") -> str:
    return (
        f"SELECT COUNT(*) n,"
        f" SUM(CASE WHEN ABS(d) < 0.005 THEN 1 ELSE 0 END) exact_n,"
        f" SUM(CASE WHEN ABS(d) < 0.005 THEN 1 ELSE 0 END) near_n,"
        f" 0 AS worst FROM ("
        f"SELECT COALESCE({_alias(le, 'l')},0) - COALESCE({_alias(re_, 'r')},0) AS d"
        f" FROM {left.source} l JOIN {right.source} r"
        f"  ON r.{_quote(right.key)} = l.{_quote(left.key)}{extra})"
    )


def pair_row_level(left: Side, right: Side) -> Amounts | None:
    """Which expression on each side means the same thing, row for row?"""
    best: tuple[tuple[float, int, int], str, str, str, str] | None = None
    for llabel, le in left.exprs:
        for rlabel, re_ in right.exprs:
            scored = _score(_measure(_probe_row_level(left, right, le, re_)))
            if scored is None:
                continue
            # Identical names break ties only; agreement still decides.
            ranked = (scored[0], scored[1] + (1 if llabel == rlabel else 0),
                      scored[2], scored[3])
            if best is None or ranked > best[0]:
                best = (ranked, llabel, rlabel, le, re_)
    if best is None:
        return None
    (agreement, _, _, covered), llabel, rlabel, le, re_ = best
    return Amounts(
        kind="row",
        left_expr=le,
        right_expr=re_,
        agreement=agreement,
        covered=covered,
        detail=f"amounts {llabel} / {rlabel}",
    )


def pair_aggregate(one: Side, many: Side) -> Amounts | None:
    """Does SUM over the many side equal the single value on the one side?

    This is what a batch settlement is: no individual gateway row equals the
    bank credit, and the identity only appears once they are added up.
    """
    best: tuple[tuple[float, int, int], str, str, str, str] | None = None
    for olabel, oe in one.exprs:
        for mlabel, me in many.exprs:
            probe = (
                f"SELECT COUNT(*) n,"
                f" SUM(CASE WHEN ABS(d) < 0.005 THEN 1 ELSE 0 END) exact_n,"
                f" SUM(CASE WHEN ABS(d) <= {MAX_RESIDUAL} THEN 1 ELSE 0 END) near_n,"
                f" MAX(CASE WHEN ABS(d) <= {MAX_RESIDUAL} THEN ABS(d) ELSE 0 END) worst"
                f" FROM (SELECT COALESCE({_alias(oe, 'o')},0)"
                f"  - SUM(COALESCE({_alias(me, 'm')},0)) AS d"
                f"  FROM {one.source} o JOIN {many.source} m"
                f"   ON m.{_quote(many.key)} = o.{_quote(one.key)}"
                f"  WHERE o.{_quote(one.key)} IS NOT NULL"
                f"  GROUP BY o.__row)"
            )
            scored = _score(_measure(probe))
            if scored is None:
                continue
            if best is None or scored > best[0]:
                best = (scored, olabel, mlabel, oe, me)
    if best is None:
        return None
    (agreement, _, tolerance, covered), olabel, mlabel, oe, me = best
    return Amounts(
        kind="aggregate",
        left_expr=oe,
        right_expr=me,
        agreement=agreement,
        covered=covered,
        tolerance_minor=tolerance,
        detail=(
            f"SUM({many.name}.{mlabel}) = {one.name}.{olabel}"
            + (f", residual up to {tolerance} minor absorbed" if tolerance else "")
        ),
    )


def pair_partitioned(one: Side, many: Side) -> Amounts | None:
    """Only one class of row on the many side corresponds.

    A ledger carries a revenue line, a fee line and a credit note against the
    same order. Exactly one of them is the order's amount; summing them is
    wrong and pairing them row-for-row is wrong. The class has to be found.
    """
    best: tuple[tuple[float, int, int], str, str, str, str, str, str] | None = None
    probes = 0
    for pcol, values in _partition_columns(many):
        for value in values:
            safe = str(value).replace("'", "''")
            extra = f" AND r.{_quote(pcol)} = '{safe}'"
            for olabel, oe in one.exprs:
                for mlabel, me in many.exprs:
                    if probes >= MAX_PARTITION_PROBES:
                        break
                    probes += 1
                    scored = _score(
                        _measure(_probe_row_level(one, many, oe, me, extra))
                    )
                    if scored is None:
                        continue
                    # Rank by rows explained, not by the fraction that agree.
                    # A narrower partition wins on fraction for free -- one
                    # settlement batch agrees with itself perfectly -- so
                    # ranking on agreement picks the partition that covers
                    # almost nothing. Agreement is the floor `_score` already
                    # enforced; coverage is what decides between survivors.
                    ranked = (scored[3], scored[0], scored[2])
                    if best is None or ranked > best[0]:
                        best = (ranked, olabel, mlabel, pcol, str(value), oe, me)
    if best is None:
        return None
    # best[0] is ranked (rows explained, agreement, tolerance) -- see above.
    (covered, agreement, _), olabel, mlabel, pcol, value, oe, me = best
    return Amounts(
        kind="partitioned",
        left_expr=oe,
        right_expr=me,
        agreement=agreement,
        covered=covered,
        partition=(pcol, value),
        detail=(
            f"{one.name}.{olabel} = {many.name}.{mlabel}"
            f" where {many.name}.{pcol} = '{value}'"
        ),
    )


# ------------------------------------------------------------------- rules --

def _sql_row_level(left: Side, right: Side, amounts: Amounts | None) -> str:
    lk, rk = _quote(left.key), _quote(right.key)
    if amounts:
        lamt = _minor(_alias(amounts.left_expr, "l"))
        ramt = "-" + _minor(_alias(amounts.right_expr, "r"))
    else:
        lamt = ramt = "NULL"
    where = ""
    if amounts and amounts.partition:
        pcol, value = amounts.partition
        where = f" AND r.{_quote(pcol)} = '{str(value).replace(chr(39), chr(39) * 2)}'"
    join = f" FROM {left.source} l JOIN {right.source} r ON r.{rk} = l.{lk}{where}"
    return (
        f"SELECT l.{lk} AS group_key, '{left.name}' AS dataset,"
        f" l.__row AS row, 'left' AS role, {lamt} AS amount_minor{join}"
        f" UNION ALL "
        f"SELECT r.{rk}, '{right.name}', r.__row, 'right', {ramt}{join}"
    )


def _sql_aggregate(one: Side, many: Side, amounts: Amounts) -> str:
    """One row on the `one` side, every matching row on the `many` side.

    Signed so the group sums to zero when the aggregate identity holds, which
    is what lets the match engine score it without knowing it is a batch.
    """
    ok, mk = _quote(one.key), _quote(many.key)
    oamt = _minor(_alias(amounts.left_expr, "o"))
    mamt = "-" + _minor(_alias(amounts.right_expr, "m"))
    return (
        f"SELECT o.{ok} AS group_key, '{one.name}' AS dataset,"
        f" o.__row AS row, 'one' AS role, {oamt} AS amount_minor"
        f" FROM {one.source} o"
        f" WHERE o.{ok} IS NOT NULL"
        f"  AND EXISTS (SELECT 1 FROM {many.source} m WHERE m.{mk} = o.{ok})"
        f" UNION ALL "
        f"SELECT m.{mk}, '{many.name}', m.__row, 'many', {mamt}"
        f" FROM {many.source} m JOIN {one.source} o ON o.{ok} = m.{mk}"
        f" WHERE m.{mk} IS NOT NULL"
    )


def _slug(value: str) -> str:
    return re.sub(r"\W+", "_", str(value)).strip("_").lower()


# ------------------------------------------------------------------- entry --

def auto_match_exact(min_coverage: float = MIN_COVERAGE) -> dict[str, Any]:
    """Run the deterministic pass across every discovered join key."""
    datasets = {
        d["name"]: d for d in db.query(
            "SELECT id, name, table_name FROM dataset WHERE status = 'ready'"
        )
    }
    types = {}
    for d in datasets.values():
        for c in _columns(d["id"]):
            types[(d["name"], c["column_name"])] = c["inferred_type"]

    # Split credit/debit columns are republished as one signed column first, so
    # the pairing below has something to compare at all.
    views: dict[str, str | None] = {
        name: normalised_view(d) for name, d in datasets.items()
    }
    normalised = {n: v for n, v in views.items() if v}

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

    results: list[dict[str, Any]] = []
    declined: list[dict[str, Any]] = []

    for p in strongest.values():
        ld, rd = datasets.get(p["left_dataset"]), datasets.get(p["right_dataset"])
        if not ld or not rd:
            continue
        left = _side(ld, p["left_column"], views.get(ld["name"]))
        right = _side(rd, p["right_column"], views.get(rd["name"]))
        if left is None or right is None:
            continue

        join_label = f"{left.name}.{left.key} = {right.name}.{right.key}"

        # --- what kind of relationship is this? --------------------------
        left_one = left.is_one_against(right)
        right_one = right.is_one_against(left)
        if left_one and right_one:
            shape, one, many = "1:1", None, None
        elif left_one:
            shape, one, many = "1:N", left, right
        elif right_one:
            shape, one, many = "N:1", right, left
        else:
            # Neither side is unique. Any group built here would fan out into
            # a blob no amount can check, so say so instead.
            declined.append({
                "join": join_label,
                "shape": "N:M",
                "reason": (
                    f"neither side is unique enough on the key to be the `one`"
                    f" ({left.name}: {left.distinct}/{left.rows} distinct ="
                    f" {left.ratio:.2f}, {right.name}: {right.distinct}/{right.rows}"
                    f" = {right.ratio:.2f});"
                    " a shared key here is not a one-to-one relationship."
                    " Match it through the sources either side, or write a"
                    " scoped rule."
                ),
            })
            continue

        # --- how does the money line up? ---------------------------------
        if shape == "1:1":
            amounts = pair_row_level(left, right)
            rule = f"auto_exact__{left.name}__{right.name}"
            sql = _sql_row_level(left, right, amounts)
            tolerance = 0
            kind = "row"
        else:
            assert one is not None and many is not None
            aggregate = pair_aggregate(one, many)
            partitioned = pair_partitioned(one, many)
            # Coverage decides, not agreement -- the same lesson as inside
            # `pair_partitioned`, one level up. A partition on a single refund
            # type ties perfectly across four rows and would otherwise beat an
            # aggregate that correctly explains ninety.
            amounts = max(
                (a for a in (aggregate, partitioned) if a),
                key=lambda a: (a.covered, a.agreement),
                default=None,
            )
            if amounts is None:
                # A one-to-many claim rests entirely on the amounts adding up.
                # Without them there is nothing to verify and nothing to say.
                declined.append({
                    "join": join_label,
                    "shape": shape,
                    "reason": (
                        f"{shape} on the key, and no amount relationship holds --"
                        " neither SUM over the many side nor any single class of"
                        " its rows agrees with the one side. Nothing here can be"
                        " verified, so nothing is proposed."
                    ),
                })
                continue
            kind = amounts.kind
            if kind == "aggregate":
                rule = f"auto_batch__{one.name}__{many.name}"
                sql = _sql_aggregate(one, many, amounts)
                tolerance = amounts.tolerance_minor
            else:
                pcol, value = amounts.partition or ("", "")
                rule = f"auto_part__{one.name}__{many.name}__{_slug(pcol)}_{_slug(value)}"
                sql = _sql_row_level(one, many, amounts)
                tolerance = 0

        description = f"{shape} on {join_label}" + (
            f"; {amounts.detail}" if amounts else "; no comparable amount column found"
        )
        try:
            outcome = matching.propose_matches(
                rule=rule, tier=1, sql=sql, description=description,
                tolerance_minor=tolerance, author=matching.SYSTEM,
            )
        except Exception as exc:
            results.append({"rule": rule, "error": f"{type(exc).__name__}: {exc}"})
            continue

        results.append({
            "rule": rule,
            "join": join_label,
            "shape": shape,
            "strategy": kind,
            "amounts": amounts.detail if amounts else None,
            "agreement": round(amounts.agreement, 3) if amounts else None,
            "tolerance_minor": tolerance,
            "proposed": outcome.get("proposed", 0),
            "by_confidence": outcome.get("by_confidence", {}),
            "skipped_already_matched": outcome.get("skipped_already_matched", 0),
            **({"duplicate_members_flagged": outcome["duplicate_members_flagged"]}
               if outcome.get("duplicate_members_flagged") else {}),
            **({"blocked_by_verification": outcome["blocked_by_verification"]}
               if outcome.get("blocked_by_verification") else {}),
        })

    total = sum(r.get("proposed", 0) for r in results)
    out: dict[str, Any] = {
        "rules_run": len(results),
        "groups_proposed": total,
        "results": results,
        # Coverage and leftovers come back in the same result on purpose.
        # Measured on a real turn, the agent followed this call with
        # reconciliation_status, list_unmatched, list_proposals, get_proposal
        # and five run_sql probes -- eight round trips to learn what this
        # function already knew. Each round trip is paid again in every later
        # call's history, so answering here is the single largest saving
        # available.
        "coverage": matching.reconciliation_status(),
        "next": "Everything above is current. Work the `declined` edges and the"
                " unmatched examples in `coverage`; do not re-fetch them.",
    }
    if normalised:
        out["normalised_views"] = normalised
    if declined:
        # Surfaced, not buried in a log: a declined edge is the most useful
        # thing this pass produces, because it is the part that needs a person.
        out["declined"] = declined
        out["next"] = (
            "Some edges were declined -- read `declined` first, then use"
            " reconciliation_status and list_unmatched for the remainder."
        )
    return out
