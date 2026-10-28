"""Pre-deploy checks: SQL for the DBA to run on the primary right before a migration.

The review itself never connects to the database. What only the live server
knows (open transactions, metadata locks, replica lag) is checked by this
script instead, scoped to the tables the migration touches. Every query
returns rows only when something should stop the deploy.
"""

from __future__ import annotations

from .analysis import analyze
from .context import LARGE_TABLE_BYTES, LARGE_TABLE_ROWS
from .splitter import split_statements
from .rules.data_safety import _write_target
from .version import Version, parse_version

LONG_TRX_SECONDS = 10   # a transaction or query older than this holds up DDL
REPLICA_LAG_SECONDS = 10  # do not start, or pause batches, above this lag

_TOUCHES = {"alter_table", "create_index", "drop_index", "drop_table", "rename_table",
            "truncate", "update", "delete", "insert"}


def touched_tables(sql: str) -> list[str]:
    """Existing tables the script changes, in order of first use."""
    created: set[str] = set()
    seen: list[str] = []
    for stmt in split_statements(sql):
        a = analyze(stmt)
        if a.kind == "create_table" and a.table:
            created.add(a.table)
            continue
        if a.kind not in _TOUCHES:
            continue
        names = list(a.tables)
        if a.tree is not None and a.kind in ("update", "delete", "insert"):
            target = _write_target(a)
            names = [target] if target else []
        for name in names:
            if name not in created and name not in seen:
                seen.append(name)
    return seen


def _quote(name: str) -> str:
    return "'" + name.replace("\\", "\\\\").replace("'", "''") + "'"


def preflight_sql(sql: str, mysql_version: str | None = None) -> str:
    tables = touched_tables(sql)
    version = parse_version(mysql_version) if mysql_version else None
    in_list = ", ".join(_quote(t) for t in tables)
    t, lag = LONG_TRX_SECONDS, REPLICA_LAG_SECONDS
    out = [
        "-- MySQL Audit preflight: run on the PRIMARY, in the target database, right before",
        "-- the migration (mysql your_db < preflight.sql). A query that returns rows means: stop",
        "-- and look first. No rows from every query means go.",
        f"-- Thresholds: transactions and queries older than {t} s, replica lag over {lag} s.",
        f"-- Tables the migration touches: {', '.join(tables) if tables else '(none that already exist)'}",
        "",
        f"-- 1. Transactions open for more than {t} s. DDL waits for their metadata locks, and",
        "--    every query on the table queues behind the waiting DDL.",
        "SELECT t.trx_mysql_thread_id AS thread_id,",
        "       TIMESTAMPDIFF(SECOND, t.trx_started, NOW()) AS seconds,",
        "       t.trx_state, LEFT(t.trx_query, 200) AS query",
        "FROM information_schema.innodb_trx t",
        f"WHERE t.trx_started < NOW() - INTERVAL {t} SECOND",
        "ORDER BY t.trx_started;",
    ]
    if tables:
        likes = " OR ".join(f"info LIKE {_quote('%' + name + '%')}" for name in tables)
        mdl_note = (
            ["--    MySQL 5.7 records these only with the MDL instrument on:",
             "--    UPDATE performance_schema.setup_instruments SET ENABLED = 'YES', TIMED = 'YES'",
             "--    WHERE NAME = 'wait/lock/metadata/sql/mdl';"]
            if version is None or version < Version(8, 0, 0) else []
        )
        out += [
            "",
            f"-- 2. Statements running for {t} s or more that mention a touched table.",
            "SELECT id AS thread_id, user, time AS seconds, state, LEFT(info, 200) AS query",
            "FROM information_schema.processlist",
            "WHERE command NOT IN ('Sleep', 'Daemon', 'Binlog Dump', 'Binlog Dump GTID')",
            f"  AND time >= {t} AND id <> CONNECTION_ID()",
            f"  AND ({likes});",
            "",
            f"-- 3. Sessions that have held a metadata lock on a touched table for {t} s or more,",
            "--    or are already waiting for one.",
            *mdl_note,
            "SELECT ml.object_name AS table_name, ml.lock_type, ml.lock_status,",
            "       th.processlist_id AS thread_id, th.processlist_time AS seconds,",
            "       LEFT(th.processlist_info, 200) AS query",
            "FROM performance_schema.metadata_locks ml",
            "JOIN performance_schema.threads th ON th.thread_id = ml.owner_thread_id",
            "WHERE ml.object_type = 'TABLE' AND ml.object_schema = DATABASE()",
            f"  AND ml.object_name IN ({in_list})",
            "  AND th.processlist_id <> CONNECTION_ID()",
            f"  AND (th.processlist_time >= {t} OR ml.lock_status = 'PENDING');",
            "",
            "-- 4. Touched tables that are large right now (1,000,000 rows or 5 GB): use gh-ost or",
            "--    pt-online-schema-change, and check free disk against the size for a rebuild.",
            "SELECT table_name, table_rows,",
            "       ROUND((data_length + index_length) / POW(1024, 3), 1) AS gb",
            "FROM information_schema.tables",
            f"WHERE table_schema = DATABASE() AND table_name IN ({in_list})",
            f"  AND (table_rows >= {LARGE_TABLE_ROWS} OR data_length + index_length >= {LARGE_TABLE_BYTES});",
        ]
    status = "SHOW SLAVE STATUS" if version is not None and version < Version(8, 0, 22) else "SHOW REPLICA STATUS"
    field = "Seconds_Behind_Master" if version is not None and version < Version(8, 0, 22) else "Seconds_Behind_Source"
    out += [
        "",
        f"-- 5. Replica lag. On EACH replica run: {status}\\G",
        f"--    Go only if {field} is {lag} or less (NULL means replication is stopped: do",
        f"--    not go). Aurora: the AuroraReplicaLag metric, {lag * 1000} ms or less.",
        f"--    For batched writes, pause between batches whenever lag goes over {lag} s.",
        "",
    ]
    return "\n".join(out)
