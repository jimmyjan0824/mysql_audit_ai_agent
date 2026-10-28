import pytest

L07_POSITIVE = [
    "DROP TABLE users",
    "DROP TABLE IF EXISTS users, orders",
    "TRUNCATE users",
    "RENAME TABLE users TO members",
    "ALTER TABLE users DROP COLUMN age",
    "ALTER TABLE users DROP age",
    "ALTER TABLE users RENAME COLUMN age TO years",
    "ALTER TABLE users CHANGE age years INT",
    "ALTER TABLE users RENAME TO members",
    "DROP DATABASE shop",
    "ALTER TABLE users DROP PARTITION p2020",
    "ALTER TABLE users TRUNCATE PARTITION p2020, p2021",
]

L07_NEGATIVE = [
    "DROP TEMPORARY TABLE tmp_users",
    "CREATE TABLE t2 (id INT); DROP TABLE t2",
    "ALTER TABLE users CHANGE age age BIGINT",
    "ALTER TABLE users DROP INDEX idx_email",
    "ALTER TABLE users ADD COLUMN note TEXT",
    "CREATE TABLE t2 (id INT PRIMARY KEY) PARTITION BY HASH (id) PARTITIONS 2; ALTER TABLE t2 TRUNCATE PARTITION p0",
]


@pytest.mark.parametrize("sql", L07_POSITIVE)
def test_l07_blocks(check, sql):
    assert check(sql, "L07") == ["block"]


@pytest.mark.parametrize("sql", L07_NEGATIVE)
def test_l07_passes(check, sql):
    assert check(sql, "L07") == []


L08_CASES = [
    ("DELETE FROM users", ["block"]),
    ("UPDATE users SET age = 0", ["block"]),
    ("DELETE FROM `shop`.`users`", ["block"]),
    ("UPDATE users SET age = 0 LIMIT 100", ["block"]),
    ("DELETE FROM users WHERE age > 90 LIMIT 100", ["warn"]),
    ("UPDATE users SET age = 0 WHERE age IS NULL LIMIT 10", ["warn"]),
    ("DELETE FROM users WHERE id = 1", []),
    ("DELETE FROM users WHERE age > 90 ORDER BY id LIMIT 100", []),
    ("UPDATE users u JOIN bans b ON b.user_id = u.id SET u.status = 'disabled'", []),
    ("SELECT * FROM users", []),
]


@pytest.mark.parametrize("sql,expected", L08_CASES)
def test_l08(check, sql, expected):
    assert check(sql, "L08") == expected


def test_l07_drop_and_recreate_is_a_warning(check):
    sql = "DROP TABLE IF EXISTS users; CREATE TABLE users (id BIGINT PRIMARY KEY)"
    assert check(sql, "L07") == ["warn"]
    assert check("DROP TABLE users, orders; CREATE TABLE users (id INT)", "L07") == ["block"]


def test_l07_table_swap_is_not_destructive(check):
    swap = "CREATE TABLE users_new LIKE users; RENAME TABLE users TO users_old, users_new TO users"
    assert check(swap, "L07") == []
    assert check("RENAME TABLE users TO members, orders TO orders", "L07") == ["block"]


def test_l07_names_every_dropped_partition():
    from mysql_audit import review

    [f] = [f for f in review("ALTER TABLE users DROP PARTITION p2020, p2021").findings if f.rule_id == "L07"]
    assert "partitions `p2020`, `p2021`" in f.message and "EXCHANGE PARTITION" in f.fix
