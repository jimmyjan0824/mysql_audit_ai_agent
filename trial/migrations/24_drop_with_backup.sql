-- expect: block
-- rules: L07
-- The drop from 12 with its backup and rollback written down: L18 stays quiet, L07 still needs a DBA's call.
-- backup: s3://db-backups/shop/orders_coupon_code_2026-10-28.sql.gz
SET SESSION lock_wait_timeout = 5;
ALTER TABLE orders DROP COLUMN coupon_code, ALGORITHM=INSTANT;
-- rollback: ALTER TABLE orders ADD COLUMN coupon_code VARCHAR(32), ALGORITHM=INSTANT; then reload it from the backup
