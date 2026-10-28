# MySQL Audit DBA trial kit

**English** | [繁體中文](README.md)

MySQL Audit reviews migrations and queries **before they run**. It finds statements that lock
tables, copy whole tables, lose data or stall replication, and gives a safe rewrite for each.
Its main users are AI coding assistants such as Claude Code and Cursor; it also runs from the
command line and as a GitHub Action.

We would like your DBA judgment: **are its verdicts right, what does it miss, and do its fixes
work in practice?** It takes about 10 to 20 minutes.

## 1. Install (2 minutes)

You need Python 3.10 or later (`python3` on macOS). Install in a virtual environment to avoid
the `externally-managed-environment` error on Homebrew Python and recent Linux distributions:

```bash
git clone https://github.com/jimmyjan0824/mysql_audit_ai_agent
cd mysql_audit_ai_agent
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install mysql-audit-ai-agent
```

In every new terminal, run `source .venv/bin/activate` in this folder first.

Check the version with `mysql-audit --version`. Upgrade with `pip install -U mysql-audit-ai-agent`
(or `uv tool upgrade mysql-audit-ai-agent` if you installed it with `uv tool install`).

**Upgraded, but it still runs the old version?** (For example, `--version` is rejected as an
unrecognized argument.) The shell is finding another copy of `mysql-audit` first, such as an
older `uv tool install` in `~/.local/bin`, or it still remembers the old path:

```bash
which -a mysql-audit   # every copy on PATH; the first one is what runs
hash -r                # forget remembered paths (zsh: rehash)
```

If the first one is not `.venv/bin/mysql-audit`, run `source .venv/bin/activate`. If it is
`~/.local/bin/mysql-audit`, upgrade it with `uv tool upgrade mysql-audit-ai-agent` or remove it
with `uv tool uninstall mysql-audit-ai-agent` so only one copy is left.
`.venv/bin/mysql-audit --version` checks the virtual environment's copy directly.

If you already have [uv](https://docs.astral.sh/uv/), `uv tool install mysql-audit-ai-agent`
makes `mysql-audit` available everywhere; then run the examples below with
`uv run --no-project --with mysql-audit-ai-agent python trial/run.py`.

## 2. Run the examples (3 minutes)

```bash
python trial/run.py        # expected and actual verdict for each example
python trial/run.py -v     # plus an explanation of every finding
```

With the virtual environment active, `python` works; no extra link is needed.

The examples use a small shop schema ([schema.sql](schema.sql)) and assume `orders` has 25
million rows and `users` 2.4 million ([stats.json](stats.json)). Every example also runs on
MySQL 8.0 and 8.4 in CI.

| Example | Rules | Expected | What we would like you to check |
|---|---|---|---|
| 01_add_column_instant | | safe | INSTANT add column plus a short lock_wait_timeout: is this safe? |
| 02_fulltext_index | L01 L03 | review | FULLTEXT allows only LOCK=SHARED; writes wait for the whole build |
| 03_change_column_type | L02 | block | INT → BIGINT is always COPY |
| 04_varchar_255_byte_boundary | L02 | block | utf8mb4 VARCHAR(60) → (100) crosses 255 bytes and copies the table |
| 05_varchar_within_boundary | | safe | Does not cross 255 bytes; metadata only |
| 06_index_on_large_table | L03 | review | Online index build, but 25M rows take long and lag replicas |
| 07_no_lock_wait_timeout | L04 | review | The default lock_wait_timeout is a year; traffic queues behind a waiting metadata lock |
| 08_foreign_key_checks_on | L05 | block | Adding a foreign key with foreign_key_checks=1 is COPY only |
| 09_foreign_key_checks_off | L05 | review | INPLACE with checks off, but existing rows are not validated |
| 10_big_update | L06 | review | Millions of rows updated in one transaction |
| 11_batched_update | | safe | Batched by primary key range |
| 12_drop_column | L07 L18 | block | The previous release still reads the column; no backup location or rollback |
| 13_table_swap | | safe | RENAME swap; the name the application uses stays the same |
| 14_delete_without_where | L08 | block | |
| 15_limit_without_order | L08 | review | LIMIT without ORDER BY is unsafe for replication |
| 16_unbatched_backfill_unknown_size | L09 | review | With the size unknown, asks for batches or a row count |
| 17_int_auto_increment | L10 | review | An INT auto-increment key runs out at 2.1 billion |
| 18_query_without_index | L11 | review | No index on the WHERE column |
| 19_query_with_index | | safe | |
| 20_sql_log_bin_off | L13 | block | With binlog off, replicas never get the change and drift apart |
| 21_add_unique_index | L14 L03 | review | Fails on existing duplicates; gh-ost / pt-osc silently drop them |
| 22_table_without_primary_key | L15 | review | No primary key: replicas scan the table per row change, and gh-ost cannot run |
| 23_grant_all | L16 | block | Login from any host with privileges on the whole server |
| 24_drop_with_backup | L07 | block | The same DROP as 12, but with `-- backup:` and `-- rollback:` notes, so L18 no longer warns |
| code/injection.py | L12 | block | SQL built by string concatenation |
| code/parameterized.py | | safe | Parameterized query |

The judgments we most want your opinion on:
1. **Large-table threshold**: 1 million rows or 5 GB and up gets a gh-ost /
   pt-online-schema-change recommendation (L03, L06). What threshold do you use?
2. **lock_wait_timeout up to 60 seconds** (L04). What do you usually set?
3. **INT UNSIGNED auto-increment keys only get a warning** (L10).
4. Are there incident types you see often that **none of the 18 rules** cover?

## 3. Your own migrations (5 to 10 minutes, the most valuable part)

```bash
# Current table definitions (no data)
mysqldump --no-data --skip-comments your_db > schema.sql
# Approximate rows and size per table
mysql -N -e "SELECT JSON_OBJECTAGG(table_name, JSON_OBJECT('rows', table_rows, 'data_bytes', data_length, 'index_bytes', index_length)) FROM information_schema.tables WHERE table_schema = 'your_db' AND table_type = 'BASE TABLE'" > stats.json
# Free space on the data volume: df -h /var/lib/mysql on the host; RDS / Aurora: FreeStorageSpace

mysql-audit your_migration.sql --schema schema.sql --stats stats.json --free-disk-gb 120
```

A table of 1 million rows or 5 GB (data plus indexes) counts as large. With sizes, changes that
rebuild a table state how much free space they need; with `--free-disk-gb` as well, a rebuild
that does not fit is a block (L17).

Add the version you actually deploy to, for example `--mysql-version 8.0.28`, `5.7.44` or
`aurora-3.04`: which ALTERs run INSTANT depends on the version, and without one the tool assumes
8.0.29 or later and says so in the result. Common settings can go in a `.mysql-audit.toml` at the
project root (see the [main README](../README.md#project-settings-mysql-audittoml)), after which
`mysql-audit your_migration.sql` is enough.

Exit code 0 = safe, 1 = review, 2 = block. Everything runs locally; your SQL is not sent anywhere.

Before a real deploy, you can generate check SQL scoped to the tables this migration touches and
run it on the primary:

```bash
mysql-audit your_migration.sql --preflight > preflight.sql
mysql your_db < preflight.sql
```

Each query returns rows only when the deploy should wait: transactions open longer than 10
seconds, statements on those tables running 10 seconds or more, sessions holding or waiting for
their metadata locks, and tables that are large right now. The script ends with how to confirm
that every replica lags 10 seconds or less.

## 4. Report a wrong result

Please use the [report form](https://github.com/jimmyjan0824/mysql_audit_ai_agent/issues/new?template=wrong-result.yml)
with the SQL that was reviewed, the table definition, the tool's output, and what actually
happens and how you know (for example "ran fine on 8.0.36 with ALGORITHM=INPLACE, LOCK=NONE").
Rename tables or columns first if you cannot share the real names.

False alarms (safe but blocked), misses (dangerous but not caught) and fixes that don't work are
all very welcome.

## Other ways to use it

- **Claude Code**: `claude mcp add mysql-audit --scope user -- uvx mysql-audit-ai-agent@latest`.
  From then on the agent reviews migrations before running them. `--scope user` makes it
  available in every project; `--scope project` writes it to the project's `.mcp.json` so the
  team gets it on commit. `claude mcp list` should show `mysql-audit ... ✓ Connected`, or type
  `/mcp` in Claude Code to see `review_migration`, `preflight_checks` and the other tools.
  Remove it with `claude mcp remove mysql-audit`.
  Note: `uvx mysql-audit-ai-agent` is the MCP server that AI tools start. Run by hand in a
  terminal it prints nothing and seems to hang; that is expected (it is waiting for an MCP
  client). Press Ctrl+C. To review SQL files yourself, use the `mysql-audit` command above.
- **GitHub Action**: reviews the migrations each pull request changes; see the
  [main README](../README.md#github-action).
