# Known limitations

Stated because the rest is only credible if the gaps are named. Each entry says
what the system does, not merely what it lacks, so you can judge whether it
matters for your data.

---

## Currency

**Value is never converted and never summed across currencies.** Each currency
stands alone in the report, and there is no FX rate anywhere in the system.

The consequences on a multi-currency dataset are worth being precise about:

- A group whose members span two currencies fails the `currency_uniform`
  invariant and cannot be released. This is deliberate — the amounts are not
  comparable — but it means such groups accumulate as exceptions rather than
  resolving.
- The report attributes a group's value to the currency of the **first member
  carrying one**. For a mixed-currency group that choice is arbitrary, so its
  open value appears under one code rather than being split. The group is
  already an exception, but the currency it is filed under should not be read as
  meaningful.
- **Per-dataset totals disappear for a mixed-currency file.** The transaction
  flow shows a money figure per source only when that file has a single
  currency; summing across currencies would produce a number that looks like
  money and is not, so it is omitted rather than invented.
- Exceptions counted as "mixed currency in one group" are counted, not priced.
  Their value sits inside the open figures.

The report is deterministic — the same database always produces the same
report — but *deterministic is not the same as complete*, and multi-currency is
where the gap is widest.

## Sources

**CSV only.** Upload accepts delimited text, which is sniffed for delimiter and
encoding and typed per column. There is no reader for Excel, JSON, Parquet, a
database connection or a bank API. A `.xlsx` renamed to `.csv` will fail to
parse rather than being converted.

**No incremental ingest.** Re-uploading a file creates a new dataset rather than
appending to or updating the existing one. There is no notion of a period close
that carries forward.

## What matching cannot check

**Fee amounts.** A group whose gross amounts tie is reported as exact even when
the fee is wrong. No fee policy is known to the system, so fee errors pass
silently. This is the single most likely source of a "clean" reconciliation that
should not have been.

**Timing against a contract.** "Late" means far outside the lag this dataset
itself exhibits — learned from the rule's own groups — not a breach of any
agreed settlement window. A processor that is uniformly two days late looks
perfectly on time.

**Many-to-many relationships are declined, not solved.** Where neither side of a
join is unique enough to be the `one`, the pass says so and proposes nothing.
Any group built there would fan out into a blob no amount could verify. Such
edges need a hand-written rule via `run_reconciliation({"mode": "rule", ...})`.

**Same identifier, different amounts** is a conflict rather than a duplicate,
and there is no safe way to pick which of the two is true. It stays an
exception.

## Duplicates

**Detection of near-duplicates needs an identifiable row.** A file where no
column stands out as identifying the row — nothing clears
`IDENTITY_FLOOR = 0.5` — gets byte-identical detection only. A file whose
repeated rows also share their id is caught by exact detection instead, so the
gap is narrow, but it exists.

**Exclusion is off by default and is a per-file judgement.** Nothing is removed
from any sum until someone says that a repeat in this file is a recording
artefact. That default is measured: releasing deduplicated groups automatically
turned real exceptions into silent auto-matches on the labelled fixtures — 100%
accuracy down to 81.7%, false auto-matches 0% to 19.3%.

## Embedded keys

**Containment is a nested loop**, capped at `MAX_PRODUCT = 40,000,000` row
pairs. Above that the probe is skipped and logged; a large bank statement against
a large processor file may not get its embedded key found.

**A row naming two references resolves to NULL** and stays unmatched. Guessing
which one was meant would put a fabricated link into a reconciliation.

**An extracted column is not in your file.** Rule descriptions say so — 
`bank.order_ref (read from bank.narration)` — but a reader who opens the CSV
looking for `order_ref` will not find it.

## Report

**The checksum covers proposals, not source files.** It is computed over
`(rule, group_key, confidence, status, members)` and detects a reconciliation
changing underneath a report. It does not detect a source CSV being edited and
re-uploaded.

**A dataset read through two edges can be counted two ways.** The per-source
money figure recovers its amount column by asking which cell each matched amount
came from and taking the majority. A gateway compared on its gross against a
ledger and on its net against a bank has two defensible answers; ties break on
column name so the figure is stable, and the column is printed beneath it so the
number can be checked. It is still one of two possible readings.

**Period detection reads only `DATE` / `TIMESTAMP` columns.** A file whose dates
were typed `TEXT` — one malformed row is enough — contributes no date range to
the report header.

**A file whose money never entered a match gets no figure**, rather than a total
that cannot be tied to anything.

## Agent

**Only the deterministic pipeline is gated.** The agent turn is not reproducible
— the same prompt on the same data has taken 3, 7 and 36 model calls depending
on the model — so the evaluation harness treats its score as a sample and gates
on `auto_match_exact` instead. A model change cannot regress the numbers, but it
can change the cost and the wording considerably.

**Model choice is a cost decision, not an accuracy one.** Measured across six
runs on identical data, two different models produced byte-identical accuracy
(98.42%) and FAMR (1.10%) while differing 16× in cost and 6× in latency.

**Exploration is bounded at six looking calls per turn.** A genuinely
complicated question may hit that ceiling and be answered from partial
evidence — the refusal tells the model to answer with what it has.

## Operations

**Single-process, single-database, no authentication.** SQLite in WAL mode, the
agent running inside the FastAPI process, no users, no tenancy and no
authorisation on any route. Anyone who can reach the API can read every uploaded
file and accept any match. It is a local analysis tool, not a deployed service.

**Discovery samples at `DISTINCT_CAP = 50,000` distinct values per column.**
Beyond that the overlap is computed on a truncated set, so a join on a very
high-cardinality column in a very large file may be under-measured.

**No background work.** Reconciliation runs inside the request. A large upload
holds the connection for the duration.

**The test modules run themselves** (`python -m tests.test_duplicates`) because
the project has no test runner installed. They also work under pytest if one is
added.
