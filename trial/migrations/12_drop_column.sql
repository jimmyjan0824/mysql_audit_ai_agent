-- expect: block
-- rules: L07 L18
-- The deployed application still reads coupon_code; requests fail until the new code ships.
SET SESSION lock_wait_timeout = 5;
ALTER TABLE orders DROP COLUMN coupon_code, ALGORITHM=INSTANT;
