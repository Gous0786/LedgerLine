"""Independent verification of a match, run before it is released.

`propose_matches` scores a group and records it in one pass, from numbers the
agent's own SQL produced. That is the weak joint in the whole system: a wrong
`CAST` -- truncation where rounding was meant -- or a `COALESCE(col, 0)` that
turns a missing amount into a balancing zero yields a group that is internally
flawless and factually wrong. Confidence cannot catch it, because confidence is
computed from those same numbers.

So this module re-derives everything, and to be worth running it must share as
little as possible with the pass it is checking. The rule it works under:

    the only thing a proposal is trusted to say is *which rows it is about*.

`match_member.(dataset_id, row)` is taken as given. Every amount is read back
out of the source cell, converted here with exact decimal arithmetic, and the
group re-balanced. An amount that corresponds to no cell in the row it claims
to come from is the signature of a bad expression, and it fails.

What this cannot do, stated plainly: it does not know which column *should*
have been used. A rule that matches gross against gross when it meant net still
verifies, because both numbers are really there. It catches arithmetic that lies
about the data, not a rule that asks the wrong question -- that is what
`rule_trust` is for.
"""

from __future__ import annotations

import json
import logging
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from app.config import get_settings
from app.core import duplicates, sqlguard, timing
from app.db import connection as db

log = logging.getLogger(__name__)

VERIFIER_VERSION = "recon-verifier-v1"

# Beyond this many numeric columns the pairwise search for a computed amount
# (credit - debit, gross - fee) is both slow and unconvincing: with enough
# columns, some pair sums to anything.
MAX_PAIR_COLUMNS = 12

_MONEY_JUNK = re.compile(r"[^\d.,+\-()]")
_NUMERIC = re.compile(r"^[+-]?\d+(\.\d+)?$")
_ISO_CURRENCY = re.compile(r"^[A-Z]{3}$")

PASS = "pass"
FAIL = "fail"


class VerifyError(Exception):
    pass


# ------------------------------------------------------------------ values --

def to_minor(value: Any) -> Decimal | None:
    """A cell value as minor units, or None if it is not a quantity.

    Decimal throughout, and `str()` before Decimal: `Decimal(0.1)` is not 0.1,
    and the entire point of this module is to not repeat the float mistake it
    is looking for. Rounding is HALF_UP, stated once here rather than left to
    whatever each rule happened to write.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        d = Decimal(value)
    elif isinstance(value, float):
        d = Decimal(str(value))
    else:
        s = str(value).strip()
        if not s:
            return None
        s = _MONEY_JUNK.sub("", s)
        negative = s.startswith("(") and s.endswith(")")  # accounting negative
        s = s.replace("(", "").replace(")", "").replace(",", "")
        if negative and not s.startswith("-"):
            s = "-" + s
        if not _NUMERIC.match(s):
            return None
        try:
            d = Decimal(s)
        except InvalidOperation:
            return None
    return (d * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP)


# ----------------------------------------------------------------- context --

class Context:
    """Dataset metadata, read once per verification batch.

    Not an lru_cache: a session reset drops every table under it, and a cache
    that survived that would verify against a schema which no longer exists.
    """

    def __init__(self) -> None:
        self.tables: dict[str, str] = {}
        self.names: dict[str, str] = {}
        self.columns: dict[str, list[str]] = {}
        self.currency: dict[str, str | None] = {}
        self._rows: dict[tuple[str, int], dict[str, Any] | None] = {}
        self._baselines: dict[str, timing.Baseline | None] = {}

        for d in db.query("SELECT id, name, table_name FROM dataset"):
            self.tables[d["id"]] = d["table_name"]
            self.names[d["id"]] = d["name"]
            cols = db.query(
                "SELECT column_name, inferred_type FROM dataset_column"
                " WHERE dataset_id = ? ORDER BY ordinal",
                (d["id"],),
            )
            # TEXT columns are included: ingest leaves an amount column as TEXT
            # the moment one row carries a stray symbol, and that column is
            # still where the money is.
            self.columns[d["id"]] = [c["column_name"] for c in cols]
            self.currency[d["id"]] = _currency_column(d["id"], d["table_name"], cols)

    def label(self, dataset_id: str, row: int) -> str:
        return f"{self.names.get(dataset_id, dataset_id)}#{row}"

    def baseline(self, rule: str) -> timing.Baseline | None:
        """What a normal settlement lag looks like for this rule.

        Computed once per rule and held for the batch, because it is a property
        of the whole population and re-deriving it per proposal would make the
        check cost more than the matching did.
        """
        if rule in self._baselines:
            return self._baselines[rule]

        members = db.query(
            "SELECT m.proposal_id, m.dataset_id, m.row FROM match_member m"
            " JOIN match_proposal p ON p.id = m.proposal_id"
            " WHERE p.rule = ? AND p.status != 'rejected'",
            (rule,),
        )
        by_proposal: dict[int, list[dict[str, Any]]] = {}
        for m in members:
            found = self.row(m["dataset_id"], m["row"])
            if found is not None:
                by_proposal.setdefault(m["proposal_id"], []).append(found)

        spans = [
            s for s in (timing.group_span_seconds(rows) for rows in by_proposal.values())
            if s is not None
        ]
        result = timing.Baseline(spans) if spans else None
        self._baselines[rule] = result
        return result

    def row(self, dataset_id: str, row: int) -> dict[str, Any] | None:
        key = (dataset_id, int(row))
        if key in self._rows:
            return self._rows[key]
        table = self.tables.get(dataset_id)
        found: dict[str, Any] | None = None
        if table:
            try:
                got = sqlguard.select_all(
                    get_settings().db_path,
                    f'SELECT * FROM "{table}" WHERE __row = {int(row)}',
                )
                found = got[0] if got else None
            except Exception:
                found = None
        self._rows[key] = found
        return found


def _currency_column(
    dataset_id: str, table: str, cols: list[dict[str, Any]]
) -> str | None:
    """A column holding ISO currency codes, discovered rather than configured.

    Same principle as the rest of the system: nothing here knows a column is
    called `currency`. It is one whose values all look like `INR`.
    """
    for c in cols:
        if c["inferred_type"] != "TEXT":
            continue
        name = c["column_name"].replace('"', '""')
        try:
            vals = sqlguard.select_all(
                get_settings().db_path,
                f'SELECT DISTINCT "{name}" AS v FROM "{table}"'
                f' WHERE "{name}" IS NOT NULL LIMIT 25',
            )
        except Exception:
            continue
        seen = [str(v["v"]).strip().upper() for v in vals]
        if seen and len(seen) <= 20 and all(_ISO_CURRENCY.match(s) for s in seen):
            return c["column_name"]
    return None


# ------------------------------------------------------------------ tracing --

def trace_amount(
    ctx: Context, dataset_id: str, data: dict[str, Any], target_minor: int
) -> dict[str, Any] | None:
    """Where in this row does `target_minor` actually come from?

    Magnitude only. The sign a rule gives a member is a modelling choice -- an
    invoice is positive so a charge can cancel it -- but the magnitude is a
    claim about the data, and that is the part which has to be true.
    """
    target = abs(Decimal(int(target_minor)))
    cells: list[tuple[str, Decimal]] = []
    for c in ctx.columns.get(dataset_id, []):
        m = to_minor(data.get(c))
        if m is not None:
            cells.append((c, m))

    for c, m in cells:
        if abs(m) == target:
            return {"how": "column", "expr": c}

    # A source already denominated in minor units (paise, cents) needs no scale.
    for c, _ in cells:
        raw = data.get(c)
        if isinstance(raw, int) and not isinstance(raw, bool) and abs(raw) == target:
            return {"how": "column_minor_units", "expr": c}

    if target == 0:
        # Nothing legitimately produces a zero leg, and a zero is exactly what
        # COALESCE(col, 0) leaves behind when the column was empty.
        return None

    if len(cells) <= MAX_PAIR_COLUMNS:
        for i, (lc, lm) in enumerate(cells):
            for rc, rm in cells[i + 1:]:
                if abs(lm - rm) == target:
                    return {"how": "expression", "expr": f"{lc} - {rc}"}
                if abs(rm - lm) == target:
                    return {"how": "expression", "expr": f"{rc} - {lc}"}
                if abs(lm + rm) == target:
                    return {"how": "expression", "expr": f"{lc} + {rc}"}
    return None


# --------------------------------------------------------------- invariants --

def _inv(code: str, passed: bool | None, detail: str) -> dict[str, Any]:
    """`passed=None` means not applicable -- reported, never counted as a pass."""
    return {"code": code, "passed": passed, "detail": detail}


def check(proposal_id: int, ctx: Context | None = None) -> dict[str, Any]:
    """Run every invariant against one proposal. Records nothing."""
    ctx = ctx or Context()
    p = db.query_one("SELECT * FROM match_proposal WHERE id = ?", (proposal_id,))
    if not p:
        raise VerifyError(f"no proposal {proposal_id}")

    members = db.query(
        "SELECT dataset_id, row, role, amount_minor, duplicate_of FROM match_member"
        " WHERE proposal_id = ? ORDER BY dataset_id, row",
        (proposal_id,),
    )
    # A member flagged as duplicating another row of the same source keeps its
    # recorded amount so a reviewer can see what the duplicated line claims,
    # but it was excluded from the group's sum when the group was built. The
    # verifier has to use the same rule or it re-adds the amount and rejects
    # every batch the exclusion just corrected.
    counted = [m for m in members if duplicates.counts_toward_balance(m)]
    duplicated = [m for m in members if m["duplicate_of"] is not None]
    tolerance = int(p["tolerance_minor"] or 0)
    invariants: list[dict[str, Any]] = []

    # 1. the rows a proposal names must exist ------------------------------
    missing = [
        ctx.label(m["dataset_id"], m["row"])
        for m in members
        if ctx.row(m["dataset_id"], m["row"]) is None
    ]
    if not members:
        detail = "proposal has no members"
    elif missing:
        detail = f"{len(missing)} member row(s) not found: {', '.join(missing[:5])}"
    else:
        detail = f"all {len(members)} member rows found in their source tables"
    invariants.append(_inv("members_resolve", bool(members) and not missing, detail))

    # 2. a match must cross a boundary -------------------------------------
    ds_ids = sorted({m["dataset_id"] for m in members})
    invariants.append(_inv(
        "spans_two_datasets",
        len(ds_ids) >= 2,
        f"{len(ds_ids)} dataset(s): " + ", ".join(ctx.names.get(d, d) for d in ds_ids),
    ))

    # 3. the summary columns must still describe the members ---------------
    edge = ",".join(ds_ids)
    count_ok = int(p["member_count"] or 0) == len(members)
    edge_ok = (p["datasets"] or "") == edge
    drift = []
    if not count_ok:
        drift.append(f"member_count={p['member_count']} but {len(members)} members")
    if not edge_ok:
        drift.append(f"datasets={p['datasets']!r} but members span {edge!r}")
    invariants.append(_inv(
        "member_record_consistent",
        count_ok and edge_ok,
        "; ".join(drift) if drift
        else "member_count and datasets agree with the recorded members",
    ))

    # 4. every amount must exist in the row it claims to come from ---------
    traces: list[dict[str, Any]] = []
    untraceable: list[str] = []
    amounts_present = 0
    for m in counted:
        label = ctx.label(m["dataset_id"], m["row"])
        if m["amount_minor"] is None:
            traces.append({"member": label, "how": "no amount recorded", "expr": None})
            continue
        amounts_present += 1
        data = ctx.row(m["dataset_id"], m["row"])
        if data is None:
            untraceable.append(f"{label} (row missing)")
            continue
        found = trace_amount(ctx, m["dataset_id"], data, int(m["amount_minor"]))
        if found is None:
            untraceable.append(
                f"{label} claims {int(m['amount_minor'])} minor,"
                " which no cell in that row holds"
            )
        else:
            traces.append(
                {"member": label, **found, "amount_minor": int(m["amount_minor"])}
            )

    if amounts_present == 0:
        invariants.append(_inv(
            "amounts_traceable", None, "no member carries an amount; nothing to trace"
        ))
    else:
        invariants.append(_inv(
            "amounts_traceable",
            not untraceable,
            f"{amounts_present - len(untraceable)}/{amounts_present} amounts traced"
            " back to a source cell"
            + ("" if not untraceable else "; " + "; ".join(untraceable[:4])),
        ))

    # 5. and the group must still balance under arithmetic done here -------
    residual: int | None = None
    if amounts_present and not untraceable:
        residual = int(sum(
            Decimal(int(m["amount_minor"]))
            for m in counted if m["amount_minor"] is not None
        ))
        within = abs(residual) <= tolerance
        # Only a proposal that *claims* to tie can fail this. One recorded
        # `unbalanced` never made that claim -- the gap is the finding, already
        # surfaced, and a reviewer accepting it as a real short-payment is doing
        # their job, not overriding a check. Failing it here would spend the
        # override on the honest case and leave nothing to say about the
        # dishonest one.
        claims_tie = p["confidence"] in ("exact", "within_tolerance")
        if not claims_tie:
            detail = (f"residual {residual} minor; proposal is recorded"
                      f" {p['confidence']!r} and does not claim to tie")
        elif within:
            detail = f"residual {residual} minor against tolerance {tolerance}"
        else:
            detail = (f"claims {p['confidence']} but members sum to {residual} minor"
                      f" against tolerance {tolerance}")
        invariants.append(_inv("balance_recomputed", within if claims_tie else None, detail))

        recorded = p["balance_minor"]
        if recorded is None:
            invariants.append(_inv(
                "balance_matches_record", None, "proposal recorded no balance"
            ))
        else:
            same = int(recorded) == residual
            invariants.append(_inv(
                "balance_matches_record", same,
                "recorded balance agrees with the recomputation" if same
                else f"recorded {int(recorded)} but members sum to {residual}",
            ))
    else:
        invariants.append(_inv(
            "balance_recomputed", None,
            "not attempted: amounts are missing or untraceable",
        ))
        invariants.append(_inv(
            "balance_matches_record", None,
            "not attempted: the balance could not be recomputed",
        ))

    # 6. nobody else has already claimed these rows on this edge -----------
    # `propose_matches` excludes claimed rows at proposal time, but a human
    # accepting a stale pending proposal later goes through set_status, which
    # checks nothing. This is the gate on that path.
    # One query for the whole group, not one per member: a batch proposal has
    # dozens of members, and asking the same question of each turned this into
    # the single most expensive statement in a reconciliation.
    clashes: list[str] = []
    if members:
        pairs = " OR ".join(
            "(mm.dataset_id = ? AND mm.row = ?)" for _ in members
        )
        params: list[Any] = []
        for m in members:
            params.extend((m["dataset_id"], int(m["row"])))
        params.extend((edge, proposal_id))
        for o in db.query(
            "SELECT p.id, mm.dataset_id, mm.row FROM match_member mm"
            " JOIN match_proposal p ON p.id = mm.proposal_id"
            f" WHERE ({pairs}) AND p.status = 'accepted'"
            "   AND p.datasets = ? AND p.id != ?",
            params,
        ):
            clashes.append(
                f"{ctx.label(o['dataset_id'], o['row'])}"
                f" is already accepted in proposal {o['id']}"
            )
    invariants.append(_inv(
        "single_claim_per_edge",
        not clashes,
        "no member is claimed by another accepted match on this edge" if not clashes
        else "; ".join(clashes[:4]),
    ))

    # 7. one match, one currency -------------------------------------------
    seen_currency: dict[str, str] = {}
    for m in members:
        col = ctx.currency.get(m["dataset_id"])
        data = ctx.row(m["dataset_id"], m["row"])
        if not col or data is None:
            continue
        val = data.get(col)
        if val is None or not str(val).strip():
            continue
        seen_currency[ctx.label(m["dataset_id"], m["row"])] = str(val).strip().upper()
    distinct = sorted(set(seen_currency.values()))
    if len(seen_currency) < 2:
        invariants.append(_inv(
            "currency_uniform", None,
            "fewer than two members carry a currency column",
        ))
    else:
        invariants.append(_inv(
            "currency_uniform",
            len(distinct) == 1,
            f"all members in {distinct[0]}" if len(distinct) == 1
            else f"mixed currency: {', '.join(distinct)}",
        ))

    # 8. did this one take unusually long to settle? -----------------------
    # A group can tie exactly and still be a finding, and no amount can see it.
    # The baseline is measured from the rule's own groups -- see core/timing.py
    # for why there is deliberately no configured settlement window.
    member_rows = [
        r for r in (ctx.row(m["dataset_id"], m["row"]) for m in members) if r is not None
    ]
    span = timing.group_span_seconds(member_rows)
    base = ctx.baseline(p["rule"])
    if base is None or not base.usable or span is None:
        invariants.append(_inv(
            "timing_consistent", None,
            base.describe(span) if base else "no comparable timestamps on this rule",
        ))
    else:
        invariants.append(_inv(
            "timing_consistent", not base.is_late(span), base.describe(span)
        ))

    # 8b. duplicated source rows, reported rather than judged --------------
    if duplicated:
        named = ", ".join(
            f"{ctx.label(m['dataset_id'], m['row'])} duplicates row {m['duplicate_of']}"
            for m in duplicated[:4]
        )
        invariants.append(_inv(
            "duplicate_rows_excluded", None,
            f"{len(duplicated)} member(s) duplicate another row of the same"
            f" source: {named}"
            + ("; excluded from the sum"
               if duplicates.EXCLUDE_DUPLICATE_AMOUNTS
               else "; still counted, so the group's residual reflects them"),
        ))

    # 9. did the rule leave evidence behind? -------------------------------
    # A partitioned rule matches one class of row and ignores the rest, so a
    # refund sitting against a matched order never reaches the group and the
    # transaction reads as clean. Any row carrying this group's own key that
    # the rule did not take is unexplained activity attached to a match.
    leftover: list[str] = []
    for ds_id in ds_ids:
        table = ctx.tables.get(ds_id)
        if not table:
            continue
        taken = sorted(int(m["row"]) for m in members if m["dataset_id"] == ds_id)
        key = str(p["group_key"]).replace("'", "''")
        matches = [
            f'"{c}" = \'{key}\'' for c in ctx.columns.get(ds_id, [])
        ]
        if not matches:
            continue
        exclude = (
            " AND __row NOT IN (" + ",".join(str(r) for r in taken) + ")" if taken else ""
        )
        try:
            found = sqlguard.select_all(
                get_settings().db_path,
                f'SELECT COUNT(*) n FROM "{table}"'
                f" WHERE ({' OR '.join(matches)}){exclude}",
            )[0]["n"]
        except Exception:
            continue
        if found:
            leftover.append(f"{found} unmatched row(s) in {ctx.names.get(ds_id, ds_id)}")
    invariants.append(_inv(
        "no_residual_evidence",
        not leftover,
        "; ".join(leftover) if leftover
        else "no rows carrying this key were left out of the group",
    ))

    # 10. the stored label must still be what the data says ----------------
    recorded_conf = p["confidence"]
    if recorded_conf in ("exact", "within_tolerance", "unbalanced") and residual is not None:
        if residual == 0:
            derived = "exact"
        elif abs(residual) <= tolerance:
            derived = "within_tolerance"
        else:
            derived = "unbalanced"
        invariants.append(_inv(
            "confidence_consistent",
            derived == recorded_conf,
            f"recorded {recorded_conf}, recomputed {derived}",
        ))
    else:
        # `ambiguous` and `high` encode facts about the batch a rule ran in,
        # which is not reconstructible from one proposal. Saying so beats
        # guessing.
        invariants.append(_inv(
            "confidence_consistent", None,
            f"{recorded_conf!r} is not re-derivable from this proposal alone",
        ))

    failed = [i for i in invariants if i["passed"] is False]
    checked = [i for i in invariants if i["passed"] is not None]
    return {
        "proposal_id": proposal_id,
        "verifier_version": VERIFIER_VERSION,
        "status": FAIL if failed else PASS,
        "checked": len(checked),
        "failed": len(failed),
        "residual_minor": residual,
        "invariants": invariants,
        "failures": [f"{i['code']}: {i['detail']}" for i in failed],
        "traces": traces,
        "rule": p["rule"],
        "group_key": p["group_key"],
        "confidence": recorded_conf,
        "proposal_status": p["status"],
    }


# --------------------------------------------------------------- recording --

def _record(result: dict[str, Any]) -> dict[str, Any]:
    db.execute(
        "INSERT INTO verification"
        " (proposal_id, verifier_version, status, checked, failed,"
        "  residual_minor, invariants)"
        " VALUES (?,?,?,?,?,?,?)",
        (
            result["proposal_id"], result["verifier_version"], result["status"],
            result["checked"], result["failed"], result["residual_minor"],
            json.dumps(result["invariants"]),
        ),
    )
    return result


def verify_proposal(proposal_id: int, ctx: Context | None = None) -> dict[str, Any]:
    """Check one proposal and record the outcome."""
    return _record(check(proposal_id, ctx))


def gate(proposal_id: int, ctx: Context | None = None) -> dict[str, Any]:
    """Verification as a release gate. Same work; the name marks the intent.

    Every path that moves a proposal to `accepted` goes through this, so
    "accepted" always means a second pass agreed -- never that the rule said so.
    """
    return verify_proposal(proposal_id, ctx)


def latest(proposal_id: int) -> dict[str, Any] | None:
    row = db.query_one(
        "SELECT * FROM verification WHERE proposal_id = ? ORDER BY id DESC LIMIT 1",
        (proposal_id,),
    )
    if not row:
        return None
    row["invariants"] = json.loads(row["invariants"])
    row["failures"] = [
        f"{i['code']}: {i['detail']}" for i in row["invariants"] if i["passed"] is False
    ]
    return row


def sweep(status: str = "accepted", limit: int = 500) -> dict[str, Any]:
    """Re-verify proposals in bulk.

    Written for the case that matters most: everything already accepted, checked
    again against the data as it stands now.
    """
    sql = "SELECT id FROM match_proposal"
    params: tuple = ()
    if status:
        sql += " WHERE status = ?"
        params = (status,)
    sql += " ORDER BY id LIMIT ?"
    ids = [r["id"] for r in db.query(sql, (*params, max(1, min(limit, 5000))))]

    ctx = Context()
    failures: list[dict[str, Any]] = []
    passed = 0
    for pid in ids:
        result = verify_proposal(pid, ctx)
        if result["status"] == PASS:
            passed += 1
            continue
        if len(failures) < 25:
            failures.append({
                "proposal_id": pid,
                "rule": result["rule"],
                "group_key": result["group_key"],
                "failures": result["failures"],
            })

    return {
        "scope": status or "all",
        "verified": len(ids),
        "passed": passed,
        "failed": len(ids) - passed,
        "verifier_version": VERIFIER_VERSION,
        "failures": failures,
    }
