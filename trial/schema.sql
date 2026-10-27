-- Example schema for the trial: a small online shop.
-- The tool reads it to know column types, charsets and indexes.
CREATE TABLE users (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  email VARCHAR(60) NOT NULL,
  name VARCHAR(100) NOT NULL,
  status ENUM('active', 'disabled') NOT NULL DEFAULT 'active',
  created_at DATETIME NOT NULL,
  UNIQUE KEY uq_users_email (email)
) DEFAULT CHARSET=utf8mb4;

CREATE TABLE orders (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id INT UNSIGNED NOT NULL,
  total_cents INT NOT NULL,
  status VARCHAR(20) NOT NULL,
  coupon_code VARCHAR(32),
  created_at DATETIME NOT NULL,
  KEY idx_orders_user (user_id)
) DEFAULT CHARSET=utf8mb4;

CREATE TABLE sessions (
  id CHAR(36) NOT NULL PRIMARY KEY,
  user_id INT UNSIGNED NOT NULL,
  expires_at DATETIME NOT NULL
) DEFAULT CHARSET=utf8mb4;

CREATE TABLE audit_log (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  actor VARCHAR(100) NOT NULL,
  action VARCHAR(50) NOT NULL,
  created_at DATETIME NOT NULL
) DEFAULT CHARSET=utf8mb4;
