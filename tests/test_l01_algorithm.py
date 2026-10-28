import pytest

from conftest import SAFE_PREFIX as P

POSITIVE = [
    ("ALTER TABLE users MODIFY age BIGINT", "warn"),
    ("ALTER TABLE users ADD COLUMN note INT, MODIFY age INT NOT NULL", "warn"),
    ("ALTER TABLE users ENGINE=InnoDB", "warn"),
    ("ALTER TABLE users ADD FULLTEXT INDEX ft (name)", "warn"),
    ("CREATE SPATIAL INDEX sp ON users (age)", "warn"),
    ("ALTER TABLE users ADD PRIMARY KEY (id)", "warn"),
    ("ALTER TABLE users ADD COLUMN note VARCHAR(100)", "info"),
    ("ALTER TABLE users ADD COLUMN age2 INT AS (age * 2) STORED", "warn"),  # COPY only
    ("ALTER TABLE users ADD INDEX idx_email (email)", "info"),
    ("CREATE INDEX idx_email ON users (email)", "info"),
    ("DROP INDEX idx_email ON users", "info"),
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
