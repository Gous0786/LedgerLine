"""The guards on embedded-key discovery, which are the whole safety argument.

Finding a reference inside a narration is easy. Not finding one that is not
there is the hard part, and it is what keeps this from inventing matches: a
two-character value is inside half of any text column, and a row mentioning two
different references has not told you which one it belongs to.

Each guard gets a case here because a guard nobody tests is a guard that stops
working silently -- which is exactly how this codebase's exploration budget
came to be dead code.
"""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path
from typing import Any

from app.core import discovery, embedded, ingest
from app.db import connection as db
from app.eval.runner import _Sandbox


def write_csv(directory: Path, name: str, rows: list[dict[str, Any]]) -> Path:
    path = directory / f"{name}.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


def load(**files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ingest each keyword as a dataset and return them, inside a sandbox."""
    directory = Path(tempfile.mkdtemp(prefix="embedded-test-"))
    for name, rows in files.items():
        path = write_csv(directory, name, rows)
        ingest.ingest_csv(path, name=name, original_name=path.name)
    return db.query(
        "SELECT id, name, table_name, row_count FROM dataset WHERE status = 'ready'"
    )


def ledger(n: int = 8) -> list[dict[str, Any]]:
    return [
        {"entry_id": f"E{i:03d}", "reference": f"ORD-{1000 + i}", "amount": 100 + i}
        for i in range(1, n + 1)
    ]


def test_reference_inside_a_narration_is_found() -> None:
    with _Sandbox():
        datasets = load(
            erp=ledger(),
            bank=[
                {"utr": f"U{i:03d}",
                 "narration": f"NEFT-RZP-ORD-{1000 + i}",
                 "credit": 100 + i}
                for i in range(1, 9)
            ],
        )
        found = embedded.find(datasets)
        assert len(found) == 1, [f.describe() for f in found]
        assert found[0].carrier_column == "narration"
        assert found[0].key_column == "reference"
        assert found[0].resolved == 8
        assert found[0].ambiguous == 0


def test_short_key_is_refused() -> None:
    """"IN" is inside "REMITTANCE". A two-character key matches everything."""
    with _Sandbox():
        datasets = load(
            codes=[{"code": c, "amount": 1} for c in
                   ("IN", "US", "GB", "DE", "FR", "JP", "AU", "CA",
                    "BR", "ZA", "NL", "SE", "NO", "IE")],
            bank=[{"utr": f"U{i}", "narration": n, "credit": 1}
                  for i, n in enumerate(
                      ["INWARD REMITTANCE", "DOMESTIC INTEREST", "USUAL FEE",
                       "GBP CONVERSION", "DEPOSIT INBOUND", "INCOMING NEFT",
                       "IN BRANCH CASH", "INSURANCE DEBIT"])],
        )
        assert embedded.find(datasets) == [], "a two-character key was believed"


def test_short_numeric_key_is_refused() -> None:
    """Digits collide even more readily, so they must be longer to be believed.

    The keys carry leading zeros deliberately. Without them ingest types the
    column INTEGER, the search never considers it, and the test would pass
    without the guard it is meant to be covering ever running.
    """
    with _Sandbox():
        datasets = load(
            batches=[{"batch": f"{i:04d}", "amount": 1} for i in range(1, 15)],
            bank=[{"utr": f"U{i}", "narration": f"UTR-{i:04d}-SETTLEMENT", "credit": 1}
                  for i in range(1, 15)],
        )
        # The guard is only meaningful if the column reaches it at all.
        assert "batch" in embedded._text_columns(
            [d for d in datasets if d["name"] == "batches"][0]
        ), "the key column was typed INTEGER and never tested"

        found = embedded.find(datasets)
        assert found == [], f"a 4-digit key was believed: {[f.describe() for f in found]}"


def test_status_column_is_refused() -> None:
    """A handful of values repeated across many rows is an enum, not a key."""
    with _Sandbox():
        datasets = load(
            gateway=[{"txn": f"T{i:03d}", "status": "CAPTURED" if i % 2 else "REFUNDED",
                      "amount": i} for i in range(1, 20)],
            bank=[{"utr": f"U{i:03d}", "narration": f"PAYMENT CAPTURED {i}", "credit": i}
                  for i in range(1, 20)],
        )
        for found in embedded.find(datasets):
            assert found.key_column != "status", "an enum was used as a key"


def test_ambiguous_rows_are_dropped_not_guessed() -> None:
    """A narration naming two references has not said which one it belongs to."""
    with _Sandbox():
        rows = [
            {"utr": f"U{i:03d}", "narration": f"NEFT-ORD-{1000 + i}", "credit": 100 + i}
            for i in range(1, 8)
        ]
        # This one names two orders. Neither may be claimed.
        rows.append({"utr": "U999", "narration": "REVERSAL ORD-1001 AND ORD-1002",
                     "credit": 1})
        datasets = load(erp=ledger(), bank=rows)

        found = embedded.find(datasets)
        assert len(found) == 1
        assert found[0].ambiguous == 1, "the two-key row was not seen as ambiguous"

        published = embedded.publish(found[0])
        assert published is not None
        rows_out = db.query(
            f'SELECT narration, "{published.column_name}" AS k'
            f' FROM "{published.view}" ORDER BY __row'
        )
        guessed = [r for r in rows_out if "AND" in r["narration"] and r["k"] is not None]
        assert not guessed, f"an ambiguous row was given a key: {guessed}"
        assert sum(r["k"] is not None for r in rows_out) == 7


def test_pair_already_joined_literally_is_skipped() -> None:
    """The pair is linked by a real column; re-deriving it the long way is waste."""
    with _Sandbox():
        datasets = load(
            erp=ledger(),
            bank=[
                {"utr": f"U{i:03d}",
                 "reference": f"ORD-{1000 + i}",              # the literal edge
                 "narration": f"NEFT-RZP-ORD-{1000 + i}",     # the same key, buried
                 "credit": 100 + i}
                for i in range(1, 9)
            ],
        )
        pairs = discovery.find_join_candidates()["pairs"]
        linked = {
            frozenset((p["left_dataset_id"], p["right_dataset_id"])) for p in pairs
        }
        assert linked, "discovery should have found the literal reference column"
        assert embedded.find(datasets, already_linked=linked) == []
        # ...and without that knowledge it would happily re-derive it.
        assert embedded.find(datasets) != []


def test_published_column_joins_as_an_ordinary_key() -> None:
    """The point of publishing: everything downstream sees a plain column."""
    with _Sandbox():
        datasets = load(
            erp=ledger(),
            bank=[
                {"utr": f"U{i:03d}",
                 "narration": f"NEFT-RZP-ORD-{1000 + i}",
                 "credit": 100 + i}
                for i in range(1, 9)
            ],
        )
        published = embedded.publish(embedded.find(datasets)[0])
        assert published is not None

        joined = db.query(
            f'SELECT COUNT(*) n FROM "{published.view}" b'
            f' JOIN "{[d for d in datasets if d["name"] == "erp"][0]["table_name"]}" e'
            f'   ON e.reference = b."{published.column_name}"'
        )[0]
        assert joined["n"] == 8, joined

        pair = embedded.as_pair(published)
        assert pair["left_column"] == published.column_name
        assert pair["right_column"] == "reference"
        assert pair["embedded_in"] == "narration"


if __name__ == "__main__":
    failures = 0
    for _name, _fn in sorted(globals().items()):
        if not _name.startswith("test_") or not callable(_fn):
            continue
        try:
            _fn()
            print(f"  ok   {_name}")
        except AssertionError as exc:
            failures += 1
            print(f"  FAIL {_name}: {exc}")
    raise SystemExit(failures)
