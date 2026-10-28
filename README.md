# mysql_audit_ai_agent

<!-- mcp-name: io.github.jimmyjan0824/mysql-audit -->

MySQL schema-change safety review for AI coding agents.

Before Claude Code, Cursor or another agent runs a migration, it sends the SQL to
`review_migration` and gets back a verdict (`safe` / `review` / `block`) plus, for
every risk, the line, what will happen in production, and a safe way to write it.
The checks are deterministic rules written from DBA experience, not another LLM guess.

> Status: beta. Every rule about server behavior is checked against real MySQL in CI. DBAs: try the [trial kit](trial/README.md) and [report wrong results](https://github.com/jimmyjan0824/mysql_audit_ai_agent/issues/new?template=wrong-result.yml).

## Try it: DBA trial kit

[`trial/`](trial/README.md) has 24 example migrations and 2 code samples on a small shop schema
(`orders` 25M rows, `users` 2.4M), each marked with the verdict it should get. Every example
also runs on MySQL 8.0 and 8.4 in CI. The guide is in Traditional Chinese.

```bash
git clone https://github.com/jimmyjan0824/mysql_audit_ai_agent
cd mysql_audit_ai_agent
python3 -m venv .venv && source .venv/bin/activate
pip install mysql-audit-ai-agent
python trial/run.py        # expected vs actual verdict for each example
python trial/run.py -v     # plus every finding
```

With [uv](https://docs.astral.sh/uv/) instead: `uv run --no-project --with mysql-audit-ai-agent python trial/run.py`.

To review your own migrations, export the schema and row counts once:

```bash
mysqldump --no-data --skip-comments your_db > schema.sql
mysql -N -e "SELECT JSON_OBJECTAGG(table_name, table_rows) FROM information_schema.tables WHERE table_schema = 'your_db' AND table_type = 'BASE TABLE'" > stats.json
mysql-audit your_migration.sql --schema schema.sql --stats stats.json
```

Found a wrong result (a false alarm, a missed risk, or a fix that doesn't work)? Please use the
[report form](https://github.com/jimmyjan0824/mysql_audit_ai_agent/issues/new?template=wrong-result.yml).

## Rules

| ID  | Checks | Default | Needs |
| --- | --- | --- | --- |
| L01 | DDL without explicit `ALGORITHM` / `LOCK`; `ALGORITHM=COPY`, `LOCK=SHARED/EXCLUSIVE` | warn / block | |
| L02 | Column changes that force a table copy: type change, VARCHAR shrink or crossing 255 bytes, ENUM reorder, charset conversion, dropping the PK, adding a STORED generated column | block | schema for exact answers |
| L03 | Row-touching DDL on a large table: use gh-ost / pt-online-schema-change | warn | stats |
| L04 | DDL without a short `SET SESSION lock_wait_timeout` (metadata-lock pile-up) | warn | |
| L05 | `ADD FOREIGN KEY` while `foreign_key_checks=1` (COPY only) | block | |
| L06 | UPDATE / DELETE / INSERT ... SELECT over a large table in one transaction (replication lag) | warn | stats |
| L07 | `DROP` / `TRUNCATE` / `RENAME` of columns, tables, databases; `DROP` / `TRUNCATE PARTITION` | block | |
| L08 | `UPDATE` / `DELETE` without `WHERE`; `LIMIT` without `ORDER BY` | block / warn | |
| L09 | Backfill not limited to a key range or batch size | warn / info | |
| L10 | Auto-increment column smaller than BIGINT; `utf8` / `utf8mb3` | warn | |
| L11 | `WHERE` / `JOIN` on a column that no index starts with | warn | schema |
| L12 | SQL built by f-strings, template literals, concatenation, `%` / `.format` / `Sprintf` (SQL injection) | block | source code |
| L13 | `SET sql_log_bin = 0` (replicas never get the change); `SET GLOBAL` / `SET PERSIST` | block / warn | |
| L14 | `ADD UNIQUE` / `ADD PRIMARY KEY` on an existing table: fails on duplicates, gh-ost / pt-osc drop them silently | warn | |
| L15 | `CREATE TABLE` without a primary key, or with an engine other than InnoDB | warn | |
| L16 | `GRANT ALL ON *.*`; grants to `'%'` or `WITH GRANT OPTION`; `DROP USER` | block / warn | |
| L17 | A table rebuild needs more free disk than the server has (under 1.5× the table size warns) | block / warn | stats with bytes, free disk |
| L18 | A risky change with no rollback; a `DROP` / `TRUNCATE` with no `-- backup:` note | warn | |

Tables created earlier in the same script are treated as empty, so DDL on them is not flagged.

- **schema**: the current `CREATE TABLE` statements (`SHOW CREATE TABLE`).
- **stats**: approximate size per table from `information_schema.tables`, either row counts
  (`{"orders": 25000000}`) or rows and bytes:

  ```sql
  SELECT JSON_OBJECTAGG(table_name, JSON_OBJECT(
           'rows', table_rows, 'data_bytes', data_length, 'index_bytes', index_length))
  FROM information_schema.tables
  WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE';
  ```

  A table counts as large at 1,000,000 rows or 5 GB (data plus indexes), and as small under
  10,000 rows. With bytes, L03 states how much free space a rebuild needs.
- **free disk** (`--free-disk-gb`, `free_disk_gb`): free space on the server's data volume,
  from `df -h /var/lib/mysql` on the host or your cloud console (RDS / Aurora: the
  `FreeStorageSpace` metric). With table bytes it enables L17.

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

**Claude Desktop, one click**: download `mysql-audit.mcpb` from the
[latest release](https://github.com/jimmyjan0824/mysql_audit_ai_agent/releases/latest) and open it.

> **Running `uvx mysql-audit-ai-agent` in a terminal prints nothing and seems to hang. That is
> expected:** it is the MCP server, waiting for an MCP client to talk to it over stdin. Press
> Ctrl+C to leave. Put the command in your client's MCP config as above, and use
> `mysql-audit` (see [Command line](#command-line)) to review files yourself, for example
> `uvx --from mysql-audit-ai-agent mysql-audit migration.sql`.

Tools: `review_migration(sql, schema?, stats?, mysql_version?, free_disk_gb?, rollback_sql?)`, `review_query(sql, schema?, stats?, mysql_version?)`,
`review_code(code)`, `preflight_checks(sql, mysql_version?)`, `explain_rule(rule_id)`, `list_rules()`.

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

### Version and upgrades

`mysql-audit --version` prints the installed version (`mysql-audit-ai-agent --version` for
the MCP server). To upgrade:

| Installed with | Upgrade |
|---|---|
| `pip install` (in a venv) | `pip install -U mysql-audit-ai-agent` |
| `uv tool install` | `uv tool upgrade mysql-audit-ai-agent` |
| `uvx` (MCP config) | uvx reuses its cached copy; use `uvx mysql-audit-ai-agent@latest` in the config to check PyPI on every start, or run `uv cache clean mysql-audit-ai-agent` once |
| GitHub Action | change `@v0.3.0` in the workflow to the new tag |

## Pre-deploy checks

The review never connects to your database. What only the live server knows (open
transactions, metadata locks, replica lag) is checked by SQL you run on the primary right
before deploying:

```bash
mysql-audit migration.sql --preflight > preflight.sql
mysql your_db < preflight.sql
```

The queries are scoped to the tables the migration touches, and each returns rows only when
the deploy should wait: transactions open longer than 10 seconds, statements on those tables
running 10 seconds or more, sessions holding or waiting for their metadata locks, and tables
that are large right now. The script also says how to check that every replica lags 10 seconds
or less. CI runs it against MySQL 5.7, 8.0.28, 8.0 and 8.4, with and without a blocking
transaction.

## MySQL version and project settings

Which `ALTER`s run INSTANT depends on the server version: 5.7 has no INSTANT,
8.0.12–8.0.28 only adds columns at the end instantly, and 8.0.29+ also adds anywhere
and drops columns instantly. Without a version the tool assumes 8.0.29+ and says so in
the result. Pass the version you deploy to, for example `8.0.28`, `5.7.44` or `aurora-3.04`:

```bash
mysql-audit migration.sql --mysql-version 8.0.28 --free-disk-gb 120
```

To avoid repeating options, put a `.mysql-audit.toml` at the repository root. The CLI,
the MCP server and the GitHub Action all read it (searching upward from the current
directory, stopping at the `.git` folder); options given on the command line or in the
tool call win.

```toml
mysql_version = "8.0.28"
schema = "db/schema.sql"        # paths are relative to this file
stats = "db/table_stats.json"   # output of the stats query above
free_disk_gb = 120
```

The `MYSQL_AUDIT_VERSION` environment variable overrides `mysql_version` for the CLI and
the MCP server, for example
`claude mcp add mysql-audit -e MYSQL_AUDIT_VERSION=8.0.28 -- uvx mysql-audit-ai-agent`.

## GitHub Action

Reviews the migrations each pull request adds or changes, annotates the lines in the diff,
keeps one summary comment on the pull request up to date, and fails the check on `block`.

```yaml
# .github/workflows/mysql-audit.yml
name: MySQL Audit
on: [pull_request, pull_request_review]   # the review event lets a DBA approval re-run it
permissions:
  contents: read
  pull-requests: write   # for the summary comment
jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: jimmyjan0824/mysql_audit_ai_agent@v0.3.0
        with:
          paths: db/migrate/**/*.sql      # default: **/*.sql
          schema: db/schema.sql           # optional, makes checks exact
          # stats: db/table_rows.json     # optional row counts, enables large-table rules
          # mysql-version: 8.0.28         # optional; .mysql-audit.toml also works
          # free-disk-gb: 120             # optional, with byte stats enables L17
          # dba-approvers: alice,bob      # optional, see below
          # code-paths: app/**/*.py       # optional SQL injection check
          # fail-on: review               # block (default), review or never
```

When the result is review or block, the comment ends with a pre-deploy checklist and the
[preflight SQL](#pre-deploy-checks) for the changed migrations.

**DBA approval.** Some blocked changes are fine after a DBA has looked, for example a
`DROP COLUMN` the application stopped using two releases ago. List the DBAs in
`dba-approvers`: when one of them approves the pull request, the check passes. The approval
must be on the latest commit, so a later push needs a new one, and a later "request changes"
from the same person withdraws it. A ticked checkbox would not do here, because anyone who can
edit the pull request can tick it.

**Rollbacks.** Down migrations are not reviewed as changes: `*.down.sql` (golang-migrate) and
`U<version>__*.sql` (Flyway) count as the rollback of their up file, and so do down sections
(`-- +goose Down`, `-- migrate:down`, `-- +migrate Down`) and Liquibase `--rollback` lines.

## Development

```bash
pip install -e ".[dev]"
pytest
```

Every rule has positive and negative test cases under `tests/`.

`tests/test_mysql_oracle.py` checks the rules against a real server: each ALTER is
run with `ALGORITHM=INPLACE, LOCK=NONE`, and MySQL's refusal (or not) must match the
rule's verdict. CI runs it on MySQL 8.0 and 8.4. `tests/test_mysql_versions.py` checks the
version-dependent INSTANT judgment the same way on 5.7, 8.0.28 and 8.4. Locally:

```bash
docker run -d -e MYSQL_ROOT_PASSWORD=root -p 3306:3306 mysql:8.4
MYSQL_HOST=127.0.0.1 MYSQL_PASSWORD=root pytest tests/test_mysql_oracle.py
```

## 中文說明

給 AI 編碼代理用的 MySQL 變更安全審查。代理在執行 migration 前呼叫 `review_migration`，
取得 `safe` / `review` / `block` 判定，以及每個風險的行號、線上影響與安全寫法。
規則由 DBA 經驗寫成，結果可重複驗證。

注意：在終端機直接執行 `uvx mysql-audit-ai-agent` 不會有任何輸出，看起來像卡住，這是正常的。
它是 MCP 伺服器，正在等 Claude Code、Cursor 等 MCP 客戶端連線，按 Ctrl+C 離開即可。這個指令要寫進
MCP 設定讓 AI 工具啟動；自己在終端機審查檔案請用 `uvx --from mysql-audit-ai-agent mysql-audit 檔名.sql`。

DBA 想試用的話，請看 [試用包說明](trial/README.md)：裡面有 24 個可直接執行的範例 migration、
用自己資料庫的 schema 與筆數檢查的方式，以及 [回報誤判的表單](https://github.com/jimmyjan0824/mysql_audit_ai_agent/issues/new?template=wrong-result.yml)。

## License

Apache-2.0
