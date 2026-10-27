import json

from mysql_audit import review
from mysql_audit.cli import main
from mysql_audit import mcp_server

SAFE = (
    "SET SESSION lock_wait_timeout = 5;\n"
    "ALTER TABLE users ADD COLUMN note VARCHAR(100), ALGORITHM=INSTANT;\n"
    "UPDATE users SET note = 'x' WHERE id = 1;"
)


def test_safe_script():
    report = review(SAFE)
    assert report.verdict == "safe"
    assert report.statements == 3


def test_verdicts_and_order():
    report = review("SET lock_wait_timeout=5;\nALTER TABLE t ADD INDEX i (a);\nDELETE FROM t;")
    assert report.verdict == "block"
    assert [f.line for f in report.findings] == sorted(f.line for f in report.findings)
    data = report.to_dict()
    assert data["findings"][0]["rule_id"] == "L01" and data["findings"][0]["line"] == 2


def test_cli_exit_codes(tmp_path, capsys):
    ok = tmp_path / "ok.sql"
    ok.write_text(SAFE)
    bad = tmp_path / "bad.sql"
    bad.write_text("DELETE FROM t;")
    assert main([str(ok)]) == 0
    assert main([str(bad), "--format", "json"]) == 2
    out = capsys.readouterr().out
    assert json.loads(out[out.index("{"):])["verdict"] == "block"


def test_mcp_tools():
    assert mcp_server.review_migration("DELETE FROM t")["verdict"] == "block"
    assert mcp_server.explain_rule("l02")["rule_id"] == "L02"
    assert "error" in mcp_server.explain_rule("L99")
    assert {r["rule_id"] for r in mcp_server.list_rules()} == {f"L{i:02d}" for i in range(1, 13)}
    assert mcp_server.review_query("SELECT * FROM t WHERE a = 1")["verdict"] == "safe"
    assert mcp_server.review_code('q = f"SELECT * FROM t WHERE id = {x}"')["verdict"] == "block"


def test_backticks_lowercase_and_comments():
    from conftest import SCHEMA

    sql = "-- widen id\nset session lock_wait_timeout = 5;\nalter table `shop`.`Users` modify `age` bigint, algorithm=inplace, lock=none;"
    rules = [(f.rule_id, f.severity.value, f.line) for f in review(sql, schema=SCHEMA).findings]
    assert rules == [("L02", "block", 3)]


def test_versions_agree():
    import pathlib

    import pytest

    import mysql_audit

    tomllib = pytest.importorskip("tomllib")  # Python 3.11+

    root = pathlib.Path(__file__).parent.parent
    server = json.loads((root / "server.json").read_text())
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    assert project["version"] == mysql_audit.__version__ == server["version"] == server["packages"][0]["version"]
    assert f"mcp-name: {server['name']}" in (root / "README.md").read_text()
