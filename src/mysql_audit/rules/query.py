"""L11: filters and joins on columns without an index."""

from __future__ import annotations

from sqlglot import exp

from ..analysis import Analyzed
from ..context import ScriptContext
from ..models import Finding, Severity
from .base import Rule, finding
from .predicates import filtered_columns, resolve, tables_of


def _conditions(tree: exp.Expression) -> list[tuple[exp.Expression, bool]]:
    """(condition, is_join) for every WHERE and JOIN ... ON in the statement."""
    out = [(w.this, False) for w in tree.find_all(exp.Where)]
    out += [(j.args["on"], True) for j in tree.find_all(exp.Join) if j.args.get("on")]
    return out


def _check_l11(a: Analyzed, ctx: ScriptContext) -> list[Finding]:
    tree = a.tree
    if a.kind not in ("select", "update", "delete", "insert") or tree is None:
        return []
    aliases = tables_of(tree)
    unindexed: dict[str, set[str]] = {}
    for cond, is_join in _conditions(tree):
        per_table: dict[str, set[str]] = {}
        for col, _ in filtered_columns(cond):
            table = resolve(col, aliases, ctx)
            if table:
                per_table.setdefault(table, set()).add(col.name.lower())
        for table, cols in per_table.items():
            if not ctx.knows(table) or ctx.is_small(table):
                continue
            if any(idx and idx[0] in cols for idx in ctx.indexes.get(table, [])):
                continue
            if is_join and len(per_table) > 1 and _other_side_indexed(per_table, table, ctx):
                continue  # MySQL can drive the join from this table and look up the other
            unindexed.setdefault(table, set()).update(cols)
    return [
        finding(
            "L11", Severity.WARN, a,
            f"`{table}` is filtered on {', '.join(sorted(cols))}, and no index starts with "
            f"{'that column' if len(cols) == 1 else 'any of them'}.",
            "MySQL reads every row of the table for each execution; fine in development, slow "
            "and lock-heavy once the table grows.",
            f"Add an index, for example ALTER TABLE {table} ADD INDEX idx_{sorted(cols)[0]} "
            f"({sorted(cols)[0]}), ALGORITHM=INPLACE, LOCK=NONE;",
        )
        for table, cols in unindexed.items()
    ]


def _other_side_indexed(per_table: dict[str, set[str]], table: str, ctx: ScriptContext) -> bool:
    for other, cols in per_table.items():
        if other != table and any(idx and idx[0] in cols for idx in ctx.indexes.get(other, [])):
            return True
    return False


L11 = Rule(
    id="L11",
    title="WHERE / JOIN on a column without an index",
    severity=Severity.WARN,
    why=(
        "A filter or join on a column that is not the leftmost column of any index makes "
        "MySQL scan the whole table. Agents write such queries constantly because test data is "
        "tiny. Needs the schema; skipped for tables known to be small. A column wrapped in a "
        "function (DATE(created_at) = ...) cannot use an index either and is not counted."
    ),
    safe_example="ALTER TABLE orders ADD INDEX idx_customer (customer_id), ALGORITHM=INPLACE, LOCK=NONE;",
    check=_check_l11,
)
