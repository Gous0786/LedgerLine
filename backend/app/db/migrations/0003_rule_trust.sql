-- Rule-level approval.
--
-- Confidence says a match is internally sound; it says nothing about whether
-- the rule that produced it was scoped to what was actually asked. An unscoped
-- rule produces perfectly `exact` matches for rows nobody asked about, so
-- `exact` alone must not be enough to finalise anything.
--
-- A rule is unproven until a human approves it once. Until then its matches
-- wait, however confident they look.

CREATE TABLE rule_trust (
    rule        TEXT PRIMARY KEY,
    status      TEXT NOT NULL DEFAULT 'unproven',   -- unproven|trusted|retired
    first_seen  TEXT NOT NULL DEFAULT (datetime('now')),
    approved_at TEXT,
    approved_by TEXT,
    note        TEXT
);

-- Existing rules predate this gate; leave them unproven so they surface for
-- review rather than being silently grandfathered in.
INSERT INTO rule_trust (rule, status)
SELECT DISTINCT rule, 'unproven' FROM match_proposal;
