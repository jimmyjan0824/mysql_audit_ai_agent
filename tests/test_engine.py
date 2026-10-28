import json

import pytest

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
    assert {r["rule_id"] for r in mcp_server.list_rules()} == {f"L{i:02d}" for i in range(1, 19)}
    assert mcp_server.review_query("SELECT * FROM t WHERE a = 1")["verdict"] == "safe"
    assert mcp_server.review_code('q = f"SELECT * FROM t WHERE id = {x}"')["verdict"] == "block"


def test_backticks_lowercase_and_comments():
    from conftest import SCHEMA

    sql = "-- widen id\nset session lock_wait_timeout = 5;\nalter table `shop`.`Users` modify `age` bigint, algorithm=inplace, lock=none;"
    rules = [(f.rule_id, f.severity.value, f.line) for f in review(sql, schema=SCHEMA).findings]
    assert rules == [("L02", "block", 3), ("L18", "warn", 3)]  # no rollback for a blocked change


def test_versions_agree():
    import pathlib

    import pytest

    import mysql_audit

    tomllib = pytest.importorskip("tomllib")  # Python 3.11+

    root = pathlib.Path(__file__).parent.parent
    server = json.loads((root / "server.json").read_text())
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    bundle = json.loads((root / "mcpb" / "manifest.json").read_text())
    assert project["version"] == mysql_audit.__version__ == server["version"] == server["packages"][0]["version"] == bundle["version"]
    assert f"mcp-name: {server['name']}" in (root / "README.md").read_text()


def test_version_flag(capsys, monkeypatch):
    import mysql_audit
    from mysql_audit import cli, mcp_server

    with pytest.raises(SystemExit) as exit_:
        cli.main(["--version"])
    assert exit_.value.code == 0
    assert capsys.readouterr().out.strip() == f"mysql-audit {mysql_audit.__version__}"
    monkeypatch.setattr("sys.argv", ["mysql-audit-ai-agent", "--version"])
    mcp_server.main()  # prints and returns instead of starting the server
    assert capsys.readouterr().out.strip() == f"mysql-audit-ai-agent {mysql_audit.__version__}"


def test_color_output(tmp_path, capsys, monkeypatch):
    from mysql_audit import cli

    sql = tmp_path / "m.sql"
    sql.write_text("ALTER TABLE t DROP COLUMN c;\nUPDATE t SET a = 1 LIMIT 10;\n")
    red, yellow, reset = "\033[31m", "\033[33m", "\033[0m"

    assert cli.main([str(sql), "--color", "always"]) == 2
    out = capsys.readouterr().out
    assert "\033[1;31mBLOCK" + reset in out
    lines = out.splitlines()
    assert any(l.startswith(red + "  line ") and "[block]" in l and l.endswith(reset) for l in lines)
    assert any(l.startswith(yellow + "  line ") and "[warn]" in l for l in lines)
    assert all(not l.startswith("\033") for l in lines if "fix:" in l)

    cli.main([str(sql), "--color", "never"])
    assert "\033[" not in capsys.readouterr().out
    cli.main([str(sql)])  # auto: captured output is not a terminal
    assert "\033[" not in capsys.readouterr().out
    monkeypatch.setenv("FORCE_COLOR", "1")
    cli.main([str(sql)])
    assert red in capsys.readouterr().out
    monkeypatch.setenv("NO_COLOR", "1")
    cli.main([str(sql)])
    assert "\033[" not in capsys.readouterr().out
    cli.main([str(sql), "--color", "always", "--format", "json"])
    assert "\033[" not in capsys.readouterr().out
