-- expect: safe
-- The same backfill in batches by primary key range; repeat with the next range.
UPDATE orders SET status = 'archived' WHERE id BETWEEN 1 AND 1000 AND created_at < '2024-01-01';
