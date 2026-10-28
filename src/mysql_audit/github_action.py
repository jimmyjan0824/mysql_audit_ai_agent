"""GitHub Action entry point: review the migrations a pull request changes.

Reads the action inputs from INPUT_* variables, reviews every changed file that
matches `paths`, then reports three ways: inline annotations on the diff, the
job summary, and one PR comment that is updated on every push. Fails the check
when the worst verdict reaches `fail-on`, unless one of `dba-approvers` has
approved the pull request at its current commit.

Down migrations (*.down.sql, Flyway U__ files) are not reviewed as changes:
they count as the rollback of the migration they pair with.
"""

from __future__ import annotations

import fnmatch
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from .config import load_config, parse_gb
from .engine import review, review_code
from .models import Report
from .preflight import preflight_sql
from .rules.rollback import is_down_file, sibling_rollback
from .version import parse_version

MARKER = "<!-- mysql-audit -->"
_RANK = {"safe": 0, "review": 1, "block": 2}
_LEVEL = {"block": "error", "warn": "warning", "info": "notice"}
_ICON = {"safe": "✅", "review": "⚠️", "block": "⛔"}


# -- inputs -----------------------------------------------------------------

def _input(env: dict[str, str], name: str, default: str = "") -> str:
    return env.get(f"INPUT_{name.upper().replace('-', '_')}", default).strip()


def _patterns(value: str) -> list[str]:
    return [p.strip() for p in value.replace(",", "\n").splitlines() if p.strip()]


def matches(path: str, patterns: list[str]) -> bool:
    """fnmatch, where a leading **/ also matches files at the top level."""
    for pattern in patterns:
        if fnmatch.fnmatch(path, pattern):
            return True
        if pattern.startswith("**/") and fnmatch.fnmatch(path, pattern[3:]):
            return True
    return False


# -- GitHub API ---------------------------------------------------------------

class GitHub:
    def __init__(self, token: str, repo: str, api: str = "https://api.github.com"):
        self.token, self.repo, self.api = token, repo, api.rstrip("/")

    def request(self, method: str, path: str, body: dict | None = None):
        req = urllib.request.Request(
            f"{self.api}/repos/{self.repo}{path}",
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "mysql-audit-action",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read() or b"null")

    def pr_files(self, number: int) -> list[str]:
        files: list[str] = []
        for page in range(1, 31):  # the API returns at most 3,000 files
            batch = self.request("GET", f"/pulls/{number}/files?per_page=100&page={page}")
            files += [f["filename"] for f in batch if f.get("status") != "removed"]
            if len(batch) < 100:
                break
        return files

    def upsert_comment(self, number: int, body: str) -> None:
        for page in range(1, 11):
            comments = self.request("GET", f"/issues/{number}/comments?per_page=100&page={page}")
            for c in comments:
                if MARKER in (c.get("body") or ""):
                    self.request("PATCH", f"/issues/comments/{c['id']}", {"body": body})
                    return
            if len(comments) < 100:
                break
        self.request("POST", f"/issues/{number}/comments", {"body": body})

    def approvers(self, number: int, head_sha: str, allowed: set[str]) -> list[str]:
        """Allowed users whose latest review approves the pull request at head_sha."""
        latest: dict[str, dict] = {}
        for page in range(1, 11):
            reviews = self.request("GET", f"/pulls/{number}/reviews?per_page=100&page={page}")
            for r in reviews:
                login = ((r.get("user") or {}).get("login") or "").lower()
                if login in allowed and r.get("state") in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
                    latest[login] = r
            if len(reviews) < 100:
                break
        return sorted(login for login, r in latest.items()
                      if r["state"] == "APPROVED" and r.get("commit_id") == head_sha)


# -- report -----------------------------------------------------------------

def _escape(text: str) -> str:
    """Workflow commands treat %, CR and LF specially."""
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def annotations(path: str, report: Report) -> list[str]:
    return [
        f"::{_LEVEL[f.severity.value]} file={path},line={f.line},title={f.rule_id}::"
        + _escape(f"{f.message}\nFix: {f.fix}")
        for f in report.findings
    ]


_CHECKLIST = [
    "Runs off-peak, with someone watching",
    "Backup taken, or rollback ready and tested",
    "Preflight checks run on the primary just before (SQL below): no rows, replica lag 10 s or less",
    "DBA approved",
]


def render(results: list[tuple[str, Report]], fail_on: str, preflight: str | None = None,
           approved_by: list[str] | None = None) -> str:
    worst = max((r.verdict for _, r in results), key=_RANK.__getitem__, default="safe")
    lines = [MARKER, f"## {_ICON[worst]} MySQL Audit: {worst.upper()}", ""]
    if not results:
        lines.append("No changed files match the migration paths.")
        return "\n".join(lines) + "\n"
    lines += ["| File | Verdict | Findings |", "|---|---|---|"]
    for path, r in results:
        counts = ", ".join(f"{sum(f.severity.value == s for f in r.findings)} {s}"
                           for s in ("block", "warn") if any(f.severity.value == s for f in r.findings))
        lines.append(f"| `{path}` | {_ICON[r.verdict]} {r.verdict} | {counts or '–'} |")
    for path, r in results:
        shown = [f for f in r.findings if f.severity.value != "info"]
        if not shown:
            continue
        lines += ["", f"### `{path}`", ""]
        for f in shown:
            lines += [
                f"- **{f.rule_id} {f.severity.value}**, line {f.line}: {f.message}",
                f"  - Impact: {f.impact}",
                f"  - Fix: {f.fix}",
            ]
    if worst != "safe":
        lines += ["", "### Before deploying", ""] + [f"- [ ] {item}" for item in _CHECKLIST]
        if preflight:
            lines += ["", "<details><summary>Preflight SQL (run on the primary right before the migration)</summary>",
                      "", "```sql", preflight.rstrip(), "```", "", "</details>"]
    if approved_by:
        lines += ["", "**Approved by " + ", ".join(f"@{u}" for u in approved_by)
                  + " at this commit**: the check passes despite the findings."]
    notes = sorted({n for _, r in results for n in r.notes})
    if notes:
        lines += ["", "<sub>" + " ".join(notes) + "</sub>"]
    if fail_on != "never":
        lines += ["", f"<sub>This check fails on `{fail_on}`. Rules: "
                  "https://github.com/jimmyjan0824/mysql_audit_ai_agent#rules</sub>"]
    return "\n".join(lines) + "\n"


# -- main -----------------------------------------------------------------

def _changed_files(gh: GitHub | None, event: dict) -> list[str] | None:
    """Files the PR touches, or None outside a pull request (then every file is checked)."""
    pr = event.get("pull_request")
    if not pr or gh is None:
        return None
    return gh.pr_files(pr["number"])


def run(env: dict[str, str] | None = None) -> int:
    env = env if env is not None else dict(os.environ)
    workspace = Path(env.get("GITHUB_WORKSPACE", "."))
    paths = _patterns(_input(env, "paths", "**/*.sql"))
    code_paths = _patterns(_input(env, "code-paths"))
    fail_on = _input(env, "fail-on", "block").lower()
    if fail_on not in ("block", "review", "never"):
        print(f"::error::fail-on must be block, review or never, not {fail_on!r}")
        return 2
    try:
        cfg = load_config(start=workspace, env={})
        version = _input(env, "mysql-version") or cfg.mysql_version
        if version:
            parse_version(version)
        free_disk = parse_gb(_input(env, "free-disk-gb")) if _input(env, "free-disk-gb") else cfg.free_disk_gb
    except (OSError, ValueError) as e:
        print(f"::error::{e}")
        return 2
    schema_path, stats_path = _input(env, "schema"), _input(env, "stats")
    schema = (workspace / schema_path).read_text(encoding="utf-8") if schema_path else cfg.schema
    stats = json.loads((workspace / stats_path).read_text(encoding="utf-8")) if stats_path else cfg.stats

    event = {}
    if env.get("GITHUB_EVENT_PATH") and Path(env["GITHUB_EVENT_PATH"]).exists():
        event = json.loads(Path(env["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    token = _input(env, "github-token")
    gh = GitHub(token, env["GITHUB_REPOSITORY"], env.get("GITHUB_API_URL", "https://api.github.com")) \
        if token and env.get("GITHUB_REPOSITORY") else None

    changed = _changed_files(gh, event) if _input(env, "changed-only", "true").lower() == "true" else None
    candidates = changed if changed is not None else sorted(
        str(p.relative_to(workspace)) for p in workspace.rglob("*") if p.is_file() and ".git" not in p.parts)
    skip = {schema_path, stats_path}

    results: list[tuple[str, Report]] = []
    for path in candidates:
        if path in skip or (workspace / path).resolve() in cfg.files or not (workspace / path).is_file():
            continue
        if matches(path, paths):
            if is_down_file(Path(path).name):
                continue
            report = review((workspace / path).read_text(encoding="utf-8", errors="replace"),
                            schema=schema, stats=stats, mysql_version=version, free_disk_gb=free_disk,
                            has_rollback=sibling_rollback(workspace / path) is not None)
        elif code_paths and matches(path, code_paths):
            report = review_code((workspace / path).read_text(encoding="utf-8", errors="replace"))
        else:
            continue
        results.append((path, report))
        for line in annotations(path, report):
            print(line)

    worst = max((_RANK[r.verdict] for _, r in results), default=0)
    failing = fail_on != "never" and worst >= _RANK[fail_on]
    pr = event.get("pull_request")
    approved_by: list[str] = []
    allowed = {u.lstrip("@").lower() for u in _patterns(_input(env, "dba-approvers"))}
    if failing and allowed and pr and gh:
        try:
            approved_by = gh.approvers(pr["number"], pr["head"]["sha"], allowed)
        except (urllib.error.HTTPError, KeyError) as e:
            print(f"::warning::Could not read the pull request's reviews ({e}).")

    migrations = [(workspace / p).read_text(encoding="utf-8", errors="replace")
                  for p, _ in results if matches(p, paths)]
    preflight = preflight_sql(";\n".join(migrations), version) if migrations else None
    body = render(results, fail_on, preflight, approved_by)
    print(body)
    if env.get("GITHUB_STEP_SUMMARY"):
        with open(env["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(body)

    if pr and gh and _input(env, "comment", "true").lower() == "true" and results:
        try:
            gh.upsert_comment(pr["number"], body)
        except urllib.error.HTTPError as e:  # e.g. read-only token on a fork PR
            print(f"::warning::Could not comment on the pull request ({e.code}); see the job summary instead.")

    if approved_by:
        print(f"::notice::Findings approved by {', '.join(approved_by)} at this commit.")
        return 0
    return 1 if failing else 0


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
