"""L14 and L15: keys and table definitions that cause trouble later."""

from __future__ import annotations

from ..analysis import Analyzed
from ..context import ScriptContext
from ..models import Finding, Severity
from .base import Rule, finding


# -- L14 -------------------------------------------------------------------

def _unique_targets(a: Analyzed) -> list[str]:
    if a.kind == "create_index" and "UNIQUE" in a.stmt.words[:3]:
        return ["a unique index"]
    if a.kind != "alter_table":
        return []
    out = []
    for c in a.clauses:
        if c.kind == "add_pk":
            out.append("a primary key")
        elif c.kind == "add_index" and "UNIQUE" in c.words:
            out.append("a unique index")
    return out


def _check_l14(a: Analyzed, ctx: ScriptContext) -> list[Finding]:
    if ctx.is_new(a.table):
        return []
    targets = _unique_targets(a)
    if not targets:
        return []
    return [finding(
        "L14", Severity.WARN, a,
        f"Adding {' and '.join(dict.fromkeys(targets))} to `{a.table}`: existing rows must already be unique.",
        "If any duplicates exist, ALTER TABLE fails with error 1062 after doing most of the work. "
        "Run through gh-ost or pt-online-schema-change, the copy uses INSERT IGNORE and silently "
        "drops the duplicate rows instead.",
        "First check with SELECT col, COUNT(*) FROM t GROUP BY col HAVING COUNT(*) > 1, clean up "
        "what it finds, and make the application stop writing duplicates before adding the key.",
    )]


L14 = Rule(
    id="L14",
    title="Unique index or primary key added to an existing table",
    severity=Severity.WARN,
    why=(
        "A unique key can only be added when the existing rows are already unique. With "
        "duplicates, a direct ALTER TABLE fails late, after reading the whole table. gh-ost and "
        "pt-online-schema-change copy rows with INSERT IGNORE, so they succeed and quietly "
        "throw the duplicates away."
    ),
    safe_example=(
        "SELECT email, COUNT(*) FROM users GROUP BY email HAVING COUNT(*) > 1;  -- must be empty\n"
        "ALTER TABLE users ADD UNIQUE INDEX uq_email (email), ALGORITHM=INPLACE, LOCK=NONE;"
    ),
    check=_check_l14,
)


# -- L15 -------------------------------------------------------------------

def _engine(words: list[str]) -> str | None:
    for i, word in enumerate(words):
        if word == "ENGINE" and i + 1 < len(words):
            j = i + 2 if words[i + 1] == "=" else i + 1
            return words[j] if j < len(words) else None
    return None


def _check_l15(a: Analyzed, ctx: ScriptContext) -> list[Finding]:
    w = a.stmt.words
    if a.kind != "create_table" or a.temporary or "LIKE" in w[:8]:
        return []
    out = []
    if "PRIMARY" not in w:
        out.append(finding(
            "L15", Severity.WARN, a,
            f"Table `{a.table}` is created without a primary key.",
            "With row-based replication, each UPDATE or DELETE on the replica may scan the whole "
            "table, so replicas fall behind. gh-ost cannot change the table later, and some "
            "managed services and clusters refuse such tables (sql_require_primary_key).",
            "Add a primary key, for example id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY.",
        ))
    engine = _engine(w)
    if engine and engine != "INNODB":
        out.append(finding(
            "L15", Severity.WARN, a,
            f"Table `{a.table}` uses the {engine} engine instead of InnoDB.",
            "No transactions or crash recovery for MyISAM-style engines, table-level locks on "
            "every write, and no online DDL.",
            "Use ENGINE=InnoDB (the default), or leave the ENGINE clause out.",
        ))
    return out


L15 = Rule(
    id="L15",
    title="New table without a primary key or not InnoDB",
    severity=Severity.WARN,
    why=(
        "InnoDB stores rows in primary key order. Without an explicit key, row-based "
        "replication has no cheap way to find a row, replicas lag, and online schema change "
        "tools cannot work on the table. Engines other than InnoDB lose transactions, crash "
        "safety and online DDL."
    ),
    safe_example=(
        "CREATE TABLE events (\n  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,\n"
        "  name VARCHAR(100) NOT NULL\n) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;"
    ),
    check=_check_l15,
)
