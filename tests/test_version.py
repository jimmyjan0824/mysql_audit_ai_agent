import pytest

from mysql_audit import review
from mysql_audit.version import Version, parse_version

P = "SET SESSION lock_wait_timeout = 5;\n"
SCHEMA = "CREATE TABLE big (id INT NOT NULL PRIMARY KEY, a INT, b INT) DEFAULT CHARSET=utf8mb4;"
STATS = {"big": 5_000_000}


@pytest.mark.parametrize("text,expected", [
    ("8.0.28", Version(8, 0, 28)),
    ("8.0.36-log", Version(8, 0, 36)),
    ("8.4", Version(8, 4, 0)),
    ("5.7", Version(5, 7, 0)),
    ("5.7.44-0ubuntu0.18.04.1", Version(5, 7, 44)),
    ("aurora-3.04", Version(8, 0, 28)),
    ("aurora-3.04.1", Version(8, 0, 28)),
    ("Aurora-MySQL-3.05", Version(8, 0, 32)),
    ("aurora-2.11", Version(5, 7, 12)),
])
def test_parse_version(text, expected):
    assert parse_version(text) == expected


@pytest.mark.parametrize("text", ["8.0", "mariadb", "", "aurora-4.0"])
def test_parse_version_rejects(text):
    with pytest.raises(ValueError):
        parse_version(text)


def rules(sql, version, rule):
    report = review(P + sql, schema=SCHEMA, stats=STATS, mysql_version=version)
    return [f.severity.value for f in report.findings if f.rule_id == rule]


# (alter, version, the change copies the table on that version)
CASES = [
    ("ALTER TABLE big ADD COLUMN c INT", "5.7.44", True),
    ("ALTER TABLE big ADD COLUMN c INT", "8.0.12", False),
    ("ALTER TABLE big ADD COLUMN c INT AFTER id", "8.0.28", True),
    ("ALTER TABLE big ADD COLUMN c INT FIRST", "8.0.28", True),
    ("ALTER TABLE big DROP COLUMN a", "8.0.28", True),
    ("ALTER TABLE big ADD COLUMN c INT AFTER id", "8.0.29", False),
    ("ALTER TABLE big DROP COLUMN a", "8.4.3", False),
    ("ALTER TABLE big DROP COLUMN a", "aurora-3.04", True),
    ("ALTER TABLE big DROP COLUMN a", "aurora-3.05", False),
    ("ALTER TABLE big DROP COLUMN a", None, False),
]


@pytest.mark.parametrize("alter,version,copies", CASES)
def test_large_table_warning_follows_version(alter, version, copies):
    assert rules(alter + ", ALGORITHM=INPLACE, LOCK=NONE", version, "L03") == (["warn"] if copies else [])


@pytest.mark.parametrize("alter,version,copies", CASES)
def test_instant_refused_on_older_servers(alter, version, copies):
    assert rules(alter + ", ALGORITHM=INSTANT", version, "L01") == (["warn"] if copies else [])


def test_suggestion_matches_version():
    [old] = review(P + "ALTER TABLE big DROP COLUMN a", schema=SCHEMA, mysql_version="8.0.28").findings[:1]
    assert "ALGORITHM=INPLACE, LOCK=NONE" in old.fix
    [new] = review(P + "ALTER TABLE big DROP COLUMN a", schema=SCHEMA, mysql_version="8.0.29").findings[:1]
    assert "ALGORITHM=INSTANT" in new.fix


def test_note_only_when_the_assumption_mattered():
    note = "No MySQL version given"
    assert any(note in n for n in review(P + "ALTER TABLE big DROP COLUMN a").notes)
    assert not any(note in n for n in review(P + "ALTER TABLE big ADD INDEX i (a)").notes)
    assert not any(note in n for n in review(P + "ALTER TABLE big DROP COLUMN a", mysql_version="8.4.3").notes)
