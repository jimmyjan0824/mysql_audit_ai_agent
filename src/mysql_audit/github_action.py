"""GitHub Action entry point: review the migrations a pull request changes.

Reads the action inputs from INPUT_* variables, reviews every changed file that
matches `paths`, then reports three ways: inline annotations on the diff, the
job summary, and one PR comment that is updated on every push. Fails the check
when the worst verdict reaches `fail-on`.
"""

from __future__ import annotations

import fnmatch
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from .engine import review, review_code
from .models import Report

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


def render(results: list[tuple[str, Report]], fail_on: str) -> str:
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
    schema_path, stats_path = _input(env, "schema"), _input(env, "stats")
    schema = (workspace / schema_path).read_text(encoding="utf-8") if schema_path else None
    stats = json.loads((workspace / stats_path).read_text(encoding="utf-8")) if stats_path else None

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
        if path in skip or not (workspace / path).is_file():
            continue
        if matches(path, paths):
            report = review((workspace / path).read_text(encoding="utf-8", errors="replace"), schema=schema, stats=stats)
        elif code_paths and matches(path, code_paths):
            report = review_code((workspace / path).read_text(encoding="utf-8", errors="replace"))
        else:
            continue
        results.append((path, report))
        for line in annotations(path, report):
            print(line)

    body = render(results, fail_on)
    print(body)
    if env.get("GITHUB_STEP_SUMMARY"):
        with open(env["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(body)

    pr = event.get("pull_request")
    if pr and gh and _input(env, "comment", "true").lower() == "true" and results:
        try:
            gh.upsert_comment(pr["number"], body)
        except urllib.error.HTTPError as e:  # e.g. read-only token on a fork PR
            print(f"::warning::Could not comment on the pull request ({e.code}); see the job summary instead.")

    worst = max((_RANK[r.verdict] for _, r in results), default=0)
    if fail_on != "never" and worst >= _RANK[fail_on]:
        return 1
    return 0


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
