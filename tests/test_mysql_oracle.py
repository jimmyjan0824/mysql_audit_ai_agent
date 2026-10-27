"""Check the rules against a real MySQL server.

The oracle: run each ALTER with ALGORITHM=INPLACE, LOCK=NONE. MySQL refuses
(errors 1845 / 1846) exactly when the change needs a table copy or blocks
writes. A rule that says "block" must match a refusal, and a rule that stays
quiet must match a statement MySQL runs online.

Runs only when MYSQL_HOST is set, e.g.
    MYSQL_HOST=127.0.0.1 MYSQL_PORT=3306 MYSQL_PASSWORD=root pytest tests/test_mysql_oracle.py
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from mysql_audit import review
from mysql_audit.splitter import split_statements

pymysql = pytest.importorskip("pymysql")

pytestmark = pytest.mark.skipif(not os.environ.get("MYSQL_HOST"), reason="MYSQL_HOST not set")

NOT_ONLINE = {1845, 1846}  # ER_ALTER_OPERATION_NOT_SUPPORTED(_REASON)
ONLINE = ", ALGORITHM=INPLACE, LOCK=NONE"

SCHEMA = """
CREATE TABLE ages (id INT NOT NULL PRIMARY KEY);
CREATE TABLE users (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(50) NOT NULL,
  email VARCHAR(60) NOT NULL,
  code VARCHAR(200) CHARACTER SET latin1,
  status ENUM('active', 'disabled') NOT NULL,
  age INT
) DEFAULT CHARSET=utf8mb4;
CREATE TABLE legacy (title VARCHAR(80)) DEFAULT CHARSET=utf8mb3;
CREATE TABLE plain (id INT NOT NULL PRIMARY KEY, note VARCHAR(10));
"""

ROWS = """
INSERT INTO ages VALUES (1), (2);
INSERT INTO users (name, email, code, status, age) VALUES ('a', 'a@x', 'c1', 'active', 1), ('b', 'b@x', 'c2', 'disabled', 2);
INSERT INTO legacy VALUES ('t');
INSERT INTO plain VALUES (1, 'n');
"""

FK = "ADD CONSTRAINT fk_age FOREIGN KEY (age) REFERENCES ages (id)"

# (setup, alter, rule, MySQL runs it online?)
CASES = [
    ("", "ALTER TABLE users MODIFY id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT", "L02", False),
    ("", "ALTER TABLE users MODIFY age BIGINT", "L02", False),
    ("", "ALTER TABLE users MODIFY name VARCHAR(40) NOT NULL", "L02", False),
    ("", "ALTER TABLE users MODIFY name VARCHAR(100) NOT NULL", "L02", False),
    ("", "ALTER TABLE users CHANGE COLUMN email email VARCHAR(255) NOT NULL", "L02", False),
    ("", "ALTER TABLE users MODIFY status ENUM('disabled', 'active') NOT NULL", "L02", False),
    ("", "ALTER TABLE users MODIFY age VARCHAR(10)", "L02", False),
    ("", "ALTER TABLE users MODIFY code VARCHAR(200) CHARACTER SET utf8mb4", "L02", False),
    ("", "ALTER TABLE users CONVERT TO CHARACTER SET utf8mb4", "L02", False),
    ("", "ALTER TABLE plain DROP PRIMARY KEY", "L02", False),
    ("", "ALTER TABLE users MODIFY name VARCHAR(60) NOT NULL", "L02", True),
    ("", "ALTER TABLE users MODIFY code VARCHAR(250) CHARACTER SET latin1", "L02", True),
    ("", "ALTER TABLE legacy MODIFY title VARCHAR(85)", "L02", True),
    ("", "ALTER TABLE users MODIFY status ENUM('active', 'disabled', 'banned') NOT NULL", "L02", True),
    ("", "ALTER TABLE users MODIFY age INT NOT NULL", "L02", True),
    ("", "ALTER TABLE plain DROP PRIMARY KEY, ADD PRIMARY KEY (id, note)", "L02", True),
    ("SET SESSION foreign_key_checks = 1", f"ALTER TABLE users {FK}", "L05", False),
    ("SET SESSION foreign_key_checks = 0", f"ALTER TABLE users {FK}", "L05", True),
]


# DDL without ALGORITHM: L01 says "info" exactly when MySQL can run it online.
L01_CASES = [
    ("ALTER TABLE users ADD COLUMN note VARCHAR(100)", True),
    ("ALTER TABLE users DROP COLUMN age", True),
    ("ALTER TABLE users ADD INDEX idx_email (email)", True),
    ("ALTER TABLE users ADD COLUMN note INT, ADD INDEX idx_note (note)", True),
    ("ALTER TABLE users ADD FULLTEXT INDEX ft (name)", False),
    ("ALTER TABLE users MODIFY age BIGINT", False),
]


def _connect(**kw):
    return pymysql.connect(
        host=os.environ["MYSQL_HOST"],
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ.get("MYSQL_USER", "root"),
        password=os.environ.get("MYSQL_PASSWORD", ""),
        autocommit=True,
        **kw,
    )


def _run(cur, script: str) -> None:
    for stmt in filter(str.strip, script.split(";")):
        cur.execute(stmt)


@pytest.fixture
def db():
    conn = _connect()
    with conn.cursor() as cur:
        cur.execute("DROP DATABASE IF EXISTS mysql_audit_test")
        cur.execute("CREATE DATABASE mysql_audit_test")
        cur.execute("USE mysql_audit_test")
        _run(cur, SCHEMA)
        _run(cur, ROWS)
    yield conn
    conn.close()


def _mysql_runs_online(conn, setup: str, alter: str) -> bool:
    with conn.cursor() as cur:
        if setup:
            cur.execute(setup)
        try:
            cur.execute(alter + ONLINE)
            return True
        except pymysql.MySQLError as e:
            if e.args[0] in NOT_ONLINE:
                return False
            raise


@pytest.mark.parametrize("setup,alter,rule,online", CASES)
def test_rule_matches_mysql(db, setup, alter, rule, online):
    assert _mysql_runs_online(db, setup, alter) is online, "case expectation is wrong for this MySQL version"

    script = "SET SESSION lock_wait_timeout = 5;\n" + (setup + ";\n" if setup else "") + alter + ONLINE
    blocked = [f for f in review(script, schema=SCHEMA).findings if f.rule_id == rule and f.severity.value == "block"]
    assert bool(blocked) is (not online)


@pytest.mark.parametrize("alter,online", L01_CASES)
def test_l01_matches_mysql(db, alter, online):
    assert _mysql_runs_online(db, "", alter) is online, "case expectation is wrong for this MySQL version"

    l01 = [f.severity.value for f in review("SET SESSION lock_wait_timeout = 5;\n" + alter, schema=SCHEMA).findings if f.rule_id == "L01"]
    assert l01 == (["info"] if online else ["warn"])


def test_metadata_lock_wait_times_out(db):
    """L04: an open transaction holds the metadata lock; with a short
    lock_wait_timeout the DDL gives up instead of queueing traffic behind it."""
    holder = _connect(database="mysql_audit_test")
    holder.autocommit(False)
    try:
        with holder.cursor() as cur:
            cur.execute("SELECT * FROM users")  # transaction now holds a shared metadata lock
        with db.cursor() as cur:
            cur.execute("SET SESSION lock_wait_timeout = 1")
            with pytest.raises(pymysql.MySQLError) as err:
                cur.execute("ALTER TABLE users ADD COLUMN note INT, ALGORITHM=INSTANT")
            assert err.value.args[0] == 1205  # ER_LOCK_WAIT_TIMEOUT
    finally:
        holder.rollback()
        holder.close()


TRIAL = Path(__file__).parent.parent / "trial"


@pytest.mark.parametrize("path", sorted((TRIAL / "migrations").glob("*.sql")), ids=lambda p: p.name)
def test_trial_migration_runs_on_mysql(path):
    """Every example in the DBA trial kit runs as written on an empty copy of its schema."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("DROP DATABASE IF EXISTS mysql_audit_trial")
            cur.execute("CREATE DATABASE mysql_audit_trial")
            cur.execute("USE mysql_audit_trial")
            for stmt in split_statements((TRIAL / "schema.sql").read_text()) + split_statements(path.read_text()):
                cur.execute(stmt.sql)
    finally:
        conn.close()
