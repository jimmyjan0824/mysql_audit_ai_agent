-- expect: review
-- rules: L15
-- No primary key: replicas scan the table for every row change, and gh-ost cannot alter it later.
CREATE TABLE login_audit (
  user_id INT UNSIGNED NOT NULL,
  logged_in_at DATETIME NOT NULL,
  ip VARCHAR(45) NOT NULL
) DEFAULT CHARSET=utf8mb4;
