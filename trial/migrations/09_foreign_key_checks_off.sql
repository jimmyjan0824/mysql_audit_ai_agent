-- expect: review
-- rules: L05
-- The online way to add a foreign key; existing rows are not validated, so check for orphans afterwards.
SET SESSION lock_wait_timeout = 5;
SET SESSION foreign_key_checks = 0;
ALTER TABLE orders ADD CONSTRAINT fk_orders_user FOREIGN KEY (user_id) REFERENCES users (id), ALGORITHM=INPLACE, LOCK=NONE;
SET SESSION foreign_key_checks = 1;
