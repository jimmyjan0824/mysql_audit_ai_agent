import pytest

L13_CASES = [
    ("SET sql_log_bin = 0", ["block"]),
    ("SET SESSION sql_log_bin = OFF", ["block"]),
    ("SET @@session.sql_log_bin = 0", ["block"]),
    ("SET @@sql_log_bin := 0", ["block"]),
    ("SET sql_log_bin = 1", []),
    ("SET GLOBAL max_connections = 500", ["warn"]),
    ("SET PERSIST read_only = OFF", ["warn"]),
    ("SET @@GLOBAL.read_only = 0", ["warn"]),
    ("SET GLOBAL max_connections = 500, sql_log_bin = 0", ["warn", "block"]),
    ("SET SESSION lock_wait_timeout = 5", []),
    ("SET foreign_key_checks = 0", []),
    ("SET @batch := 1000", []),
]


@pytest.mark.parametrize("sql,expected", L13_CASES)
def test_l13(check, sql, expected):
    assert check(sql, "L13") == expected


L14_CASES = [
    ("ALTER TABLE users ADD UNIQUE INDEX uq_email (email)", ["warn"]),
    ("ALTER TABLE users ADD UNIQUE KEY uq_email (email), ALGORITHM=INPLACE, LOCK=NONE", ["warn"]),
    ("ALTER TABLE users ADD CONSTRAINT uq_email UNIQUE (email)", ["warn"]),
    ("CREATE UNIQUE INDEX uq_email ON users (email)", ["warn"]),
    ("ALTER TABLE legacy ADD PRIMARY KEY (title)", ["warn"]),
    ("ALTER TABLE users ADD INDEX idx_email (email)", []),
    ("CREATE INDEX idx_email ON users (email)", []),
    ("CREATE TABLE t2 (a INT); ALTER TABLE t2 ADD UNIQUE INDEX u (a)", []),
]


@pytest.mark.parametrize("sql,expected", L14_CASES)
def test_l14(check, sql, expected):
    assert check(sql, "L14") == expected


L15_CASES = [
    ("CREATE TABLE logs (msg TEXT)", ["warn"]),
    ("CREATE TABLE logs (id BIGINT NOT NULL PRIMARY KEY, msg TEXT) ENGINE=MyISAM", ["warn"]),
    ("CREATE TABLE logs (msg TEXT) ENGINE = MEMORY", ["warn", "warn"]),
    ("CREATE TABLE logs AS SELECT * FROM users", ["warn"]),
    ("CREATE TABLE logs (id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, msg TEXT)", []),
    ("CREATE TABLE logs (id BIGINT NOT NULL, msg TEXT, PRIMARY KEY (id)) ENGINE=InnoDB", []),
    ("CREATE TEMPORARY TABLE tmp (a INT)", []),
    ("CREATE TABLE users_copy LIKE users", []),
]


@pytest.mark.parametrize("sql,expected", L15_CASES)
def test_l15(check, sql, expected):
    assert check(sql, "L15") == expected


L16_CASES = [
    ("GRANT ALL PRIVILEGES ON *.* TO 'app'@'%'", ["block"]),
    ("GRANT ALL ON *.* TO 'dba'@'localhost'", ["block"]),
    ("GRANT SELECT ON shop.* TO 'app'@'%'", ["warn"]),
    ("GRANT SELECT ON shop.* TO 'app'@'10.0.%' WITH GRANT OPTION", ["warn"]),
    ("DROP USER 'app'@'%'", ["block"]),
    ("DROP USER IF EXISTS app@localhost", ["block"]),
    ("GRANT SELECT, INSERT ON shop.* TO 'app'@'10.0.%'", []),
    ("GRANT ALL ON shop.* TO 'app'@'10.0.%'", []),
    ("GRANT 'reader' TO 'app'@'10.0.%'", []),
]


@pytest.mark.parametrize("sql,expected", L16_CASES)
def test_l16(check, sql, expected):
    assert check(sql, "L16") == expected


def test_l16_names_the_account(check):
    from mysql_audit import review

    [f] = review("DROP USER 'app'@'%', 'job'@'10.0.%'").findings
    assert "`app@%`, `job@10.0.%`" in f.message
