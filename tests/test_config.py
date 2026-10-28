import json

import pytest

from mysql_audit import github_action as ga
from mysql_audit import mcp_server
from mysql_audit.cli import main
from mysql_audit.config import load_config

SCHEMA = "CREATE TABLE big (id INT NOT NULL PRIMARY KEY, a INT) DEFAULT CHARSET=utf8mb4;\n"
DROP = "SET SESSION lock_wait_timeout = 5;\nALTER TABLE big ADD COLUMN c INT AFTER id, ALGORITHM=INPLACE, LOCK=NONE;\n"


@pytest.fixture
def project(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "db").mkdir()
    (tmp_path / "db" / "schema.sql").write_text(SCHEMA)
    (tmp_path / "db" / "stats.json").write_text(json.dumps({"big": 5_000_000}))
    (tmp_path / "db" / "001_add.sql").write_text(DROP)
    (tmp_path / ".mysql-audit.toml").write_text(
        'mysql_version = "8.0.28"\nschema = "db/schema.sql"\nstats = "db/stats.json"\n')
    return tmp_path


def test_config_is_found_from_a_subdirectory(project):
    cfg = load_config(start=project / "db", env={})
    assert cfg.mysql_version == "8.0.28" and "CREATE TABLE big" in cfg.schema and cfg.stats == {"big": 5_000_000}


def test_config_stops_at_the_repository_root(tmp_path):
    (tmp_path / ".mysql-audit.toml").write_text('mysql_version = "5.7"\n')
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    assert load_config(start=tmp_path / "repo", env={}).path is None


def test_environment_overrides_version(project):
    assert load_config(start=project, env={"MYSQL_AUDIT_VERSION": "8.4.3"}).mysql_version == "8.4.3"


def test_unknown_setting_is_an_error(tmp_path):
    (tmp_path / ".mysql-audit.toml").write_text('mysql_verison = "8.0.28"\n')
    with pytest.raises(ValueError, match="mysql_verison"):
        load_config(start=tmp_path, env={})


def test_cli_reads_the_config(project, monkeypatch, capsys):
    monkeypatch.chdir(project / "db")
    monkeypatch.delenv("MYSQL_AUDIT_VERSION", raising=False)
    assert main(["001_add.sql"]) == 1                          # 8.0.28: AFTER rebuilds the large table
    assert "L03" in capsys.readouterr().out
    assert main(["001_add.sql", "--mysql-version", "8.0.29"]) == 0  # the option wins
    with pytest.raises(SystemExit):
        main(["001_add.sql", "--mysql-version", "8.0"])


def test_mcp_fills_in_from_the_config(project, monkeypatch):
    monkeypatch.chdir(project)
    monkeypatch.delenv("MYSQL_AUDIT_VERSION", raising=False)
    result = mcp_server.review_migration(DROP)
    assert result["verdict"] == "review" and any(".mysql-audit.toml" in n for n in result["notes"])
    assert mcp_server.review_migration(DROP, mysql_version="8.4.3")["verdict"] == "safe"
    assert "error" in mcp_server.review_migration(DROP, mysql_version="nope")


def test_action_reads_the_config_and_skips_its_files(project, tmp_path_factory, capsys):
    out = tmp_path_factory.mktemp("out")
    env = {"GITHUB_WORKSPACE": str(project), "GITHUB_STEP_SUMMARY": str(out / "s.md"), "INPUT_FAIL_ON": "review"}
    assert ga.run(env) == 1
    printed = capsys.readouterr().out
    assert "file=db/001_add.sql" in printed and "db/schema.sql" not in printed
    assert ga.run({**env, "INPUT_MYSQL_VERSION": "8.4.3"}) == 0
