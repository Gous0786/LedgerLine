# Demo script — 5 minutes

Every number below is real and was produced by running the demo data through the
app. If a figure on screen disagrees with this script, the data drifted — re-run
`python demo/generate.py` and `uv run python ../demo/load.py`.

## Before you record

```bash
python demo/generate.py                  # deterministic; same files every time
cd backend && uv run python ../demo/load.py     # clean slate, files loaded, nothing matched
```

Then refresh the browser. Have `docs/ARCHITECTURE.md` open in a second tab for
the architecture beat — the mermaid diagram renders on GitHub.

**Do not** pass `--reconcile` for the real take. The agent doing it live is the
demo. Use it only to re-record a later section.

One honest caveat to plan around: the agent turn takes **20–45 seconds**. Either
cut away to the architecture during it, or speed it 4× with a "reconciling…"
caption. Don't leave dead air, and don't pretend it's instant.

---

## 0:00 — 0:30 · The problem

**On screen:** the three CSVs open in a viewer, side by side. Scroll each once.

> Three files from three systems. An ERP ledger, a payment gateway export, and a
> bank statement.
>
> The ledger calls it `order_ref`. The gateway calls it `order_ref` too — but
> the bank has no reference column at all. Its only clue is buried in a text
> field: `NEFT CR-RAZORPAYX-BATCH-0007-SETTLEMENT`.
>
> The amounts don't match either. The gateway takes a fee, so the bank credits
> less than the order was worth. And the bank settles in batches — one line for
> four payments.
>
> Nobody has told this system any of that.

**Point the cursor at** `bank_statement.csv` — the narration column. That column
is the whole reason the demo is interesting.

## 0:30 — 1:15 · Upload, and ask

**On screen:** upload page, drag all three CSVs, then type into the chat bar and
press Enter — it carries you into the workspace.

> Upload. It sniffs the delimiter, types each column, and — this is new — marks
> duplicate rows on the way in.

Type: **`reconcile it`**

> One instruction. No mapping, no configuration, no schema.

**While it runs**, the source rail on the right shows the three files. Open
`gateway_transactions` and scroll to **row 27**: it is tinted, badged
`dup of 27`, and the footer reads `1 repeated · counted`.

> It already found one. Two rows for the same capture — same order, same amount,
> a minute apart, different transaction id. It's marked, and deliberately still
> counted. I'll come back to why.

## 1:15 — 2:15 · What came back

**On screen:** the agent's answer, then the reconciled rail on the left.

Expected result — **2 rules, 74 groups**:

| Rule | Shape | How it ties |
| --- | --- | --- |
| `erp_ledger.order_ref = gateway_transactions.order_ref` | 1:1 row-level | `amount` ↔ `gross_amount`, agreement 0.983 |
| `bank_statement.settlement_batch_id (read from narration) = gateway.settlement_batch_id` | 1:N aggregate | `SUM(net_amount) = credit_amount`, agreement 0.933 |

> Two relationships, both found by measurement. The first is one-to-one. The
> second is one-to-many — one bank credit against four gateway captures — and it
> worked out that the identity is `SUM(net) = credit`, not `gross`, because
> that's the pair that actually agrees.
>
> Nothing here was configured. It measured which columns overlap, classified the
> cardinality, and searched for the amount relationship that holds.

**Open the transaction chain view.** 60 transactions: **51 reconciled, 4
exception, 4 pending, 1 unmatched.**

> Order to gateway to bank, end to end, for every transaction.

## 2:15 — 3:15 · The four that didn't

This is the heart of it. Read each reason off the screen.

| Transaction | State | What it says |
| --- | --- | --- |
| `ORD-2006` | exception | *erp_ledger and gateway_transactions differ by 100.00* |
| `ORD-2027` | exception | *erp_ledger and gateway_transactions differ by 63,064.02 (2+ gateway_transactions rows)* |
| `ORD-2019` | unmatched | *nothing in gateway_transactions matches* |
| `ORD-2041` | pending | *held: spans 157.5h against a typical 35.5h for this rule* |

> Four different failures, four different explanations.
>
> The first is a genuine amount break — captured a hundred rupees short.
>
> The second is that duplicate. And here's the decision that matters: it would
> be trivial to drop the repeated row and make this tie. **It refuses to.** A
> file recording a settlement twice is a disagreement between that file and the
> bank, and someone has to decide which is right. Netting it out silently is how
> you turn a real exception into a clean-looking match.
>
> I measured that. Auto-excluding duplicates took accuracy from 100% to 81.7%
> and false auto-matches from zero to nineteen percent. So it's a switch, per
> file, off by default.
>
> The third never reached the gateway at all — the ledger has it, nothing else
> does.
>
> The fourth is my favourite. It ties to the penny. It's still held — because it
> settled 157 hours out when this processor normally takes 35. **Nobody
> configured 35 hours.** It learned the normal lag from this dataset's own
> settlements, and flagged the one that broke the pattern.

## 3:15 — 4:00 · How it works

**On screen:** cut to `docs/ARCHITECTURE.md` and `docs/RULE-ENGINE.md` — the two
mermaid diagrams.

> One rule shapes the whole system: **the language model never does arithmetic.**
>
> Matching, summing and balancing are SQL. The agent has six tools, picks the
> strategy and explains the result — but every figure traces to a source row.
> It cannot produce a number.

**Scroll the rule-engine flowchart.**

> Ingest, duplicate marking, overlap discovery, embedded keys, cardinality,
> amounts, proposals — and then this.

**Point at the verification stage.**

> Confidence is computed from the numbers the matching SQL returned, so it
> cannot notice those numbers being wrong. A truncating cast, or a `COALESCE`
> turning a missing amount into a balancing zero, gives you a group that ties
> perfectly and means nothing.
>
> So every proposal is re-checked by an independent pass that trusts only the
> row pointers and re-derives each figure from the source cell in exact decimal.
> Twelve invariants. It's the only way anything reaches "accepted", and it's
> what held that late settlement.

Optional, if you have the seconds: the false-auto-match number.

> Scored against eleven labelled fixtures: 97 to 100% accuracy, and the number I
> actually care about — false auto-match rate — between zero and three percent.
> Missing a match costs an afternoon. Inventing one puts a wrong figure in front
> of someone who signs it off.

## 4:00 — 4:40 · The close report

**On screen:** click through to `/report`. Scroll steadily.

> Then it writes the close.
>
> Value by currency, never converted. The flow, with what each file is worth and
> which column that came from — so the figure is checkable.

**Pause on the duplicates section.**

> What each file recorded twice, and whether those rows were counted.

**Pause on the accountability ledger.**

> Who decided what. Released automatically, accepted by a person, and — even at
> zero — accepted despite failed verification. The row exists so that the zero
> means something.

**Click Download report.**

> One self-contained HTML file. Same markup, same stylesheet, no dependencies.

## 4:40 — 5:00 · What it does not do

**On screen:** the report's limits section, then `docs/LIMITATIONS.md`.

> And it tells you what it didn't check.
>
> It can't see a wrong fee — if the gross ties, it reads as exact. "Late" means
> unusual for this dataset, not a breach of a contract it has never seen. It
> reads CSVs and nothing else. And it will not net out a repeated row unless
> someone who knows the file says to.
>
> A reconciliation you can't check is worth less than one that tells you where
> it stopped looking.

---

## Shot list

| # | Duration | Shot | Watch for |
| --- | --- | --- | --- |
| 1 | 30s | Three CSVs side by side | Land on the narration column |
| 2 | 45s | Upload → type `reconcile it` | Cut away during the wait |
| 3 | 20s | Source rail, gateway row 27 | The `dup of 27` badge |
| 4 | 40s | Agent answer, two rules | Read the aggregate identity aloud |
| 5 | 20s | Chain view, 60 transactions | 51 / 4 / 4 / 1 |
| 6 | 60s | The four failures | Read each reason verbatim |
| 7 | 45s | Architecture + rule-engine diagrams | Land on verification |
| 8 | 40s | Close report, top to bottom | Duplicates + accountability |
| 9 | 20s | Download, limits | End on the limits |

## If something goes wrong on the day

| Symptom | Cause | Fix |
| --- | --- | --- |
| Only one rule ran | Bank narration didn't resolve | Re-run `generate.py`; batch ids must exceed 12 distinct |
| Transactions keyed by date | Spine picked the wrong file | Confirm `erp_ledger → gateway → bank` in the chain header |
| Agent stalls mid-turn | Provider timeout | Retry; it's an upstream error and it says so |
| Numbers differ from this script | Data drifted | `generate.py` is seeded — regenerate and reload |
