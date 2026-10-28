"""L07 and L08: statements that lose data or break running code."""

from __future__ import annotations

from sqlglot import exp

from ..analysis import Analyzed
from ..context import LARGE_TABLE_ROWS, ScriptContext
from ..models import Finding, Severity
from .base import Rule, finding
from .predicates import key_targeted


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
        # A swap (RENAME TABLE t TO t_old, t_new TO t) keeps every name the
        # application uses; only names that disappear are a problem.
        targets = {new for _, new in a.renames}
        return [f"renames table `{old}` to `{new}`" for old, new in a.renames
                if old not in targets and not ctx.is_new(old)]
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


def _check_partitions(a: Analyzed, ctx: ScriptContext) -> list[Finding]:
    if a.kind != "alter_table" or ctx.is_new(a.table):
        return []
    out = []
    for i, c in enumerate(a.clauses):
        if c.kind not in ("drop_partition", "truncate_partition"):
            continue
        # DROP PARTITION p1, p2 is split at the comma: the later names arrive as bare clauses.
        names = [t.text for t in c.tokens[2:]]
        for rest in a.clauses[i + 1:]:
            if rest.kind != "other" or len(rest.tokens) != 1:
                break
            names.append(rest.tokens[0].text)
        verb = "drops" if c.kind == "drop_partition" else "empties"
        plural = "partitions" if len(names) > 1 else "partition"
        listed = ", ".join(f"`{n}`" for n in names)
        out.append(finding(
            "L07", Severity.BLOCK, a,
            f"This statement {verb} {plural} {listed} of `{a.table}` and deletes every row in {'them' if len(names) > 1 else 'it'}.",
            "The rows are gone at once, with no WHERE clause to check and no undo. Partition "
            "names say nothing about what is inside, so a wrong name deletes live data.",
            "Check the partition's boundaries and row count first (information_schema.partitions), "
            "then move it out with ALTER TABLE ... EXCHANGE PARTITION into an archive table and "
            "keep that table until the data is confirmed unneeded.",
        ))
    return out


def _check_l07(a: Analyzed, ctx: ScriptContext) -> list[Finding]:
    partitions = _check_partitions(a, ctx)
    if partitions:
        return partitions
    actions = _destructive_actions(a, ctx)
    if not actions:
        return []
    if a.kind == "drop_table" and all(t in ctx.recreated for t in a.tables):
        return [finding(
            "L07", Severity.WARN, a,
            "Drop-and-recreate of " + ", ".join(f"`{t}`" for t in a.tables) + ": this looks like an install or reset script.",
            "Fine on an empty database. Run against a database that has data, it deletes all of it.",
            "Keep install scripts separate from migrations, and never point them at production.",
        )]
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
    title="Dropping or renaming a column, table, partition or database",
    severity=Severity.BLOCK,
    why=(
        "DROP, TRUNCATE and RENAME take effect immediately, while application servers still run "
        "the previous release. That code keeps querying the old name and fails. Dropped data "
        "cannot be restored by rolling back the deploy. DROP PARTITION and TRUNCATE PARTITION "
        "delete every row in the partition at once."
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


# -- L06 and L09 -----------------------------------------------------------

def _write_target(a: Analyzed) -> str | None:
    tree = a.tree
    if isinstance(tree, (exp.Update, exp.Delete)) and isinstance(tree.this, exp.Table):
        return tree.this.name.lower()
    if isinstance(tree, exp.Insert):
        table = tree.this.find(exp.Table) if tree.this else None
        return table.name.lower() if table else None
    return None


def _bulk_write(a: Analyzed, ctx: ScriptContext) -> tuple[str, int | None] | None:
    """(table, rows) when a write may touch many rows in one transaction."""
    tree = a.tree
    if a.kind in ("update", "delete") and isinstance(tree, (exp.Update, exp.Delete)):
        table = _write_target(a)
        if not table or not tree.args.get("where") or tree.args.get("limit"):
            return None  # no WHERE is L08's case; LIMIT means the write is batched
        if key_targeted(tree, table, ctx):
            return None
        return table, ctx.size(table)
    if a.kind == "insert" and isinstance(tree, exp.Insert) and isinstance(tree.expression, exp.Select):
        select = tree.expression
        if select.args.get("limit"):
            return None
        sources = [t.name.lower() for t in select.find_all(exp.Table)]
        sizes = [ctx.size(t) for t in sources if ctx.size(t) is not None]
        return (sources[0] if sources else "?"), (max(sizes) if sizes else None)
    return None


def _check_l06(a: Analyzed, ctx: ScriptContext) -> list[Finding]:
    bulk = _bulk_write(a, ctx)
    if not bulk or bulk[1] is None or bulk[1] < LARGE_TABLE_ROWS:
        return []
    table, rows = bulk
    return [finding(
        "L06", Severity.WARN, a,
        f"This write can touch a large part of `{table}` (about {rows:,} rows) in one transaction.",
        "One huge transaction holds row locks until it commits, builds a large undo log, and "
        "reaches replicas as one event, so they lag while applying it.",
        "Loop over primary-key ranges (WHERE id BETWEEN x AND x+999) or use LIMIT 1000 with "
        "ORDER BY id, commit each batch, and pause when replicas lag.",
    )]


def _check_l09(a: Analyzed, ctx: ScriptContext) -> list[Finding]:
    bulk = _bulk_write(a, ctx)
    if not bulk or bulk[1] is not None:
        return []  # known size: L06 handles large tables, small ones are fine
    table, _ = bulk
    severity = Severity.WARN if ctx.knows(table) else Severity.INFO
    return [finding(
        "L09", severity, a,
        f"This write on `{table}` is not limited to a key range or batch size.",
        "If the table is large, every matching row is changed in one transaction: long row "
        "locks and replication lag.",
        "Batch it by primary-key range or LIMIT with ORDER BY id. Pass table row counts as "
        "stats to get an exact verdict.",
    )]


L06 = Rule(
    id="L06",
    title="Large write in a single transaction (replication lag)",
    severity=Severity.WARN,
    why=(
        "A replica applies a transaction only after the primary commits it, as one unit. An "
        "UPDATE, DELETE or INSERT ... SELECT over millions of rows therefore stalls replicas, "
        "holds row locks for its whole run and builds a large undo log."
    ),
    safe_example=(
        "-- repeat until 0 rows affected\n"
        "UPDATE orders SET archived = 1 WHERE created_at < '2024-01-01' AND archived = 0 "
        "ORDER BY id LIMIT 1000;"
    ),
    check=_check_l06,
)

L09 = Rule(
    id="L09",
    title="Backfill that is not batched",
    severity=Severity.WARN,
    why=(
        "Backfills written as one UPDATE look harmless in development, where tables are small. "
        "In production the same statement can touch millions of rows at once. Without row "
        "counts this rule cannot tell, so it asks for a batched form or for stats."
    ),
    safe_example="UPDATE users SET plan = 'free' WHERE id BETWEEN 1 AND 1000 AND plan IS NULL;",
    check=_check_l09,
)
