"""Pre-deploy check SQL: scoped to the tables a migration touches."""

from mysql_audit import cli, mcp_server
from mysql_audit.preflight import preflight_sql, touched_tables

MIGRATION = """
SET SESSION lock_wait_timeout = 5;
CREATE TABLE fresh (id INT PRIMARY KEY);
ALTER TABLE shop.orders ADD INDEX i (a), ALGORITHM=INPLACE, LOCK=NONE;
CREATE INDEX j ON fresh (id);
UPDATE users SET a = 1 WHERE b = 2;
INSERT INTO fresh SELECT id FROM orders;
DELETE FROM `o'brien` WHERE id < 10;
RENAME TABLE users TO users_old, users_new TO users;
"""


def test_touched_tables_skips_new_tables_and_reads():
    assert touched_tables(MIGRATION) == ["orders", "users", "o'brien", "users_new"]


def test_queries_use_the_tables_and_thresholds():
    sql = preflight_sql(MIGRATION)
    assert "IN ('orders', 'users', 'o''brien', 'users_new')" in sql
    assert "INTERVAL 10 SECOND" in sql and "time >= 10" in sql and "processlist_time >= 10" in sql
    assert "SHOW REPLICA STATUS" in sql and "Seconds_Behind_Source is 10 or less" in sql
    assert "wait/lock/metadata/sql/mdl" in sql  # version unknown: say how to turn it on for 5.7


def test_version_picks_the_replica_command():
    old = preflight_sql(MIGRATION, "5.7.44")
    assert "SHOW SLAVE STATUS" in old and "Seconds_Behind_Master" in old and "sql/mdl" in old
    new = preflight_sql(MIGRATION, "8.0.36")
    assert "SHOW REPLICA STATUS" in new and "sql/mdl" not in new
    assert "SHOW SLAVE STATUS" in preflight_sql(MIGRATION, "8.0.21")


def test_only_new_tables_leaves_the_table_checks_out():
    sql = preflight_sql("CREATE TABLE t (id INT PRIMARY KEY); INSERT INTO t VALUES (1);")
    assert "innodb_trx" in sql and "metadata_locks" not in sql and "REPLICA STATUS" in sql


def test_cli(tmp_path, monkeypatch, capsys):
    (tmp_path / ".git").mkdir()
    (tmp_path / "a.sql").write_text("ALTER TABLE orders ADD INDEX i (a);")
    (tmp_path / "b.sql").write_text("UPDATE users SET a = 1 WHERE b = 2")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MYSQL_AUDIT_VERSION", raising=False)
    assert cli.main(["a.sql", "b.sql", "--preflight", "--mysql-version", "5.7.44"]) == 0
    out = capsys.readouterr().out
    assert "IN ('orders', 'users')" in out and "SHOW SLAVE STATUS" in out


def test_mcp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MYSQL_AUDIT_VERSION", raising=False)
    result = mcp_server.preflight_checks("ALTER TABLE orders ADD INDEX i (a)")
    assert result["tables"] == ["orders"] and "metadata_locks" in result["sql"]
    assert "error" in mcp_server.preflight_checks("SELECT 1", mysql_version="bogus")
