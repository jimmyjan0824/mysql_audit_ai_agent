"""MCP server exposing the review engine to AI coding agents (stdio)."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from . import __version__
from .engine import review
from .rules import RULES

server = MCPServer(
    name="mysql-audit",
    version=__version__,
    instructions=(
        "Call review_migration before running any MySQL DDL, migration file, or bulk "
        "UPDATE/DELETE. If the verdict is 'block', do not run the SQL; rewrite it using each "
        "finding's fix and review again. If it is 'review', tell the user about the findings."
    ),
)


@server.tool()
def review_migration(sql: str, schema: str | None = None) -> dict:
    """Review MySQL DDL or a migration script for locking, data-loss and replication risks.

    Args:
        sql: The SQL to run, one or more statements separated by semicolons.
        schema: Optional CREATE TABLE statements for the tables involved (e.g. from
            SHOW CREATE TABLE). Makes column-type checks exact.

    Returns a verdict (safe / review / block) and findings with line, impact and fix.
    """
    return review(sql, schema=schema).to_dict()


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
