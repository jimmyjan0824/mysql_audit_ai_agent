import pytest

from mysql_audit import review

SCHEMA = """
CREATE TABLE users (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  email VARCHAR(100) NOT NULL UNIQUE,
  status VARCHAR(20),
  created_at DATETIME,
  KEY idx_status_created (status, created_at)
);
CREATE TABLE orders (
  id BIGINT NOT NULL PRIMARY KEY,
  user_id BIGINT NOT NULL,
  total DECIMAL(10,2),
  note VARCHAR(100),
  FOREIGN KEY (user_id) REFERENCES users (id)
);
CREATE TABLE coupons (code VARCHAR(20), owner VARCHAR(50));
"""


def hits(sql, stats=None):
    return [f.message for f in review(sql, schema=SCHEMA, stats=stats).findings if f.rule_id == "L11"]


FLAGGED = [
    "SELECT * FROM users WHERE created_at > '2026-01-01'",           # not the leftmost column
    "SELECT * FROM orders WHERE total > 100",
    "SELECT * FROM orders o WHERE o.note = 'x'",
    "UPDATE orders SET total = 0 WHERE note LIKE 'abc%'",
    "SELECT * FROM coupons c JOIN orders o ON o.note = c.code",         # neither side indexed
    "DELETE FROM orders WHERE total = 0 AND note = 'x'",
]

CLEAN = [
    "SELECT * FROM users WHERE email = 'a@x'",
    "SELECT * FROM users WHERE status = 'active' AND created_at > NOW()",
    "SELECT * FROM orders WHERE user_id = 7",                           # FK index
    "SELECT * FROM users u JOIN orders o ON o.user_id = u.id WHERE u.id = 1",
    "SELECT * FROM orders o JOIN users u ON u.id = o.user_id",         # lookup side indexed
    "SELECT * FROM orders WHERE note LIKE '%abc'",                      # cannot use an index anyway
    "SELECT * FROM invoices WHERE x = 1",                               # table not in schema
    "SELECT * FROM orders",
    "CREATE INDEX idx_total ON orders (total); SELECT * FROM orders WHERE total > 5",
]


@pytest.mark.parametrize("sql", FLAGGED)
def test_l11_flags(sql):
    assert len(hits(sql)) >= 1


@pytest.mark.parametrize("sql", CLEAN)
def test_l11_passes(sql):
    assert hits(sql) == []


def test_l11_skips_small_tables():
    assert hits("SELECT * FROM orders WHERE total > 100", stats={"orders": 500}) == []
