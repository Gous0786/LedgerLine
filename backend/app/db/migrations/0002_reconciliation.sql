-- Reconciliation state.
--
-- A "match" is a group of rows drawn from one or more datasets that reconcile
-- together. A 1:1 invoice->charge link and an N:1 batch settlement are the same
-- shape: a group with members. Groups are proposed by the agent (always via
-- SQL, never by passing rows) and either auto-accepted on deterministic
-- evidence or queued for a human.

-- Normalisation views the agent defines over raw ds_* tables. Stored so they
-- can be listed, shown in the UI, and rebuilt.
CREATE TABLE dataset_view (
    name        TEXT PRIMARY KEY,
    dataset_id  TEXT REFERENCES dataset(id) ON DELETE CASCADE,
    sql         TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE match_proposal (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT,
    rule          TEXT NOT NULL,
    tier          INTEGER NOT NULL DEFAULT 0,
    group_key     TEXT NOT NULL,
    -- exact | high | ambiguous | unbalanced -- computed from evidence by the
    -- matching engine, never supplied by the agent.
    confidence    TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending',   -- pending|accepted|rejected
    member_count  INTEGER NOT NULL DEFAULT 0,
    datasets      TEXT,
    -- signed sum across members; 0 means the group balances.
    balance_minor INTEGER,
    description   TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_proposal_status ON match_proposal(status, confidence);
CREATE INDEX idx_proposal_rule ON match_proposal(rule, tier);

CREATE TABLE match_member (
    proposal_id  INTEGER NOT NULL REFERENCES match_proposal(id) ON DELETE CASCADE,
    dataset_id   TEXT NOT NULL,
    row          INTEGER NOT NULL,
    role         TEXT,
    amount_minor INTEGER,
    PRIMARY KEY (proposal_id, dataset_id, row)
);

-- Drives tier exclusion: "is this row already spoken for?"
CREATE INDEX idx_member_row ON match_member(dataset_id, row);

-- Append-only. The reconciled view renders this in order, and it is the audit
-- record: why a match exists, who accepted it, when.
CREATE TABLE match_event (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id INTEGER NOT NULL REFERENCES match_proposal(id) ON DELETE CASCADE,
    ts          TEXT NOT NULL DEFAULT (datetime('now')),
    kind        TEXT NOT NULL,     -- proposed|auto_accepted|accepted|rejected|noted
    actor       TEXT NOT NULL,     -- agent|human|system
    detail      TEXT
);

CREATE INDEX idx_event_proposal ON match_event(proposal_id, id);

-- What the agent learns between batches. Typed and versioned rather than free
-- text, so a wrong pattern can be found and retired instead of silently
-- steering every later run.
CREATE TABLE pattern (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT NOT NULL,      -- join_key|transform|exclusion|namespace|tolerance
    name       TEXT NOT NULL,
    content    TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'candidate',  -- candidate|confirmed|retired
    evidence   TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (kind, name)
);
