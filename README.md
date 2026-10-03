# Ledgerline

Ledgerline checks whether payment records from different systems agree with
each other. Upload CSV exports, for example an ERP ledger, a payment gateway
export and a bank statement, and ask it to reconcile. It tells you what matched,
what didn't, and why. Every figure points back to a row in one of your files.

You don't have to describe your files first. Ledgerline works out from the data
which columns link the files, which column holds the amount, and which file
comes first in the flow of money.

```text
┌──────────────┐      ┌───────────────────┐      ┌────────────────┐
│ erp_ledger   │─────▶│ gateway_razorpayx │─────▶│ bank_hdfc      │
│ 9 of 10 rows │      │  10 of 10 rows    │      │  9 of 10 rows  │
└──────────────┘      └───────────────────┘      └────────────────┘
   ORD-1002  erp and gateway differ by 50.00        exception
   ORD-1008  two gateway rows for one capture       exception
   ORD-1006  never reached the gateway              unmatched
```

## Core ideas

1. **The AI never does the maths.** All matching and adding up happens in SQL.
   The AI agent decides what to run and explains the results. It never
   produces a number itself.
2. **Settings are measured from the data, not hard-coded.** Join columns,
   amount columns and the normal settlement delay are all worked out from the
   files you upload.
3. **Nothing is auto-approved without a second check.** Before any match is
   marked `accepted`, a separate verifier re-reads the original rows and redoes
   the sums.
4. **Unmatched rows are normal.** A bank statement has fees and balance lines
   that no order will explain. They are reported plainly, not treated as errors.

## Quick start

You need Python 3.12 with [`uv`](https://docs.astral.sh/uv/), Node.js, and an
[OpenRouter](https://openrouter.ai) API key.

```bash
# backend (http://127.0.0.1:8000)
cd backend
uv sync
cp .env.example .env          # then add your OPENROUTER_API_KEY
uv run uvicorn app.main:app --reload

# frontend (http://localhost:5173, sends /api calls to the backend)
cd frontend
npm install
npm run dev
```

On Windows, `./dev.ps1` starts both.

Then upload CSVs on `/upload` and ask the agent to reconcile. `/report` shows
the close report, which you can download as a single HTML file.

For demo data, run `uv run python ../demo/load.py` from `backend/`. It wipes the
database and loads the three files in `demo/data/`.

## Stack

| Layer | Choice |
| --- | --- |
| Backend | FastAPI + uvicorn, Python 3.12, managed with `uv` |
| Database | SQLite (WAL mode). Each uploaded CSV becomes its own table |
| Agent | Google ADK `LlmAgent`; models through LiteLLM → OpenRouter |
| Streaming | Vercel AI SDK "UI Message Stream" over server-sent events |
| Frontend | Vite 8, React 19, TypeScript, Tailwind 4, `@ai-sdk/react` |

## Documentation

| Doc | Read it for |
| --- | --- |
| [Architecture](docs/ARCHITECTURE.md) | How the pieces fit, what happens in a chat turn, the data model |
| [Rule engine](docs/RULE-ENGINE.md) | How a match is found, checked and approved, step by step |
| [Agent and tools](docs/TOOLS.md) | The six tools the agent can call, and its limits |
| [Limitations](docs/LIMITATIONS.md) | What Ledgerline doesn't check, and known bugs |

## Tests

```bash
cd backend
uv run python -m tests.test_duplicates
uv run python -m tests.test_embedded_keys
uv run python -m tests.test_translator_reasoning
uv run python -m tests.test_release_gate
```

No test runner is installed, so each file runs itself. They also work under
pytest if you add it. Lint with `uv run ruff check app tests`, and type-check
the frontend with `npm run typecheck`.

## Evaluation

The matching pipeline can be scored against labelled test data ("fixtures"):

```bash
cd backend
uv run python -m app.eval --fixture <dir>
uv run python -m app.eval --fixture <dir> --json > eval.json
uv run python -m app.eval --fixture <dir> --max-false-auto-match 0.03 --min-recall 0.95
uv run python -m app.eval --fixture <dir> --agent    # runs a real agent turn; costs money
```

A fixture is a folder of CSVs plus an `expected_reconciliation.csv` that says
what the right answer is. Without `--agent`, no AI model is used. The harness
loads the files into a temporary database, runs the automatic matching, and
compares the result with the expected answer.

The most important number is the **false auto-match rate**: of the matches
approved without a person, how many were wrong. A missed match costs someone an
afternoon. A wrong match puts a false figure in front of the person who signs
off on the books.

> The fixtures are not in this repository, so you need your own to run the
> evaluation. The last recorded result was 97–100% accuracy with a 0–2.9% false
> auto-match rate across eleven fixtures.

## Project layout

```text
backend/app/
  main.py, config.py   app setup and settings (.env)
  api/                 REST routes and the /api/chat stream
  core/                the matching pipeline (no AI here)
    ingest.py            CSV → its own ds_<id> table
    duplicates.py        mark repeated rows
    discovery.py         find columns whose values overlap across files
    embedded.py          find references hidden inside text, e.g. a narration
    automatch.py         decide join shape and amount column, build matching SQL
    matching.py          turn SQL results into proposals; the approval gate
    verify.py            the independent second check
    timing.py            learn the normal settlement delay
    spine.py             decide which file the money flow starts from
    transactions.py      group matches into end-to-end chains
    report.py            the close report
    sqlguard.py          run the agent's SQL read-only
  agents/              the AI agent, its six tools, and its callbacks
  streaming/           turn agent events into the stream the browser reads
  db/                  connection, migration runner, migrations/
  eval/                the evaluation harness
frontend/src/
  routes/              Home · Upload · Workspace · Report
  components/          chat panel, matched/source side panels, chain view
  state/               React context for datasets, proposals and chat
  types/stream.ts      TypeScript copy of streaming/protocol.py
demo/                  demo data and a script for a live walkthrough
```
