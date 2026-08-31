"""A labelled fixture: source CSVs plus what the answer should have been.

Built against the ReconRiver synthetic scenarios, whose ground truth is one row
per *work key* -- an order at L1, a settlement batch at L2 -- carrying the
outcome a correct reconciliation should reach.

The two vocabularies do not line up one for one, and pretending they do would
make the score meaningless. Ground truth distinguishes fifteen outcomes,
including ones this system has no way to express: it does not know a fee policy
from a rounding difference, and it should not be marked wrong for that. What it
*can* express is whether rows belong together, and whether they tie. So the
outcomes collapse to the three states it can actually claim:

    MATCHED    these rows reconcile
    EXCEPTION  these rows belong together but something is wrong with them
    MISSING    there is nothing here to match

Collapsing is a deliberate loss of resolution, recorded per outcome so the
report can still say *which* exception kind was got wrong.
"""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

MATCHED = "MATCHED"
EXCEPTION = "EXCEPTION"
MISSING = "MISSING"

# A match really happened and should be claimed as one.
_MATCHED = {"MATCHED", "REFUND_MATCHED"}

# Nothing to match: the counterpart does not exist, or the row was never valid.
_MISSING = {
    "MISSING_PROCESSOR",
    "MISSING_INTERNAL",
    "MISSING_BANK_SETTLEMENT",
    "INVALID_SOURCE_ROW",
}

# Everything else -- amount, currency, fee, duplicate, ambiguity, late window --
# is a real relationship with a real problem, which is what EXCEPTION means.

# Source files, in the order a transaction moves through them. The names become
# dataset names, so they are also what shows up in a proposal's `datasets`.
SOURCES = (
    ("internal_transactions", "internal_transactions.csv"),
    ("processor_transactions", "processor_transactions.csv"),
    ("bank_settlements", "bank_settlements.csv"),
)

GROUND_TRUTH = "expected_reconciliation.csv"
MANIFEST = "sample_manifest.json"


@dataclass
class Expectation:
    scope: str            # ORDER | SETTLEMENT
    work_key: str
    outcome: str          # the collapsed class
    raw_outcome: str      # what the fixture actually said
    reason_code: str
    difference: str
    members: dict[str, str] = field(default_factory=dict)


@dataclass
class Fixture:
    path: Path
    sources: list[tuple[str, Path]]
    expectations: list[Expectation]
    manifest: dict[str, Any]
    unlabelled_orders: set[str] = field(default_factory=set)

    @property
    def name(self) -> str:
        return self.path.name

    def by_scope(self, scope: str) -> list[Expectation]:
        return [e for e in self.expectations if e.scope == scope]


def collapse(outcome: str) -> str:
    if outcome in _MATCHED:
        return MATCHED
    if outcome in _MISSING:
        return MISSING
    return EXCEPTION


def _rows(path: Path) -> list[dict[str, str]]:
    # utf-8-sig: these files carry a BOM, and a BOM on the first header turns
    # `scenario_id` into something that does not compare equal to itself.
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def load(path: Path) -> Fixture:
    """Read a fixture directory, and refuse one whose labels do not fit its data."""
    path = Path(path)
    if not path.is_dir():
        raise FileNotFoundError(f"no fixture directory at {path}")

    sources: list[tuple[str, Path]] = []
    for name, filename in SOURCES:
        f = path / filename
        if not f.exists():
            raise FileNotFoundError(f"fixture {path.name} is missing {filename}")
        sources.append((name, f))

    gt_path = path / GROUND_TRUTH
    if not gt_path.exists():
        raise FileNotFoundError(f"fixture {path.name} is missing {GROUND_TRUTH}")

    expectations = []
    for r in _rows(gt_path):
        raw = (r.get("expected_outcome") or "").strip()
        expectations.append(Expectation(
            scope=(r.get("result_scope") or "").strip(),
            work_key=(r.get("work_key") or "").strip(),
            outcome=collapse(raw),
            raw_outcome=raw,
            reason_code=(r.get("expected_reason_code") or "").strip(),
            difference=(r.get("expected_difference") or "").strip(),
            members={
                k: (r.get(k) or "").strip()
                for k in ("internal_payment_id", "processor_transaction_id",
                          "bank_entry_id", "settlement_batch_id")
                if (r.get(k) or "").strip()
            },
        ))

    manifest = {}
    if (path / MANIFEST).exists():
        manifest = json.loads((path / MANIFEST).read_text(encoding="utf-8"))

    # --- does the ground truth actually describe this data? ---------------
    # A fixture whose CSVs were regenerated after its labels were written will
    # score badly for reasons that have nothing to do with the system. Catching
    # that here is the difference between an eval and a rumour.
    internal = _rows(path / "internal_transactions.csv")
    processor = _rows(path / "processor_transactions.csv")
    source_orders = (
        {r.get("merchant_order_id", "") for r in internal}
        | {r.get("merchant_order_id", "") for r in processor}
    ) - {""}
    labelled_orders = {e.work_key for e in expectations if e.scope == "ORDER"}
    unlabelled = source_orders - labelled_orders

    if source_orders and len(unlabelled) > len(labelled_orders) * 0.1:
        raise ValueError(
            f"fixture {path.name} is not internally consistent:"
            f" {len(unlabelled)} of {len(source_orders)} source orders carry no"
            f" label (only {len(labelled_orders)} are labelled). Its CSVs were"
            " probably regenerated after expected_reconciliation.csv was"
            " written. Scoring against it would measure the fixture, not the"
            " system."
        )

    return Fixture(
        path=path,
        sources=sources,
        expectations=expectations,
        manifest=manifest,
        unlabelled_orders=unlabelled,
    )
