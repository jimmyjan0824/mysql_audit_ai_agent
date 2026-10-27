-- expect: safe
-- utf8mb4 VARCHAR(60) -> VARCHAR(63) stays under 255 bytes: metadata-only change.
SET SESSION lock_wait_timeout = 5;
ALTER TABLE users MODIFY email VARCHAR(63) NOT NULL, ALGORITHM=INPLACE, LOCK=NONE;
