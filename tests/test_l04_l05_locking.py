import pytest

DDL = "ALTER TABLE users ADD INDEX i (email), ALGORITHM=INPLACE, LOCK=NONE"

L04_POSITIVE = [
    DDL,
    "SET SESSION lock_wait_timeout = 600; " + DDL,
    "SET GLOBAL lock_wait_timeout = 5; " + DDL,
    "DROP TABLE users",
    "RENAME TABLE users TO users_old",
    "TRUNCATE TABLE users",
]

L04_NEGATIVE = [
    "SET SESSION lock_wait_timeout = 5; " + DDL,
    "SET lock_wait_timeout=10; " + DDL,
    "SET @@session.lock_wait_timeout = 30; " + DDL,
    "CREATE TABLE t2 (id INT); ALTER TABLE t2 ADD INDEX i (id)",
    "UPDATE users SET age = 1 WHERE id = 1",
]


@pytest.mark.parametrize("sql", L04_POSITIVE)
def test_l04_flags(check, sql):
    assert check(sql, "L04") == ["warn"]


@pytest.mark.parametrize("sql", L04_NEGATIVE)
def test_l04_passes(check, sql):
    assert check(sql, "L04") == []


def test_l04_reported_once_per_script(check):
    assert check(DDL + "; " + DDL, "L04") == ["warn"]


FK = "FOREIGN KEY (age) REFERENCES ages (id)"

L05_CASES = [
    (f"ALTER TABLE users ADD {FK}", ["block"]),
    (f"ALTER TABLE users ADD CONSTRAINT fk_age {FK}", ["block"]),
    (f"ALTER TABLE users ADD COLUMN x INT, ADD CONSTRAINT fk_age {FK}", ["block"]),
    (f"SET foreign_key_checks = 1; ALTER TABLE users ADD {FK}", ["block"]),
    (f"SET foreign_key_checks = 0; ALTER TABLE users ADD {FK}", ["warn"]),
    (f"SET SESSION foreign_key_checks = OFF; ALTER TABLE users ADD {FK}", ["warn"]),
    ("ALTER TABLE users ADD CONSTRAINT uq UNIQUE (email)", []),
    ("ALTER TABLE users DROP FOREIGN KEY fk_age", []),
    (f"CREATE TABLE t2 (age INT); ALTER TABLE t2 ADD {FK}", []),
    (f"CREATE TABLE t3 (age INT, {FK})", []),
]


@pytest.mark.parametrize("sql,expected", L05_CASES)
def test_l05(check, sql, expected):
    assert check(sql, "L05") == expected
