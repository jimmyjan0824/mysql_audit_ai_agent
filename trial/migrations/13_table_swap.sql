-- expect: safe
-- Swapping in a rebuilt table keeps the name the application uses (e.g. after gh-ost style copy).
SET SESSION lock_wait_timeout = 5;
CREATE TABLE sessions_new LIKE sessions;
RENAME TABLE sessions TO sessions_old, sessions_new TO sessions;
