-- expect: review
-- rules: L06
-- One transaction over millions of orders: long row locks and replica lag.
UPDATE orders SET status = 'archived' WHERE created_at < '2024-01-01';
