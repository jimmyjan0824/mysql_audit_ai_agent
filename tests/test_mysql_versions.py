"""Version-dependent judgments against a real server of that version.

For each column change, MySQL itself says whether it can run INSTANT. The
review, given the server's own version, must agree: no large-table warning
when MySQL runs it INSTANT, a warning when it has to rebuild the table.
The disk-space rule (L17) is checked the same way: a rebuilt table gets a new
InnoDB table id, so L17 must fire exactly for the ALTERs that change it.
CI runs this on MySQL 5.7, 8.0.28, 8.0 and 8.4.
"""

from __future__ import annotations

import json
import os

import pytest

from mysql_audit import review

pymysql = pytest.importorskip("pymysql")

pytestmark = pytest.mark.skipif(not os.environ.get("MYSQL_HOST"), reason="MYSQL_HOST not set")

NOT_INSTANT = {1064, 1800, 1845, 1846}  # 5.7: 1800 unknown ALGORITHM; 8.0: 1845/1846 not supported
SCHEMA = ("CREATE TABLE big (id INT NOT NULL PRIMARY KEY, a INT, b INT, "
          "name VARCHAR(50) NOT NULL) DEFAULT CHARSET=utf8mb4")

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
        c.execute("INSERT INTO big VALUES (1, 1, 1, 'x'), (2, 2, 2, 'y')")
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


REBUILD_ALTERS = ALTERS + [
    "ALTER TABLE big ENGINE=InnoDB",
    "ALTER TABLE big ADD INDEX i (a)",
    "ALTER TABLE big MODIFY a BIGINT",
    "ALTER TABLE big MODIFY name VARCHAR(60) NOT NULL",   # within 255 bytes: metadata only
    "ALTER TABLE big MODIFY name VARCHAR(70) NOT NULL",   # crosses 255 bytes: copy
    "ALTER TABLE big CONVERT TO CHARACTER SET latin1",
    "ALTER TABLE big DROP PRIMARY KEY, ADD PRIMARY KEY (id, a)",
    "ALTER TABLE big ADD COLUMN g INT AS (a * 2) STORED",
]


def _table_id(cur) -> int:
    for view in ("INNODB_TABLES", "INNODB_SYS_TABLES"):  # 8.0 / 5.7
        try:
            cur.execute(f"SELECT TABLE_ID FROM information_schema.{view} "
                        "WHERE NAME = 'mysql_audit_versions/big'")
        except pymysql.MySQLError:
            continue
        return cur.fetchone()[0]
    raise AssertionError("no InnoDB table view")


@pytest.mark.parametrize("alter", REBUILD_ALTERS)
def test_disk_rule_matches_table_rebuilds(cur, alter):
    cur.execute("SELECT VERSION()")
    version = cur.fetchone()[0]
    before = _table_id(cur)
    cur.execute(alter)
    rebuilt = _table_id(cur) != before

    stats = {"big": {"rows": 2, "data_bytes": 10 * 1024**3, "index_bytes": 0}}
    report = review(alter, schema=SCHEMA, stats=stats, mysql_version=version, free_disk_gb=1)
    flagged = any(f.rule_id == "L17" for f in report.findings)
    assert flagged is rebuilt, f"MySQL {version}: table {'rebuilt' if rebuilt else 'kept'}"


def test_stats_query_feeds_the_review(cur):
    """The stats export query in the README runs on this server and gives byte sizes."""
    cur.execute(
        "SELECT JSON_OBJECTAGG(table_name, JSON_OBJECT("
        "'rows', table_rows, 'data_bytes', data_length, 'index_bytes', index_length)) "
        "FROM information_schema.tables "
        "WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE'"
    )
    stats = json.loads(cur.fetchone()[0])
    assert stats["big"]["data_bytes"] > 0
    report = review("ALTER TABLE big ENGINE=InnoDB", schema=SCHEMA, stats=stats, free_disk_gb=0)
    assert any(f.rule_id == "L17" for f in report.findings)


def _preflight_results(cur, script: str) -> dict[int, list]:
    """Run each check of the preflight script; {check number: rows}."""
    results, number, lines = {}, 0, []
    for line in script.splitlines():
        if line.startswith("-- ") and line[3:4].isdigit():
            number = int(line[3])
        elif line.strip() and not line.startswith("--"):
            lines.append(line)
            if line.rstrip().endswith(";"):
                cur.execute("\n".join(lines))
                results[number] = list(cur.fetchall())
                lines = []
    return results


def test_preflight_sql_finds_a_blocking_transaction(cur):
    from mysql_audit.preflight import preflight_sql

    cur.execute("SELECT VERSION()")
    version = cur.fetchone()[0]
    if version.startswith("5.7"):
        cur.execute("UPDATE performance_schema.setup_instruments SET ENABLED = 'YES', TIMED = 'YES' "
                    "WHERE NAME = 'wait/lock/metadata/sql/mdl'")
    script = preflight_sql("ALTER TABLE big ADD INDEX i (a)", version)

    quiet = _preflight_results(cur, script)
    assert sorted(quiet) == [1, 2, 3, 4] and not any(quiet.values()), quiet

    def connect():
        conn = pymysql.connect(host=os.environ["MYSQL_HOST"], port=int(os.environ.get("MYSQL_PORT", "3306")),
                               user=os.environ.get("MYSQL_USER", "root"),
                               password=os.environ.get("MYSQL_PASSWORD", ""),
                               database="mysql_audit_versions", autocommit=True)
        return conn

    import threading
    import time

    holder, waiter = connect(), connect()
    with holder.cursor() as h:
        h.execute("BEGIN")
        h.execute("SELECT * FROM big")  # holds a shared metadata lock until commit

    def ddl():
        with waiter.cursor() as w:
            w.execute("SET SESSION lock_wait_timeout = 30")
            try:
                w.execute("ALTER TABLE big ADD INDEX i (a)")
            except pymysql.MySQLError:
                pass

    thread = threading.Thread(target=ddl)
    thread.start()
    try:
        time.sleep(11)  # past the 10-second thresholds
        found = _preflight_results(cur, script)
    finally:
        holder.commit()
        thread.join()
        holder.close()
        waiter.close()
    assert found[1], "long transaction not found"
    assert found[2], "long-waiting ALTER on the table not found"
    assert any(row[2] == "PENDING" for row in found[3]) and len(found[3]) >= 2, found[3]
