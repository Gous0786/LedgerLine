"""CSV to SQLite ingestion.

Each uploaded file becomes its own table (`ds_<id>`), preserving its original
schema in `dataset_column`. This supports multi-source, multi-directional
reconciliation without forcing a shared canonical schema.

Type is definied based on values of each column, column with all integers
becomes INTEGER, column with all floats becomes REAL, otherwise it remains
TEXT.

"""

from __future__ import annotations

import csv
import logging
import re
import sqlite3
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core import duplicates
from app.db import connection as db

log = logging.getLogger(__name__)

# Analysing some rows to infer its column type
SNIFF_BYTES = 64 * 1024
SAMPLE_ROWS = 2000
INSERT_BATCH = 1000

CANDIDATE_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")

# Ordinal column preserving original file order. Reserved against collision.
ROW_COL = "__row"

_INT_RE = re.compile(r"^[+-]?\d+$")
_GROUPED_RE = re.compile(r"^[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?$")
_FLOAT_RE = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$|^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}$")
_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}")

# Beyond this many digits, a numeric-looking value is far more likely to be an
# identifier (UTR, account, card) than a quantity.
_MAX_INT_DIGITS = 15


class IngestError(Exception):
    pass


@dataclass
class ColumnSpec:
    ordinal: int
    source_name: str
    column_name: str
    inferred_type: str = "TEXT"
    null_count: int = 0
    samples: list[str] = field(default_factory=list)

    @property
    def affinity(self) -> str:
        """SQLite storage class. DATE/TIMESTAMP have no native type."""
        return self.inferred_type if self.inferred_type in ("INTEGER", "REAL") else "TEXT"


# --------------------------------------------------------------- detection --

def _detect_encoding(path: Path) -> str:
    head = path.read_bytes()[:SNIFF_BYTES]
    for enc in CANDIDATE_ENCODINGS:
        try:
            head.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    return "latin-1"  # decodes any byte sequence


def _detect_delimiter(path: Path, encoding: str) -> str:
    with path.open("r", encoding=encoding, newline="") as fh:
        sample = fh.read(SNIFF_BYTES)
    if not sample.strip():
        raise IngestError("file is empty")
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","  # single-column files make the sniffer throw


def _quote(identifier: str) -> str:
    """Quote a SQL identifier, escaping any embedded double quotes."""
    return '"' + identifier.replace('"', '""') + '"'


def _sanitize_headers(headers: list[str]) -> list[str]:
    """Map CSV headers to unique, safe SQL identifiers."""
    out: list[str] = []
    for i, raw in enumerate(headers):
        name = re.sub(r"\W+", "_", (raw or "").strip()).strip("_").lower()
        if not name:
            name = f"col_{i + 1}"
        if name[0].isdigit():
            name = f"c_{name}"
        if name == ROW_COL:
            name = f"{name}_col"
        out.append(name)

    # De-duplicate, including against names produced by earlier suffixing.
    seen: set[str] = set()
    unique: list[str] = []
    for name in out:
        candidate, n = name, 1
        while candidate in seen:
            n += 1
            candidate = f"{name}_{n}"
        seen.add(candidate)
        unique.append(candidate)
    return unique


# --------------------------------------------------------------- inference --

def _numeric_kind(v: str) -> str | None:
    """INTEGER / REAL / None, with identifier hazards excluded.

    The hazards matter more than the convenience of a numeric column: a UTR
    like ``0007712345`` parses cleanly as a number, and coercing it silently
    destroys the padding that makes it matchable. Anything that looks like a
    padded or over-long digit run stays TEXT.
    """
    digits = v.lstrip("+-")
    if not digits:
        return None

    # Leading zero means the padding is significant -- but 0.5 is a real number.
    if len(digits) > 1 and digits[0] == "0" and digits[1] not in ".eE":
        return None

    if _INT_RE.match(v):
        return "INTEGER" if len(digits) <= _MAX_INT_DIGITS else None
    if _GROUPED_RE.match(v):
        return "REAL"
    if _FLOAT_RE.match(v):
        # A long digit run with no fractional part is an identifier, and float
        # would cost precision anyway.
        if "." not in v and "e" not in v.lower() and len(digits) > _MAX_INT_DIGITS:
            return None
        return "REAL"
    return None


def _infer_type(values: list[str]) -> str:
    if not values:
        return "TEXT"
    kinds = [_numeric_kind(v) for v in values]
    if all(k == "INTEGER" for k in kinds):
        return "INTEGER"
    if all(k is not None for k in kinds):
        return "REAL"
    if all(_TS_RE.match(v) for v in values):
        return "TIMESTAMP"
    if all(_DATE_RE.match(v) for v in values):
        return "DATE"
    return "TEXT"


def _coerce(value: str, affinity: str) -> Any:
    if value == "":
        return None
    if affinity == "INTEGER":
        try:
            return int(value)
        except ValueError:
            return value
    if affinity == "REAL":
        try:
            return float(value.replace(",", ""))
        except ValueError:
            return value
    return value


# ------------------------------------------------------------------ ingest --

def _read_header_and_sample(
    path: Path, encoding: str, delimiter: str
) -> tuple[list[str], list[list[str]]]:
    with path.open("r", encoding=encoding, newline="") as fh:
        reader = csv.reader(fh, delimiter=delimiter)
        try:
            headers = next(reader)
        except StopIteration as exc:
            raise IngestError("file has no header row") from exc
        if not headers:
            raise IngestError("file has no header row")

        sample: list[list[str]] = []
        for row in reader:
            sample.append(row)
            if len(sample) >= SAMPLE_ROWS:
                break
    return headers, sample


def _build_columns(headers: list[str], sample: list[list[str]]) -> list[ColumnSpec]:
    names = _sanitize_headers(headers)
    cols = [
        ColumnSpec(ordinal=i, source_name=(headers[i] or "").strip(), column_name=names[i])
        for i in range(len(headers))
    ]
    for col in cols:
        seen = [
            row[col.ordinal].strip()
            for row in sample
            if col.ordinal < len(row) and row[col.ordinal].strip() != ""
        ]
        col.inferred_type = _infer_type(seen)
        col.null_count = len(sample) - len(seen)
        col.samples = seen[:3]
    return cols


def ingest_csv(
    path: Path,
    *,
    name: str,
    original_name: str,
    role: str | None = None,
) -> dict[str, Any]:
    """Load one CSV into its own table and register it. Returns the dataset row."""
    dataset_id = uuid.uuid4().hex[:12]
    table = f"ds_{dataset_id}"

    encoding = _detect_encoding(path)
    delimiter = _detect_delimiter(path, encoding)
    headers, sample = _read_header_and_sample(path, encoding, delimiter)
    cols = _build_columns(headers, sample)

    col_defs = ", ".join(f"{_quote(c.column_name)} {c.affinity}" for c in cols)
    insert_cols = ", ".join([_quote(ROW_COL)] + [_quote(c.column_name) for c in cols])
    placeholders = ", ".join(["?"] * (len(cols) + 1))
    affinities = [c.affinity for c in cols]
    width = len(cols)

    row_count = 0
    with db.cursor() as conn:
        try:
            conn.execute("BEGIN")
            conn.execute(
                f"CREATE TABLE {_quote(table)} "
                f"({_quote(ROW_COL)} INTEGER PRIMARY KEY, {col_defs},"
                f' "__duplicate_of" INTEGER, "__duplicate_kind" TEXT)'
            )

            conn.execute(
                "INSERT INTO dataset (id, name, original_name, table_name, role,"
                " delimiter, encoding, byte_size, status)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')",
                (
                    dataset_id,
                    name,
                    original_name,
                    table,
                    role,
                    delimiter,
                    encoding,
                    path.stat().st_size,
                ),
            )
            conn.executemany(
                "INSERT INTO dataset_column (dataset_id, ordinal, source_name, column_name,"
                " inferred_type, null_count, sample) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        dataset_id,
                        c.ordinal,
                        c.source_name,
                        c.column_name,
                        c.inferred_type,
                        c.null_count,
                        " | ".join(c.samples),
                    )
                    for c in cols
                ],
            )

            sql = f"INSERT INTO {_quote(table)} ({insert_cols}) VALUES ({placeholders})"
            with path.open("r", encoding=encoding, newline="") as fh:
                reader = csv.reader(fh, delimiter=delimiter)
                next(reader, None)  # skip header
                batch: list[tuple] = []
                for raw in reader:
                    # Ragged rows: pad short ones, drop overflow cells.
                    row = (raw + [""] * width)[:width]
                    row_count += 1
                    batch.append(
                        (
                            row_count,
                            *(
                                _coerce(v.strip(), a)
                                for v, a in zip(row, affinities, strict=True)
                            ),
                        )
                    )
                    if len(batch) >= INSERT_BATCH:
                        conn.executemany(sql, batch)
                        batch.clear()
                if batch:
                    conn.executemany(sql, batch)

            conn.execute(
                "UPDATE dataset SET row_count = ?, status = 'ready' WHERE id = ?",
                (row_count, dataset_id),
            )
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.OperationalError:
                pass
            # The table is created inside the transaction, so rollback drops it.
            log.exception("ingest failed for %s", original_name)
            raise

    # After the transaction that wrote the rows, because it reads them back and
    # because a failed scan must not undo a successful ingest. A dataset whose
    # marks are missing is merely un-deduplicated, which is what every dataset
    # was until this existed.
    marks = duplicates.scan(dataset_id)

    log.info("ingested %s -> %s (%d rows, %d cols)", original_name, table, row_count, width)
    return {
        "id": dataset_id,
        "name": name,
        "original_name": original_name,
        "table_name": table,
        "role": role,
        "row_count": row_count,
        "column_count": width,
        **marks,
        "delimiter": delimiter,
        "encoding": encoding,
        "status": "ready",
    }


def drop_dataset(dataset_id: str) -> bool:
    row = db.query_one("SELECT table_name FROM dataset WHERE id = ?", (dataset_id,))
    if not row:
        return False
    with db.cursor() as conn:
        conn.execute("BEGIN")
        try:
            conn.execute(f"DROP TABLE IF EXISTS {_quote(row['table_name'])}")
            # match_member.dataset_id is a plain column, not a foreign key, so
            # nothing cascades. Without this the matches survive their own
            # evidence and the reconciled view breaks on rows that are gone.
            conn.execute(
                "DELETE FROM match_proposal WHERE id IN ("
                "  SELECT DISTINCT proposal_id FROM match_member WHERE dataset_id = ?"
                ")",
                (dataset_id,),
            )
            conn.execute("DELETE FROM dataset WHERE id = ?", (dataset_id,))
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.OperationalError:
                pass
            raise
    return True
