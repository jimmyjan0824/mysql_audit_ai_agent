"""Version-dependent judgments against a real server of that version.

For each column change, MySQL itself says whether it can run INSTANT. The
review, given the server's own version, must agree: no large-table warning
when MySQL runs it INSTANT, a warning when it has to rebuild the table.
CI runs this on MySQL 5.7, 8.0.28, 8.0 and 8.4.
"""

from __future__ import annotations

import os

import pytest

from mysql_audit import review

pymysql = pytest.importorskip("pymysql")

pytestmark = pytest.mark.skipif(not os.environ.get("MYSQL_HOST"), reason="MYSQL_HOST not set")

NOT_INSTANT = {1064, 1800, 1845, 1846}  # 5.7: 1800 unknown ALGORITHM; 8.0: 1845/1846 not supported
SCHEMA = "CREATE TABLE big (id INT NOT NULL PRIMARY KEY, a INT, b INT)"

ALTERS = [
    "ALTER TABLE big ADD COLUMN c INT",
    "ALTER TABLE big ADD COLUMN c INT AFTER id",
    "ALTER TABLE big ADD COLUMN c INT FIRST",
    "ALTER TABLE big DROP COLUMN a",
]


@pytest.fixture
def cur():
    conn = pymysql.connect(
        host=os.environ["MYSQL_HOST"],
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ.get("MYSQL_USER", "root"),
        password=os.environ.get("MYSQL_PASSWORD", ""),
        autocommit=True,
    )
    with conn.cursor() as c:
        c.execute("DROP DATABASE IF EXISTS mysql_audit_versions")
        c.execute("CREATE DATABASE mysql_audit_versions")
        c.execute("USE mysql_audit_versions")
        c.execute(SCHEMA)
        c.execute("INSERT INTO big VALUES (1, 1, 1), (2, 2, 2)")
        yield c
    conn.close()


@pytest.mark.parametrize("alter", ALTERS)
def test_instant_judgment_matches_the_server(cur, alter):
    cur.execute("SELECT VERSION()")
    version = cur.fetchone()[0]
    try:
        cur.execute(alter + ", ALGORITHM=INSTANT")
        instant = True
    except pymysql.MySQLError as e:
        assert e.args[0] in NOT_INSTANT, e
        instant = False

    script = "SET SESSION lock_wait_timeout = 5;\n" + alter + ", ALGORITHM=INPLACE, LOCK=NONE"
    report = review(script, schema=SCHEMA, stats={"big": 5_000_000}, mysql_version=version)
    warned = any(f.rule_id == "L03" for f in report.findings)
    assert warned is (not instant), f"MySQL {version}: INSTANT {'works' if instant else 'refused'}"
