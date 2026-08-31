-- Small key/value store for inferred-or-declared state.
--
-- The spine (which source starts a transaction) is inferred from foreign-key
-- containment, but the agent may override it when the user's request implies
-- one -- "reconcile all orders" makes orders the spine regardless of what the
-- structure suggests. Persisting it keeps that decision stable across requests.
CREATE TABLE app_setting (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    reason     TEXT,
    set_by     TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
