"""Entry points: review a SQL script, or review application code."""

from __future__ import annotations

from .analysis import analyze
from .context import ScriptContext
from .models import Report
from .rules import RULES, review_code
from .splitter import split_statements

__all__ = ["review", "review_code"]


def review(sql: str, schema: str | None = None, stats: dict[str, int] | None = None) -> Report:
    """Review a migration or SQL script.

    schema: optional CREATE TABLE statements describing the current tables.
        With it, column changes are checked exactly and missing indexes found.
    stats: optional approximate row count per table, e.g. from
        SELECT table_name, table_rows FROM information_schema.tables.
        Enables the large-table rules (L03, L06).
    """
    ctx = ScriptContext()
    report = Report()

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

    report.findings.sort(key=lambda f: f.line)
    return report
