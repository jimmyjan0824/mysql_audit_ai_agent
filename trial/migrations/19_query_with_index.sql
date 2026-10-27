-- expect: safe
SELECT id, total_cents FROM orders WHERE user_id = 42 ORDER BY id DESC LIMIT 20;
