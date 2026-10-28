"""L18: rollback and backup notes, down sections, sibling down files, and the Action's
checklist and DBA approval gate."""

import json

import pytest

from mysql_audit import cli, mcp_server, review
from mysql_audit import github_action as ga
from mysql_audit.rules.rollback import is_down_file, sibling_rollback

SCHEMA = "CREATE TABLE orders (id INT NOT NULL PRIMARY KEY, total INT, note TEXT);"
P = "SET SESSION lock_wait_timeout = 5;\n"
RISKY = P + "ALTER TABLE orders MODIFY total BIGINT;\n"           # L02 block
DROP = P + "ALTER TABLE orders DROP COLUMN note, ALGORITHM=INSTANT;\n"  # L07 block, deletes data


def l18(sql, **kw):
    return [f.message for f in review(sql, schema=SCHEMA, **kw).findings if f.rule_id == "L18"]


def test_risky_change_without_rollback():
    [msg] = l18(RISKY)
    assert "no rollback" in msg


def test_safe_change_needs_nothing():
    assert l18(P + "ALTER TABLE orders ADD COLUMN c INT, ALGORITHM=INSTANT;") == []


def test_queries_and_server_statements_need_no_rollback():
    assert l18("SELECT * FROM orders WHERE total > 5") == []        # L11 is about queries
    assert l18("SET GLOBAL max_connections = 500") == []


@pytest.mark.parametrize("note", [
    "-- rollback: ALTER TABLE orders MODIFY total INT;",
    "--rollback ALTER TABLE orders MODIFY total INT;",              # Liquibase formatted SQL
    "  -- ROLLBACK: restore from snapshot",
])
def test_rollback_notes(note):
    assert l18(RISKY + note) == []


def test_empty_rollback_note_does_not_count():
    assert l18(RISKY + "-- rollback:") != []


@pytest.mark.parametrize("up,down", [
    ("-- +goose Up\n", "-- +goose Down\n"),
    ("-- migrate:up\n", "-- migrate:down\n"),                          # dbmate
    ("-- +migrate Up\n", "-- +migrate Down\n"),                        # sql-migrate
])
def test_down_sections_count_and_are_not_reviewed(up, down):
    sql = up + RISKY + down + "ALTER TABLE orders MODIFY total INT;\nDROP TABLE orders;\n"
    report = review(sql, schema=SCHEMA)
    rules = {f.rule_id for f in report.findings}
    assert "L02" in rules and not rules & {"L07", "L18"}  # no L07 from the down section, no L18
    assert report.statements == 2


def test_empty_down_section_does_not_count():
    assert l18("-- +goose Up\n" + RISKY + "-- +goose Down\n-- nothing\n") != []


def test_deleting_data_needs_a_backup_note():
    messages = l18(DROP + "-- rollback: ALTER TABLE orders ADD COLUMN note TEXT;")
    assert len(messages) == 1 and "backup" in messages[0]
    assert l18(DROP + "-- rollback: re-add the column\n-- backup: s3://b/orders_note.sql.gz") == []
    assert len(l18(DROP)) == 2  # no backup and no rollback


@pytest.mark.parametrize("sql", [
    "DROP TABLE orders;", "TRUNCATE TABLE orders;", "DROP DATABASE shop;",
    "ALTER TABLE orders TRUNCATE PARTITION p1;",
])
def test_every_kind_of_deletion(sql):
    assert any("backup" in m for m in l18(P + sql, has_rollback=True))


def test_new_tables_are_not_deletions():
    assert l18(P + "CREATE TABLE t (id INT PRIMARY KEY);\nDROP TABLE t;") == []


def test_has_rollback_flag():
    assert l18(RISKY, has_rollback=True) == []


def test_down_file_names(tmp_path):
    assert is_down_file("0001_x.down.sql") and is_down_file("U3__undo.sql")
    assert not is_down_file("V3__x.sql") and not is_down_file("users.sql")
    (tmp_path / "0001_x.up.sql").write_text(RISKY)
    (tmp_path / "V3_1__x.sql").write_text(RISKY)
    (tmp_path / "V4__y.sql").write_text(RISKY)
    assert sibling_rollback(tmp_path / "0001_x.up.sql") is None
    (tmp_path / "0001_x.down.sql").write_text("ALTER TABLE orders MODIFY total INT;")
    (tmp_path / "U3_1__x.sql").write_text("ALTER TABLE orders MODIFY total INT;")
    assert sibling_rollback(tmp_path / "0001_x.up.sql") == tmp_path / "0001_x.down.sql"
    assert sibling_rollback(tmp_path / "V3_1__x.sql") == tmp_path / "U3_1__x.sql"
    assert sibling_rollback(tmp_path / "V4__y.sql") is None


def test_cli_finds_the_sibling(tmp_path, monkeypatch, capsys):
    (tmp_path / ".git").mkdir()
    (tmp_path / "schema.sql").write_text(SCHEMA)
    (tmp_path / "1_a.up.sql").write_text(RISKY)
    (tmp_path / "2_b.up.sql").write_text(RISKY)
    (tmp_path / "1_a.down.sql").write_text("ALTER TABLE orders MODIFY total INT;")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MYSQL_AUDIT_VERSION", raising=False)
    cli.main(["1_a.up.sql", "2_b.up.sql", "--schema", "schema.sql", "--format", "json"])
    out = json.loads(capsys.readouterr().out)
    assert ["L18" in {f["rule_id"] for f in r["findings"]} for r in out] == [False, True]


def test_mcp_rollback_sql(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MYSQL_AUDIT_VERSION", raising=False)
    rules = lambda r: {f["rule_id"] for f in r["findings"]}  # noqa: E731
    assert "L18" in rules(mcp_server.review_migration(RISKY, schema=SCHEMA))
    assert "L18" not in rules(mcp_server.review_migration(RISKY, schema=SCHEMA, rollback_sql="ALTER TABLE orders MODIFY total INT;"))
    assert "L18" not in rules(mcp_server.review_query("SELECT * FROM orders WHERE total = 1", schema=SCHEMA))


# -- GitHub Action ----------------------------------------------------------------

class FakeGitHub(ga.GitHub):
    def __init__(self, files, reviews=()):
        super().__init__("token", "o/r")
        self.files, self.reviews, self.calls = files, list(reviews), []

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        if "/reviews" in path:
            return self.reviews
        if path.startswith("/pulls/"):
            return [{"filename": f, "status": "added"} for f in self.files]
        if method == "GET":
            return []
        return {}


@pytest.fixture
def repo(tmp_path):
    d = tmp_path / "repo" / "db"
    d.mkdir(parents=True)
    (d / "schema.sql").write_text(SCHEMA)
    (d / "1_a.up.sql").write_text(RISKY)
    (d / "1_a.down.sql").write_text("DROP TABLE orders;")  # would block if reviewed as a change
    return tmp_path / "repo"


def _run(repo, tmp_path, monkeypatch, reviews=(), **inputs):
    fake = FakeGitHub(["db/1_a.up.sql", "db/1_a.down.sql"], reviews)
    monkeypatch.setattr(ga, "GitHub", lambda *a: fake)
    (tmp_path / "event.json").write_text(json.dumps({"pull_request": {"number": 7, "head": {"sha": "abc"}}}))
    env = {"GITHUB_WORKSPACE": str(repo), "GITHUB_STEP_SUMMARY": str(tmp_path / "s.md"),
           "GITHUB_EVENT_PATH": str(tmp_path / "event.json"), "GITHUB_REPOSITORY": "o/r",
           "INPUT_GITHUB_TOKEN": "t", "INPUT_SCHEMA": "db/schema.sql"}
    env.update({f"INPUT_{k.upper()}": v for k, v in inputs.items()})
    code = ga.run(env)
    [post] = [c[2]["body"] for c in fake.calls if c[0] == "POST"]
    return code, post


def test_action_pairs_down_files_and_adds_the_checklist(repo, tmp_path, monkeypatch):
    code, body = _run(repo, tmp_path, monkeypatch)
    assert code == 1
    assert "1_a.down.sql" not in body and "L18" not in body and "L02" in body
    assert "### Before deploying" in body and "- [ ] DBA approved" in body
    assert "Preflight SQL" in body and "IN ('orders')" in body


def test_dba_approval_lets_the_check_pass(repo, tmp_path, monkeypatch):
    def review_(user, state, sha="abc"):
        return {"user": {"login": user}, "state": state, "commit_id": sha}

    approvers = {"dba_approvers": "@Alice, bob"}
    code, body = _run(repo, tmp_path, monkeypatch, [review_("alice", "APPROVED")], **approvers)
    assert code == 0 and "Approved by @alice" in body
    # an approval from someone else, on an older commit, or later withdrawn does not count
    for reviews in ([review_("mallory", "APPROVED")], [review_("bob", "APPROVED", sha="old")],
                    [review_("bob", "APPROVED"), review_("bob", "CHANGES_REQUESTED")]):
        code, body = _run(repo, tmp_path, monkeypatch, reviews, **approvers)
        assert code == 1 and "Approved by" not in body
    # a later plain comment keeps the approval
    code, _ = _run(repo, tmp_path, monkeypatch, [review_("bob", "APPROVED"), review_("bob", "COMMENTED")], **approvers)
    assert code == 0
    # without dba-approvers, approvals are not looked at
    code, _ = _run(repo, tmp_path, monkeypatch, [review_("alice", "APPROVED")])
    assert code == 1
