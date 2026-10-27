-- expect: block
-- rules: L02
-- INT -> BIGINT rebuilds the 25M-row table with ALGORITHM=COPY and blocks writes.
SET SESSION lock_wait_timeout = 5;
ALTER TABLE orders MODIFY total_cents BIGINT NOT NULL;
