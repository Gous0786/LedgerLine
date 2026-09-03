-- Duplicates become a property of the row, decided once at ingest.
--
-- Previously a duplicate was noticed at match time and recorded against a
-- match member, which meant a redundant row still entered every sum and every
-- group before anything knew it was redundant. Marking the row itself lets
-- matching simply not select it, so a group with a duplicated line balances by
-- construction rather than by a correction applied afterwards.
--
-- Exclusion is opt-in per dataset, and that default is measured rather than
-- cautious. Dropping a duplicated row makes its group tie, and a group that
-- ties gets released without a person -- which on the labelled fixtures turned
-- real exceptions into silent auto-matches: accuracy 100% -> 81.7%, false
-- auto-matches 0% -> 19.3%. A file recording a settlement twice is a
-- disagreement between that file and the bank, and someone has to decide which
-- is right.
--
-- So by default every duplicate is marked, visible and still counted. Turning
-- the toggle on for a dataset says: in this file a repeated row is a recording
-- artefact, not a finding. That is a claim only someone who knows the file can
-- make, which is exactly why it is a switch and not a constant.

ALTER TABLE dataset ADD COLUMN duplicate_rows INTEGER NOT NULL DEFAULT 0;
ALTER TABLE dataset ADD COLUMN near_duplicate_rows INTEGER NOT NULL DEFAULT 0;
ALTER TABLE dataset ADD COLUMN exclude_duplicates INTEGER NOT NULL DEFAULT 0;
