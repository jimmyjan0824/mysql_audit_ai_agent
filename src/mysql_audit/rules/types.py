"""L10: column types that fail later (auto-increment overflow, 3-byte utf8)."""

from __future__ import annotations

from sqlglot import exp

from ..analysis import Analyzed
from ..context import ScriptContext
from ..models import Finding, Severity
from .base import Rule, finding

# Auto-increment limits for types smaller than BIGINT.
_LIMITS = {
    exp.DataType.Type.TINYINT: "127", exp.DataType.Type.UTINYINT: "255",
    exp.DataType.Type.SMALLINT: "32,767", exp.DataType.Type.USMALLINT: "65,535",
    exp.DataType.Type.MEDIUMINT: "8,388,607", exp.DataType.Type.UMEDIUMINT: "16,777,215",
    exp.DataType.Type.INT: "2,147,483,647", exp.DataType.Type.UINT: "4,294,967,295",
}
_UTF8_3BYTE = {"utf8", "utf8mb3"}


def _auto_increment_columns(a: Analyzed) -> list[tuple[str, exp.DataType]]:
    out = []
    if a.kind == "create_table" and isinstance(a.tree, exp.Create) and isinstance(a.tree.this, exp.Schema):
        for col in a.tree.this.expressions:
            if isinstance(col, exp.ColumnDef) and isinstance(col.kind, exp.DataType) and any(
                isinstance(c.kind, exp.AutoIncrementColumnConstraint) for c in col.constraints
            ):
                out.append((col.name.lower(), col.kind))
    elif a.kind == "alter_table":
        for c in a.clauses:
            if c.kind in ("add_column", "modify", "change") and "AUTO_INCREMENT" in c.words and c.type_sql:
                try:
                    out.append((c.new_column or c.column or "?", exp.DataType.build(c.type_sql, dialect="mysql")))
                except Exception:
                    pass
    return out


def _uses_utf8mb3(words: list[str]) -> bool:
    for i, word in enumerate(words):
        value = None
        if word in ("CHARSET", "COLLATE") and i + 1 < len(words):
            value = words[i + 2] if words[i + 1] == "=" and i + 2 < len(words) else words[i + 1]
        elif word == "SET" and i > 0 and words[i - 1] == "CHARACTER" and i + 1 < len(words):
            value = words[i + 2] if words[i + 1] == "=" and i + 2 < len(words) else words[i + 1]
        if value and value.lower().split("_")[0] in _UTF8_3BYTE:
            return True
    return False


def _check_l10(a: Analyzed, ctx: ScriptContext) -> list[Finding]:
    if a.kind not in ("create_table", "alter_table"):
        return []
    out = []
    for name, dtype in _auto_increment_columns(a):
        if dtype.this in _LIMITS:
            out.append(finding(
                "L10", Severity.WARN, a,
                f"Auto-increment column `{name}` is {dtype.sql('mysql')}, which runs out at {_LIMITS[dtype.this]}.",
                "When the counter reaches the limit every INSERT fails with a duplicate-key error, "
                "and widening the column later needs a full table copy on a big table.",
                "Use BIGINT UNSIGNED for auto-increment keys from the start.",
            ))
    if _uses_utf8mb3(a.stmt.words):
        out.append(finding(
            "L10", Severity.WARN, a,
            "utf8 / utf8mb3 stores at most 3 bytes per character.",
            "Emoji and some CJK characters fail to insert or are cut off; utf8mb3 is deprecated "
            "and converting the table later needs a full copy.",
            "Use CHARACTER SET utf8mb4 (MySQL 8.0 default) with an utf8mb4 collation.",
        ))
    return out


L10 = Rule(
    id="L10",
    title="Type that fails later: INT auto-increment, utf8mb3",
    severity=Severity.WARN,
    why=(
        "A signed INT auto-increment key stops at 2,147,483,647; busy tables reach it and every "
        "INSERT then fails. utf8 in MySQL means utf8mb3, which cannot store 4-byte characters "
        "such as emoji. Both are cheap to get right in CREATE TABLE and expensive to fix on a "
        "large table later."
    ),
    safe_example=(
        "CREATE TABLE events (\n  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,\n"
        "  title VARCHAR(200) NOT NULL\n) DEFAULT CHARSET=utf8mb4;"
    ),
    check=_check_l10,
)
