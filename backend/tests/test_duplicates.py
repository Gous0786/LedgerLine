"""Duplicate marking at ingest, and the policy that decides what it means.

The classification is the easy half. The half worth testing is that marking a
row does not, on its own, change a single number: on the labelled fixtures,
letting deduplicated groups release themselves cost 100% accuracy down to
81.7%. So the default must mark everything and count everything, and only an
explicit per-file decision may take a row out of the arithmetic.
"""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path
from typing import Any

from app.core import duplicates, ingest
from app.db import connection as db
from app.eval.runner import _Sandbox


def load(name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    directory = Path(tempfile.mkdtemp(prefix="dupe-test-"))
    path = directory / f"{name}.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    ingest.ingest_csv(path, name=name, original_name=path.name)
    return db.query_one("SELECT * FROM dataset WHERE name = ?", (name,))


def payments(n: int = 10) -> list[dict[str, Any]]:
    return [
        {"txn_id": f"T{i:04d}", "order_ref": f"ORD-{1000 + i}",
         "amount": 100 + i, "currency": "INR", "status": "captured"}
        for i in range(1, n + 1)
    ]


def test_identical_row_is_marked_exact() -> None:
    with _Sandbox():
        rows = payments()
        rows.append(dict(rows[3]))          # the same line, twice
        ds = load("gateway", rows)
        assert ds["duplicate_rows"] == 1, dict(ds)
        assert ds["near_duplicate_rows"] == 0

        marks = duplicates.redundant_rows(ds["id"])
        assert marks == {11: 4}, marks


def test_same_event_new_id_is_marked_near_not_exact() -> None:
    """The shape the labelled data calls an ambiguity, not a duplicate."""
    with _Sandbox():
        rows = payments()
        twin = dict(rows[3])
        twin["txn_id"] = "T0004_DUP"        # only the row's own id differs
        rows.append(twin)
        ds = load("gateway", rows)
        assert ds["duplicate_rows"] == 0, "a differing id is not byte-identical"
        assert ds["near_duplicate_rows"] == 1, dict(ds)


def test_two_real_payments_are_not_duplicates() -> None:
    """Same customer, same day, same amount -- and genuinely two payments.

    The rows differ in their reference, which is what makes them two events.
    Collapsing them would delete real money.
    """
    with _Sandbox():
        rows = payments()
        rows.append({"txn_id": "T9999", "order_ref": "ORD-9999",
                     "amount": 104, "currency": "INR", "status": "captured"})
        ds = load("gateway", rows)
        assert ds["duplicate_rows"] == 0
        assert ds["near_duplicate_rows"] == 0, "two distinct orders were merged"


def test_nothing_is_excluded_by_default() -> None:
    """Marking must not, by itself, remove a row from any sum."""
    with _Sandbox():
        rows = payments()
        rows.append(dict(rows[3]))
        ds = load("gateway", rows)
        assert duplicates.excluded_kinds(dict(ds)) == ()

        source = duplicates.filtered_source(dict(ds), f'"{ds["table_name"]}"')
        visible = db.query_one(f"SELECT COUNT(*) c FROM {source} x")["c"]
        assert visible == ds["row_count"] == 11, visible


def test_opting_in_takes_both_classes_out() -> None:
    with _Sandbox():
        rows = payments()
        rows.append(dict(rows[3]))          # exact
        twin = dict(rows[5])
        twin["txn_id"] = "T0006_DUP"        # near
        rows.append(twin)
        ds = load("gateway", rows)
        assert (ds["duplicate_rows"], ds["near_duplicate_rows"]) == (1, 1), dict(ds)

        db.execute("UPDATE dataset SET exclude_duplicates = 1 WHERE id = ?", (ds["id"],))
        ds = db.query_one("SELECT * FROM dataset WHERE id = ?", (ds["id"],))
        assert duplicates.excluded_kinds(dict(ds)) == (duplicates.EXACT, duplicates.NEAR)

        source = duplicates.filtered_source(dict(ds), f'"{ds["table_name"]}"')
        visible = db.query_one(f"SELECT COUNT(*) c FROM {source} x")["c"]
        assert visible == 10, f"expected the two repeats gone, saw {visible}"


def test_rescan_is_idempotent() -> None:
    """Uploading is not the only way in; a rescan must not accumulate marks."""
    with _Sandbox():
        rows = payments()
        rows.append(dict(rows[3]))
        ds = load("gateway", rows)
        first = duplicates.scan(ds["id"])
        second = duplicates.scan(ds["id"])
        assert first == second == {"duplicate_rows": 1, "near_duplicate_rows": 0}
        assert len(duplicates.redundant_rows(ds["id"])) == 1


def test_a_file_of_repeats_still_finds_its_id_column() -> None:
    """The bootstrapping trap: duplicates destroy the uniqueness of an id.

    Requiring a perfectly unique column to identify the row makes detection
    blind exactly when a file is full of repeats, which is when it matters.
    """
    with _Sandbox():
        rows = payments(40)
        for i in (2, 7, 11, 19, 23):        # a fifth of the file, twinned
            twin = dict(rows[i])
            twin["txn_id"] = f"{twin['txn_id']}_DUP"
            rows.append(twin)
        ds = load("gateway", rows)
        assert ds["near_duplicate_rows"] == 5, dict(ds)


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
