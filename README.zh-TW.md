# mysql_audit_ai_agent

[English](README.md) | **繁體中文**

給 AI 程式助理（AI coding agent）用的 MySQL 變更安全審查。

Claude Code、Cursor 等 AI 助理在執行 migration 之前，先把 SQL 送給 `review_migration`，
取得 `safe` / `review` / `block` 判定，以及每個風險的行號、上線後會發生什麼事，和安全的寫法。
判斷依據是由 DBA 經驗寫成的固定規則，不是另一個 LLM 的猜測，同樣的 SQL 永遠得到同樣的結果。

> 狀態：beta。所有和伺服器行為有關的規則，都在 CI 中用真實 MySQL 驗證。DBA 歡迎試用 [試用包](trial/README.md)，並 [回報誤判](https://github.com/jimmyjan0824/mysql_audit_ai_agent/issues/new?template=wrong-result.yml)。

**目錄：** [專案目的](#專案目的) · [檢查哪些事](#檢查哪些事) · [快速開始](#快速開始) ·
[搭配 AI 助理使用（MCP）](#搭配-ai-助理使用mcp) · [命令列](#命令列) · [規則一覽](#規則一覽) ·
[讓判斷更準確的輸入](#讓判斷更準確的輸入) · [部署前檢查](#部署前檢查) ·
[回滾與備份](#回滾與備份) · [GitHub Action](#github-action) · [查看與更新版本](#查看與更新版本) ·
[疑難排解](#疑難排解) · [DBA 試用包](#dba-試用包) · [開發](#開發)

## 專案目的

AI 程式助理寫 migration、跑 migration 都很快，但「看起來正確」的 SQL 常常正是讓線上服務出事的 SQL：
一個 `ALTER TABLE` 悄悄把 2,500 萬筆的表整個複製一遍、期間擋住所有寫入；改欄位型別逼得整表重建；
`DROP COLUMN` 刪掉上一版程式還在讀的欄位；`UPDATE` 忘了寫 `WHERE`；一次回填幾百萬筆讓每台從庫延遲好幾分鐘。
這些都是 DBA 在審查時會攔下來的事故，而 AI 助理的流程裡沒有 DBA。

MySQL Audit 把這道審查放在 AI 助理執行之前：

- **執行前，不是出事後。** AI 在執行 migration、查詢或組 SQL 的程式碼之前呼叫審查工具；判定為 `block` 時，它會改寫後再審一次。
- **結果固定、可驗證。** 同樣的 SQL 永遠得到同樣的判定。每條和伺服器行為有關的規則，都在 CI 中用真實的 MySQL 5.7、8.0、8.4 驗證。
- **可以直接照做。** 每個發現都附上行號、對線上的影響，以及具體的修正方式（例如 `ALGORITHM=INSTANT`、gh-ost、依主鍵分批、expand and contract）。
- **在本機執行、不外傳。** 工具不會連線到你的資料庫，全部在你的電腦上執行，SQL 和資料都不會離開。

## 檢查哪些事

- **Migration 與 DDL**：整表複製與寫入鎖（Online DDL 的 `ALGORITHM` / `LOCK`）、依版本而不同的 INSTANT 變更、metadata lock 造成的排隊、外鍵、唯一鍵、大表、重建表所需的磁碟空間、`DROP` / `TRUNCATE` / `RENAME` 造成的資料遺失、缺少回滾與備份。
- **資料變更**：沒有 `WHERE` 的 `UPDATE` / `DELETE`、沒有分批的回填、`LIMIT` 沒有 `ORDER BY`、會讓複寫中斷的寫法（`sql_log_bin = 0`）。
- **查詢**：`WHERE` / `JOIN` 用到的欄位沒有可用的索引。
- **表結構設計**：沒有主鍵、自增欄位會溢位、`utf8mb3`。
- **安全**：應用程式碼（Python、JS/TS、PHP、Go、Java）中的 SQL injection，以及危險的 `GRANT`。

有三種使用方式：

| 使用方式 | 誰在用 | 做什麼 |
| --- | --- | --- |
| MCP 伺服器 | Claude Code、Cursor、Windsurf、Claude Desktop 等 AI 工具 | AI 自己呼叫 `review_migration`、`review_query`、`review_code`、`preflight_checks` |
| `mysql-audit` 命令列 | 開發者與 DBA | 手動審查檔案，或放進任何 CI；結束碼 0 / 1 / 2 |
| GitHub Action | 團隊 | 審查每個 PR 的 migration、在 diff 上標註、留言、遇到 `block` 讓檢查失敗，支援 DBA 核准 |

## 快速開始

需要 Python 3.10 以上，或 [uv](https://docs.astral.sh/uv/)（uv 會自備 Python）。

**1. 用命令列審查檔案**

```bash
pip install mysql-audit-ai-agent          # 請在虛擬環境中安裝
mysql-audit migration.sql
# 或者不安裝，直接用 uv 執行：
uvx --from mysql-audit-ai-agent mysql-audit migration.sql
```

輸出範例：

```text
trial/migrations/12_drop_column.sql: BLOCK (2 statements)
  line 5 [block] L07: This statement drops column `coupon_code`.
    fix: Use expand and contract: ship code that no longer uses the column or table first, take a backup, then drop it in a later release. ...
  line 5 [warn] L18: This migration deletes data, and the file does not say where the backup is.
    fix: Back up what is deleted first ... and note it in the file: -- backup: s3://bucket/orders_2026-10-28.sql.gz
```

（審查結果目前以英文輸出。）

**2. 讓 AI 助理使用（Claude Code）**

```bash
claude mcp add mysql-audit --scope user -- uvx mysql-audit-ai-agent@latest
```

之後 Claude 在執行 migration 前會自動審查。其他 AI 工具請見 [搭配 AI 助理使用](#搭配-ai-助理使用mcp)。

**3. 審查每個 Pull Request**：用 [GitHub Action](#github-action)。

## 搭配 AI 助理使用（MCP）

需要 [uv](https://docs.astral.sh/uv/)。伺服器透過 stdio 在本機執行，SQL 不會離開你的電腦。

**Claude Code**

```bash
# 已發佈的版本
claude mcp add mysql-audit --scope user -- uvx mysql-audit-ai-agent@latest
```

`--scope user` 讓所有專案都能用；改成 `--scope project` 會寫進專案的 `.mcp.json`，commit 後團隊成員 clone 下來就能用。
用 `claude mcp list` 確認顯示 `mysql-audit ... ✓ Connected`，或在 Claude Code 裡輸入 `/mcp` 看工具清單。
接著請 Claude 審查 migration，或直接讓它執行 migration，它會自己先呼叫 `review_migration`。
移除用 `claude mcp remove mysql-audit`。

**Cursor、Windsurf、Claude Desktop 及其他 MCP 客戶端**（`mcp.json` / `claude_desktop_config.json`）：

```json
{
  "mcpServers": {
    "mysql-audit": { "command": "uvx", "args": ["mysql-audit-ai-agent@latest"] }
  }
}
```

| 工具 | 設定檔位置 |
| --- | --- |
| Cursor | 全域 `~/.cursor/mcp.json`，或專案內 `.cursor/mcp.json` |
| Windsurf | `~/.codeium/windsurf/mcp_config.json` |
| Claude Desktop（macOS） | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Claude Desktop（Windows） | `%APPDATA%\Claude\claude_desktop_config.json` |

存檔後完全關掉再重開該工具。設定檔若已有其他 server，只要把 `"mysql-audit": {...}` 這一項加進去，不要覆蓋整個檔案。
桌面程式若顯示 `spawn uvx ENOENT`，代表它找不到 uvx：用 `which uvx`（Windows 用 `where uvx`）查出完整路徑，取代 `"uvx"`。

**Claude Desktop 一鍵安裝**：從 [最新 release](https://github.com/jimmyjan0824/mysql_audit_ai_agent/releases/latest) 下載 `mysql-audit.mcpb`，點兩下開啟。

> **在終端機直接執行 `uvx mysql-audit-ai-agent` 不會有任何輸出，看起來像卡住，這是正常的。**
> 它是 MCP 伺服器，正在等 Claude Code、Cursor 等 MCP 客戶端透過 stdin 連線，按 Ctrl+C 離開即可。
> 這個指令要寫進上面的 MCP 設定讓 AI 工具啟動；自己在終端機審查檔案請用 `mysql-audit`（見 [命令列](#命令列)），
> 例如 `uvx --from mysql-audit-ai-agent mysql-audit migration.sql`。

### 提供給 AI 的工具

| 工具 | 參數 | 回傳 |
| --- | --- | --- |
| `review_migration` | `sql`，選填 `schema`、`stats`、`mysql_version`、`free_disk_gb`、`rollback_sql` | DDL、migration 腳本、大量寫入的判定與發現 |
| `review_query` | `sql`，選填 `schema`、`stats`、`mysql_version` | 應用程式會執行的查詢的判定與發現 |
| `review_code` | `code` | 應用程式碼中的 SQL injection |
| `preflight_checks` | `sql`，選填 `mysql_version` | 部署前在主庫執行的 [檢查 SQL](#部署前檢查) |
| `explain_rule` | `rule_id`（例如 `L02`） | 規則為什麼重要，以及安全的寫法範例 |
| `list_rules` | | 所有規則的編號、名稱與預設嚴重度 |

呼叫時沒給的參數，會從 [`.mysql-audit.toml`](#專案設定mysql-audittoml) 讀取。
可以試試這些提示：「幫 `users` 加一個 `nickname` 欄位」、「把 `orders` 的 `note` 欄位刪掉」、
「檢查這段 Python 有沒有 SQL injection：`cur.execute(f\"... {email}\")`」、「用 mysql-audit 解釋規則 L03」。

在我們的 [agent 評估](docs/agent-eval.md) 中，Claude Code 在 10 個 migration 任務裡 10 次都主動呼叫了這個工具，不需要額外提示。

## 命令列

```text
mysql-audit [檔案 ...] [--schema 檔案] [--stats 檔案] [--mysql-version 版本]
            [--free-disk-gb GB] [--config 檔案] [--format text|json] [--color auto|always|never]
            [--code] [--preflight] [--version]
```

| 選項 | 說明 |
| --- | --- |
| `檔案` | 要審查的 SQL 檔；沒給時從 stdin 讀取 |
| `--schema 檔案` | 目前的 `CREATE TABLE` 語句（例如 `mysqldump --no-data` 的輸出）；讓欄位與索引的判斷更準確 |
| `--stats 檔案` | 各表大小的 JSON：`{"orders": 25000000}` 或 `{"orders": {"rows": ..., "data_bytes": ..., "index_bytes": ...}}`；啟用大表相關規則 |
| `--mysql-version 版本` | 目標伺服器版本，例如 `8.0.28`、`8.4.3`、`5.7.44`、`aurora-3.04`（預設：8.0.29 以上） |
| `--free-disk-gb GB` | 資料磁碟的剩餘空間；搭配位元組大小啟用 L17 |
| `--config 檔案` | 設定檔（預設：最近的 `.mysql-audit.toml`） |
| `--format json` | 輸出 JSON，方便程式處理 |
| `--color auto\|always\|never` | 文字輸出上色：`[block]` 行紅色、`[warn]` 行黃色，判定依結果顯示紅 / 黃 / 綠。`auto`（預設）只在終端機上色，並遵守 `NO_COLOR` / `FORCE_COLOR` 環境變數 |
| `--code` | 檔案是應用程式碼：檢查 SQL injection |
| `--preflight` | 不審查，改為輸出這些 migration 的部署前檢查 SQL |
| `--version` | 顯示目前安裝的版本 |

範例：

```bash
mysql-audit db/migrate/20261027_add_index.sql --schema schema.sql --stats stats.json
mysql-audit db/migrate/*.sql --mysql-version 8.0.28 --format json
echo "UPDATE users SET status = 0;" | mysql-audit          # 從 stdin 讀取
mysql-audit --code app/models/user.py                      # 檢查 SQL injection
mysql-audit migration.sql --preflight > preflight.sql      # 部署前檢查
```

**結束碼：** 0 = safe、1 = review、2 = block，可以直接當成任何 CI 的關卡。

**判定的意思：** `block` 代表不要照這樣執行；`review` 代表可以執行，但應該先有人看過這些發現；
`safe` 代表沒有 warn 以上等級的發現。每個發現都有嚴重度（`block`、`warn`、`info`）、行號、影響與修正方式。

## 規則一覽

| 編號 | 檢查內容 | 預設 | 需要 |
| --- | --- | --- | --- |
| L01 | DDL 沒有明確寫 `ALGORITHM` / `LOCK`；`ALGORITHM=COPY`、`LOCK=SHARED/EXCLUSIVE` | warn / block | |
| L02 | 會整表複製的欄位變更：改型別、VARCHAR 縮短或跨過 255 bytes、ENUM 重新排序、轉換字元集、刪除主鍵、新增 STORED 生成欄位 | block | schema（判斷更準） |
| L03 | 在大表上執行會動到每一列的 DDL：建議用 gh-ost / pt-online-schema-change | warn | stats |
| L04 | DDL 前沒有設定較短的 `SET SESSION lock_wait_timeout`（metadata lock 造成排隊） | warn | |
| L05 | `foreign_key_checks=1` 時 `ADD FOREIGN KEY`（只能 COPY） | block | |
| L06 | 在一個交易中對大表執行 UPDATE / DELETE / INSERT ... SELECT（造成複寫延遲） | warn | stats |
| L07 | `DROP` / `TRUNCATE` / `RENAME` 欄位、表、資料庫；`DROP` / `TRUNCATE PARTITION` | block | |
| L08 | 沒有 `WHERE` 的 `UPDATE` / `DELETE`；`LIMIT` 沒有 `ORDER BY` | block / warn | |
| L09 | 回填沒有限制主鍵範圍或批次大小 | warn / info | |
| L10 | 自增欄位小於 BIGINT；`utf8` / `utf8mb3` | warn | |
| L11 | `WHERE` / `JOIN` 的欄位沒有以它開頭的索引 | warn | schema |
| L12 | 用 f-string、template literal、字串串接、`%` / `.format` / `Sprintf` 組 SQL（SQL injection） | block | 原始碼 |
| L13 | `SET sql_log_bin = 0`（從庫收不到變更）；`SET GLOBAL` / `SET PERSIST` | block / warn | |
| L14 | 對既有表 `ADD UNIQUE` / `ADD PRIMARY KEY`：有重複資料會失敗，用 gh-ost / pt-osc 則會靜默丟掉重複列 | warn | |
| L15 | `CREATE TABLE` 沒有主鍵，或使用 InnoDB 以外的引擎 | warn | |
| L16 | `GRANT ALL ON *.*`；授權給 `'%'` 或 `WITH GRANT OPTION`；`DROP USER` | block / warn | |
| L17 | 重建表需要的空間超過伺服器剩餘磁碟（不到表大小的 1.5 倍時警告） | block / warn | 含位元組的 stats、剩餘磁碟 |
| L18 | 有風險的變更沒有回滾方式；`DROP` / `TRUNCATE` 沒有寫 `-- backup:` 備份位置 | warn | |

同一個腳本中前面才建立的表會視為空表，對它們的 DDL 不會被標記。
命令列本身沒有解釋規則的指令；可以請 AI 助理「解釋規則 L03」，或閱讀 `src/mysql_audit/rules/`。

## 讓判斷更準確的輸入

沒有額外資訊時，審查會比較保守：它分不出一張表是 100 筆還是 1 億筆，也不知道欄位現在是什麼型別。
以下三種輸入可以解決這個問題。它們都不需要工具連線到資料庫，只要匯出一次即可。

- **schema**：目前的 `CREATE TABLE` 語句（`SHOW CREATE TABLE`，或 `mysqldump --no-data --skip-comments your_db > schema.sql`）。
- **stats**：從 `information_schema.tables` 取得各表的大約大小，可以只給筆數（`{"orders": 25000000}`），或筆數加位元組：

  ```sql
  SELECT JSON_OBJECTAGG(table_name, JSON_OBJECT(
           'rows', table_rows, 'data_bytes', data_length, 'index_bytes', index_length))
  FROM information_schema.tables
  WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE';
  ```

  在 shell 中執行：`mysql -N -e "<上面的查詢>" your_db > stats.json`。
  100 萬筆以上或 5 GB 以上（資料加索引）算大表，1 萬筆以下算小表。有位元組大小時，L03 會寫出重建需要多少剩餘空間。
- **剩餘磁碟**（`--free-disk-gb`、`free_disk_gb`）：資料磁碟的剩餘空間，在主機上用 `df -h /var/lib/mysql` 查，
  或看雲端主控台（RDS / Aurora 看 `FreeStorageSpace` 指標）。搭配表的位元組大小即可啟用 L17。

### MySQL 版本

哪些 `ALTER` 能 INSTANT 完成，依伺服器版本而不同：5.7 沒有 INSTANT；8.0.12–8.0.28 只有「在最後面加欄位」是 INSTANT；
8.0.29 以上在任何位置加欄位、刪欄位都是 INSTANT。沒給版本時，工具會假設 8.0.29 以上，並在結果中註明。
請給實際部署的版本（`SELECT VERSION();`），例如 `8.0.28`、`5.7.44` 或 `aurora-3.04`：

```bash
mysql-audit migration.sql --mysql-version 8.0.28 --free-disk-gb 120
```

### 專案設定（`.mysql-audit.toml`）

不想每次重複輸入選項的話，在 repo 根目錄放一個 `.mysql-audit.toml`。命令列、MCP 伺服器和 GitHub Action 都會讀它
（從目前目錄往上找，找到 `.git` 資料夾為止）；命令列選項或工具呼叫時給的參數優先。

```toml
mysql_version = "8.0.28"
schema = "db/schema.sql"        # 路徑相對於這個檔案
stats = "db/table_stats.json"   # 上面 stats 查詢的輸出
free_disk_gb = 120
```

環境變數 `MYSQL_AUDIT_VERSION` 會覆蓋命令列與 MCP 伺服器的 `mysql_version`，例如
`claude mcp add mysql-audit -e MYSQL_AUDIT_VERSION=8.0.28 -- uvx mysql-audit-ai-agent`。

## 部署前檢查

審查本身從不連線到資料庫。只有線上伺服器才知道的事（未結束的交易、metadata lock、從庫延遲），
改由你在正式部署前、在主庫上執行一段檢查 SQL：

```bash
mysql-audit migration.sql --preflight > preflight.sql
mysql your_db < preflight.sql
```

這些查詢只針對這次 migration 用到的表，而且只有在應該先暫停時才會回傳資料列：超過 10 秒的交易、
在這些表上跑了 10 秒以上的查詢、持有或等待這些表 metadata lock 的連線，以及目前已經是大表的表。
腳本最後也說明如何確認每台從庫的延遲在 10 秒以內。每個查詢都沒有回傳資料列，就代表可以部署。
CI 會在 MySQL 5.7、8.0.28、8.0、8.4 上，分別在有、沒有卡住的交易時執行它。AI 助理可以透過 `preflight_checks` 工具取得同一段 SQL。

## 回滾與備份

當有 review 或 block 發現的 migration 沒有回滾方式，或刪除資料卻沒寫備份位置時，L18 會提醒。以下任何一種都算有回滾：

- 同一個檔案中的 down 段落：`-- +goose Down`、`-- migrate:down`（dbmate）、`-- +migrate Down`（sql-migrate）；
- Liquibase 的 `--rollback` 行；
- 旁邊的對應檔案：`*.up.sql` 旁的 `*.down.sql`（golang-migrate），或 `V<版本>__*.sql` 旁的 `U<版本>__*.sql`（Flyway）；
- 一次性腳本可以寫一行註記：`-- rollback: <要執行什麼>`。

備份位置用 `-- backup: <備份在哪裡>` 註記，例如 `-- backup: s3://db-backups/shop/orders_2026-10-28.sql.gz`。
down migration 本身不會被當成變更審查。

## GitHub Action

審查每個 Pull Request 新增或修改的 migration，在 diff 對應的行上標註、在 PR 上維持一則持續更新的摘要留言，遇到 `block` 時讓檢查失敗。

```yaml
# .github/workflows/mysql-audit.yml
name: MySQL Audit
on: [pull_request, pull_request_review]   # review 事件讓 DBA 核准後能重新執行檢查
permissions:
  contents: read
  pull-requests: write   # 用來留摘要留言
jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: jimmyjan0824/mysql_audit_ai_agent@v0.3.2
        with:
          paths: db/migrate/**/*.sql      # 預設：**/*.sql
          schema: db/schema.sql           # 選填，讓判斷更準確
          # stats: db/table_rows.json     # 選填，表的筆數，啟用大表規則
          # mysql-version: 8.0.28         # 選填；也可以寫在 .mysql-audit.toml
          # free-disk-gb: 120             # 選填，搭配位元組 stats 啟用 L17
          # dba-approvers: alice,bob      # 選填，見下方說明
          # code-paths: app/**/*.py       # 選填，檢查 SQL injection
          # fail-on: review               # block（預設）、review 或 never
```

| 參數 | 預設 | 說明 |
| --- | --- | --- |
| `paths` | `**/*.sql` | migration 檔的 glob 樣式（以逗號或換行分隔） |
| `schema` | | 目前 `CREATE TABLE` 語句的檔案 |
| `stats` | | 各表大小的 JSON；啟用大表規則 |
| `mysql-version` | 8.0.29 以上 | 目標 MySQL 版本 |
| `free-disk-gb` | | 資料磁碟剩餘空間；搭配位元組 stats 啟用 L17 |
| `dba-approvers` | | 這些 GitHub 使用者核准 PR 後，失敗的檢查就會通過 |
| `code-paths` | | 要檢查 SQL injection 的應用程式碼 glob 樣式 |
| `changed-only` | `true` | 在 PR 中只審查這個 PR 新增或修改的檔案 |
| `fail-on` | `block` | 在 `block`、`review` 或 `never` 時讓檢查失敗 |
| `comment` | `true` | 在 PR 上留一則摘要留言並持續更新 |
| `github-token` | `github.token` | 用來列出檔案與留言的 token |

結果是 review 或 block 時，留言最後會附上部署前檢查清單，以及這次變更的 migration 對應的 [檢查 SQL](#部署前檢查)。

**DBA 核准。** 有些被 block 的變更在 DBA 看過後其實沒問題，例如應用程式兩個版本前就不再使用的欄位要 `DROP COLUMN`。
把 DBA 列在 `dba-approvers`：只要其中一人核准（Approve）這個 PR，檢查就會通過。核准必須是在最新的 commit 上，
之後再 push 就需要重新核准；同一個人之後選「Request changes」也會撤回核准。這裡不用勾選框，因為任何能編輯 PR 的人都能勾。

**回滾檔。** down migration 不會被當成變更審查：`*.down.sql`（golang-migrate）與 `U<版本>__*.sql`（Flyway）
會被視為對應 up 檔的回滾，down 段落（`-- +goose Down`、`-- migrate:down`、`-- +migrate Down`）與 Liquibase `--rollback` 行也是。

## 查看與更新版本

查看目前版本：`mysql-audit --version`（MCP 伺服器用 `mysql-audit-ai-agent --version`）。更新方式依安裝方式而定：

| 安裝方式 | 更新指令 |
|---|---|
| `pip install`（虛擬環境） | 先 `source .venv/bin/activate`，再 `pip install -U mysql-audit-ai-agent` |
| `uv tool install` | `uv tool upgrade mysql-audit-ai-agent` |
| `uvx`（包括 MCP 設定） | uvx 會沿用快取的舊版：在設定中改用 `uvx mysql-audit-ai-agent@latest`，每次啟動都會檢查 PyPI；或執行一次 `uv cache clean mysql-audit-ai-agent` |
| GitHub Action | 把 workflow 裡的 `@vX.Y.Z` 改成新版 tag |

## 疑難排解

| 狀況 | 解法 |
| --- | --- |
| `uvx mysql-audit-ai-agent` 沒有任何輸出、像卡住 | 正常：它是在等客戶端連線的 MCP 伺服器，按 Ctrl+C 離開。請把它加進 AI 工具的 MCP 設定，自己審查檔案用 `mysql-audit` |
| `pip install` 出現 `externally-managed-environment` | 在虛擬環境中安裝：`python3 -m venv .venv && source .venv/bin/activate`，或改用 `uv tool install mysql-audit-ai-agent` |
| 桌面程式顯示 `spawn uvx ENOENT` | 把 `command` 改成 `which uvx` 查到的完整路徑 |
| 第一次啟動 MCP 伺服器逾時 | 第一次要下載套件。先執行一次 `uvx --from mysql-audit-ai-agent mysql-audit --help`，再重開 AI 工具 |
| 結果和本文件不同 | 可能是快取的舊版，見 [查看與更新版本](#查看與更新版本) |
| 明明是小表卻觸發大表規則 | 提供 `--stats`（或在 `.mysql-audit.toml` 設定 `stats`），讓工具知道表的大小 |
| 判斷錯誤 | 請用 [回報表單](https://github.com/jimmyjan0824/mysql_audit_ai_agent/issues/new?template=wrong-result.yml) |

**更新後執行的還是舊版？**（例如 `--version` 出現 `unrecognized arguments`）這代表終端機先找到了另一份舊的 `mysql-audit`，
例如之前用 `uv tool install` 裝在 `~/.local/bin` 的那份，或者 shell 還記著舊的路徑：

```bash
which -a mysql-audit   # 列出所有找得到的 mysql-audit，第一個就是實際執行的那個
hash -r                # 清掉 shell 記住的舊路徑（zsh 用 rehash）
```

如果第一個不是你更新的那份，請啟用對應的虛擬環境（`source .venv/bin/activate`），
或更新、移除另一份（`uv tool upgrade mysql-audit-ai-agent` / `uv tool uninstall mysql-audit-ai-agent`）。
也可以直接執行 `.venv/bin/mysql-audit --version` 確認虛擬環境裡的版本。

## DBA 試用包

[`trial/`](trial/README.md) 有 24 個範例 migration 和 2 個程式碼範例，用的是一個小型電商資料庫
（`orders` 2,500 萬筆、`users` 240 萬筆），每個範例都標註了應得的判定，也都在 CI 中於 MySQL 8.0 與 8.4 實際執行過。
說明文件：[繁體中文](trial/README.md) · [English](trial/README.en.md)。

```bash
git clone https://github.com/jimmyjan0824/mysql_audit_ai_agent
cd mysql_audit_ai_agent
python3 -m venv .venv && source .venv/bin/activate
pip install mysql-audit-ai-agent
python trial/run.py        # 每個範例的預期判定與實際判定
python trial/run.py -v     # 加上每一條發現
```

改用 [uv](https://docs.astral.sh/uv/) 的話：`uv run --no-project --with mysql-audit-ai-agent python trial/run.py`。

發現判斷錯誤（誤報、漏報，或建議做法不可行）？請用 [回報表單](https://github.com/jimmyjan0824/mysql_audit_ai_agent/issues/new?template=wrong-result.yml)。

## 開發

```bash
git clone https://github.com/jimmyjan0824/mysql_audit_ai_agent
cd mysql_audit_ai_agent
pip install -e ".[dev]"
pytest
```

每條規則在 `tests/` 下都有正反兩面的測試案例。

想在 Claude Code 測試本機修改、不用發版的話，把它指向你的 repo 資料夾。每次啟動都會跑本機當下的程式碼；
改完程式後，重開 Claude Code 或在 `/mcp` 裡重新連線就會生效。

```bash
claude mcp add mysql-audit-dev -- uv --directory /你的路徑/mysql_audit_ai_agent run mysql-audit-mcp
```

`tests/test_mysql_oracle.py` 用真實伺服器驗證規則：每個 ALTER 都以 `ALGORITHM=INPLACE, LOCK=NONE` 執行，
MySQL 拒絕與否必須和規則的判定一致。CI 在 MySQL 8.0 與 8.4 上執行它。`tests/test_mysql_versions.py`
用同樣方式在 5.7、8.0.28、8.4 上驗證依版本而不同的 INSTANT 判斷。在本機執行：

```bash
docker run -d -e MYSQL_ROOT_PASSWORD=root -p 3306:3306 mysql:8.4
MYSQL_HOST=127.0.0.1 MYSQL_PASSWORD=root pytest tests/test_mysql_oracle.py
```

### 專案結構

| 路徑 | 內容 |
| --- | --- |
| `src/mysql_audit/engine.py` | 切分腳本、執行所有規則、產生報告 |
| `src/mysql_audit/rules/` | 依規則類別分成各模組（鎖表、資料安全、查詢、injection、回滾等） |
| `src/mysql_audit/cli.py` | `mysql-audit` 指令 |
| `src/mysql_audit/mcp_server.py` | MCP 伺服器（`mysql-audit-mcp` / `mysql-audit-ai-agent`） |
| `src/mysql_audit/github_action.py`、`action.yml` | GitHub Action |
| `src/mysql_audit/preflight.py` | 部署前檢查 SQL |
| `src/mysql_audit/config.py`、`version.py` | `.mysql-audit.toml` 與 MySQL 版本處理 |
| `tests/` | 單元測試與真實 MySQL 驗證 |
| `trial/` | DBA 試用包 |
| `mcpb/`、`server.json` | Claude Desktop 打包檔與 MCP Registry 資訊 |

### 發版

更新 `pyproject.toml`、`src/mysql_audit/__init__.py`、`server.json`（兩處）、`mcpb/manifest.json`，
以及 README.md 與本文件中 Action 範例的版本號，合併後在 `main` 上發佈 tag 為 `vX.Y.Z` 的 GitHub release。
Release workflow 會先確認 tag 與每個版本欄位一致，再發佈到 PyPI 與 MCP Registry，並附上 `.mcpb` 打包檔。

## 授權

Apache-2.0
