-- expect: review
-- rules: L04
-- Even an INSTANT change waits for the metadata lock; with the default 1-year timeout, traffic queues behind it.
ALTER TABLE sessions ADD COLUMN ip VARCHAR(45), ALGORITHM=INSTANT;
