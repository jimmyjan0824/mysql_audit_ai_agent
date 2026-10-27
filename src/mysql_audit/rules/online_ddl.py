"""L01 and L02: will MySQL run this DDL online, or copy and lock the table?"""

from __future__ import annotations

from sqlglot import exp

from ..analysis import AlterClause, Analyzed
from ..context import CHARSET_MAXLEN, Column, ScriptContext
from ..models import Finding, Severity
from .base import Rule, finding

# Clauses that never touch table data, so the ALGORITHM clause adds nothing.
_METADATA_ONLY = {"option", "rename_table", "rename_index", "alter_column"}
_INSTANT_FRIENDLY = {"add_column", "drop_column", "option"}
# Clauses MySQL can always run at least INPLACE without blocking writes: left
# without ALGORITHM, MySQL still never picks COPY for them.
_ALWAYS_ONLINE = _METADATA_ONLY | {
    "add_column", "drop_column", "add_index", "drop_index", "drop_fk",
}
_BLOCKING_INDEX = {"FULLTEXT", "SPATIAL"}  # built INPLACE but with LOCK=SHARED
_INT_TYPES = {
    exp.DataType.Type.TINYINT, exp.DataType.Type.UTINYINT, exp.DataType.Type.SMALLINT,
    exp.DataType.Type.USMALLINT, exp.DataType.Type.MEDIUMINT, exp.DataType.Type.UMEDIUMINT,
    exp.DataType.Type.INT, exp.DataType.Type.UINT, exp.DataType.Type.BIGINT,
    exp.DataType.Type.UBIGINT,
}
_VAR_TYPES = {exp.DataType.Type.VARCHAR, exp.DataType.Type.VARBINARY}


# -- L01 -------------------------------------------------------------------

def _check_l01(a: Analyzed, ctx: ScriptContext) -> list[Finding]:
    if a.kind not in ("alter_table", "create_index", "drop_index") or ctx.is_new(a.table):
        return []
    kinds = {c.kind for c in a.clauses}
    if a.kind == "alter_table" and kinds <= _METADATA_ONLY:
        return []

    if a.algorithm == "COPY" or a.lock in ("SHARED", "EXCLUSIVE"):
        what = "ALGORITHM=COPY" if a.algorithm == "COPY" else f"LOCK={a.lock}"
        return [finding(
            "L01", Severity.BLOCK, a,
            f"{what} on `{a.table}` blocks writes for the whole run.",
            "Writes to the table wait until the copy finishes; on a large table that is minutes to hours.",
            "Use ALGORITHM=INPLACE, LOCK=NONE (or INSTANT where supported). If MySQL refuses, "
            "run the change with gh-ost or pt-online-schema-change instead.",
        )]

    if a.algorithm is None:
        if a.kind == "alter_table" and kinds <= _INSTANT_FRIENDLY:
            suggestion = "ALGORITHM=INSTANT (ADD COLUMN on 8.0.12+, DROP COLUMN on 8.0.29+)"
        else:
            suggestion = "ALGORITHM=INPLACE, LOCK=NONE"
        blocking_index = bool(_BLOCKING_INDEX & set(a.stmt.words))
        if not blocking_index and (a.kind in ("create_index", "drop_index") or kinds <= _ALWAYS_ONLINE):
            return [finding(
                "L01", Severity.INFO, a,
                f"No ALGORITHM is given for DDL on `{a.table}`; MySQL will pick an online algorithm here.",
                "None expected: these operations never fall back to COPY, though INPLACE may still rebuild the table.",
                f"Add {suggestion} anyway, so a reviewer sees the intended algorithm and MySQL errors out if it differs.",
            )]
        return [finding(
            "L01", Severity.WARN, a,
            f"No ALGORITHM is given for DDL on `{a.table}`, so MySQL may silently fall back to a table copy.",
            "If the operation cannot run online, MySQL picks COPY and blocks writes instead of failing.",
            f"Add {suggestion}. MySQL then errors out instead of locking, and you choose what to do.",
        )]

    if a.algorithm == "INPLACE" and a.lock is None:
        return [finding(
            "L01", Severity.INFO, a,
            f"ALGORITHM=INPLACE without LOCK on `{a.table}`: MySQL may still take a shared lock.",
            "Some in-place operations allow reads but block writes when LOCK is not stated.",
            "Add LOCK=NONE so the statement fails rather than blocking writes.",
        )]
    return []


L01 = Rule(
    id="L01",
    title="DDL without an explicit ALGORITHM / LOCK",
    severity=Severity.WARN,
    why=(
        "Without ALGORITHM and LOCK, MySQL chooses the cheapest algorithm it can. When an online "
        "change is not possible it falls back to COPY, which rebuilds the table and blocks writes, "
        "and nobody finds out until production stalls. Stating ALGORITHM=INSTANT or "
        "ALGORITHM=INPLACE, LOCK=NONE turns that silent fallback into an immediate error."
    ),
    safe_example="ALTER TABLE orders ADD INDEX idx_customer (customer_id), ALGORITHM=INPLACE, LOCK=NONE;",
    check=_check_l01,
)


# -- L02 -------------------------------------------------------------------

def _build_type(type_sql: str | None) -> exp.DataType | None:
    if not type_sql:
        return None
    try:
        return exp.DataType.build(type_sql, dialect="mysql")
    except Exception:
        return None


def _length(t: exp.DataType) -> int | None:
    if not t.expressions:
        return None
    try:
        return int(t.expressions[0].name)
    except (TypeError, ValueError):
        return None


def _members(t: exp.DataType) -> list[str]:
    return [e.name for e in t.expressions]


def _set_bytes(n: int) -> int:
    return {1: 1, 2: 2, 3: 3, 4: 4}.get((n + 7) // 8, 8)


def classify_type_change(old: Column, new: exp.DataType, old_cs: str, new_cs: str) -> tuple[str, str]:
    """Return ("online" | "copy", reason) for changing a column from old to new."""
    o = old.type
    if old_cs != new_cs and (o.this in _VAR_TYPES or new.this in _VAR_TYPES or o.is_type("text", "char")):
        return "copy", f"the character set changes from {old_cs} to {new_cs}"

    if o.this in _INT_TYPES and new.this in _INT_TYPES:
        if o.this == new.this:
            return "online", "same type"
        return "copy", f"{o.sql('mysql')} to {new.sql('mysql')} changes the stored data type"

    if o.this in _VAR_TYPES and new.this == o.this:
        ol, nl = _length(o), _length(new)
        if ol is None or nl is None:
            return "copy", "the column length could not be read"
        if nl < ol:
            return "copy", f"shrinking {o.sql('mysql')} to {new.sql('mysql')} rebuilds the table and may truncate data"
        mb = 1 if o.this == exp.DataType.Type.VARBINARY else CHARSET_MAXLEN.get(new_cs, 4)
        if (ol * mb <= 255) == (nl * mb <= 255):
            return "online", "VARCHAR grows within the same length-prefix size"
        return "copy", (
            f"{o.sql('mysql')} to {new.sql('mysql')} crosses the 255-byte length-prefix boundary "
            f"({ol * mb} to {nl * mb} bytes in {new_cs})"
        )

    if o.this == new.this and o.this in (exp.DataType.Type.ENUM, exp.DataType.Type.SET):
        om, nm = _members(o), _members(new)
        if nm[: len(om)] == om:
            if o.this == exp.DataType.Type.ENUM and (len(om) <= 255) == (len(nm) <= 255):
                return "online", "ENUM members appended at the end"
            if o.this == exp.DataType.Type.SET and _set_bytes(len(om)) == _set_bytes(len(nm)):
                return "online", "SET members appended at the end"
        return "copy", "members are reordered, removed, or the storage size changes"

    if o.sql("mysql").upper() == new.sql("mysql").upper():
        return "online", "same type"
    return "copy", f"{o.sql('mysql')} to {new.sql('mysql')} changes the stored data type"


def _clause_findings(a: Analyzed, ctx: ScriptContext, c: AlterClause) -> list[Finding]:
    new_type = _build_type(c.type_sql)
    if new_type is None:
        return []
    old = ctx.column(a.table, c.column)
    if old is None:
        return [finding(
            "L02", Severity.WARN, a,
            f"`{a.table}`.`{c.column}` is redefined as {c.type_sql}, but its current type is unknown.",
            "Changing a column's data type rebuilds the table with ALGORITHM=COPY and blocks writes.",
            "Pass the table's CREATE TABLE as schema so the change can be checked exactly, "
            "or run it with gh-ost / pt-online-schema-change.",
        )]
    new_cs = c.charset or ctx.charset_of(a.table, old)
    verdict, reason = classify_type_change(old, new_type, ctx.charset_of(a.table, old), new_cs)
    if verdict == "online":
        return []
    return [finding(
        "L02", Severity.BLOCK, a,
        f"Changing `{a.table}`.`{c.column}` needs a full table copy: {reason}.",
        "MySQL rebuilds the table with ALGORITHM=COPY; writes are blocked for the whole rebuild.",
        "Run the change with gh-ost or pt-online-schema-change, or add a new column, backfill it "
        "in batches and switch reads over (expand and contract).",
    )]


def _check_l02(a: Analyzed, ctx: ScriptContext) -> list[Finding]:
    if a.kind != "alter_table" or ctx.is_new(a.table):
        return []
    out: list[Finding] = []
    kinds = {c.kind for c in a.clauses}
    for c in a.clauses:
        if c.kind in ("modify", "change"):
            out.extend(_clause_findings(a, ctx, c))
        elif c.kind == "convert_charset":
            out.append(finding(
                "L02", Severity.BLOCK, a,
                f"CONVERT TO CHARACTER SET rebuilds `{a.table}` and rewrites every text column.",
                "MySQL copies the whole table and blocks writes until it finishes.",
                "Run the conversion with gh-ost or pt-online-schema-change during a quiet period.",
            ))
        elif c.kind == "drop_pk" and "add_pk" not in kinds:
            out.append(finding(
                "L02", Severity.BLOCK, a,
                f"Dropping the primary key of `{a.table}` without adding a new one needs ALGORITHM=COPY.",
                "MySQL copies the whole table and blocks writes until it finishes.",
                "Drop and add the primary key in the same ALTER TABLE, which can run INPLACE.",
            ))
    return out


L02 = Rule(
    id="L02",
    title="Column change that rebuilds the table",
    severity=Severity.BLOCK,
    why=(
        "Changing a column's data type (INT to BIGINT, shrinking a VARCHAR, VARCHAR growing past "
        "255 bytes, reordering ENUM members, converting the character set) can only run with "
        "ALGORITHM=COPY. MySQL rebuilds the table and blocks every write until it finishes. "
        "Growing a VARCHAR inside the same length-prefix size, or appending ENUM members, is online."
    ),
    safe_example=(
        "-- online: VARCHAR(50) to VARCHAR(60) in utf8mb4 stays under 255 bytes\n"
        "ALTER TABLE users MODIFY name VARCHAR(60) NOT NULL, ALGORITHM=INPLACE, LOCK=NONE;\n"
        "-- INT to BIGINT: use gh-ost or pt-online-schema-change\n"
        "gh-ost --alter=\"MODIFY id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT\" --table=orders ..."
    ),
    check=_check_l02,
)


# -- L03 -------------------------------------------------------------------

# Clauses MySQL 8.0 can apply without touching rows (INSTANT or metadata only).
_NO_ROW_WORK = _METADATA_ONLY | {"add_column", "drop_column"}


def _check_l03(a: Analyzed, ctx: ScriptContext) -> list[Finding]:
    if a.kind not in ("alter_table", "create_index") or ctx.is_new(a.table) or not ctx.is_large(a.table):
        return []
    if a.kind == "alter_table" and {c.kind for c in a.clauses} <= _NO_ROW_WORK:
        return []
    rows = ctx.size(a.table)
    return [finding(
        "L03", Severity.WARN, a,
        f"`{a.table}` has about {rows:,} rows; this DDL has to read or rebuild all of them.",
        "Even an online ALTER runs for a long time, holds undo, and replicas apply it only after "
        "the primary finishes, so they fall behind by the full duration.",
        "Run it with gh-ost or pt-online-schema-change, which copy in throttled chunks and pause "
        "when replicas lag.",
    )]


L03 = Rule(
    id="L03",
    title="Row-touching DDL on a large table",
    severity=Severity.WARN,
    why=(
        "ALGORITHM=INPLACE avoids blocking writes, but on a table with millions of rows the "
        "change still takes minutes to hours. A replica starts the same ALTER only after the "
        "primary commits it, so replication lag grows by the whole duration. Online schema "
        "change tools copy the table in small, throttled chunks instead."
    ),
    safe_example=(
        "gh-ost --database=shop --table=orders --alter=\"ADD INDEX idx_created (created_at)\" "
        "--max-lag-millis=1500 --execute"
    ),
    check=_check_l03,
)
