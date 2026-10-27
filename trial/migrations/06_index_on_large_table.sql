-- expect: review
-- rules: L03
-- Online, but building an index on 25M rows takes a while and adds replica lag.
SET SESSION lock_wait_timeout = 5;
ALTER TABLE orders ADD INDEX idx_orders_created (created_at), ALGORITHM=INPLACE, LOCK=NONE;
