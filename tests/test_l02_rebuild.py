import pytest

from conftest import SAFE_PREFIX as P

OPT = ", ALGORITHM=INPLACE, LOCK=NONE"

POSITIVE = [
    "ALTER TABLE users MODIFY id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT",  # INT -> BIGINT
    "ALTER TABLE users MODIFY age BIGINT",
    "ALTER TABLE users MODIFY name VARCHAR(40) NOT NULL",                   # shrink
    "ALTER TABLE users MODIFY name VARCHAR(100) NOT NULL",                  # 200 -> 400 bytes
    "ALTER TABLE users CHANGE COLUMN email email VARCHAR(255) NOT NULL",    # crosses 255 bytes
    "ALTER TABLE users MODIFY status ENUM('disabled', 'active') NOT NULL",  # reordered
    "ALTER TABLE users MODIFY age VARCHAR(10)",                             # different type
    "ALTER TABLE users MODIFY code VARCHAR(200) CHARACTER SET utf8mb4",     # charset change
    "ALTER TABLE users CONVERT TO CHARACTER SET utf8mb4",
    "ALTER TABLE users DROP PRIMARY KEY",
    "ALTER TABLE users ADD COLUMN age2 INT AS (age * 2) STORED",            # computed for every row
    "ALTER TABLE users ADD COLUMN age2 INT GENERATED ALWAYS AS (age * 2) STORED",
]

NEGATIVE = [
    "ALTER TABLE users MODIFY name VARCHAR(60) NOT NULL",                   # 200 -> 240 bytes
    "ALTER TABLE users MODIFY code VARCHAR(250) CHARACTER SET latin1",      # 200 -> 250 bytes
    "ALTER TABLE legacy MODIFY title VARCHAR(85)",                          # utf8mb3: 240 -> 255
    "ALTER TABLE users MODIFY status ENUM('active', 'disabled', 'banned') NOT NULL",
    "ALTER TABLE users MODIFY age INT NOT NULL",                            # nullability only
    "ALTER TABLE users DROP PRIMARY KEY, ADD PRIMARY KEY (id, email)",
    "CREATE TABLE t2 (a INT); ALTER TABLE t2 MODIFY a BIGINT",
    "ALTER TABLE users ADD COLUMN age2 INT AS (age * 2) VIRTUAL",
    "ALTER TABLE users ADD COLUMN age2 INT AS (age * 2)",                   # VIRTUAL by default
]


@pytest.mark.parametrize("sql", POSITIVE)
def test_l02_blocks(check, sql):
    assert check(P + sql + OPT, "L02") == ["block"]


@pytest.mark.parametrize("sql", NEGATIVE)
def test_l02_passes(check, sql):
    assert check(P + sql + OPT, "L02") == []


def test_l02_unknown_column_warns(check):
    assert check(P + "ALTER TABLE orders MODIFY total DECIMAL(12,2)" + OPT, "L02") == ["warn"]
    assert check(P + "ALTER TABLE users MODIFY age BIGINT" + OPT, "L02", schema=None) == ["warn"]
