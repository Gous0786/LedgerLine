"""Join keys that live inside a text field.

A bank statement rarely carries the order reference in a column of its own. It
carries it inside a narration -- `NEFT-RZP-ORD-1001` -- and value-overlap
discovery compares whole cells, so the reference is invisible: the statement
shares nothing with anything, and the entire bank leg goes unmatched. That is
not a small gap. It is a third of the files in a typical close.

Nothing here knows what a narration looks like. No prefix, no bank and no
format is named anywhere in this module. What it does is ask a question the
data can answer on its own: does one column's value appear *inside* another
column's text, often enough and unambiguously enough to be the key? The
containment is then resolved once and published as an ordinary column, so the
cardinality classification, the amount search, the verifier and every other
stage downstream keep working on a plain equality join and need to know nothing
about any of this.

The guards are the whole design. A short value appears inside free text by
coincidence -- "IN" is inside "REMITTANCE" -- so a key must be long enough that
coincidence is implausible, and longer still when it is all digits. A row
containing two different keys has said nothing about which one it belongs to,
so it is dropped rather than guessed at. And a pair that already overlaps
literally is left alone, because ordinary discovery handles it better.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from app.config import get_settings
from app.core import sqlguard
from app.db import connection as db

log = logging.getLogger(__name__)

# Below this there is no distribution to measure -- any pattern found in four
# rows is as likely to be an accident as a rule.
MIN_CARRIER_ROWS = 5

# Share of the carrier's rows that must resolve to exactly one key. Matches the
# intent of `discovery.MIN_COVERAGE`: a key that explains less than half a file
# is not that file's key, whatever else it is.
MIN_CONTAINMENT = 0.5

# The coincidence guard, and the reason this is safe to run unsupervised. Every
# value of the key column must clear it, not merely the average, because a
# single short value ("IN", "NA", "0") is enough to match half a text column and
# drag unrelated rows into a group.
MIN_KEY_CHARS = 4

# Digits collide far more readily than mixed text: a four-digit key turns up
# inside any long reference number by chance, while "ORD-1001" does not. So an
# all-digit key has to be longer before it is believed.
MIN_NUMERIC_KEY_CHARS = 6

# A column with this few distinct values is a status or a currency, and
# containment against it matches everything. Same constant as the overlap
# matrix uses, for the same reason.
ENUM_MAX_DISTINCT = 12

# If the two columns already share this much as whole values, ordinary
# discovery has the edge covered and will do a better job of it.
ALREADY_JOINED = 0.25

# Containment is a nested loop. SQLite runs it in C, but the product still has
# to stay sane on a large upload.
MAX_PRODUCT = 40_000_000


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _slug(name: str) -> str:
    return re.sub(r"\W+", "_", name).strip("_").lower()


@dataclass
class Extraction:
    """One text column that turned out to be carrying another file's key."""

    carrier: dict[str, Any]        # dataset holding the text
    carrier_column: str
    key_dataset: dict[str, Any]    # dataset the key belongs to
    key_column: str
    rows: int                      # carrier rows in total
    resolved: int                  # carrier rows resolving to exactly one key
    ambiguous: int                 # carrier rows containing two or more keys
    column_name: str = ""          # what the extracted column is called
    view: str = ""                 # view publishing it

    @property
    def coverage(self) -> float:
        return (self.resolved / self.rows) if self.rows else 0.0

    def describe(self) -> str:
        return (
            f"{self.carrier['name']}.{self.carrier_column} contains"
            f" {self.key_dataset['name']}.{self.key_column}"
            f" in {self.resolved}/{self.rows} rows"
        )


def _columns(dataset_id: str) -> list[dict[str, Any]]:
    return db.query(
        "SELECT column_name, inferred_type FROM dataset_column"
        " WHERE dataset_id = ? ORDER BY ordinal",
        (dataset_id,),
    )


def _text_columns(dataset: dict[str, Any]) -> list[str]:
    return [
        c["column_name"] for c in _columns(dataset["id"])
        if c["inferred_type"] == "TEXT"
    ]


def _key_stats(table: str, column: str) -> dict[str, Any] | None:
    """Whether this column could be a key at all, before anyone looks for it."""
    q = _quote(column)
    try:
        return sqlguard.select_all(
            get_settings().db_path,
            f"SELECT COUNT({q}) n, COUNT(DISTINCT {q}) d,"
            f" MIN(LENGTH({q})) min_len,"
            # All-digit values collide much more easily, so they are counted
            # here and held to a longer minimum below.
            f" SUM(CASE WHEN TRIM({q}) GLOB '*[^0-9]*' THEN 0 ELSE 1 END) numeric_like"
            f" FROM {_quote(table)}"
            f" WHERE {q} IS NOT NULL AND TRIM({q}) <> ''",
        )[0]
    except Exception:
        return None


def _usable_key(stats: dict[str, Any]) -> bool:
    distinct, n = stats["d"] or 0, stats["n"] or 0
    if not n:
        return False
    if distinct <= ENUM_MAX_DISTINCT and n > distinct * 2:
        return False  # a status, not a key
    floor = (
        MIN_NUMERIC_KEY_CHARS
        if (stats["numeric_like"] or 0) == n
        else MIN_KEY_CHARS
    )
    # The *shortest* value has to clear the bar: one two-character value is
    # enough to poison the whole join.
    return (stats["min_len"] or 0) >= floor


def _literal_overlap(carrier: str, ccol: str, key: str, kcol: str) -> float:
    """How much the two columns already share as whole values."""
    c, k = _quote(ccol), _quote(kcol)
    try:
        row = sqlguard.select_all(
            get_settings().db_path,
            f"SELECT (SELECT COUNT(DISTINCT {c}) FROM {_quote(carrier)}"
            f"  WHERE {c} IN (SELECT {k} FROM {_quote(key)})) shared,"
            f" (SELECT COUNT(DISTINCT {c}) FROM {_quote(carrier)}) total",
        )[0]
    except Exception:
        return 0.0
    total = row["total"] or 0
    return ((row["shared"] or 0) / total) if total else 0.0


def _measure(carrier: dict[str, Any], ccol: str,
             key: dict[str, Any], kcol: str) -> Extraction | None:
    """Count carrier rows containing exactly one of the key column's values."""
    ct, kt = _quote(carrier["table_name"]), _quote(key["table_name"])
    c, k = _quote(ccol), _quote(kcol)
    try:
        row = sqlguard.select_all(
            get_settings().db_path,
            # One inner row per carrier row, carrying how many distinct keys it
            # contains. INSTR runs the containment in C; the outer query counts.
            f"SELECT SUM(CASE WHEN hits = 1 THEN 1 ELSE 0 END) resolved,"
            f" SUM(CASE WHEN hits > 1 THEN 1 ELSE 0 END) ambiguous,"
            f" COUNT(*) n FROM ("
            f"  SELECT ("
            f"    SELECT COUNT(DISTINCT kt.{k}) FROM {kt} kt"
            f"    WHERE kt.{k} IS NOT NULL AND TRIM(kt.{k}) <> ''"
            f"      AND INSTR(ct.{c}, kt.{k}) > 0"
            f"  ) hits FROM {ct} ct WHERE ct.{c} IS NOT NULL"
            f")",
        )[0]
    except Exception:
        log.debug("containment probe failed on %s.%s",
                  carrier["name"], ccol, exc_info=True)
        return None

    return Extraction(
        carrier=carrier, carrier_column=ccol,
        key_dataset=key, key_column=kcol,
        rows=row["n"] or 0,
        resolved=row["resolved"] or 0,
        ambiguous=row["ambiguous"] or 0,
    )


def find(datasets: list[dict[str, Any]],
         already_linked: set[frozenset[str]] | None = None) -> list[Extraction]:
    """The strongest embedded key per (carrier, key) dataset pair.

    `already_linked` names dataset pairs that ordinary overlap discovery has
    joined. Skipping them is not just an optimisation. Whether two files are
    already joined is a property of the *pair*, not of any column pair: a bank
    statement can repeat its batch id inside a free-text description while also
    carrying it in a column of its own, and probing column against column never
    sees that the edge is already covered. It would then republish the same key
    the long way round -- same answer, more machinery, and a real join quietly
    replaced by an inferred one.
    """
    best: dict[tuple[str, str], Extraction] = {}
    linked = already_linked or set()

    for carrier in datasets:
        if (carrier["row_count"] or 0) < MIN_CARRIER_ROWS:
            continue
        carrier_cols = _text_columns(carrier)
        if not carrier_cols:
            continue

        for key in datasets:
            if key["id"] == carrier["id"]:
                continue
            if frozenset((carrier["id"], key["id"])) in linked:
                continue
            product = (carrier["row_count"] or 0) * (key["row_count"] or 0)
            if product > MAX_PRODUCT:
                log.info("skipping embedded-key probe %s x %s: %d row pairs",
                         carrier["name"], key["name"], product)
                continue

            for kcol in _text_columns(key):
                stats = _key_stats(key["table_name"], kcol)
                if not stats or not _usable_key(stats):
                    continue
                for ccol in carrier_cols:
                    overlap = _literal_overlap(
                        carrier["table_name"], ccol, key["table_name"], kcol
                    )
                    if overlap >= ALREADY_JOINED:
                        continue  # ordinary discovery already has this edge
                    found = _measure(carrier, ccol, key, kcol)
                    if not found or found.coverage < MIN_CONTAINMENT:
                        continue
                    slot = (carrier["id"], key["id"])
                    if slot not in best or found.coverage > best[slot].coverage:
                        best[slot] = found

    return sorted(best.values(), key=lambda e: e.coverage, reverse=True)


def publish(found: Extraction, source: str | None = None) -> Extraction | None:
    """Resolve the containment once and expose the result as a column.

    Materialised rather than left as a correlated subquery inside the view: the
    uploaded files do not change after ingest, and every later stage -- the
    cardinality classification, the amount search, the verifier re-reading
    source rows -- would otherwise re-run the nested loop each time it touched
    the key.

    Rows containing more than one candidate key resolve to NULL. Guessing which
    was meant would put a fabricated link into a reconciliation, which is the
    one outcome worse than leaving the row unmatched.
    """
    existing = {c["column_name"] for c in _columns(found.carrier["id"])}
    name = found.key_column
    while name in existing:
        name += "_ref"

    # Every name carries the carrier column *and* the key it was resolved
    # against. One narration can hold two different references -- an order id
    # and a settlement id -- and a name built from the dataset alone would make
    # the second extraction drop the first one's table and build a view that
    # selects from itself.
    slug = _slug(found.carrier["name"])
    stem = f"{slug}_{_slug(found.carrier_column)}_{_slug(found.key_dataset['name'])}"
    keys_table = f"ek_{stem}"
    view = f"v_{stem}_key"
    # Chained onto whatever view the carrier already has, so an extraction
    # never hides the normalisation -- or the extraction -- that came before it.
    base = _quote(source) if source else _quote(found.carrier["table_name"])

    ct = _quote(found.carrier["table_name"])
    kt = _quote(found.key_dataset["table_name"])
    c, k = _quote(found.carrier_column), _quote(found.key_column)
    qname = _quote(name)

    body = (
        f"SELECT b.*, e.{qname} FROM {base} b"
        f" LEFT JOIN {_quote(keys_table)} e ON e.__row = b.__row"
    )
    try:
        with db.cursor() as conn:
            conn.execute(f'DROP VIEW IF EXISTS "{view}"')
            conn.execute(f'DROP TABLE IF EXISTS "{keys_table}"')
            conn.execute(
                f'CREATE TABLE "{keys_table}" AS'
                f" SELECT ct.__row AS __row, MIN(kt.{k}) AS {qname}"
                f" FROM {ct} ct JOIN {kt} kt"
                f"   ON kt.{k} IS NOT NULL AND TRIM(kt.{k}) <> ''"
                f"  AND INSTR(ct.{c}, kt.{k}) > 0"
                f" GROUP BY ct.__row"
                # Exactly one candidate, or nothing at all.
                f" HAVING COUNT(DISTINCT kt.{k}) = 1"
            )
            conn.execute(f'CREATE VIEW "{view}" AS {body}')
        db.execute(
            "INSERT INTO dataset_view (name, dataset_id, sql) VALUES (?,?,?)"
            " ON CONFLICT(name) DO UPDATE SET sql = excluded.sql,"
            "   dataset_id = excluded.dataset_id",
            (view, found.carrier["id"], body),
        )
    except Exception:
        log.warning("could not publish embedded key for %s.%s",
                    found.carrier["name"], found.carrier_column, exc_info=True)
        return None

    found.column_name = name
    found.view = view
    log.info("embedded key: %s -> %s.%s (%d ambiguous, dropped)",
             found.describe(), view, name, found.ambiguous)
    return found


def as_pair(found: Extraction) -> dict[str, Any]:
    """The extraction, in the shape `discovery.find_join_candidates` returns.

    So that the rest of matching consumes it through one code path and cannot
    treat an embedded key as a second class of thing.
    """
    coverage = round(found.coverage, 3)
    return {
        "left_dataset": found.carrier["name"],
        "left_dataset_id": found.carrier["id"],
        "left_column": found.column_name,
        "right_dataset": found.key_dataset["name"],
        "right_dataset_id": found.key_dataset["id"],
        "right_column": found.key_column,
        "overlap": found.resolved,
        "left_coverage": coverage,
        "right_coverage": coverage,
        "jaccard": coverage,
        "embedded_in": found.carrier_column,
        "examples": [],
    }
