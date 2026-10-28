"""Entry points: review a SQL script, or review application code."""

from __future__ import annotations

from .analysis import analyze
from .context import ScriptContext
from .models import Report
from .rules import RULES, review_code
from .rules.rollback import check_rollback, has_backup_note, has_rollback_note, split_down
from .splitter import split_statements
from .version import parse_version

__all__ = ["review", "review_code"]


def _load_stats(stats: dict, ctx: ScriptContext) -> None:
    """Accept {"t": rows} or {"t": {"rows", "data_bytes", "index_bytes"}}."""
    for name, value in stats.items():
        table = name.lower().split(".")[-1]
        if isinstance(value, dict):
            v = {k.lower(): n for k, n in value.items() if n is not None}
            rows = v.get("rows", v.get("table_rows"))
            if rows is not None:
                ctx.rows[table] = int(rows)
            parts = [v.get("data_bytes", v.get("data_length")), v.get("index_bytes", v.get("index_length"))]
            if any(n is not None for n in parts):
                ctx.sizes[table] = sum(int(n) for n in parts if n is not None)
        elif value is not None:
            ctx.rows[table] = int(value)


def review(
    sql: str,
    schema: str | None = None,
    stats: dict | None = None,
    mysql_version: str | None = None,
    free_disk_gb: float | None = None,
    has_rollback: bool = False,
) -> Report:
    """Review a migration or SQL script.

    schema: optional CREATE TABLE statements describing the current tables.
        With it, column changes are checked exactly and missing indexes found.
    stats: optional size per table from information_schema.tables, either a row
        count ({"orders": 25000000}) or {"orders": {"rows": 25000000,
        "data_bytes": ..., "index_bytes": ...}}. Enables the large-table rules
        (L03, L06; large = 1,000,000 rows or 5 GB) and the disk-space check (L17).
    mysql_version: optional target server, e.g. "8.0.28" or "aurora-3.04". Older
        servers copy the table for ADD COLUMN ... AFTER and DROP COLUMN (before
        8.0.29) or for every ADD COLUMN (5.7). Without it, 8.0.29 or later is assumed.
    free_disk_gb: optional free space on the server's data volume. With table
        sizes in stats, a rebuild that needs more than this is blocked (L17).
    has_rollback: the caller found a rollback outside this text (a sibling
        .down.sql or Flyway U__ file). Down sections and --rollback lines inside
        the text are found here; the down section itself is not reviewed.
    """
    sql, down = split_down(sql)
    has_rollback = has_rollback or has_rollback_note(sql, down)
    ctx = ScriptContext(backup_noted=has_backup_note(sql))
    report = Report()
    if mysql_version:
        ctx.version = parse_version(mysql_version)

    if schema:
        for stmt in split_statements(schema):
            ctx.learn_schema(analyze(stmt))
    else:
        report.notes.append("No schema given: column changes are judged conservatively and indexes are not checked.")
    if free_disk_gb is not None:
        ctx.free_disk = int(float(free_disk_gb) * 1024**3)
    if stats:
        _load_stats(stats, ctx)
        if ctx.free_disk is not None and not ctx.sizes:
            report.notes.append("free_disk_gb given but stats have no data_bytes / index_bytes: "
                                "the disk-space check (L17) is skipped.")
    else:
        report.notes.append("No table stats given: large-table rules (L03, L06) are skipped.")

    analyzed = [analyze(stmt) for stmt in split_statements(sql)]
    ctx.recreated = {a.table for a in analyzed if a.kind in ("create_table", "create_view") and a.table}
    for a in analyzed:
        report.statements += 1
        for rule in RULES.values():
            report.findings.extend(rule.check(a, ctx))
        ctx.update(a)

    check_rollback(report, has_rollback)
    if ctx.version_assumed:
        report.notes.append(
            "No MySQL version given: assumed 8.0.29 or later, where ADD COLUMN (any position) and "
            "DROP COLUMN run INSTANT. Pass mysql_version for older servers or Aurora."
        )
    report.findings.sort(key=lambda f: f.line)
    return report
