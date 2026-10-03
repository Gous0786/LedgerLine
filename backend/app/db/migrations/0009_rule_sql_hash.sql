-- Trust belongs to a rule's SQL, not to its name.
--
-- Approval was keyed on the rule name alone, so a query submitted under a name
-- that was already trusted inherited that trust -- including a system rule's,
-- whose names are returned to the agent. The hash pins approval to the query
-- that was actually approved.
--
-- Existing rows have no hash. They adopt the next SQL submitted under their
-- name; an agent submission demotes a trusted one to unproven, since there is
-- no way to tell whether it is the query a person approved.

ALTER TABLE rule_trust ADD COLUMN sql_hash TEXT;
