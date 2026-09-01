# Agentic Reconciliation System

Multi-source, multi-directional reconciliation. Sources are arbitrary CSVs with no
fixed schema; the direction of reconciliation follows the transaction flow rather
than a predefined model.


## Stack

| Layer     | Choice                                                  |
| --------- | ------------------------------------------------------- |
| Backend   | FastAPI + uvicorn (Python 3.12, `uv`)                   |
| Store     | SQLite (WAL); each CSV lands in its own table            |
| Agent     | Google ADK, models via LiteLLM → OpenRouter              |
| Transport | Vercel AI SDK **UI Message Stream** over SSE             |
| Frontend  | Vite 8 + React 19 + TypeScript, Tailwind 4, `@ai-sdk/react` |

## Design decisions

**The LLM never does arithmetic.** Matching, summing and balancing run as SQL. The
agent chooses strategies and interprets results; every figure the UI shows traces to
a database row, not a token. The root agent's instruction enforces this.

**A shared key is not a relationship.** Before proposing anything, the
deterministic pass classifies each discovered join by cardinality and picks a
strategy: row-level equality where both sides are unique, the aggregate identity
`SUM(many) = one` for batch settlements, or a single partition of the many side
where only one class of row corresponds. Where neither side is unique it
declines and says why — a many-to-many join yields identifier-only groups that
no amount can verify, and those read as progress while explaining nothing.
Split credit/debit columns are republished as one signed column in a `v_*_norm`
view first, so a statement has something comparable at all.

**No configured windows, rates or policies.** A batch can tie to the penny and
still be late, but "three days" is a fact about one processor's contract, not
about reconciliation, and there is no constant that is right for the next
dataset. So the normal settlement lag is measured from the rule's own groups and
outliers are flagged against that. The first version used a Tukey fence and
failed silently once a third of a dataset was late — a tail test breaks down when
the tail gets big — so the split is found where the distribution actually
separates. See `core/timing.py`.

**Nothing is accepted on its own say-so.** Confidence is computed from the numbers
the matching SQL returned, so it cannot notice those numbers being wrong — a
truncating `CAST`, or a `COALESCE(col, 0)` that turns a missing amount into a
balancing zero, produces a group that ties perfectly and means nothing. Every
route to `accepted` therefore passes through `core/verify.py`, which trusts only
the `(dataset, row)` pointers and re-derives each figure from the source cell in
exact decimal. An amount that appears nowhere in the row it claims to come from
fails, and the proposal stays pending. A human can override with `force`, and the
override is recorded as one.

**The agent runs in the FastAPI process,** not behind a separate `adk api_server` —
one event bus, one SQLite handle, no cross-process plumbing between the agent and
the stream the UI reads.

**No canonical schema.** Uploaded CSVs are sniffed and written to their own tables
(`ds_<id>`), with findings recorded in `dataset_column`. Matching and break tables
arrive once the flow model is settled.

**One protocol for everything realtime.** Agent prose, reasoning and tool calls use
the AI SDK's native chunk types, so `useChat` renders them with no custom code.
Agent status and the cost/token/time meter travel as custom `data-*` parts. Two
behaviours are load-bearing:

- a data part with a **stable `id`** updates in place instead of appending — one
  live status row rather than a growing list;
- a data part marked **`transient`** reaches `onData` but never enters message
  history — correct for high-frequency meter ticks.

Contract lives in `backend/app/streaming/protocol.py` and mirrors
`frontend/src/types/stream.ts`. Change one, change the other.

## Evaluation

The deterministic pipeline is scored against labelled data, so a change to
matching is measured rather than eyeballed:

```bash
cd backend
uv run python -m app.eval --fixture ../../reconriver/sample-100-v2
uv run python -m app.eval --fixture <dir> --json > eval.json
uv run python -m app.eval --fixture <dir> --max-false-auto-match 0.12   # CI gate
```

No LLM is involved — it runs ingest, `auto_match_exact`, the release gate and
the verifier in a throwaway database, then compares the result to the fixture's
`expected_reconciliation.csv`. A fixture whose CSVs no longer match its labels
is rejected rather than scored.

Ground truth distinguishes fifteen outcomes; this system can claim three
(`MATCHED`, `EXCEPTION`, `MISSING`), so the outcomes collapse to those and the
report names which ones were not recovered. The headline number is the **false
auto-match rate** — of the groups that were actually released without a human,
how many were not real matches. Missing a match costs an afternoon; inventing
one puts a wrong figure in front of someone who signs it off.

## Setup

```bash
# backend
cd backend
uv sync
cp .env.example .env        # add OPENROUTER_API_KEY
uv run uvicorn app.main:app --reload

# frontend
cd frontend
npm install
npm run dev                 # http://localhost:5173, proxies /api → :8000
```

## Layout

```
backend/app/
  config.py            settings (models, db path, CORS)
  db/                  sqlite connection, migration runner, migrations/
  api/                 health · chat · datasets · runs · metrics
  streaming/
    protocol.py        AI SDK UI Message Stream chunk builders
    sse.py             StreamingResponse wrapper + required headers
    translator.py      ADK Event → chunk mapping  (documented, not yet wired)
  agents/
    models.py          LiteLLM → OpenRouter model factory
    root_agent.py      orchestrator placeholder
frontend/src/
  types/stream.ts      typed mirror of protocol.py
  components/          ChatPanel · Placeholder
  tabs/                Sources · Console · Matches · Breaks · Activity · Metrics
```

## What is verified

- `uv sync` resolves; ADK 2.7.1 `LiteLlm` instantiates against an OpenRouter model id
- migrations apply and are idempotent
- `/api/chat` emits correct headers, every chunk family, and the `[DONE]` terminator
- the real `DefaultChatTransport` parses that stream into text, reasoning and tool
  parts; stable-id updates and transient suppression both behave as designed
- frontend typechecks and builds clean

## Next

1. CSV ingest → per-dataset tables, sniffing and typing; Sources tab
2. Deterministic matching over SQL, driven by the flow model — **before** the agent,
   so the numbers are reproducible without an LLM in the loop
3. ADK tree + `translator.py`, replacing the scripted stream in `api/chat.py`
4. Activity and Metrics surfaces off the `data-*` parts already defined
