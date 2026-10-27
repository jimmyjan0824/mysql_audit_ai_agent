-- expect: review
-- rules: L01 L03
-- FULLTEXT can only be built with LOCK=SHARED: writes to users wait for the whole build.
SET SESSION lock_wait_timeout = 5;
ALTER TABLE users ADD FULLTEXT INDEX ft_users_name (name);
