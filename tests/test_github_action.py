from __future__ import annotations

import json

import pytest

from mysql_audit import github_action as ga

SCHEMA = "CREATE TABLE orders (id INT NOT NULL PRIMARY KEY, total INT);"
SAFE = "SET SESSION lock_wait_timeout = 5;\nALTER TABLE orders ADD COLUMN note VARCHAR(20), ALGORITHM=INSTANT;\n"
BLOCK = "SET SESSION lock_wait_timeout = 5;\nALTER TABLE orders DROP COLUMN total;\n"


class FakeGitHub(ga.GitHub):
    def __init__(self, files, comments=()):
        super().__init__("token", "o/r")
        self.files, self.comments, self.calls = files, list(comments), []

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path.startswith("/pulls/"):
            return [{"filename": f, "status": s} for f, s in self.files]
        if method == "GET" and "/comments" in path:
            return self.comments
        return {}


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "db" / "migrate").mkdir(parents=True)
    (tmp_path / "db" / "migrate" / "001_safe.sql").write_text(SAFE)
    (tmp_path / "db" / "migrate" / "002_drop.sql").write_text(BLOCK)
    (tmp_path / "db" / "schema.sql").write_text(SCHEMA)
    (tmp_path / "app.py").write_text('cur.execute(f"SELECT * FROM users WHERE id = {user_id}")\n')
    return tmp_path


def _env(repo, tmp_path, event=None, **inputs):
    env = {"GITHUB_WORKSPACE": str(repo), "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md")}
    if event is not None:
        (tmp_path / "event.json").write_text(json.dumps(event))
        env.update(GITHUB_EVENT_PATH=str(tmp_path / "event.json"), GITHUB_REPOSITORY="o/r")
    for name, value in inputs.items():
        env[f"INPUT_{name.upper()}"] = value
    return env


@pytest.mark.parametrize("path,patterns,hit", [
    ("a.sql", ["**/*.sql"], True),
    ("db/migrate/a.sql", ["**/*.sql"], True),
    ("db/migrate/a.sql", ["db/migrate/*.sql"], True),
    ("db/seed/a.sql", ["db/migrate/*.sql"], False),
    ("a.py", ["**/*.sql"], False),
])
def test_matches(path, patterns, hit):
    assert ga.matches(path, patterns) is hit


def test_push_reviews_every_matching_file(repo, tmp_path, capsys):
    code = ga.run(_env(repo, tmp_path, schema="db/schema.sql"))
    out = capsys.readouterr().out
    assert code == 1  # 002_drop.sql blocks
    assert "::error file=db/migrate/002_drop.sql,line=2,title=L07::" in out
    assert "db/schema.sql" not in out.split("## ")[1].split("###")[0]  # the schema file itself is not reviewed
    summary = (tmp_path / "summary.md").read_text()
    assert "MySQL Audit: BLOCK" in summary and "`db/migrate/001_safe.sql` | ✅ safe" in summary


def test_pull_request_reviews_only_changed_files_and_comments(repo, tmp_path, monkeypatch):
    fake = FakeGitHub([("db/migrate/001_safe.sql", "added"), ("db/migrate/002_drop.sql", "removed")])
    monkeypatch.setattr(ga, "GitHub", lambda *a: fake)
    code = ga.run(_env(repo, tmp_path, {"pull_request": {"number": 7}}, schema="db/schema.sql", github_token="t"))
    assert code == 0
    posts = [c for c in fake.calls if c[0] == "POST"]
    assert posts and posts[0][1] == "/issues/7/comments"
    assert ga.MARKER in posts[0][2]["body"] and "SAFE" in posts[0][2]["body"]


def test_existing_comment_is_updated(repo, tmp_path, monkeypatch):
    fake = FakeGitHub([("db/migrate/002_drop.sql", "modified")],
                      comments=[{"id": 5, "body": "hi"}, {"id": 9, "body": ga.MARKER + " old"}])
    monkeypatch.setattr(ga, "GitHub", lambda *a: fake)
    assert ga.run(_env(repo, tmp_path, {"pull_request": {"number": 7}}, github_token="t")) == 1
    assert [c[:2] for c in fake.calls if c[0] in ("POST", "PATCH")] == [("PATCH", "/issues/comments/9")]


def test_fail_on_levels(repo, tmp_path):
    assert ga.run(_env(repo, tmp_path, fail_on="never")) == 0
    (repo / "db" / "migrate" / "002_drop.sql").unlink()
    # 001_safe.sql alone: no lock_wait warning, nothing to fail on even at "review"
    assert ga.run(_env(repo, tmp_path, fail_on="review", schema="db/schema.sql")) == 0
    assert ga.run(_env(repo, tmp_path, fail_on="sometimes")) == 2


def test_code_paths_check_injection(repo, tmp_path, capsys):
    (repo / "db" / "migrate" / "002_drop.sql").unlink()
    code = ga.run(_env(repo, tmp_path, code_paths="**/*.py", schema="db/schema.sql"))
    assert code == 1
    assert "file=app.py,line=1,title=L12" in capsys.readouterr().out


def test_annotation_text_is_escaped():
    report = ga.review("UPDATE orders SET total = 0;")
    [line] = [a for a in ga.annotations("m.sql", report) if "L08" in a]
    assert "\n" not in line and "%0AFix:" in line


def test_changed_only_false_reviews_everything_in_a_pr(repo, tmp_path, monkeypatch):
    fake = FakeGitHub([("db/migrate/001_safe.sql", "added")])
    monkeypatch.setattr(ga, "GitHub", lambda *a: fake)
    env = _env(repo, tmp_path, {"pull_request": {"number": 7}}, github_token="t", changed_only="false", comment="false")
    assert ga.run(env) == 1  # 002_drop.sql is reviewed although the PR did not touch it
    assert not [c for c in fake.calls if c[0] == "POST"]
