"""Build the demo dataset.

Deterministic: same seed, same files, so every take of the video shows exactly
the same numbers. Run it from the repo root:

    python demo/generate.py

Three sources shaped like a real close, and every awkward case in them is there
to make one capability visible on camera:

    ORD-2019   never reached the gateway        -> unmatched, legitimately
    ORD-2006   ledger and gateway disagree      -> an amount break with a reason
    ORD-2027   captured twice by the gateway    -> a duplicate, marked not netted
    BATCH-0011 settles a week late              -> timing learned from the data
    stray row  quarterly bank charges           -> out of scope, not a failure

The bank statement deliberately carries **no batch id column**. The reference
lives inside the narration, the way every real statement does it, so the demo
has to find a key that whole-cell overlap cannot see.
"""

from __future__ import annotations

import csv
import random
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

SEED = 20260304
ORDERS = 60
PER_BATCH = 4          # 15 batches: enough distinct ids to read as a key, and
                       # enough groups for the timing baseline to mean anything
FEE_RATE = Decimal("0.02")

OUT = Path(__file__).parent / "data"

CUSTOMERS = [
    "Acme Traders", "Bharat Retail", "Ganga Textiles", "Kanha Logistics",
    "Om Enterprises", "Vindhya Motors", "Sunrise Foods", "Meridian Labs",
    "Priya Sharma", "Rahul Gupta", "Neha Verma", "Sana Khan",
    "Deccan Spices", "Konkan Marine", "Nilgiri Estates",
]

# What each awkward row is for.
MISSING_AT_GATEWAY = 19     # ORD-2019: the ledger has it, nothing else does
AMOUNT_BREAK = 6            # ORD-2006: gateway captured less than the order
DUPLICATED = 27             # ORD-2027: one capture, two rows in the export
LATE_BATCH = 11             # BATCH-0011: settles seven days out, not one


def money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def main() -> None:
    rng = random.Random(SEED)
    OUT.mkdir(parents=True, exist_ok=True)
    start = datetime(2026, 3, 2, 9, 0, 0)

    orders = []
    for i in range(1, ORDERS + 1):
        placed = start + timedelta(days=(i - 1) // 5, minutes=rng.randint(0, 400))
        gross = Decimal(rng.randrange(45_000, 9_800_000)) / 100
        orders.append({
            "n": i,
            "ref": f"ORD-{2000 + i}",
            "placed": placed,
            "gross": gross.quantize(Decimal("0.01")),
            "customer": rng.choice(CUSTOMERS),
        })

    # ---------------------------------------------------------------- ledger --
    with (OUT / "erp_ledger.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["entry_id", "posting_date", "order_ref", "customer",
                    "amount", "currency", "status"])
        for o in orders:
            w.writerow([
                f"ERP-{o['n']:05d}",
                o["placed"].date().isoformat(),
                o["ref"],
                o["customer"],
                money(o["gross"]),
                "INR",
                "Posted",
            ])

    # --------------------------------------------------------------- gateway --
    captured = []      # what the gateway actually holds, in file order
    for o in orders:
        if o["n"] == MISSING_AT_GATEWAY:
            continue
        gross = o["gross"]
        if o["n"] == AMOUNT_BREAK:
            gross = gross - Decimal("100.00")   # captured less than ordered
        fee = (gross * FEE_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        row = {
            "order": o,
            "txn": f"pay_{o['n']:05d}",
            "gross": gross,
            "fee": fee,
            "net": gross - fee,
            "at": o["placed"] + timedelta(minutes=rng.randint(2, 90)),
        }
        captured.append(row)
        if o["n"] == DUPLICATED:
            # The exporter ran twice. Same capture, new row id, a minute later.
            twin = dict(row)
            twin["txn"] = f"pay_{o['n']:05d}_1"
            twin["at"] = row["at"] + timedelta(minutes=1)
            captured.append(twin)

    # Batches are assigned over the real captures, so the duplicate lands inside
    # one and stops it tying -- which is the whole point of it being there.
    for index, row in enumerate(captured):
        row["batch"] = f"BATCH-{index // PER_BATCH + 1:04d}"

    with (OUT / "gateway_transactions.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["txn_id", "order_ref", "captured_at", "gross_amount", "fee",
                    "net_amount", "currency", "settlement_batch_id", "status"])
        for r in captured:
            w.writerow([
                r["txn"],
                r["order"]["ref"],
                r["at"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                money(r["gross"]),
                money(r["fee"]),
                money(r["net"]),
                "INR",
                r["batch"],
                "captured",
            ])

    # ------------------------------------------------------------------ bank --
    batches: dict[str, list[dict]] = {}
    for r in captured:
        batches.setdefault(r["batch"], []).append(r)

    with (OUT / "bank_statement.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["bank_account", "value_date", "narration", "credit_amount",
                    "currency", "utr"])
        for name, rows in batches.items():
            number = int(name.split("-")[1])
            # The bank credits the batch once. Where the gateway exported a
            # capture twice, the bank still only moved the money once -- so the
            # duplicate is excluded here, and the batch will not tie.
            seen: set[str] = set()
            credited = Decimal("0.00")
            for r in rows:
                key = r["order"]["ref"]
                if key in seen:
                    continue
                seen.add(key)
                credited += r["net"]

            settled = max(r["at"] for r in rows) + timedelta(
                days=7 if number == LATE_BATCH else 1
            )
            w.writerow([
                "HDFC-XXXX4471",
                settled.date().isoformat(),
                # No batch id column. The reference is inside the text.
                f"NEFT CR-RAZORPAYX-{name}-SETTLEMENT",
                money(credited),
                "INR",
                f"UTR{number:07d}",
            ])

        # A line no order will ever explain. Out of scope, not a failure.
        w.writerow([
            "HDFC-XXXX4471",
            (start + timedelta(days=13)).date().isoformat(),
            "QUARTERLY ACCOUNT MAINTENANCE CHARGES",
            "-1180.00",
            "INR",
            "UTR9900001",
        ])

    print(f"ledger   {ORDERS} orders")
    print(f"gateway  {len(captured)} rows  "
          f"(1 missing, 1 duplicated, 1 short by 100.00)")
    print(f"bank     {len(batches)} settlements + 1 stray")
    print(f"written to {OUT}")


if __name__ == "__main__":
    main()
