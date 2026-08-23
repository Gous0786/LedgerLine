# Agentic Reconciliation System

Multi-source, multi-directional reconciliation. Sources are arbitrary CSVs with no
fixed schema; the direction of reconciliation follows the transaction flow rather
than a predefined model.

**Status: CSV ingest + display.** Upload multiple CSVs, each lands in its own SQLite
table and gets its own switchable tab in the Sources view. No matching logic or agent
is wired yet.

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

## CSV ingestion

Each file becomes its own table (`ds_<id>`); nothing is forced into a shared schema.
Delimiter (`, ; 	 |`), encoding (UTF-8/BOM, cp1252, latin-1) and column types are
detected per file, and what was found is recorded in `dataset_column`.

Type inference is deliberately conservative, because in reconciliation a mangled
identifier becomes a false break. A column is numeric only if *every* non-empty
value parses **and** no identifier hazard applies:

- **Leading zeros stay TEXT.** A UTR of `0007712345` parses fine as a number, and
  coercing it destroys the padding that makes it matchable. `0.5` is still REAL.
- **Digit runs longer than 15 stay TEXT** — an identifier, and float would cost
  precision anyway.
- Ragged rows are padded/truncated to the header width rather than rejected.
- One bad file in a batch does not sink the rest; it returns in `failed`.

    POST   /api/datasets/upload          multipart, repeated `files` field
    GET    /api/datasets                 list
    GET    /api/datasets/{id}            metadata + columns
    GET    /api/datasets/{id}/rows       ?offset&limit (max 500)
    DELETE /api/datasets/{id}            drops the table too

## Next

1. Deterministic matching over SQL, driven by the flow model — **before** the agent,
   so the numbers are reproducible without an LLM in the loop
2. ADK tree + `translator.py`, replacing the scripted stream in `api/chat.py`
3. Activity and Metrics surfaces off the `data-*` parts already defined
