"""Entry point: review a SQL script and return a Report."""

from __future__ import annotations

from .analysis import analyze
from .context import ScriptContext
from .models import Report
from .rules import RULES
from .splitter import split_statements


def review(sql: str, schema: str | None = None) -> Report:
    """Review a migration or SQL script.

    schema: optional CREATE TABLE statements describing the current tables.
    With it, column changes are checked exactly instead of conservatively.
    """
    ctx = ScriptContext()
    report = Report()

    if schema:
        for stmt in split_statements(schema):
            ctx.learn_schema(analyze(stmt))
    else:
        report.notes.append("No schema given: column type changes are judged conservatively.")

    for stmt in split_statements(sql):
        report.statements += 1
        a = analyze(stmt)
        for rule in RULES.values():
            report.findings.extend(rule.check(a, ctx))
        ctx.update(a)

    report.findings.sort(key=lambda f: f.line)
    return report
