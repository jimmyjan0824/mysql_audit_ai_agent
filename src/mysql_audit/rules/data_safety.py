"""L07 and L08: statements that lose data or break running code."""

from __future__ import annotations

from sqlglot import exp

from ..analysis import Analyzed
from ..context import ScriptContext
from ..models import Finding, Severity
from .base import Rule, finding


# -- L07 -------------------------------------------------------------------

def _destructive_actions(a: Analyzed, ctx: ScriptContext) -> list[str]:
    if a.kind == "drop_database":
        return ["drops a whole database"]
    if a.kind == "drop_table" and not a.temporary:
        old = [t for t in a.tables if not ctx.is_new(t)]
        return [f"drops table `{t}`" for t in old]
    if a.kind == "truncate":
        return [f"deletes every row of `{a.table}`"]
    if a.kind == "rename_table":
        return ["renames a table"]
    if a.kind != "alter_table" or ctx.is_new(a.table):
        return []
    actions = []
    for c in a.clauses:
        if c.kind == "drop_column":
            actions.append(f"drops column `{c.column}`")
        elif c.kind == "rename_column":
            actions.append(f"renames column `{c.column}` to `{c.new_column}`")
        elif c.kind == "change" and c.new_column and c.column != c.new_column:
            actions.append(f"renames column `{c.column}` to `{c.new_column}`")
        elif c.kind == "rename_table":
            actions.append(f"renames table `{a.table}`")
    return actions


def _check_l07(a: Analyzed, ctx: ScriptContext) -> list[Finding]:
    actions = _destructive_actions(a, ctx)
    if not actions:
        return []
    return [finding(
        "L07", Severity.BLOCK, a,
        "This statement " + ", ".join(actions) + ".",
        "Data is lost or renamed while the currently deployed application still reads the old "
        "name. Requests fail from the moment the statement runs until the new code ships, and "
        "a rollback of the code cannot bring the data back.",
        "Use expand and contract: ship code that no longer uses the column or table first, take "
        "a backup, then drop it in a later release. For a rename, add the new name, write to "
        "both, backfill, switch reads, and drop the old name last.",
    )]


L07 = Rule(
    id="L07",
    title="Dropping or renaming a column, table or database",
    severity=Severity.BLOCK,
    why=(
        "DROP, TRUNCATE and RENAME take effect immediately, while application servers still run "
        "the previous release. That code keeps querying the old name and fails. Dropped data "
        "cannot be restored by rolling back the deploy."
    ),
    safe_example=(
        "-- release 1: stop reading and writing users.legacy_flag in the application\n"
        "-- release 2, after a backup:\n"
        "ALTER TABLE users DROP COLUMN legacy_flag, ALGORITHM=INSTANT;"
    ),
    check=_check_l07,
)


# -- L08 -------------------------------------------------------------------

def _has_join(tree: exp.Expression) -> bool:
    if isinstance(tree, exp.Update):
        return bool(tree.this.args.get("joins")) or bool(tree.args.get("from_"))
    if isinstance(tree, exp.Delete):
        return bool(tree.args.get("tables")) or bool(tree.args.get("using"))
    return False


def _check_l08(a: Analyzed, ctx: ScriptContext) -> list[Finding]:
    tree = a.tree
    if a.kind not in ("update", "delete") or not isinstance(tree, (exp.Update, exp.Delete)):
        return []
    verb = a.kind.upper()
    if not tree.args.get("where") and not _has_join(tree):
        return [finding(
            "L08", Severity.BLOCK, a,
            f"{verb} has no WHERE clause and touches every row of the table.",
            "Every row is changed or deleted in one transaction: data loss, long row locks and "
            "replication lag.",
            "Add the WHERE clause you intended. If every row really must change, do it in "
            "batches by primary key range.",
        )]
    if tree.args.get("limit") and not tree.args.get("order"):
        return [finding(
            "L08", Severity.WARN, a,
            f"{verb} uses LIMIT without ORDER BY, so which rows it hits is not defined.",
            "Different runs and replicas can change different rows; statement-based replication "
            "flags it as unsafe.",
            "Add ORDER BY on the primary key, for example ORDER BY id LIMIT 1000.",
        )]
    return []


L08 = Rule(
    id="L08",
    title="UPDATE / DELETE without WHERE, or LIMIT without ORDER BY",
    severity=Severity.BLOCK,
    why=(
        "An UPDATE or DELETE without WHERE rewrites the whole table in a single transaction. A "
        "LIMIT without ORDER BY picks rows in an undefined order, so primary and replicas can "
        "diverge."
    ),
    safe_example="DELETE FROM sessions WHERE expires_at < NOW() ORDER BY id LIMIT 1000;",
    check=_check_l08,
)
