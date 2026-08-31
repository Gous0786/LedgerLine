-- Independent verification of a match before it is released.
--
-- `propose_matches` scores and records in one pass, and every amount it scores
-- came out of the agent's own SELECT expression. A wrong CAST -- truncation
-- where rounding was meant, or COALESCE turning a NULL into a balancing zero --
-- produces a group that is internally perfect and factually wrong. Confidence
-- cannot catch that, because confidence is computed from the same numbers.
--
-- So nothing reaches `accepted` until a second pass re-derives the figures from
-- the source rows themselves, trusting only the (dataset_id, row) pointers.
--
-- Append-only, like match_event: a verification is evidence, and re-running it
-- later against changed data should add a record rather than replace one.

CREATE TABLE verification (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id      INTEGER NOT NULL REFERENCES match_proposal(id) ON DELETE CASCADE,
    ts               TEXT NOT NULL DEFAULT (datetime('now')),
    verifier_version TEXT NOT NULL,
    status           TEXT NOT NULL,            -- pass | fail
    checked          INTEGER NOT NULL DEFAULT 0,
    failed           INTEGER NOT NULL DEFAULT 0,
    -- Signed residual the verifier computed from source cells, NOT the value
    -- the proposal recorded. The two disagreeing is itself a finding.
    residual_minor   INTEGER,
    invariants       TEXT NOT NULL             -- JSON array of {code,passed,detail}
);

CREATE INDEX idx_verification_proposal ON verification(proposal_id, id);
