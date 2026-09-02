-- Mark a member that duplicates another row of the same source.

-- A file can record the same event twice, byte for byte. That is not a second
-- event, and in an aggregate match -- where one bank credit is checked against
-- the sum of many processor rows -- counting it twice makes the batch disagree
-- with the bank by exactly the duplicated amount.
--
-- The member stays in the group. Removing it would hide the defect, and the
-- reviewer needs to see both rows to decide which is right; what changes is
-- that its amount no longer contributes to the sum. `duplicate_of` holds the
-- __row it duplicates, so the UI can pair them and the verifier knows to skip
-- it rather than treating a zeroed amount as an untraceable figure.
--
-- Null for every ordinary member, which is nearly all of them.

ALTER TABLE match_member ADD COLUMN duplicate_of INTEGER;
