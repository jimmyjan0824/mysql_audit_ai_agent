-- expect: block
-- rules: L13
-- A "quick fix" run with binary logging off: the primary changes, the replicas never do.
SET SESSION sql_log_bin = 0;
UPDATE orders SET status = 'refunded' WHERE id = 42;
SET SESSION sql_log_bin = 1;
