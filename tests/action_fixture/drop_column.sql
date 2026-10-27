-- Used by the action self-test in CI: must make the check fail.
SET SESSION lock_wait_timeout = 5;
ALTER TABLE orders DROP COLUMN total;
