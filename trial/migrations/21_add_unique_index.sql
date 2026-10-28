-- expect: review
-- rules: L14 L03
-- Fails if two orders already share a coupon; gh-ost / pt-osc would silently drop one of them.
SET SESSION lock_wait_timeout = 5;
ALTER TABLE orders ADD UNIQUE INDEX uq_orders_coupon (coupon_code), ALGORITHM=INPLACE, LOCK=NONE;
