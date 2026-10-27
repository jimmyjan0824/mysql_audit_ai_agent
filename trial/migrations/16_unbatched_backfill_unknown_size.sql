-- expect: review
-- rules: L09
-- audit_log has no row count in stats.json, so the tool cannot tell how many rows this touches.
UPDATE audit_log SET actor = LOWER(actor) WHERE action = 'login';
