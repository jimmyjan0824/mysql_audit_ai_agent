# MySQL Audit DBA 試用包

MySQL Audit 會在 migration 和查詢**執行之前**審查它們，找出會鎖表、整表複製、遺失資料、拖垮複寫的寫法，並附上安全的改寫方式。主要使用者是 Claude Code、Cursor 這類 AI 程式助理，也可以用命令列或 GitHub Action 執行。

我們想請您用 DBA 的經驗檢查：**它的判斷對不對？漏了什麼？建議做法實際可行嗎？** 大約 10 到 20 分鐘。

## 1. 安裝（2 分鐘）

需要 Python 3.10 以上（macOS 的指令是 `python3`）。在虛擬環境裡安裝，可以避開 macOS Homebrew 與新版 Linux 的 `externally-managed-environment` 錯誤：

```bash
git clone https://github.com/jimmyjan0824/mysql_audit_ai_agent
cd mysql_audit_ai_agent
python3 -m venv .venv
source .venv/bin/activate          # Windows：.venv\Scripts\activate
pip install mysql-audit-ai-agent
```

之後每次開新的終端機，先在這個資料夾執行 `source .venv/bin/activate`。

已經有 [uv](https://docs.astral.sh/uv/) 的話，也可以改用 `uv tool install mysql-audit-ai-agent`，`mysql-audit` 指令就能在任何地方使用；這時下面的範例請用 `uv run --no-project --with mysql-audit-ai-agent python trial/run.py` 執行。

## 2. 跑一遍範例（3 分鐘）

```bash
python trial/run.py        # 每個範例的預期結果與實際結果
python trial/run.py -v     # 加上每一條發現的說明
```

啟用虛擬環境後 `python` 指令就能用，不需要另外建立連結。

範例用的是一個小型電商資料庫（[schema.sql](schema.sql)），並假設 `orders` 有 2,500 萬筆、`users` 有 240 萬筆（[stats.json](stats.json)）。每個範例都在 CI 裡實際於 MySQL 8.0 和 8.4 上執行過。

| 範例 | 規則 | 預期 | 想請您確認的地方 |
|---|---|---|---|
| 01_add_column_instant | | safe | INSTANT 加欄位＋短 lock_wait_timeout，這樣算安全嗎？ |
| 02_fulltext_index | L01 L03 | review | FULLTEXT 只能 LOCK=SHARED，寫入會等整個建索引過程 |
| 03_change_column_type | L02 | block | INT → BIGINT 一定是 COPY |
| 04_varchar_255_byte_boundary | L02 | block | utf8mb4 VARCHAR(60)→(100) 跨過 255 bytes，要整表複製 |
| 05_varchar_within_boundary | | safe | 沒跨過 255 bytes，只改 metadata |
| 06_index_on_large_table | L03 | review | 線上建索引，但 2,500 萬筆會跑很久、複寫延遲 |
| 07_no_lock_wait_timeout | L04 | review | 預設 lock_wait_timeout 一年，卡 metadata lock 時流量會排隊 |
| 08_foreign_key_checks_on | L05 | block | foreign_key_checks=1 加外鍵只能 COPY |
| 09_foreign_key_checks_off | L05 | review | 關掉檢查改用 INPLACE，但舊資料不會被驗證 |
| 10_big_update | L06 | review | 一個交易更新幾百萬筆 |
| 11_batched_update | | safe | 依主鍵範圍分批 |
| 12_drop_column | L07 L18 | block | 舊版程式還在讀這個欄位；沒寫備份位置與回滾方式 |
| 13_table_swap | | safe | RENAME 交換表名，應用程式用的名稱不變 |
| 14_delete_without_where | L08 | block | |
| 15_limit_without_order | L08 | review | LIMIT 沒有 ORDER BY，複寫不安全 |
| 16_unbatched_backfill_unknown_size | L09 | review | 不知道表大小時要求分批或提供筆數 |
| 17_int_auto_increment | L10 | review | INT 自增主鍵 21 億會用完 |
| 18_query_without_index | L11 | review | WHERE 欄位沒有索引 |
| 19_query_with_index | | safe | |
| 20_sql_log_bin_off | L13 | block | 關掉 binlog 後的修改不會到從庫，主從從此不一致 |
| 21_add_unique_index | L14 L03 | review | 已有重複資料會失敗；用 gh-ost / pt-osc 會靜默丟掉重複列 |
| 22_table_without_primary_key | L15 | review | 沒有主鍵：從庫套用變更要掃全表，gh-ost 也無法使用 |
| 23_grant_all | L16 | block | 任何位址都能登入、擁有整台伺服器的權限 |
| 24_drop_with_backup | L07 | block | 和 12 同一個 DROP，但寫了 `-- backup:` 與 `-- rollback:`，L18 就不再提醒 |
| code/injection.py | L12 | block | 字串拼接 SQL |
| code/parameterized.py | | safe | 參數化查詢 |

我們最想聽到意見的判斷：
1. **大表門檻**：100 萬筆或 5 GB 以上就建議用 gh-ost / pt-online-schema-change（L03、L06）。您的經驗中門檻是多少？
2. **lock_wait_timeout 上限 60 秒**（L04）。您平常設多少？
3. **INT UNSIGNED 自增主鍵只給警告**（L10）。
4. 有沒有您常見、但這 18 條規則**完全沒涵蓋**的事故類型？

## 3. 用您自己的 migration（5 到 10 分鐘，最有價值）

```bash
# 現有表結構（不含資料）
mysqldump --no-data --skip-comments your_db > schema.sql
# 每張表的大約筆數與大小
mysql -N -e "SELECT JSON_OBJECTAGG(table_name, JSON_OBJECT('rows', table_rows, 'data_bytes', data_length, 'index_bytes', index_length)) FROM information_schema.tables WHERE table_schema = 'your_db' AND table_type = 'BASE TABLE'" > stats.json
# 資料磁碟剩餘空間：在主機上 df -h /var/lib/mysql，RDS / Aurora 看 FreeStorageSpace

mysql-audit your_migration.sql --schema schema.sql --stats stats.json --free-disk-gb 120
```

100 萬筆以上或 5 GB 以上（資料加索引）算大表。給了大小後，需要重建表的變更會寫出需要多少剩餘空間；再給 `--free-disk-gb`，空間不足時判 block（L17）。

請加上實際部署的版本，例如 `--mysql-version 8.0.28`、`5.7.44` 或 `aurora-3.04`：哪些 ALTER 能 INSTANT 完成依版本而不同，沒給版本時會假設 8.0.29 以上並在結果中註明。常用的設定可以寫進專案根目錄的 `.mysql-audit.toml`（見[主 README](../README.md#mysql-version-and-project-settings)），之後只要執行 `mysql-audit your_migration.sql`。

結束碼 0 = safe、1 = review、2 = block。所有判斷都在本機執行，SQL 不會傳到任何地方。

正式部署前，可以產生一份只針對這次 migration 用到的表的檢查 SQL，在主庫上執行：

```bash
mysql-audit your_migration.sql --preflight > preflight.sql
mysql your_db < preflight.sql
```

每個查詢只有在應該先暫停時才會回傳資料列：超過 10 秒的交易、在這些表上跑了 10 秒以上的查詢、持有或等待這些表 metadata lock 的連線，以及目前已經是大表的表。腳本最後也會說明如何確認每台從庫的延遲在 10 秒以內。

## 4. 回報誤判

請到 [回報表單](https://github.com/jimmyjan0824/mysql_audit_ai_agent/issues/new?template=wrong-result.yml) 填寫：被審查的 SQL、表結構、工具的輸出，以及實際上會怎樣、依據是什麼（例如「在 8.0.36 用 ALGORITHM=INPLACE, LOCK=NONE 實際跑成功」）。表名或欄位名不便公開的話，請先改成假的名稱。

不論是誤報（其實安全卻被擋）、漏報（其實危險卻沒抓到），還是建議做法不可行，都非常歡迎。

## 也可以這樣用

- **Claude Code**：`claude mcp add mysql-audit -- uvx mysql-audit-ai-agent`，之後 AI 在跑 migration 前會自己呼叫審查。
  注意：`uvx mysql-audit-ai-agent` 是給 AI 工具啟動的 MCP 伺服器，自己在終端機執行時不會有任何輸出、看起來像卡住，這是正常的（它在等 MCP 客戶端連線），按 Ctrl+C 離開即可。自己審查 SQL 檔請用上面的 `mysql-audit` 指令。
- **GitHub Action**：每個 PR 自動審查改到的 migration，設定見[主 README](../README.md#github-action)。
