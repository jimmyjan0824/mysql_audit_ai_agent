"""Table sizes in bytes: the 5 GB large-table threshold, free-space hints (L03) and L17."""

import json

import pytest

from mysql_audit import review
from mysql_audit import cli, mcp_server
from mysql_audit.config import load_config

GB = 1024**3
P = "SET SESSION lock_wait_timeout = 5;\n"
OPT = ", ALGORITHM=INPLACE, LOCK=NONE"
SCHEMA = ("CREATE TABLE logs (id BIGINT NOT NULL PRIMARY KEY, body TEXT, n INT) ENGINE=InnoDB;\n"
          "CREATE TABLE small (id INT NOT NULL PRIMARY KEY, n INT) ENGINE=InnoDB;")
# Few rows but wide: large only by bytes.
STATS = {"logs": {"rows": 200_000, "data_bytes": 8 * GB, "index_bytes": 2 * GB},
         "small": {"rows": 500, "data_bytes": 64 * 1024, "index_bytes": 0}}


def rules(sql, stats=STATS, **kw):
    report = review(P + sql, schema=SCHEMA, stats=stats, **kw)
    return {f.rule_id: f for f in report.findings}, report


def test_old_row_count_format_still_works():
    found, _ = rules("ALTER TABLE logs ADD INDEX i (n)" + OPT, stats={"logs": 5_000_000})
    assert "L03" in found and "5,000,000 rows" in found["L03"].message


def test_large_by_bytes_alone():
    found, _ = rules("ALTER TABLE logs ADD INDEX i (n)" + OPT)
    assert "L03" in found and "10.0 GB" in found["L03"].message
    assert "L03" not in rules("ALTER TABLE logs ADD INDEX i (n)" + OPT,
                              stats={"logs": {"rows": 200_000, "data_bytes": 4 * GB}})[0]


def test_information_schema_column_names_and_qualified_tables():
    stats = {"shop.logs": {"TABLE_ROWS": 1, "DATA_LENGTH": str(6 * GB), "INDEX_LENGTH": None}}
    assert "L03" in rules("ALTER TABLE logs ADD INDEX i (n)" + OPT, stats=stats)[0]


def test_l03_states_free_space_for_rebuilds_only():
    rebuild = rules("ALTER TABLE logs ENGINE=InnoDB" + OPT)[0]["L03"]
    assert "about 10.0 GB" in rebuild.impact and "innodb_online_alter_log_max_size" in rebuild.impact
    index = rules("ALTER TABLE logs ADD INDEX i (n)" + OPT)[0]["L03"]
    assert "new copy" not in index.impact and "innodb_online_alter_log_max_size" in index.impact


def test_l06_large_by_bytes():
    found, _ = rules("UPDATE logs SET n = 0 WHERE n IS NULL")
    assert "L06" in found and "L09" not in found


@pytest.mark.parametrize("sql,free,expected", [
    ("ALTER TABLE logs ENGINE=InnoDB" + OPT, 8, "block"),          # 10 GB copy, 8 GB free
    ("ALTER TABLE logs ENGINE=InnoDB" + OPT, 12, "warn"),          # fits, but under 1.5x
    ("ALTER TABLE logs ENGINE=InnoDB" + OPT, 20, None),
    ("ALTER TABLE logs MODIFY n BIGINT", 8, "block"),               # COPY
    ("ALTER TABLE logs ADD PRIMARY KEY (id, n)" + OPT, 8, "block"),
    ("ALTER TABLE logs ADD INDEX i (n)" + OPT, 8, None),            # no table copy
    ("ALTER TABLE logs ADD COLUMN c INT, ALGORITHM=INSTANT", 8, None),
    ("ALTER TABLE logs ADD COLUMN c INT AFTER id" + OPT, 8, None),  # INSTANT on 8.0.29+
    ("ALTER TABLE small ENGINE=InnoDB" + OPT, 0, "block"),          # even small tables need room
    ("CREATE TABLE fresh (id INT PRIMARY KEY);\nALTER TABLE fresh ENGINE=InnoDB" + OPT, 0, None),
])
def test_l17(sql, free, expected):
    found, _ = rules(sql, free_disk_gb=free)
    assert (found["L17"].severity.value if "L17" in found else None) == expected


def test_l17_follows_the_version():
    sql = "ALTER TABLE logs ADD COLUMN c INT AFTER id" + OPT
    assert rules(sql, free_disk_gb=8, mysql_version="8.0.28")[0]["L17"].severity.value == "block"
    assert "L17" not in rules(sql, free_disk_gb=8, mysql_version="8.0.36")[0]


def test_l17_needs_bytes_and_free_space():
    assert "L17" not in rules("ALTER TABLE logs ENGINE=InnoDB" + OPT)[0]
    found, report = rules("ALTER TABLE logs ENGINE=InnoDB" + OPT, stats={"logs": 5_000_000}, free_disk_gb=1)
    assert "L17" not in found and any("free_disk_gb" in n for n in report.notes)


def test_cli_and_config(tmp_path, monkeypatch, capsys):
    (tmp_path / ".git").mkdir()
    (tmp_path / "schema.sql").write_text(SCHEMA)
    (tmp_path / "stats.json").write_text(json.dumps(STATS))
    (tmp_path / "m.sql").write_text(P + "ALTER TABLE logs ENGINE=InnoDB" + OPT + ";")
    monkeypatch.chdir(tmp_path)
    args = ["m.sql", "--schema", "schema.sql", "--stats", "stats.json"]
    assert cli.main(args + ["--free-disk-gb", "8"]) == 2
    assert "L17" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.main(args + ["--free-disk-gb", "lots"])

    (tmp_path / ".mysql-audit.toml").write_text('stats = "stats.json"\nschema = "schema.sql"\nfree_disk_gb = 8\n')
    assert load_config().free_disk_gb == 8
    assert cli.main(["m.sql"]) == 2
    assert cli.main(["m.sql", "--free-disk-gb", "100"]) == 1  # the option wins; L03 still warns
    result = mcp_server.review_migration(P + "ALTER TABLE logs ENGINE=InnoDB" + OPT)
    assert result["verdict"] == "block"
    result = mcp_server.review_migration(P + "ALTER TABLE logs ENGINE=InnoDB" + OPT, free_disk_gb=100)
    assert result["verdict"] == "review"
    assert "error" in mcp_server.review_migration("SELECT 1", free_disk_gb=-1)

    (tmp_path / ".mysql-audit.toml").write_text('free_disk_gb = "many"\n')
    with pytest.raises(ValueError):
        load_config()


def test_action_input(tmp_path, capsys):
    from mysql_audit import github_action as ga

    (tmp_path / "db").mkdir()
    (tmp_path / "db" / "schema.sql").write_text(SCHEMA)
    (tmp_path / "db" / "stats.json").write_text(json.dumps(STATS))
    (tmp_path / "db" / "001.sql").write_text(P + "ALTER TABLE logs ENGINE=InnoDB" + OPT + ";")
    env = {"GITHUB_WORKSPACE": str(tmp_path), "GITHUB_STEP_SUMMARY": str(tmp_path / "s.md"),
           "INPUT_PATHS": "db/0*.sql", "INPUT_SCHEMA": "db/schema.sql", "INPUT_STATS": "db/stats.json"}
    assert ga.run({**env, "INPUT_FREE_DISK_GB": "8"}) == 1          # block fails the check
    assert "L17" in capsys.readouterr().out
    assert ga.run({**env, "INPUT_FREE_DISK_GB": "100"}) == 0         # only L03 (warn)
    assert ga.run({**env, "INPUT_FREE_DISK_GB": "x"}) == 2
