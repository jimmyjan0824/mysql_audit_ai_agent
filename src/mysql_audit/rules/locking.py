"""L04 and L05: metadata-lock waits and foreign keys."""

from __future__ import annotations

from ..analysis import Analyzed
from ..context import ScriptContext
from ..models import Finding, Severity
from .base import DDL_KINDS, Rule, finding

MAX_LOCK_WAIT = 60  # seconds; above this a queued DDL stalls traffic for too long


# -- L04 -------------------------------------------------------------------

def _check_l04(a: Analyzed, ctx: ScriptContext) -> list[Finding]:
    if a.kind not in DDL_KINDS or "L04" in ctx.reported:
        return []
    if a.tables and all(ctx.is_new(t) for t in a.tables):
        return []
    if ctx.lock_wait_timeout is not None and ctx.lock_wait_timeout <= MAX_LOCK_WAIT:
        return []
    ctx.reported.add("L04")
    if ctx.lock_wait_timeout is None:
        message = "DDL runs without SET lock_wait_timeout; the server default is one year."
    else:
        message = f"lock_wait_timeout is {ctx.lock_wait_timeout}s, above the {MAX_LOCK_WAIT}s this rule allows."
    return [finding(
        "L04", Severity.WARN, a, message,
        "If a long transaction holds the table, the DDL waits for its metadata lock, and every "
        "query on that table queues behind the DDL. The application stalls.",
        "Put SET SESSION lock_wait_timeout = 5; before the DDL and retry on timeout. Just before "
        "deploying, run the SQL from mysql-audit --preflight to find long transactions on the table.",
    )]


L04 = Rule(
    id="L04",
    title="DDL without a short lock_wait_timeout",
    severity=Severity.WARN,
    why=(
        "Every DDL needs an exclusive metadata lock, even an INSTANT one. While it waits behind a "
        "long-running transaction, all new queries on the table queue behind it, so a one-second "
        "change can take the whole application down. lock_wait_timeout defaults to 31536000 "
        "seconds (one year)."
    ),
    safe_example="SET SESSION lock_wait_timeout = 5;\nALTER TABLE orders ADD COLUMN note VARCHAR(100), ALGORITHM=INSTANT;",
    check=_check_l04,
)


# -- L05 -------------------------------------------------------------------

def _check_l05(a: Analyzed, ctx: ScriptContext) -> list[Finding]:
    if a.kind != "alter_table" or ctx.is_new(a.table):
        return []
    if not any(c.kind == "add_fk" for c in a.clauses):
        return []
    if ctx.fk_checks_off:
        return [finding(
            "L05", Severity.WARN, a,
            f"Foreign key on `{a.table}` is added with foreign_key_checks=0, so existing rows are not validated.",
            "The change can run INPLACE, but orphaned rows already in the table stay undetected.",
            "Before turning foreign_key_checks back on, check for orphans with a LEFT JOIN on the parent table.",
        )]
    return [finding(
        "L05", Severity.BLOCK, a,
        f"Adding a foreign key to `{a.table}` with foreign_key_checks=1 can only use ALGORITHM=COPY.",
        "MySQL copies the whole table and blocks writes while it validates every row.",
        "SET SESSION foreign_key_checks = 0; run the ALTER with ALGORITHM=INPLACE, LOCK=NONE; "
        "SET SESSION foreign_key_checks = 1; then check for orphaned rows with a LEFT JOIN.",
    )]


L05 = Rule(
    id="L05",
    title="Foreign key added with foreign_key_checks on",
    severity=Severity.BLOCK,
    why=(
        "MySQL supports adding a foreign key INPLACE only when foreign_key_checks is disabled. "
        "With checks on, the only algorithm is COPY: the table is rebuilt and writes are blocked "
        "while every existing row is validated."
    ),
    safe_example=(
        "SET SESSION foreign_key_checks = 0;\n"
        "ALTER TABLE orders ADD CONSTRAINT fk_orders_customer FOREIGN KEY (customer_id) "
        "REFERENCES customers (id), ALGORITHM=INPLACE, LOCK=NONE;\n"
        "SET SESSION foreign_key_checks = 1;"
    ),
    check=_check_l05,
)
