# Ledgerline

Multi-source payment reconciliation over arbitrary CSVs. No canonical schema, no
configured field mapping, no declared relationship between the files: which
columns join, which direction the money flows, and which column holds the amount
are all measured from the data on upload.

Point it at a ledger, a gateway export and a bank statement, ask it to reconcile,
and get back what tied, what did not, and why — with every figure traceable to a
source row.

```text
┌──────────────┐      ┌───────────────────┐      ┌────────────────┐
│ erp_ledger   │─────▶│ gateway_razorpayx │─────▶│ bank_hdfc      │
│ 9 of 10 rows │      │  10 of 10 rows    │      │  9 of 10 rows  │
└──────────────┘      └───────────────────┘      └────────────────┘
   ORD-1002  erp and gateway differ by 50.00        exception
   ORD-1008  two gateway rows for one capture       exception
   ORD-1006  never reached the gateway              unmatched
```

## Documentation

| | |
| --- | --- |
| [Architecture](docs/ARCHITECTURE.md) | System diagram, request lifecycle, module map, data model |
| [Rule engine](docs/RULE-ENGINE.md) | How a match is decided, stage by stage, and why each threshold is measured |
| [Agent surface](docs/TOOLS.md) | The six tools, the guardrails, what the agent may not do |
| [Limitations](docs/LIMITATIONS.md) | What this does not check, and where it will mislead you |

## Stack

| Layer | Choice |
| --- | --- |
| Backend | FastAPI + uvicorn (Python 3.12, `uv`) |
| Store | SQLite (WAL); each CSV lands in its own table |
| Agent | Google ADK `LlmAgent`, models via LiteLLM → OpenRouter |
| Transport | Vercel AI SDK **UI Message Stream** over SSE |
| Frontend | Vite 8 + React 19 + TypeScript, Tailwind 4, `@ai-sdk/react` |

## The four decisions that shape everything

**The LLM never does arithmetic.** Matching, summing and balancing run as SQL.
The agent chooses strategies and interprets results; every figure the UI shows
traces to a database row, not a token.

**Nothing is configured that can be measured.** A shared key is classified by
cardinality before anything is proposed. Amount columns are found by how often
they agree across a join, never by name. The normal settlement lag is learned
from each rule's own groups. A constant right for one processor's contract is
wrong for the next dataset — so there are none.

**Nothing is accepted on its own say-so.** Confidence is computed from the
numbers the matching SQL returned, so it cannot notice those numbers being
wrong. Every route to `accepted` passes through an independent verifier that
trusts only `(dataset, row)` pointers and re-derives each figure from the source
cell in exact decimal.

**Findings are not failures.** A bank statement holds fees and balance lines no
order will ever explain. What did not reconcile is reported as plainly as what
did, and the close report states what it did not check.

## Setup

```bash
# backend
cd backend
uv sync
cp .env.example .env          # add OPENROUTER_API_KEY
uv run uvicorn app.main:app --reload

# frontend
cd frontend
npm install
npm run dev                   # http://localhost:5173, proxies /api → :8000
```

Upload CSVs on `/upload`, then ask the agent to reconcile. `/report` renders the
close report and downloads as a self-contained HTML file.

## Evaluation

The deterministic pipeline is scored against labelled fixtures, so a change to
matching is measured rather than eyeballed:

```bash
cd backend
uv run python -m app.eval --fixture <dir>
uv run python -m app.eval --fixture <dir> --json > eval.json
uv run python -m app.eval --fixture <dir> --max-false-auto-match 0.03 --min-recall 0.95
uv run python -m app.eval --fixture <dir> --agent      # drives a real turn; costs money
```

No LLM is involved by default — it runs ingest, `auto_match_exact`, the release
gate and the verifier in a throwaway database, then compares against the
fixture's `expected_reconciliation.csv`. A fixture whose CSVs no longer match its
labels is rejected rather than scored.

Ground truth distinguishes fifteen outcomes; this system can claim three
(`MATCHED`, `EXCEPTION`, `MISSING`), so outcomes collapse to those and the report
names which were not recovered. The headline number is the **false auto-match
rate** — of the groups released without a human, how many were not real matches.
Missing a match costs an afternoon; inventing one puts a wrong figure in front of
someone who signs it off.

Current: **97.0–100% accuracy, 0–2.9% false auto-match** across eleven fixtures
spanning clean, mixed-exception, month-end and failed-reconciliation scenarios.

## Tests

```bash
cd backend
uv run python -m tests.test_duplicates
uv run python -m tests.test_embedded_keys
uv run python -m tests.test_translator_reasoning
uv run python -m tests.test_release_gate
```

They run themselves because the project has no test runner installed, and work
under pytest if one is added. Each guard in the duplicate and embedded-key
detectors has a test that fails when the guard is disabled.

## Layout

```text
backend/app/
  config.py            settings (model, db path, CORS, timeouts)
  db/                  connection, migration runner, migrations/
  api/                 health · chat · datasets · proposals · coverage ·
                       transactions · runs · metrics · report · session
  core/
    ingest.py          CSV → its own ds_<id> table
    duplicates.py      mark repeated rows at ingest; per-file policy
    discovery.py       value-overlap matrix; trace_record
    embedded.py        keys buried inside free text
    automatch.py       cardinality, amount discovery, rule construction
    matching.py        proposals, confidence, the release gate
    verify.py          twelve invariants; the only door to accepted
    timing.py          settlement lag learned from the data
    spine.py           which dataset transactions start from
    transactions.py    end-to-end chains along the spine
    report.py          the close report
    sqlguard.py        read-only SQL for agent queries
  agents/
    root_agent.py      the single LlmAgent and its instruction
    tools/recon.py     the six tools
    callbacks.py       exploration budget, result capping, run accounting
  streaming/           AI SDK chunk builders, SSE wrapper, ADK → chunk translator
  eval/                fixtures, runner, scoring, the CI gate
frontend/src/
  routes/              Home · Upload · Workspace · Report
  components/workspace ChatPanel · ReconciledRail · SourceRail · Chain · TokenMeter
  state/               datasets · proposals · chat providers
  types/stream.ts      typed mirror of streaming/protocol.py
```
