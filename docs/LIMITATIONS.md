# Limitations and known issues

This page lists what Ledgerline doesn't do, where it can mislead you, and bugs
we know about but haven't fixed. Read it before trusting a result on real data.

---

## Known bugs

These are confirmed in the code and still open.

- **Files with more than 10,000 distinct values in a column can't be
  reconciled.** `discovery._distinct_values` asks for up to 50,000 values
  (`DISTINCT_CAP`), but `sqlguard.select_all` raises an error past 10,000 rows
  (`HARD_ROW_CAP`) instead of stopping there. Discovery fails, and auto-matching
  fails with it. The same 10,000-row limit hits a matching rule's SQL (about
  5,000 rows per side for a 1:1 join) and the chain view (more than 10,000 rows
  in the starting file).
- **Rows with the wrong number of fields are silently fixed up.** Short rows
  are padded with blanks and extra fields are dropped (`ingest.py`), with no
  warning. An unquoted `1,234.50` in a comma-separated file shifts every later
  column, so the stored amount is wrong and verification agrees with it.
- **Some common amount formats are stored as text.** Indian digit grouping
  (`1,23,456.00`), currency symbols (`₹1,200`), amounts in brackets (`(50.00)`)
  and `CR`/`DR` suffixes aren't recognised as numbers, so automatic matching
  can't use the column. The verifier *does* understand these formats, so the
  two disagree.
- **The file encoding is guessed from the first 64 KB only.** If that slice
  ends in the middle of a multi-byte character, a UTF-8 file can be read as
  cp1252. Characters like `₹` are then garbled, and text ids containing them
  stop matching.
- **Report totals are overstated for multi-step flows.** Each match adds its
  value again, so an order matched to the gateway and the gateway matched to
  the bank is counted twice. Rejected matches are also counted as "open".
- **Transaction chains reach only one step beyond the starting file.** In a
  four-file flow, the later steps show as missing even when they're matched.
- **A file name with a quote in it breaks matching.** Dataset names are put
  into the generated SQL without escaping, so `O'Brien.csv` causes a SQL error
  for every rule on that file.

---

## Currency

**Amounts are never converted between currencies or added across them.** There
are no exchange rates anywhere in the system.

- A group with members in two currencies fails the `currency_uniform` check and
  can't be approved. It stays an exception.
- The report files a group's value under the currency of its **first** member
  that has one. For a mixed-currency group, that choice is arbitrary.
- If a file has more than one currency, the report shows no money total for
  it. Adding across currencies would give a meaningless number.

## Input files

- **CSV only.** There's no support for Excel, JSON, Parquet, databases or bank
  APIs. An `.xlsx` file renamed to `.csv` won't load.
- **No incremental uploads.** Uploading a file again creates a new dataset; it
  doesn't add to or replace the old one. There's no concept of carrying a
  period close forward.
- **No upload size limit**, and a large upload holds the request open while
  it's processed. There's no background job queue.

## What matching can't check

- **Fees.** If the gross amounts match, the group is `exact` even when the fee
  is wrong. Ledgerline doesn't know anyone's fee rates. This is the most likely
  way a "clean" result is actually wrong.
- **Contractual settlement times.** "Late" means far outside the delay seen in
  this same data, not a breach of an agreed deadline. A provider that is
  always two days late looks on time.
- **N:M links are skipped, not solved.** When neither side is unique enough to
  be the "one", nothing is proposed. Write a rule by hand with
  `run_reconciliation({"mode": "rule", ...})`.
- **The amount column can still be picked wrongly.** Constant columns and
  mostly-empty or mostly-zero columns are rejected. But a column with only a
  few values (like a quantity of 1 to 3), or a numeric id present in both
  files, can still agree more often than the real amount.
- **Amounts assume two decimal places.** Minor units are always the amount
  × 100, which is wrong for currencies with three decimals (KWD, BHD).
- **Same id, different amounts** is an exception, not a duplicate. There's no
  safe way to choose which row is right.

## Duplicates

- **Near-duplicate detection needs an id column.** If no column is at least
  50% distinct (`IDENTITY_FLOOR`), only exact duplicates are detected.
- **Duplicates are kept in the sums by default.** Turn on exclusion per file
  only when you know repeats in that file are export errors. See
  [RULE-ENGINE.md](RULE-ENGINE.md#1-duplicate-rows) for why this is the
  default.

## References inside text

- **The search is skipped for very large file pairs.** It compares every row
  with every row, so it doesn't run above 40 million row pairs (`MAX_PRODUCT`).
  The skip is logged.
- **Prefix matches can create false links.** The search checks whether a key
  appears anywhere inside the text. A narration containing `pay_ABC123` can
  link to `pay_ABC12` when `pay_ABC123` isn't in the other file.
- **A row that mentions two references links to neither.**
- **An extracted column isn't in your file.** Rule descriptions say where it
  came from, for example `bank.order_ref (read from bank.narration)`.

## The report

- **The checksum covers matching decisions, not the source files.** It detects
  the reconciliation changing. It doesn't detect a CSV being edited and
  uploaded again.
- **A file matched in two ways can have two possible totals.** For example, a
  gateway file can be matched on gross against the ledger and on net against
  the bank. The report picks the column most matches used, and prints which
  column it chose.
- **The report period comes only from `DATE` and `TIMESTAMP` columns.** One
  bad value makes a date column text, and then it's ignored.
- **A file with no matched amounts gets no money figure.**

## The agent

- **Agent turns aren't repeatable.** The same question on the same data can
  take a very different number of model calls depending on the model. That's
  why the evaluation scores the automatic pipeline, not the agent.
- **Exploration is capped at six "looking" calls per turn.** A complicated
  question may be answered from partial evidence.
- **Uploaded data reaches the model.** Cell values (like bank narrations,
  which a payer can write) appear in tool results, and file names and column
  names appear in the agent's instructions. Instructions hidden in that text
  could steer the agent. The code-level limits (read-only SQL, verification,
  rule approval) still apply.

## Running it

- **Single process, single SQLite database, no login.** There are no users and
  no permissions on any route. Anyone who can reach the API can read every
  file and accept any match.
- **Any website open in your browser can call the API.** `POST
  /api/session/reset` (which wipes all data) and file uploads need no special
  headers, so CORS doesn't block them. Run Ledgerline only on your own
  machine.
- **It's a local analysis tool, not a deployed service.**
