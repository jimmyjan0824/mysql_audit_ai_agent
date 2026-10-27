-- expect: review
-- rules: L08
-- Which 1000 rows? Undefined, and unsafe for statement-based replication.
DELETE FROM sessions WHERE expires_at < NOW() LIMIT 1000;
