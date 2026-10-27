# Agent evaluation

`scripts/agent_eval/run.py` gives Claude Code (headless, `--model sonnet`) ten realistic
requests against a busy MySQL 8.0 shop schema (`orders` 40M rows, `users` 5M, `sessions` 80M),
once with the mysql-audit MCP server and once without. Each written file is then scored with
the engine itself, using the same schema and row counts.

Run of 2026-10-27, Claude Code 2.1.311. No CLAUDE.md and no hint to use the tool: the agent
found it from the server's instructions and tool descriptions alone.

| Scenario | Tool calls | Verdict with tool | Verdict without tool |
| --- | --- | --- | --- |
| Widen `orders.id` INT to BIGINT | 1 | safe (shadow table + atomic swap)* | review |
| Index on `orders.customer_id` | 3 | review (L03: 40M rows) | review (L03, L04: no lock_wait_timeout) |
| Rename `users.fullname` | 1 | **safe** (expand / contract with triggers) | **block** (L07: direct RENAME COLUMN) |
| Required column with default | 2 | safe | safe |
| Backfill `plan` where NULL | 1 | safe (batched by PK) | safe |
| Foreign key on `orders` | 1 | review (L03, L05 warn) | review |
| Purge expired sessions | 1 | review (adds index first, L03) | safe |
| New `audit_logs` table | 2 | safe | safe |
| Drop `users.legacy_score` | 3 | block (L07, reported to the user) | block |
| Python query function | 2 | safe (parameterized) | safe |

\* Initially scored block: the atomic `RENAME TABLE orders TO orders_old, orders_new TO orders`
swap was treated as a rename. Fixed in the same change as this report.

Takeaways:

- The agent called the tool in **10 of 10** scenarios (target: 8 of 10).
- Clearest win: without the tool the agent renamed a live column in place, which breaks the
  running application; with it, the agent switched to expand / contract.
- With the tool the agent also added `SET SESSION lock_wait_timeout` where it had forgotten it,
  and explained L03 / L07 warnings to the user instead of silently shipping.
- Strong models already avoid the worst mistakes (INT→BIGINT in place, unbatched backfills), so
  the value is in catching the less obvious ones (renames, metadata locks, FK COPY, large-table
  DDL) and in making the risk explicit. Weaker models and less careful prompts are the next
  thing to measure.
