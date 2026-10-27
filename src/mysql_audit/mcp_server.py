"""MCP server exposing the review engine to AI coding agents (stdio)."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from . import __version__
from .engine import review
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
        "the findings. For exact results pass the CREATE TABLE statements as schema and row "
        "counts from information_schema.tables as stats."
    ),
)


@server.tool()
def review_migration(sql: str, schema: str | None = None, stats: dict[str, int] | None = None) -> dict:
    """Review MySQL DDL or a migration script for locking, data-loss and replication risks.

    Args:
        sql: The SQL to run, one or more statements separated by semicolons.
        schema: Optional CREATE TABLE statements for the tables involved (e.g. from
            SHOW CREATE TABLE). Makes column-type and index checks exact.
        stats: Optional approximate row count per table, e.g. {"orders": 25000000}, from
            SELECT table_name, table_rows FROM information_schema.tables.

    Returns a verdict (safe / review / block) and findings with line, impact and fix.
    """
    return review(sql, schema=schema, stats=stats).to_dict()


@server.tool()
def review_query(sql: str, schema: str | None = None, stats: dict[str, int] | None = None) -> dict:
    """Review queries an application will run (SELECT / UPDATE / DELETE / INSERT) for missing
    indexes, unbatched writes and unsafe UPDATE/DELETE. Pass schema for index checks.

    Returns a verdict (safe / review / block) and findings with line, impact and fix.
    """
    return review(sql, schema=schema, stats=stats).to_dict()


@server.tool()
def review_code(code: str) -> dict:
    """Check application source code (Python, JS/TS, PHP, Go, Java) for SQL built by string
    interpolation or concatenation, i.e. SQL injection.

    Returns a verdict (safe / block) and findings with line and the parameterized fix.
    """
    return _review_code(code).to_dict()


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
