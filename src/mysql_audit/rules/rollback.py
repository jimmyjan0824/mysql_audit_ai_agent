"""L18: a risky migration with no way back, or data deleted with no backup noted."""

from __future__ import annotations

import re
from pathlib import Path

from ..analysis import Analyzed
from ..context import ScriptContext
from ..models import Finding, Report, Severity
from .base import Rule, finding

# Sections that tools run as the down migration: everything after the marker.
_DOWN_MARKER = re.compile(
    r"^[ \t]*--[ \t]*(?:\+goose[ \t]+down|\+migrate[ \t]+down|migrate:down)\b.*$",
    re.IGNORECASE | re.MULTILINE,
)
# Liquibase formatted SQL: --rollback <sql>; also our own "-- rollback: ..." note.
_ROLLBACK_NOTE = re.compile(r"^[ \t]*--[ \t]*rollback\b(?:[ \t]*:)?[ \t]*[^\s:]", re.IGNORECASE | re.MULTILINE)
_BACKUP_NOTE = re.compile(r"^[ \t]*--[ \t]*backup[ \t]*:[ \t]*\S", re.IGNORECASE | re.MULTILINE)
# Findings about changes to tables and their data, the ones a rollback undoes.
_CHANGE_RULES = {"L01", "L02", "L03", "L05", "L06", "L07", "L08", "L09", "L14", "L17"}
_COMMENT_LINE = re.compile(r"^[ \t]*(?:--|#).*$", re.MULTILINE)


def split_down(sql: str) -> tuple[str, str | None]:
    """(up, down) for goose / sql-migrate / dbmate files; down is None without a marker."""
    m = _DOWN_MARKER.search(sql)
    if not m:
        return sql, None
    return sql[: m.start()], sql[m.end():]


def has_rollback_note(sql: str, down: str | None) -> bool:
    if down is not None and _COMMENT_LINE.sub("", down).strip(" \t\r\n;"):
        return True
    return bool(_ROLLBACK_NOTE.search(sql))


def has_backup_note(sql: str) -> bool:
    return bool(_BACKUP_NOTE.search(sql))


def _deletes_data(a: Analyzed, ctx: ScriptContext) -> bool:
    if a.kind == "drop_database":
        return True
    if a.kind in ("drop_table", "truncate") and not a.temporary:
        return any(not ctx.is_new(t) for t in a.tables)
    if a.kind == "alter_table" and not ctx.is_new(a.table):
        return any(c.kind in ("drop_column", "drop_partition", "truncate_partition") for c in a.clauses)
    return False


def _check_l18(a: Analyzed, ctx: ScriptContext) -> list[Finding]:
    """Per statement: data deleted while the script names no backup (once per script)."""
    if ctx.backup_noted or "L18-backup" in ctx.reported or not _deletes_data(a, ctx):
        return []
    ctx.reported.add("L18-backup")
    return [finding(
        "L18", Severity.WARN, a,
        "This migration deletes data, and the file does not say where the backup is.",
        "A down migration can recreate a dropped column or table, but not the rows that were in "
        "it. Without a backup the only way back is a point-in-time restore of the whole server.",
        "Back up what is deleted first (mysqldump --where, or CREATE TABLE ... AS SELECT into an "
        "archive schema) and note it in the file: -- backup: s3://bucket/orders_2026-10-28.sql.gz",
    )]


def check_rollback(report: Report, has_rollback: bool) -> None:
    """Script-wide: warn when a risky migration has no rollback. Runs after the other rules."""
    if has_rollback:
        return
    risky = [f for f in report.findings if f.severity != Severity.INFO and f.rule_id in _CHANGE_RULES]
    if not risky:
        return
    first = min(risky, key=lambda f: f.line)
    report.findings.append(Finding(
        "L18", Severity.WARN, first.line, first.statement,
        "This migration has review or block findings but no rollback.",
        "If it goes wrong in production, whoever is on call has to write the reverse SQL under "
        "pressure, against a half-changed schema.",
        "Add the reverse steps: a down section (-- +goose Down, -- migrate:down, -- +migrate Down), "
        "a sibling .down.sql (golang-migrate) or U__ file (Flyway), or --rollback lines "
        "(Liquibase). For a one-off script, -- rollback: <what to run> is enough.",
    ))


L18 = Rule(
    id="L18",
    title="No rollback for a risky migration, or no backup for deleted data",
    severity=Severity.WARN,
    why=(
        "Risky changes are the ones most likely to need undoing, and the worst time to write the "
        "reverse SQL is during the incident. Deleted rows cannot be brought back by any down "
        "migration, so a migration that drops or truncates should name its backup. Rollbacks are "
        "found in down sections (goose, sql-migrate, dbmate), Liquibase --rollback lines, a "
        "sibling .down.sql or Flyway U__ file, or a -- rollback: note."
    ),
    safe_example=(
        "-- backup: s3://db-backups/shop/legacy_notes_2026-10-28.sql.gz\n"
        "DROP TABLE legacy_notes;\n"
        "-- rollback: restore legacy_notes from the backup above"
    ),
    check=_check_l18,
)


# -- rollback files next to a migration ----------------------------------------

_FLYWAY = re.compile(r"^[VU](\d+(?:[._]\d+)*)__.+\.sql$", re.IGNORECASE)


def is_down_file(name: str) -> bool:
    """golang-migrate *.down.sql or a Flyway undo file U<version>__*.sql."""
    return name.lower().endswith(".down.sql") or (name[:1] in "Uu" and bool(_FLYWAY.match(name)))


def sibling_rollback(path: Path) -> Path | None:
    """The down / undo file that pairs with an up migration, if it exists."""
    name = path.name
    if name.lower().endswith(".up.sql"):
        down = path.with_name(name[: -len(".up.sql")] + ".down.sql")
        return down if down.is_file() else None
    m = _FLYWAY.match(name)
    if m and name[0] in "Vv":
        return next((p for p in sorted(path.parent.glob(f"U{m.group(1)}__*.sql")) if p.is_file()), None)
    return None
