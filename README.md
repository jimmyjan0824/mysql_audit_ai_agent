# mysql_audit_ai_agent

<!-- mcp-name: io.github.jimmyjan0824/mysql-audit -->

MySQL schema-change safety review for AI coding agents.

Before Claude Code, Cursor or another agent runs a migration, it sends the SQL to
`review_migration` and gets back a verdict (`safe` / `review` / `block`) plus, for
every risk, the line, what will happen in production, and a safe way to write it.
The checks are deterministic rules written from DBA experience, not another LLM guess.

> Status: early development (v0.1). All twelve planned rules are in.

## Rules

| ID  | Checks | Default | Needs |
| --- | --- | --- | --- |
| L01 | DDL without explicit `ALGORITHM` / `LOCK`; `ALGORITHM=COPY`, `LOCK=SHARED/EXCLUSIVE` | warn / block | |
| L02 | Column changes that force a table copy: type change, VARCHAR shrink or crossing 255 bytes, ENUM reorder, charset conversion, dropping the PK | block | schema for exact answers |
| L03 | Row-touching DDL on a large table: use gh-ost / pt-online-schema-change | warn | stats |
| L04 | DDL without a short `SET SESSION lock_wait_timeout` (metadata-lock pile-up) | warn | |
| L05 | `ADD FOREIGN KEY` while `foreign_key_checks=1` (COPY only) | block | |
| L06 | UPDATE / DELETE / INSERT ... SELECT over a large table in one transaction (replication lag) | warn | stats |
| L07 | `DROP` / `TRUNCATE` / `RENAME` of columns, tables, databases | block | |
| L08 | `UPDATE` / `DELETE` without `WHERE`; `LIMIT` without `ORDER BY` | block / warn | |
| L09 | Backfill not limited to a key range or batch size | warn / info | |
| L10 | Auto-increment column smaller than BIGINT; `utf8` / `utf8mb3` | warn | |
| L11 | `WHERE` / `JOIN` on a column that no index starts with | warn | schema |
| L12 | SQL built by f-strings, template literals, concatenation, `%` / `.format` / `Sprintf` (SQL injection) | block | source code |

Tables created earlier in the same script are treated as empty, so DDL on them is not flagged.

- **schema**: the current `CREATE TABLE` statements (`SHOW CREATE TABLE`).
- **stats**: approximate row counts, `{"orders": 25000000}`, from
  `SELECT table_name, table_rows FROM information_schema.tables WHERE table_schema = DATABASE()`.
  Tables of 1,000,000 rows or more count as large; under 10,000 as small.

## Use with an AI agent (MCP)

Requires [uv](https://docs.astral.sh/uv/). The server runs locally over stdio; your SQL never
leaves your machine.

**Claude Code**

```bash
claude mcp add mysql-audit -- uvx mysql-audit-ai-agent
```

**Cursor, Windsurf, Claude Desktop and other MCP clients** (`mcp.json` / `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "mysql-audit": { "command": "uvx", "args": ["mysql-audit-ai-agent"] }
  }
}
```

Tools: `review_migration(sql, schema?, stats?)`, `review_query(sql, schema?, stats?)`,
`review_code(code)`, `explain_rule(rule_id)`, `list_rules()`.

In our [agent evaluation](docs/agent-eval.md) Claude Code called the tool on its own in 10 of
10 migration tasks, with no extra prompt.

## Command line

```bash
pip install mysql-audit-ai-agent
mysql-audit migrations/20261027_add_index.sql --schema schema.sql
mysql-audit migration.sql --stats rows.json --format json
mysql-audit --code app/models/user.py      # SQL injection check
```

Exit code: 0 safe, 1 review, 2 block, so it can gate CI.

## Development

```bash
pip install -e ".[dev]"
pytest
```

Every rule has positive and negative test cases under `tests/`.

`tests/test_mysql_oracle.py` checks the rules against a real server: each ALTER is
run with `ALGORITHM=INPLACE, LOCK=NONE`, and MySQL's refusal (or not) must match the
rule's verdict. CI runs it on MySQL 8.0 and 8.4. Locally:

```bash
docker run -d -e MYSQL_ROOT_PASSWORD=root -p 3306:3306 mysql:8.4
MYSQL_HOST=127.0.0.1 MYSQL_PASSWORD=root pytest tests/test_mysql_oracle.py
```

## 中文說明

給 AI 編碼代理用的 MySQL 變更安全審查。代理在執行 migration 前呼叫 `review_migration`，
取得 `safe` / `review` / `block` 判定，以及每個風險的行號、線上影響與安全寫法。
規則由 DBA 經驗寫成，結果可重複驗證。

## License

Apache-2.0
