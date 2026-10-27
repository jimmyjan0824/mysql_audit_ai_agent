# mysql_audit_ai_agent

MySQL schema-change safety review for AI coding agents.

Before Claude Code, Cursor or another agent runs a migration, it sends the SQL to
`review_migration` and gets back a verdict (`safe` / `review` / `block`) plus, for
every risk, the line, what will happen in production, and a safe way to write it.
The checks are deterministic rules written from DBA experience, not another LLM guess.

> Status: early development (v0.1). Six of the twelve planned rules are in.

## Rules

| ID  | Checks | Default |
| --- | --- | --- |
| L01 | DDL without explicit `ALGORITHM` / `LOCK`; `ALGORITHM=COPY`, `LOCK=SHARED/EXCLUSIVE` | warn / block |
| L02 | Column changes that force a table copy: type change, VARCHAR shrink or crossing 255 bytes, ENUM reorder, charset conversion, dropping the PK | block |
| L04 | DDL without a short `SET SESSION lock_wait_timeout` (metadata-lock pile-up) | warn |
| L05 | `ADD FOREIGN KEY` while `foreign_key_checks=1` (COPY only) | block |
| L07 | `DROP` / `TRUNCATE` / `RENAME` of columns, tables, databases | block |
| L08 | `UPDATE` / `DELETE` without `WHERE`; `LIMIT` without `ORDER BY` | block / warn |

Planned: L03 (large-table DDL needs gh-ost / pt-osc), L06 (replication lag),
L09 (unbatched backfill), L10 (INT overflow, utf8 vs utf8mb4), L11 (missing index),
L12 (SQL injection in code snippets).

Tables created earlier in the same script are treated as empty, so DDL on them is not flagged.
Pass the current `CREATE TABLE` statements as `schema` to get exact answers for column changes.

## Use with an AI agent (MCP)

```bash
pip install -e .            # PyPI release comes later
claude mcp add mysql-audit -- mysql-audit-mcp
```

Tools: `review_migration(sql, schema?)`, `explain_rule(rule_id)`, `list_rules()`.

## Command line

```bash
mysql-audit migrations/20261027_add_index.sql --schema schema.sql
mysql-audit migration.sql --format json
```

Exit code: 0 safe, 1 review, 2 block, so it can gate CI.

## Development

```bash
pip install -e ".[dev]"
pytest
```

Every rule has positive and negative test cases under `tests/`.

## 中文說明

給 AI 編碼代理用的 MySQL 變更安全審查。代理在執行 migration 前呼叫 `review_migration`，
取得 `safe` / `review` / `block` 判定，以及每個風險的行號、線上影響與安全寫法。
規則由 DBA 經驗寫成，結果可重複驗證。

## License

Apache-2.0
