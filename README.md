# mysql_audit_ai_agent

<!-- mcp-name: io.github.jimmyjan0824/mysql-audit -->

**English** | [繁體中文](https://github.com/jimmyjan0824/mysql_audit_ai_agent/blob/main/README.zh-TW.md)

MySQL schema-change safety review for AI coding agents.

Before Claude Code, Cursor or another agent runs a migration, it sends the SQL to
`review_migration` and gets back a verdict (`safe` / `review` / `block`) plus, for
every risk, the line, what will happen in production, and a safe way to write it.
The checks are deterministic rules written from DBA experience, not another LLM guess.

> Status: beta. Every rule about server behavior is checked against real MySQL in CI. DBAs: try the [trial kit](trial/README.en.md) and [report wrong results](https://github.com/jimmyjan0824/mysql_audit_ai_agent/issues/new?template=wrong-result.yml).

**Contents:** [Why](#why) · [What it checks](#what-it-checks) · [Quick start](#quick-start) ·
[Use with an AI agent (MCP)](#use-with-an-ai-agent-mcp) · [Command line](#command-line) ·
[Rules](#rules) · [Inputs that make results exact](#inputs-that-make-results-exact) ·
[Pre-deploy checks](#pre-deploy-checks) · [Rollbacks and backups](#rollbacks-and-backups) ·
[GitHub Action](#github-action) · [Version and upgrades](#version-and-upgrades) ·
[Troubleshooting](#troubleshooting) · [DBA trial kit](#dba-trial-kit) · [Development](#development)

## Why

AI coding agents write and run migrations quickly, but the SQL that looks correct is often the
SQL that takes production down: an `ALTER TABLE` that silently copies a 25-million-row table and
blocks writes, a column type change that forces a full rebuild, a `DROP COLUMN` the previous
release still reads, an `UPDATE` without `WHERE`, a backfill that leaves every replica minutes
behind. These are the incidents a DBA catches in review, and an agent has no DBA in the loop.

MySQL Audit puts that review in front of the agent:

- **Before it runs, not after.** The agent calls the review tool before executing a migration,
  query or SQL-building code. On `block` it rewrites and reviews again.
- **Deterministic.** The same SQL always gets the same verdict. Each rule that depends on server
  behavior is tested against real MySQL 5.7, 8.0 and 8.4 in CI.
- **Actionable.** Every finding has the line, the production impact and a concrete fix (for
  example `ALGORITHM=INSTANT`, gh-ost, batching by primary key, expand and contract).
- **Local and private.** It never connects to your database and runs entirely on your machine.
  Your SQL and data never leave it.

## What it checks

- **Migrations and DDL**: table copies and write locks (Online DDL `ALGORITHM` / `LOCK`),
  version-dependent INSTANT changes, metadata-lock pile-ups, foreign keys, unique keys, large
  tables, free disk for rebuilds, data loss from `DROP` / `TRUNCATE` / `RENAME`, missing
  rollbacks and backups.
- **Data changes**: `UPDATE` / `DELETE` without `WHERE`, unbatched backfills, `LIMIT` without
  `ORDER BY`, statements that stop replication (`sql_log_bin = 0`).
- **Queries**: `WHERE` / `JOIN` columns no index can use.
- **Schema design**: tables without a primary key, auto-increment columns that will overflow,
  `utf8mb3`.
- **Security**: SQL injection in application code (Python, JS/TS, PHP, Go, Java) and dangerous
  `GRANT`s.

It is used in three ways:

| Surface | Who uses it | What it does |
| --- | --- | --- |
| MCP server | Claude Code, Cursor, Windsurf, Claude Desktop and other agents | The agent calls `review_migration`, `review_query`, `review_code` and `preflight_checks` on its own |
| `mysql-audit` CLI | Developers and DBAs | Review files by hand or in any CI; exit code 0 / 1 / 2 |
| GitHub Action | Teams | Reviews each pull request's migrations, annotates lines, comments, fails on `block`, supports DBA approval |

## Quick start

You need Python 3.10 or later, or [uv](https://docs.astral.sh/uv/) (uv brings its own Python).

**1. Review a file from the command line**

```bash
pip install mysql-audit-ai-agent          # in a virtual environment
mysql-audit migration.sql
# or without installing anything, with uv:
uvx --from mysql-audit-ai-agent mysql-audit migration.sql
```

Example output:

```text
trial/migrations/12_drop_column.sql: BLOCK (2 statements)
  line 5 [block] L07: This statement drops column `coupon_code`.
    fix: Use expand and contract: ship code that no longer uses the column or table first, take a backup, then drop it in a later release. ...
  line 5 [warn] L18: This migration deletes data, and the file does not say where the backup is.
    fix: Back up what is deleted first ... and note it in the file: -- backup: s3://bucket/orders_2026-10-28.sql.gz
```

**2. Let your AI agent use it (Claude Code)**

```bash
claude mcp add mysql-audit --scope user -- uvx mysql-audit-ai-agent@latest
```

From then on, Claude reviews migrations before running them. Other agents: see
[Use with an AI agent](#use-with-an-ai-agent-mcp).

**3. Review every pull request** with the [GitHub Action](#github-action).

## Use with an AI agent (MCP)

Requires [uv](https://docs.astral.sh/uv/). The server runs locally over stdio; your SQL never
leaves your machine.

**Claude Code**

```bash
claude mcp add mysql-audit --scope user -- uvx mysql-audit-ai-agent@latest
```

`--scope user` makes it available in every project. `--scope project` writes it to the
project's `.mcp.json` instead, so everyone who clones the repo gets it. Check that it is
connected with `claude mcp list` (it should show `mysql-audit ... ✓ Connected`), or type `/mcp`
inside Claude Code to see the tools. Then ask Claude to review a migration, or just let it run one:
it calls `review_migration` on its own. Remove it with `claude mcp remove mysql-audit`.

**Cursor, Windsurf, Claude Desktop and other MCP clients** (`mcp.json` / `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "mysql-audit": { "command": "uvx", "args": ["mysql-audit-ai-agent@latest"] }
  }
}
```

| Client | Config file |
| --- | --- |
| Cursor | `~/.cursor/mcp.json`, or `.cursor/mcp.json` in the project |
| Windsurf | `~/.codeium/windsurf/mcp_config.json` |
| Claude Desktop (macOS) | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Claude Desktop (Windows) | `%APPDATA%\Claude\claude_desktop_config.json` |

Restart the client after editing. If a desktop app reports `spawn uvx ENOENT`, it cannot find
uvx: replace `"uvx"` with the full path from `which uvx` (Windows: `where uvx`).

**Claude Desktop, one click**: download `mysql-audit.mcpb` from the
[latest release](https://github.com/jimmyjan0824/mysql_audit_ai_agent/releases/latest) and open it.

> **Running `uvx mysql-audit-ai-agent` in a terminal prints nothing and seems to hang. That is
> expected:** it is the MCP server, waiting for an MCP client to talk to it over stdin. Press
> Ctrl+C to leave. Put the command in your client's MCP config as above, and use
> `mysql-audit` (see [Command line](#command-line)) to review files yourself, for example
> `uvx --from mysql-audit-ai-agent mysql-audit migration.sql`.

### Tools

| Tool | Arguments | Returns |
| --- | --- | --- |
| `review_migration` | `sql`, optional `schema`, `stats`, `mysql_version`, `free_disk_gb`, `rollback_sql` | Verdict and findings for DDL, migration scripts and bulk writes |
| `review_query` | `sql`, optional `schema`, `stats`, `mysql_version` | Verdict and findings for queries the application will run |
| `review_code` | `code` | SQL injection findings in application source |
| `preflight_checks` | `sql`, optional `mysql_version` | [Pre-deploy SQL](#pre-deploy-checks) to run on the primary |
| `explain_rule` | `rule_id` (e.g. `L02`) | Why the rule matters and a safe example |
| `list_rules` | | Every rule with its id, title and default severity |

Arguments the call leaves out are read from [`.mysql-audit.toml`](#project-settings-mysql-audittoml).
Example prompts to try: "Add a `nickname` column to `users`", "Drop the `note` column from
`orders`", "Check this Python for SQL injection: `cur.execute(f\"... {email}\")`",
"Explain mysql-audit rule L03".

In our [agent evaluation](docs/agent-eval.md) Claude Code called the tool on its own in 10 of
10 migration tasks, with no extra prompt.

## Command line

```text
mysql-audit [files ...] [--schema FILE] [--stats FILE] [--mysql-version VERSION]
            [--free-disk-gb GB] [--config FILE] [--format text|json] [--color auto|always|never]
            [--code] [--preflight] [--version]
```

| Option | Meaning |
| --- | --- |
| `files` | SQL files to review; reads stdin when omitted |
| `--schema FILE` | Current `CREATE TABLE` statements (e.g. `mysqldump --no-data`); makes column and index checks exact |
| `--stats FILE` | JSON table sizes, `{"orders": 25000000}` or `{"orders": {"rows": ..., "data_bytes": ..., "index_bytes": ...}}`; enables the large-table rules |
| `--mysql-version V` | Target server, e.g. `8.0.28`, `8.4.3`, `5.7.44`, `aurora-3.04` (default: 8.0.29 or later) |
| `--free-disk-gb GB` | Free space on the server's data volume; with byte sizes enables L17 |
| `--config FILE` | Settings file (default: the nearest `.mysql-audit.toml`) |
| `--format json` | Machine-readable output |
| `--color auto\|always\|never` | Color text output: `[block]` lines red, `[warn]` lines yellow, the verdict red / yellow / green. `auto` (default) colors only on a terminal and honors `NO_COLOR` / `FORCE_COLOR` |
| `--code` | The files are application code: check for SQL injection |
| `--preflight` | Print pre-deploy SQL for these migrations instead of reviewing them |
| `--version` | Print the installed version |

Examples:

```bash
mysql-audit db/migrate/20261027_add_index.sql --schema schema.sql --stats stats.json
mysql-audit db/migrate/*.sql --mysql-version 8.0.28 --format json
echo "UPDATE users SET status = 0;" | mysql-audit          # from stdin
mysql-audit --code app/models/user.py                      # SQL injection check
mysql-audit migration.sql --preflight > preflight.sql      # pre-deploy checks
```

**Exit code:** 0 = safe, 1 = review, 2 = block, so it can gate any CI.

**Verdicts:** `block` means do not run it as written; `review` means it can run but a person
should read the findings first; `safe` means no findings at warn level or above. Each finding
has a severity (`block`, `warn`, `info`), a line number, the impact and a fix.

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
`mysql-audit` cannot explain a rule by itself; ask the agent ("explain rule L03") or read
`src/mysql_audit/rules/`.

## Inputs that make results exact

Without extra input the review is conservative: it cannot tell a 100-row table from a
100-million-row one, or what type a column has now. Three inputs fix that. None of them
needs a connection from the tool to your database; you export them once.

- **schema**: the current `CREATE TABLE` statements (`SHOW CREATE TABLE`, or
  `mysqldump --no-data --skip-comments your_db > schema.sql`).
- **stats**: approximate size per table from `information_schema.tables`, either row counts
  (`{"orders": 25000000}`) or rows and bytes:

  ```sql
  SELECT JSON_OBJECTAGG(table_name, JSON_OBJECT(
           'rows', table_rows, 'data_bytes', data_length, 'index_bytes', index_length))
  FROM information_schema.tables
  WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE';
  ```

  From a shell: `mysql -N -e "<the query above>" your_db > stats.json`.
  A table counts as large at 1,000,000 rows or 5 GB (data plus indexes), and as small under
  10,000 rows. With bytes, L03 states how much free space a rebuild needs.
- **free disk** (`--free-disk-gb`, `free_disk_gb`): free space on the server's data volume,
  from `df -h /var/lib/mysql` on the host or your cloud console (RDS / Aurora: the
  `FreeStorageSpace` metric). With table bytes it enables L17.

### MySQL version

Which `ALTER`s run INSTANT depends on the server version: 5.7 has no INSTANT,
8.0.12–8.0.28 only adds columns at the end instantly, and 8.0.29+ also adds anywhere
and drops columns instantly. Without a version the tool assumes 8.0.29+ and says so in
the result. Pass the version you deploy to (`SELECT VERSION();`), for example `8.0.28`,
`5.7.44` or `aurora-3.04`:

```bash
mysql-audit migration.sql --mysql-version 8.0.28 --free-disk-gb 120
```

### Project settings (`.mysql-audit.toml`)

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
or less. No rows from every query means go. CI runs it against MySQL 5.7, 8.0.28, 8.0 and 8.4,
with and without a blocking transaction. Agents get the same SQL from the `preflight_checks` tool.

## Rollbacks and backups

L18 warns when a migration with review or block findings has no way back, and when it deletes
data without saying where the backup is. It accepts any of these as a rollback:

- a down section in the same file: `-- +goose Down`, `-- migrate:down` (dbmate),
  `-- +migrate Down` (sql-migrate);
- Liquibase `--rollback` lines;
- a sibling file: `*.down.sql` next to `*.up.sql` (golang-migrate), or `U<version>__*.sql`
  next to `V<version>__*.sql` (Flyway);
- for a one-off script, a note: `-- rollback: <what to run>`.

A backup is noted with `-- backup: <where it is>`, for example
`-- backup: s3://db-backups/shop/orders_2026-10-28.sql.gz`. Down migrations are not reviewed
as changes themselves.

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
      - uses: jimmyjan0824/mysql_audit_ai_agent@v0.3.1
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

| Input | Default | Meaning |
| --- | --- | --- |
| `paths` | `**/*.sql` | Glob patterns (comma or newline separated) of migration files |
| `schema` | | File with the current `CREATE TABLE` statements |
| `stats` | | JSON table sizes; enables the large-table rules |
| `mysql-version` | 8.0.29+ | Target MySQL version |
| `free-disk-gb` | | Free space on the data volume; with byte stats enables L17 |
| `dba-approvers` | | GitHub users whose approving review lets a failing check pass |
| `code-paths` | | Glob patterns of application code to check for SQL injection |
| `changed-only` | `true` | In pull requests, review only the files the pull request adds or changes |
| `fail-on` | `block` | Fail the check at `block`, `review`, or `never` |
| `comment` | `true` | Post and keep updating one summary comment |
| `github-token` | `github.token` | Token used to list files and comment |

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

## Version and upgrades

`mysql-audit --version` prints the installed version (`mysql-audit-ai-agent --version` for
the MCP server). To upgrade:

| Installed with | Upgrade |
|---|---|
| `pip install` (in a venv) | `pip install -U mysql-audit-ai-agent` |
| `uv tool install` | `uv tool upgrade mysql-audit-ai-agent` |
| `uvx` (MCP config) | uvx reuses its cached copy; use `uvx mysql-audit-ai-agent@latest` in the config to check PyPI on every start, or run `uv cache clean mysql-audit-ai-agent` once |
| GitHub Action | change the `@vX.Y.Z` tag in the workflow to the new release |

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `uvx mysql-audit-ai-agent` prints nothing and seems to hang | Expected: it is the MCP server waiting for a client. Press Ctrl+C. Add it to your agent's MCP config, and use `mysql-audit` to review files yourself |
| `pip install` fails with `externally-managed-environment` | Install in a virtual environment: `python3 -m venv .venv && source .venv/bin/activate`, or use `uv tool install mysql-audit-ai-agent` |
| Desktop app shows `spawn uvx ENOENT` | Use the full path from `which uvx` as the `command` |
| First start of the MCP server times out | The first run downloads the package. Run `uvx --from mysql-audit-ai-agent mysql-audit --help` once, then restart the client |
| Results differ from this README | You may have an old cached copy; see [Version and upgrades](#version-and-upgrades) |
| A rule fires on a table you know is small | Pass `--stats` (or `stats` in `.mysql-audit.toml`) so the size is known |
| A result is wrong | Please use the [report form](https://github.com/jimmyjan0824/mysql_audit_ai_agent/issues/new?template=wrong-result.yml) |

**Upgraded, but `mysql-audit` still runs the old version?** (For example,
`--version` is rejected as an unrecognized argument.) The shell is finding another copy
first, such as an older `uv tool install` in `~/.local/bin`, or it still remembers the old path:

```bash
which -a mysql-audit   # every copy on PATH; the first one is what runs
hash -r                # forget remembered paths (zsh: rehash)
```

If the first copy is not the one you upgraded, activate that environment
(`source .venv/bin/activate`), or upgrade or remove the other copy
(`uv tool upgrade mysql-audit-ai-agent` / `uv tool uninstall mysql-audit-ai-agent`).
`.venv/bin/mysql-audit --version` checks a venv's copy directly.

## DBA trial kit

[`trial/`](trial/README.en.md) has 24 example migrations and 2 code samples on a small shop
schema (`orders` 25M rows, `users` 2.4M), each marked with the verdict it should get. Every
example also runs on MySQL 8.0 and 8.4 in CI. Guides: [English](trial/README.en.md) ·
[繁體中文](trial/README.md).

```bash
git clone https://github.com/jimmyjan0824/mysql_audit_ai_agent
cd mysql_audit_ai_agent
python3 -m venv .venv && source .venv/bin/activate
pip install mysql-audit-ai-agent
python trial/run.py        # expected vs actual verdict for each example
python trial/run.py -v     # plus every finding
```

With [uv](https://docs.astral.sh/uv/) instead: `uv run --no-project --with mysql-audit-ai-agent python trial/run.py`.

Found a wrong result (a false alarm, a missed risk, or a fix that doesn't work)? Please use the
[report form](https://github.com/jimmyjan0824/mysql_audit_ai_agent/issues/new?template=wrong-result.yml).

## Development

```bash
git clone https://github.com/jimmyjan0824/mysql_audit_ai_agent
cd mysql_audit_ai_agent
pip install -e ".[dev]"
pytest
```

Every rule has positive and negative test cases under `tests/`.

To try your local changes in Claude Code without publishing, point it at your checkout. Each
session runs the code as it is now; after an edit, restart Claude Code or reconnect in `/mcp`.

```bash
claude mcp add mysql-audit-dev -- uv --directory /path/to/mysql_audit_ai_agent run mysql-audit-mcp
```

`tests/test_mysql_oracle.py` checks the rules against a real server: each ALTER is
run with `ALGORITHM=INPLACE, LOCK=NONE`, and MySQL's refusal (or not) must match the
rule's verdict. CI runs it on MySQL 8.0 and 8.4. `tests/test_mysql_versions.py` checks the
version-dependent INSTANT judgment the same way on 5.7, 8.0.28 and 8.4. Locally:

```bash
docker run -d -e MYSQL_ROOT_PASSWORD=root -p 3306:3306 mysql:8.4
MYSQL_HOST=127.0.0.1 MYSQL_PASSWORD=root pytest tests/test_mysql_oracle.py
```

### Project layout

| Path | Contents |
| --- | --- |
| `src/mysql_audit/engine.py` | Splits the script, runs every rule, builds the report |
| `src/mysql_audit/rules/` | One module per rule family (locking, data safety, queries, injection, rollback, ...) |
| `src/mysql_audit/cli.py` | The `mysql-audit` command |
| `src/mysql_audit/mcp_server.py` | The MCP server (`mysql-audit-mcp` / `mysql-audit-ai-agent`) |
| `src/mysql_audit/github_action.py`, `action.yml` | The GitHub Action |
| `src/mysql_audit/preflight.py` | Pre-deploy SQL |
| `src/mysql_audit/config.py`, `version.py` | `.mysql-audit.toml` and MySQL version handling |
| `tests/` | Unit tests and the real-MySQL checks |
| `trial/` | DBA trial kit |
| `mcpb/`, `server.json` | Claude Desktop bundle and MCP Registry metadata |

### Releasing

Bump the version in `pyproject.toml`, `src/mysql_audit/__init__.py`, `server.json` (twice),
`mcpb/manifest.json` and the Action example in this README and in README.zh-TW.md, merge, then
publish a GitHub release tagged `vX.Y.Z` on `main`. The Release workflow checks that the tag
matches every version field, then publishes to PyPI and the MCP Registry and attaches the
`.mcpb` bundle.

## License

Apache-2.0
