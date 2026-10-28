"""MCP server exposing the review engine to AI coding agents (stdio)."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from . import __version__
from .config import load_config, parse_gb
from .engine import review
from .preflight import preflight_sql, touched_tables
from .engine import review_code as _review_code
from .rules import RULES

server = MCPServer(
    name="mysql-audit",
    version=__version__,
    instructions=(
        "Call review_migration before running any MySQL DDL, migration file, or bulk "
        "UPDATE/DELETE, review_query for queries you add to application code, and review_code "
        "for code that builds SQL. If the verdict is 'block', do not run or commit it; rewrite "
        "it using each finding's fix and review again. If it is 'review', tell the user about "
        "the findings. For exact results pass the CREATE TABLE statements as schema, row "
        "counts from information_schema.tables as stats, and the server's version as "
        "mysql_version. A .mysql-audit.toml in the project supplies any of these you leave out. "
        "Before a migration on existing tables is deployed, give the user preflight_checks."
    ),
)


def _review(sql: str, schema: str | None, stats: dict | None, mysql_version: str | None,
            free_disk_gb: float | None = None, rollback_sql: str | None = None) -> dict:
    """Fill what the call leaves out from .mysql-audit.toml / MYSQL_AUDIT_VERSION, then review."""
    try:
        cfg = load_config()
        report = review(sql, schema=schema or cfg.schema, stats=stats or cfg.stats,
                        mysql_version=mysql_version or cfg.mysql_version,
                        free_disk_gb=parse_gb(free_disk_gb) if free_disk_gb is not None else cfg.free_disk_gb,
                        has_rollback=bool(rollback_sql and rollback_sql.strip()))
    except (OSError, ValueError) as e:
        return {"error": str(e)}
    if cfg.path and not (schema and stats and mysql_version):
        report.notes.append(f"Settings not passed in the call were read from {cfg.path}.")
    return report.to_dict()


@server.tool()
def review_migration(
    sql: str,
    schema: str | None = None,
    stats: dict | None = None,
    mysql_version: str | None = None,
    free_disk_gb: float | None = None,
    rollback_sql: str | None = None,
) -> dict:
    """Review MySQL DDL or a migration script for locking, data-loss and replication risks.

    Args:
        sql: The SQL to run, one or more statements separated by semicolons.
        schema: Optional CREATE TABLE statements for the tables involved (e.g. from
            SHOW CREATE TABLE). Makes column-type and index checks exact.
        stats: Optional size per table from information_schema.tables: a row count
            ({"orders": 25000000}) or {"orders": {"rows": 25000000, "data_bytes":
            <data_length>, "index_bytes": <index_length>}}. Large = 1M rows or 5 GB.
        mysql_version: Optional target server version, e.g. "8.0.28", "8.4.3" or
            "aurora-3.04" (SELECT VERSION()). Older servers copy the table for more
            column changes. Without it, 8.0.29 or later is assumed.
        free_disk_gb: Optional free space on the server's data volume, in GB. With
            byte sizes in stats, a table rebuild that does not fit is blocked.
        rollback_sql: Optional down migration kept in a separate file (e.g. a
            golang-migrate .down.sql or Flyway U__ file). Down sections and
            --rollback lines inside sql are found without it.

    Returns a verdict (safe / review / block) and findings with line, impact and fix.
    """
    return _review(sql, schema, stats, mysql_version, free_disk_gb, rollback_sql)


@server.tool()
def review_query(
    sql: str, schema: str | None = None, stats: dict | None = None, mysql_version: str | None = None
) -> dict:
    """Review queries an application will run (SELECT / UPDATE / DELETE / INSERT) for missing
    indexes, unbatched writes and unsafe UPDATE/DELETE. Pass schema for index checks.

    Returns a verdict (safe / review / block) and findings with line, impact and fix.
    """
    return _review(sql, schema, stats, mysql_version)


@server.tool()
def review_code(code: str) -> dict:
    """Check application source code (Python, JS/TS, PHP, Go, Java) for SQL built by string
    interpolation or concatenation, i.e. SQL injection.

    Returns a verdict (safe / block) and findings with line and the parameterized fix.
    """
    return _review_code(code).to_dict()


@server.tool()
def preflight_checks(sql: str, mysql_version: str | None = None) -> dict:
    """SQL for the user (or DBA) to run on the primary right before deploying a migration:
    long transactions, long queries and metadata locks on the tables it touches, current
    table sizes, and how to check replica lag. Each query returns rows only when the deploy
    should wait. This tool does not connect to the database; hand the SQL to the user.

    Args:
        sql: The migration that is about to run.
        mysql_version: Optional server version, e.g. "5.7.44"; picks SHOW SLAVE / REPLICA STATUS.
    """
    try:
        version = mysql_version or load_config().mysql_version
        return {"tables": touched_tables(sql), "sql": preflight_sql(sql, version),
                "how_to_read": "Run on the primary in the target database. No rows from every "
                               "query, and replica lag of 10 s or less, means go."}
    except (OSError, ValueError) as e:
        return {"error": str(e)}


@server.tool()
def explain_rule(rule_id: str) -> dict:
    """Explain one rule (e.g. "L02"): why it matters and a safe example."""
    rule = RULES.get(rule_id.upper())
    if rule is None:
        return {"error": f"Unknown rule {rule_id}", "known_rules": sorted(RULES)}
    return rule.explain()


@server.tool()
def list_rules() -> list[dict]:
    """List every rule this server checks, with its id, title and default severity."""
    return [{"rule_id": r.id, "title": r.title, "default_severity": r.severity.value} for r in RULES.values()]


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
