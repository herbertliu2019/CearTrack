# CPU Module — Technical Reference

*Last updated: 2026-06*

---

## Overview

CPU 模块解析 Intel IPDT64 测试工具生成的 `.txt` log 文件，存入 SQLite 数据库，通过
Flask Blueprint 提供 REST API 和仪表盘页面。

**注册方式：** 不通过 auto-discovery，在 `app.py` 末尾直接调用：
```python
from modules.cpu.integration import register_cpu_module
register_cpu_module(app)
```

---

## File Structure

```
modules/cpu/
├── integration.py   注册入口，读取 config/cpu_paths.json，初始化 DB，启动 scheduler
├── parser.py        解析单个 IPDT64 .txt 文件，返回 dict
├── db.py            SQLite 读写，schema 迁移，所有查询函数
├── scanner.py       扫描器：collect_log_paths / run_full / run_incremental
├── scheduler.py     后台线程：增量轮询（30min）+ 凌晨4点全量扫描
└── routes.py        Flask Blueprint /cpu/*

templates/cpu/
├── dashboard.html   主仪表盘（KPI卡片 + 横向图表 + 今日记录）
└── all_tests.html   全部记录分页列表（排序 + 过滤）

config/
└── cpu_paths.json   路径配置
```

---

## Configuration

`config/cpu_paths.json`:
```json
{
  "cpu_root_dir": "/mnt/CPU",
  "cpu_db_path": "/opt/monitorcenter/data/cpu/cpu.db",
  "poll_interval_sec": 1800
}
```

---

## Database

- **路径：** `/opt/monitorcenter/data/cpu/cpu.db`
- **模式：** WAL + synchronous=NORMAL
- **主表：** `cpu_records`
- **唯一键：** `log_path`（文件绝对路径）
- **冲突策略：** `INSERT ... ON CONFLICT(log_path) DO UPDATE` — 仅当 `start_time` 或
  `overall_result` 变化时更新，内容不变则跳过

### 重要字段说明

| 字段 | 来源 | 说明 |
|------|------|------|
| `sn` | 文件所在目录名 | 电脑机器 SN，不是 CPU 芯片序列号（CPU无序列号） |
| `test_date` | log 内容 `IPDT64 - Start Time` | 实际测试日期，不是文件创建/同步日期 |
| `cpu_full_name` | parser 正则解析 | 如 `i7-9700`，Xeon 系列为 None |
| `cpu_series` | parser 分类 | `Core i3/i5/i7/i9`、`Xeon E5`、`Xeon Gold` 等 |
| `log_path` | 文件绝对路径 | 唯一键，路径变化=新记录 |

### 统计逻辑
- 所有计数以**文件数**为准（每个 `.txt` = 1条记录）
- 不按 SN 去重（同一台电脑多次测试 = 多条记录）
- `This Week` = 本周日到今天；`This Month` = 本月1号到今天

### Schema 迁移
`init_db()` 分3步：创建表 → `_migrate_schema()`（`PRAGMA table_info` 检查缺失列）→ 创建索引。
历史库升级时自动补列并 SQL CASE 回填 `cpu_series`。

---

## Scanner

### 增量扫描 `run_incremental()`
1. `_deep_mtimes(max_depth=3)` — stat 3层目录，约1000次 os.stat，不读文件
2. 与上次保存的 `cpu_scan_state.json` 比较 mtime
3. 只对变化的子树调用 `collect_log_paths(subtree)`
4. 扫描前设 `scan_status=running`，完成后设 `done`

### 全量扫描 `run_full()`
1. 遍历所有 `.txt` 文件（不限文件名，parser 内部验证 `IPDT64`）
2. 扫描完成后调用 `delete_missing_paths()` 删除磁盘已不存在的记录
3. 更新 `cpu_scan_state.json` 重置增量基准

### 文件识别
- 扩展名：`.txt`（大小写不敏感）
- 内容验证：必须含 `IPDT64` 字样，否则 parser 返回 None → 计入 errors

---

## Scheduler

两个独立后台线程，由 `start_poll_scheduler()` 启动：

| 线程 | 名称 | 行为 |
|------|------|------|
| `cpu-poller` | 增量轮询 | 每30分钟运行 `run_incremental()` |
| `cpu-nightly` | 凌晨全扫描 | 每天 4:00 AM 本地时间运行 `run_full()` |

`/cpu/api/poll/status` 返回两个线程的状态，包括 `last_full_at` 和 `next_full_at`。

---

## API Routes

| Method | Path | 说明 |
|--------|------|------|
| GET | `/cpu/` | 仪表盘页面 |
| GET | `/cpu/all` | 全部记录页面 |
| GET | `/cpu/api/today` | 今日记录 |
| GET | `/cpu/api/stats?period=week\|month\|custom` | 统计数据 |
| GET | `/cpu/api/day/<date>` | 指定日期记录（Daily Breakdown 用） |
| GET | `/cpu/api/records?offset=&limit=` | 分页记录（max 200） |
| GET | `/cpu/api/search?q=` | 按 SN/型号搜索 |
| POST | `/cpu/api/scan?full=0\|1` | 触发扫描（full=1 为全量） |
| GET | `/cpu/api/scan/status` | 扫描进度 |
| GET | `/cpu/api/poll/status` | 自动轮询状态 |
| GET | `/cpu/api/image/<id>` | 测试截图 |

---

## Server Directory Structure

```
/mnt/CPU/                        ← cpu_root_dir，通过 SharePoint 同步脚本拉取
  ├── By SN/                     ← 正式归档（每台电脑一个 SN 子目录）
  │   └── <SN>/
  │       ├── TESTRESULTS.TXT    ← 或任意 .txt 文件名
  │       └── *.png / *.jpg      ← 测试截图（可选）
  ├── Ryans cpu/                 ← 临时目录，下班前移到 By SN
  ├── Carsons cpu/
  ├── Nicks cpu/
  └── First Failed CPU/
```

**重要：** 文件同步日期 ≠ 测试日期。log 可能今天同步但测试是上周做的。

---

## SharePoint Sync

- **脚本：** `/opt/monitorcenter/sharepoint_sync_incremental.py`
- **状态文件：** `/opt/testonedrive/last_sync.json`（UTC 时间戳）
- **Token 缓存：** `/opt/testonedrive/token_cache.bin`

### Cron 计划
```
0 2 * * *  python3 sharepoint_sync_incremental.py --full   # 凌晨2点全量
0 * * * *  python3 sharepoint_sync_incremental.py          # 每小时增量
```

### 已知问题与修复
1. **文件名大小写**：SharePoint 搜索索引返回大写 `TESTRESULTS.TXT`，实际存储为小写
   `testresults.txt`，直接下载返回 404。
   **修复**：下载 404 时自动列出目录，找实际 `.txt` 文件重试。

2. **增量过滤**：脚本原来只下载 `endswith("TESTRESULTS.TXT")` 的文件。
   **修复**：改为 `server_url.lower().endswith(".txt")`，文件名不限。

3. **时区**：last_sync.json 存 UTC，SharePoint API 也返回 UTC，无需转换。

### 手动重置同步（调试用）
```bash
# 重新拉取今天所有文件
echo '{"/sites/CEARITAD/Shared Documents/ITAD Docs/06 Testing/CPU": "2026-06-03T00:00:00Z"}' \
  > /opt/testonedrive/last_sync.json
/opt/monitorcenter/venv/bin/python3 /opt/monitorcenter/sharepoint_sync_incremental.py
```

---

## Debugging

```bash
# 服务日志（实时）
sudo journalctl -u monitorcenter -f

# CPU 模块是否注册（注意：用 logger 不用 print，不会出现 [OK] 前缀）
curl -s http://localhost:5004/cpu/api/scan/status

# 数据库记录数和最新插入
sqlite3 /opt/monitorcenter/data/cpu/cpu.db \
  "SELECT COUNT(*), MAX(inserted_at) FROM cpu_records;"

# 扫描状态
sqlite3 /opt/monitorcenter/data/cpu/cpu.db \
  "SELECT status, total, done, inserted, skipped, errors, finished_at FROM scan_status;"

# 最近插入的记录
sqlite3 /opt/monitorcenter/data/cpu/cpu.db \
  "SELECT sn, processor_name, test_date, inserted_at FROM cpu_records ORDER BY inserted_at DESC LIMIT 10;"

# 各日期记录数
sqlite3 /opt/monitorcenter/data/cpu/cpu.db \
  "SELECT test_date, COUNT(*) FROM cpu_records GROUP BY test_date ORDER BY test_date DESC LIMIT 10;"
```

---

## Common Issues

| 现象 | 原因 | 解决 |
|------|------|------|
| CPU 模块不在服务日志中 | 用 Python logger 而非 print | 用 `curl localhost:5004/cpu/api/scan/status` 验证 |
| scan 后页面不更新 | `run_incremental` 未设 scan_status | 已修复，扫描前后设 running/done |
| `api_day` 重复注册启动报错 | routes.py 有两个同名函数 | 已修复，只保留一个 |
| 文件内容是 `401 UNAUTHORIZED` | /mnt/CPU 挂载认证过期 | 重新挂载或检查同步脚本 |
| inserted=0 全部 skipped | 文件已在 DB，内容未变 | 正常行为，不是 bug |
| today 看不到新记录 | test_date 是测试日期非同步日期 | 查 test_date 字段确认实际测试日期 |
