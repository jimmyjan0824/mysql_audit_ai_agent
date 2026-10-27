-- expect: review
-- rules: L11
-- orders.status has no index: a full scan of 25M rows on every call.
SELECT id, total_cents FROM orders WHERE status = 'pending';
