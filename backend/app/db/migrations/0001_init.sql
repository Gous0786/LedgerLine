-- Infrastructure tables only.
--
-- There is intentionally NO canonical reconciliation schema here. Reconciliation
-- is multi-source and multi-directional, so the shape of the data is discovered
-- per upload: each CSV gets its own table (ds_<dataset_id>) and `dataset_column`
-- records what was found. Matching/break tables arrive once the flow model is
-- settled.

-- ---------------------------------------------------------------- datasets --
CREATE TABLE dataset (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    original_name  TEXT,
    table_name     TEXT UNIQUE,          -- physical table holding the rows
    role           TEXT,                 -- free-form: 'gateway', 'bank', 'ledger', ...
    row_count      INTEGER NOT NULL DEFAULT 0,
    byte_size      INTEGER NOT NULL DEFAULT 0,
    delimiter      TEXT,
    encoding       TEXT,
    status         TEXT NOT NULL DEFAULT 'pending',  -- pending|ready|failed
    error          TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE dataset_column (
    dataset_id     TEXT NOT NULL REFERENCES dataset(id) ON DELETE CASCADE,
    ordinal        INTEGER NOT NULL,
    source_name    TEXT NOT NULL,        -- header as it appeared in the CSV
    column_name    TEXT NOT NULL,        -- sanitised SQL identifier
    inferred_type  TEXT,                 -- TEXT|INTEGER|REAL|DATE|TIMESTAMP
    null_count     INTEGER NOT NULL DEFAULT 0,
    distinct_count INTEGER,
    sample         TEXT,
    PRIMARY KEY (dataset_id, ordinal)
);

-- -------------------------------------------------------------------- runs --
CREATE TABLE run (
    id             TEXT PRIMARY KEY,
    title          TEXT,
    status         TEXT NOT NULL DEFAULT 'created',  -- created|running|done|failed|cancelled
    adk_session_id TEXT,
    config_json    TEXT,
    error          TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    started_at     TEXT,
    finished_at    TEXT
);

-- Durable activity feed. Every chunk pushed to the UI is persisted here first,
-- so the Activity tab can replay a run after a reload or reconnect.
-- `seq` is the client's resume cursor.
CREATE TABLE run_event (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT NOT NULL REFERENCES run(id) ON DELETE CASCADE,
    seq          INTEGER NOT NULL,
    ts           TEXT NOT NULL DEFAULT (datetime('now')),
    kind         TEXT NOT NULL,     -- ui-message-stream chunk type, e.g. 'tool-input-available'
    agent        TEXT,              -- emitting ADK agent
    payload_json TEXT NOT NULL,     -- the chunk itself, verbatim
    UNIQUE (run_id, seq)
);

CREATE INDEX idx_run_event_run_seq ON run_event(run_id, seq);
CREATE INDEX idx_run_event_kind ON run_event(run_id, kind);

-- One row per model call / tool call, for the cost + tokens + time panel.
CREATE TABLE run_metric (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id            TEXT NOT NULL REFERENCES run(id) ON DELETE CASCADE,
    ts                TEXT NOT NULL DEFAULT (datetime('now')),
    agent             TEXT,
    model             TEXT,
    tool_name         TEXT,
    prompt_tokens     INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    cached_tokens     INTEGER NOT NULL DEFAULT 0,
    reasoning_tokens  INTEGER NOT NULL DEFAULT 0,
    cost_usd          REAL    NOT NULL DEFAULT 0,
    latency_ms        INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_run_metric_run ON run_metric(run_id, ts);
