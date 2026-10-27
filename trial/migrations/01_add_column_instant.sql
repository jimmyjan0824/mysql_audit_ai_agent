-- expect: safe
-- The safe pattern: short lock wait, explicit INSTANT so MySQL refuses instead of copying.
SET SESSION lock_wait_timeout = 5;
ALTER TABLE orders ADD COLUMN note VARCHAR(255), ALGORITHM=INSTANT;
