"""Read WHERE / JOIN conditions: which columns of which tables are filtered."""

from __future__ import annotations

from sqlglot import exp

from ..context import ScriptContext

_EQ = (exp.EQ, exp.NullSafeEQ, exp.In)
_RANGE = (exp.GT, exp.GTE, exp.LT, exp.LTE, exp.Between)


def tables_of(tree: exp.Expression) -> dict[str, str]:
    """alias (or name) -> table name, for every table the statement reads or writes."""
    out: dict[str, str] = {}
    for t in tree.find_all(exp.Table):
        name = t.name.lower()
        if not name:
            continue
        out[(t.alias or name).lower()] = name
        out.setdefault(name, name)
    return out


def filtered_columns(cond: exp.Expression | None) -> list[tuple[exp.Column, str]]:
    """Columns compared directly (not inside a function) in a condition.

    Returns (column, "eq" | "range") pairs. A column wrapped in a function,
    e.g. DATE(created_at) = ..., cannot use an index and is left out.
    """
    if cond is None:
        return []
    out: list[tuple[exp.Column, str]] = []
    for node in cond.find_all(*_EQ, *_RANGE, exp.Like):
        kind = "eq" if isinstance(node, _EQ) else "range"
        if isinstance(node, exp.Like):
            pattern = node.expression
            if not (isinstance(pattern, exp.Literal) and pattern.is_string and not pattern.this.startswith("%")):
                continue
        for side in (node.this, node.args.get("expression")):
            if isinstance(side, exp.Column):
                out.append((side, kind))
    return out


def resolve(col: exp.Column, aliases: dict[str, str], ctx: ScriptContext) -> str | None:
    """The table a column belongs to, or None when it cannot be told."""
    if col.table:
        return aliases.get(col.table.lower())
    tables = set(aliases.values())
    if len(tables) == 1:
        return next(iter(tables))
    owners = [t for t in tables if col.name.lower() in ctx.columns.get(t, {})]
    return owners[0] if len(owners) == 1 else None


def key_targeted(tree: exp.Expression, table: str, ctx: ScriptContext) -> bool:
    """Does the WHERE clause pin the statement to a few rows of `table`?

    True when it compares the first primary-key / unique-key column, or a
    range on it (the usual batching pattern WHERE id BETWEEN ...). Without a
    schema, a column named `id` is taken as the primary key.
    """
    aliases = tables_of(tree)
    filtered = {
        c.name.lower()
        for c, _ in filtered_columns(tree.args.get("where"))
        if resolve(c, aliases, ctx) == table
    }
    keys = ctx.uniques.get(table) if ctx.knows(table) else [["id"]]
    return any(k and k[0] in filtered for k in keys or [])
