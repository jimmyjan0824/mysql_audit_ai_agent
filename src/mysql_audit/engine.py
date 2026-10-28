"""Entry points: review a SQL script, or review application code."""

from __future__ import annotations

from .analysis import analyze
from .context import ScriptContext
from .models import Report
from .rules import RULES, review_code
from .splitter import split_statements
from .version import parse_version

__all__ = ["review", "review_code"]


def review(
    sql: str,
    schema: str | None = None,
    stats: dict[str, int] | None = None,
    mysql_version: str | None = None,
) -> Report:
    """Review a migration or SQL script.

    schema: optional CREATE TABLE statements describing the current tables.
        With it, column changes are checked exactly and missing indexes found.
    stats: optional approximate row count per table, e.g. from
        SELECT table_name, table_rows FROM information_schema.tables.
        Enables the large-table rules (L03, L06).
    mysql_version: optional target server, e.g. "8.0.28" or "aurora-3.04". Older
        servers copy the table for ADD COLUMN ... AFTER and DROP COLUMN (before
        8.0.29) or for every ADD COLUMN (5.7). Without it, 8.0.29 or later is assumed.
    """
    ctx = ScriptContext()
    report = Report()
    if mysql_version:
        ctx.version = parse_version(mysql_version)

    if schema:
        for stmt in split_statements(schema):
            ctx.learn_schema(analyze(stmt))
    else:
        report.notes.append("No schema given: column changes are judged conservatively and indexes are not checked.")
    if stats:
        ctx.rows = {name.lower().split(".")[-1]: int(rows) for name, rows in stats.items()}
    else:
        report.notes.append("No table stats given: large-table rules (L03, L06) are skipped.")

    analyzed = [analyze(stmt) for stmt in split_statements(sql)]
    ctx.recreated = {a.table for a in analyzed if a.kind in ("create_table", "create_view") and a.table}
    for a in analyzed:
        report.statements += 1
        for rule in RULES.values():
            report.findings.extend(rule.check(a, ctx))
        ctx.update(a)

    if ctx.version_assumed:
        report.notes.append(
            "No MySQL version given: assumed 8.0.29 or later, where ADD COLUMN (any position) and "
            "DROP COLUMN run INSTANT. Pass mysql_version for older servers or Aurora."
        )
    report.findings.sort(key=lambda f: f.line)
    return report
