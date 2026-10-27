import pytest

from mysql_audit import review

P = "SET SESSION lock_wait_timeout = 5;\n"
OPT = ", ALGORITHM=INPLACE, LOCK=NONE"
BIG = {"users": 5_000_000, "orders": 30_000_000, "tags": 500}


def hits(sql, rule, stats=BIG, schema=None):
    from conftest import SCHEMA

    return [f.severity.value for f in review(P + sql, schema=schema or SCHEMA, stats=stats).findings if f.rule_id == rule]


L03_CASES = [
    ("ALTER TABLE users ADD INDEX idx_email (email)" + OPT, ["warn"]),
    ("CREATE INDEX idx_email ON users (email)", ["warn"]),
    ("ALTER TABLE users MODIFY name VARCHAR(60) NOT NULL" + OPT, ["warn"]),
    ("ALTER TABLE users ENGINE=InnoDB", ["warn"]),
    ("ALTER TABLE `shop`.`orders` ADD INDEX i (a)" + OPT, ["warn"]),
    ("ALTER TABLE users ADD COLUMN note INT, ALGORITHM=INSTANT", []),
    ("ALTER TABLE users RENAME INDEX a TO b", []),
    ("ALTER TABLE tags ADD INDEX i (a)" + OPT, []),
    ("ALTER TABLE unknown_table ADD INDEX i (a)" + OPT, []),
]


@pytest.mark.parametrize("sql,expected", L03_CASES)
def test_l03(sql, expected):
    assert hits(sql, "L03") == expected


def test_l03_needs_stats():
    assert hits("ALTER TABLE users ADD INDEX i (email)" + OPT, "L03", stats=None) == []


L06_CASES = [
    ("UPDATE users SET age = 0 WHERE age IS NULL", ["warn"]),
    ("DELETE FROM orders WHERE created_at < '2024-01-01'", ["warn"]),
    ("INSERT INTO archive SELECT * FROM orders WHERE created_at < '2024-01-01'", ["warn"]),
    ("UPDATE users SET age = 0 WHERE status = 'disabled' AND age > 3", ["warn"]),
    ("UPDATE users SET age = 0 WHERE age IS NULL ORDER BY id LIMIT 1000", []),
    ("UPDATE users SET age = 0 WHERE id BETWEEN 1 AND 1000", []),
    ("DELETE FROM users WHERE id IN (1, 2, 3)", []),
    ("UPDATE tags SET a = 1 WHERE b = 2", []),
    ("INSERT INTO archive SELECT * FROM orders WHERE id > 5 LIMIT 1000", []),
]


@pytest.mark.parametrize("sql,expected", L06_CASES)
def test_l06(sql, expected):
    assert hits(sql, "L06") == expected


L09_CASES = [
    ("UPDATE users SET age = 0 WHERE age IS NULL", ["warn"]),           # schema known
    ("DELETE FROM users WHERE status = 'disabled'", ["warn"]),
    ("UPDATE invoices SET paid = 1 WHERE due < NOW()", ["info"]),        # table unknown
    ("INSERT INTO archive SELECT * FROM invoices", ["info"]),
    ("UPDATE users SET age = 0 WHERE email = 'a@x'", ["warn"]),          # email has no unique key here
    ("UPDATE users SET age = 0 WHERE id = 7", []),
    ("UPDATE invoices SET paid = 1 WHERE id BETWEEN 1 AND 500", []),
    ("UPDATE users SET age = 0 WHERE age IS NULL LIMIT 500", []),
    ("UPDATE users SET age = 0", []),                                    # L08's case
]


@pytest.mark.parametrize("sql,expected", L09_CASES)
def test_l09(sql, expected):
    assert hits(sql, "L09", stats=None) == expected


def test_l09_defers_to_size():
    assert hits("UPDATE users SET age = 0 WHERE age IS NULL", "L09") == []   # large: L06
    assert hits("UPDATE tags SET a = 1 WHERE b = 2", "L09") == []            # known small
