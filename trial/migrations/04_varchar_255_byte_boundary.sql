-- expect: block
-- rules: L02
-- utf8mb4 VARCHAR(60) is 240 bytes; VARCHAR(100) is 400 bytes, past the 255-byte length prefix, so it is a table copy.
SET SESSION lock_wait_timeout = 5;
ALTER TABLE users MODIFY email VARCHAR(100) NOT NULL;
