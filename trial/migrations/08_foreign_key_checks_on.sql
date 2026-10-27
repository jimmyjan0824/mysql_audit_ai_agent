-- expect: block
-- rules: L05
-- With foreign_key_checks=1 adding a foreign key can only use COPY.
SET SESSION lock_wait_timeout = 5;
ALTER TABLE orders ADD CONSTRAINT fk_orders_user FOREIGN KEY (user_id) REFERENCES users (id);
