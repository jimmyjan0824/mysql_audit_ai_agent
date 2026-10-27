import pytest

from conftest import SAFE_PREFIX as P

POSITIVE = [
    ("ALTER TABLE users ADD COLUMN note VARCHAR(100)", "warn"),
    ("ALTER TABLE users ADD INDEX idx_email (email)", "warn"),
    ("CREATE INDEX idx_email ON users (email)", "warn"),
    ("DROP INDEX idx_email ON users", "warn"),
    ("ALTER TABLE users ADD INDEX idx_email (email), ALGORITHM=COPY", "block"),
    ("ALTER TABLE users ADD INDEX idx_email (email), ALGORITHM=INPLACE, LOCK=EXCLUSIVE", "block"),
    ("ALTER TABLE users ADD INDEX idx_email (email), LOCK=SHARED", "block"),
    ("ALTER TABLE users ADD INDEX idx_email (email), ALGORITHM=INPLACE", "info"),
]

NEGATIVE = [
    "ALTER TABLE users ADD INDEX idx_email (email), ALGORITHM=INPLACE, LOCK=NONE",
    "ALTER TABLE users ADD COLUMN note VARCHAR(100), ALGORITHM=INSTANT",
    "CREATE INDEX idx_email ON users (email) ALGORITHM=INPLACE LOCK=NONE",
    "ALTER TABLE users RENAME INDEX a TO b",
    "ALTER TABLE users ALTER COLUMN age SET DEFAULT 0",
    "CREATE TABLE t2 (id INT); ALTER TABLE t2 ADD INDEX i (id)",
]


@pytest.mark.parametrize("sql,severity", POSITIVE)
def test_l01_flags(check, sql, severity):
    assert check(P + sql, "L01") == [severity]


@pytest.mark.parametrize("sql", NEGATIVE)
def test_l01_passes(check, sql):
    assert check(P + sql, "L01") == []


def test_l01_suggests_instant_for_add_column():
    from mysql_audit import review

    f = review(P + "ALTER TABLE users ADD COLUMN note INT").findings[0]
    assert "INSTANT" in f.fix
