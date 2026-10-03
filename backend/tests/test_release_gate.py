"""The routes by which a group reaches `accepted` without a person.

Each case here was a way to get a false auto-match past the gate: a query run
under a name someone else earned trust for, a column that agrees because it
never changes, a rejection the next run quietly overturned, and a zero that
"traced" to whatever other cell in the row happened to be zero.

False auto-matches are the number this project is judged on, so each hole gets
a case that fails when the guard is taken out.
"""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path
from typing import Any

from app.core import automatch, ingest, matching, verify
from app.db import connection as db
from app.eval.runner import _Sandbox

ORDERS = 30


def write_csv(directory: Path, name: str, rows: list[dict[str, Any]]) -> Path:
    path = directory / f"{name}.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


def load(**files: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    directory = Path(tempfile.mkdtemp(prefix="gate-test-"))
    for name, rows in files.items():
        path = write_csv(directory, name, rows)
        ingest.ingest_csv(path, name=name, original_name=path.name)
    return {
        d["name"]: d for d in db.query(
            "SELECT id, name, table_name FROM dataset WHERE status = 'ready'"
        )
    }


def ledger(**extra: Any) -> list[dict[str, Any]]:
    return [
        {"order_id": f"ORD-{1000 + i}", "amount": 100 + 7 * i,
         **{k: (v(i) if callable(v) else v) for k, v in extra.items()}}
        for i in range(1, ORDERS + 1)
    ]


def gateway(off_by: set[int] = frozenset(), **extra: Any) -> list[dict[str, Any]]:
    return [
        {"pay_id": f"pay_{i:04d}", "order_id": f"ORD-{1000 + i}",
         "gross_amount": 100 + 7 * i + (50 if i in off_by else 0),
         **{k: (v(i) if callable(v) else v) for k, v in extra.items()}}
        for i in range(1, ORDERS + 1)
    ]


def accepted_keys() -> set[str]:
    return {
        r["group_key"] for r in db.query(
            "SELECT group_key FROM match_proposal WHERE status = 'accepted'"
        )
    }


def pair_sql(ds: dict[str, dict[str, Any]], order: str, key: str) -> str:
    """A hand-written rule pairing one order with its gateway row."""
    led, gw = ds["ledger"], ds["gateway"]
    return (
        f"SELECT '{key}' AS group_key, 'ledger' AS dataset, __row AS row,"
        f" CAST(ROUND(amount * 100) AS INTEGER) AS amount_minor"
        f" FROM \"{led['table_name']}\" WHERE order_id = '{order}'"
        f" UNION ALL"
        f" SELECT '{key}', 'gateway', __row,"
        f" -CAST(ROUND(gross_amount * 100) AS INTEGER)"
        f" FROM \"{gw['table_name']}\" WHERE order_id = '{order}'"
    )


# ------------------------------------------------------------- rule trust --

def test_agent_cannot_run_sql_under_a_system_rule_name() -> None:
    with _Sandbox():
        ds = load(ledger=ledger(), gateway=gateway())
        automatch.auto_match_exact()
        system_rule = db.query_one(
            "SELECT rule FROM rule_trust WHERE rule LIKE 'auto_%'"
        )["rule"]
        try:
            matching.propose_matches(
                rule=system_rule, tier=1, sql=pair_sql(ds, "ORD-1001", "X"),
            )
        except matching.MatchError:
            return
        raise AssertionError("an agent query ran under a trusted system rule's name")


def test_approved_rule_name_does_not_carry_trust_to_new_sql() -> None:
    with _Sandbox():
        ds = load(ledger=ledger(), gateway=gateway())
        approved = pair_sql(ds, "ORD-1001", "A")
        matching._register_rule("hand_pair", approved)
        matching.trust_rule("hand_pair")

        # Whitespace is not a different query.
        spaced = approved.replace(" UNION ALL ", "\n  UNION ALL\n  ")
        out = matching.propose_matches(rule="hand_pair", tier=1, sql=spaced)
        assert out["auto_accepted"] == 1, out

        try:
            matching.propose_matches(
                rule="hand_pair", tier=1, sql=pair_sql(ds, "ORD-1002", "B"),
            )
        except matching.MatchError:
            assert "B" not in accepted_keys()
            return
        raise AssertionError("new SQL inherited the trust approved for other SQL")


# ------------------------------------------------------- amount discovery --

def test_constant_column_is_not_taken_for_the_amount() -> None:
    """Both files carry merchant_id = 12345. It agrees on every row; the real
    amount only agrees where there is no exception."""
    off = {3, 6, 9, 12, 15, 18, 21, 24, 27, 30}
    with _Sandbox():
        load(
            ledger=ledger(merchant_id=12345),
            gateway=gateway(off_by=off, merchant_id=12345),
        )
        out = automatch.auto_match_exact()
        rule = next(r for r in out["results"] if r["rule"].startswith("auto_exact__"))
        assert "merchant_id" not in (rule["amounts"] or ""), rule
        wrongly = {f"ORD-{1000 + i}" for i in off} & accepted_keys()
        assert not wrongly, f"amount breaks auto-accepted: {sorted(wrongly)}"


def test_mostly_zero_column_is_not_taken_for_the_amount() -> None:
    """A discount that is 0 on nearly every row agrees on nearly every row."""
    off = {3, 6, 9, 12, 15, 18, 21, 24, 27, 30}
    discount = lambda i: 5 if i in (1, 2) else 0  # noqa: E731
    with _Sandbox():
        load(
            ledger=ledger(discount=discount),
            gateway=gateway(off_by=off, discount=discount),
        )
        out = automatch.auto_match_exact()
        rule = next(r for r in out["results"] if r["rule"].startswith("auto_exact__"))
        assert "discount" not in (rule["amounts"] or ""), rule
        wrongly = {f"ORD-{1000 + i}" for i in off} & accepted_keys()
        assert not wrongly, f"amount breaks auto-accepted: {sorted(wrongly)}"


# -------------------------------------------------------------- rejection --

def test_rejected_group_is_not_reproposed_on_the_next_run() -> None:
    with _Sandbox():
        load(ledger=ledger(), gateway=gateway())
        automatch.auto_match_exact()
        p = db.query_one(
            "SELECT id, group_key FROM match_proposal"
            " WHERE status = 'accepted' ORDER BY id LIMIT 1"
        )
        matching.set_status(p["id"], "rejected")

        automatch.auto_match_exact()
        again = db.query(
            "SELECT status FROM match_proposal WHERE group_key = ?", (p["group_key"],)
        )
        assert [r["status"] for r in again] == ["rejected"], again


def test_trusted_rule_cannot_release_rows_a_person_rejected() -> None:
    with _Sandbox():
        ds = load(ledger=ledger(), gateway=gateway())
        automatch.auto_match_exact()
        p = db.query_one(
            "SELECT id FROM match_proposal WHERE group_key = 'ORD-1001'"
        )
        matching.set_status(p["id"], "rejected")

        sql = pair_sql(ds, "ORD-1001", "regrouped")
        matching._register_rule("hand_pair", sql)
        matching.trust_rule("hand_pair")
        out = matching.propose_matches(rule="hand_pair", tier=1, sql=sql)
        assert out["auto_accepted"] == 0, out
        assert out["held_previously_rejected"] == 1, out
        assert "regrouped" not in accepted_keys()


# ---------------------------------------------------------------- tracing --

def test_zero_amount_does_not_trace_to_some_other_zero_cell() -> None:
    """An empty amount COALESCEs to 0; a fee of 0 must not vouch for it."""
    with _Sandbox():
        rows = ledger(fee=0)
        rows[0]["amount"] = ""
        ds = load(ledger=rows)
        ctx = verify.Context()
        data = ctx.row(ds["ledger"]["id"], 1)
        assert data is not None
        found = verify.trace_amount(ctx, ds["ledger"]["id"], data, 0)
        assert found is None, found


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
