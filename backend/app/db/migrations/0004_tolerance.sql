-- Match tolerance.
--
-- A bank batch that lands 0.02 away from the computed net is reconciled, not
-- broken -- rounding differs between systems. Without a tolerance every such
-- rounding difference becomes a false exception, which buries the real ones.
--
-- The allowance is stored per proposal, not just applied and forgotten: the
-- reviewer needs to see what slack was permitted, and the residual it absorbed.
ALTER TABLE match_proposal ADD COLUMN tolerance_minor INTEGER NOT NULL DEFAULT 0;
