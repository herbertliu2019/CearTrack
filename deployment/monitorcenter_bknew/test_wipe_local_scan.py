"""
本地 Windows 测试脚本。

使用方法：
  1. 把你的 .log 文件放入下面的目录（按年/月子目录，或先放到 test_logs/ 由脚本自动分）
  2. python test_wipe_local_scan.py

目录结构（必须）：
  test_wipe_data/
  └── logs/
      ├── 2024/
      │   ├── 01 January/   ← 把 2024年1月的 log 放这里
      │   └── 04 April/
      └── 2026/
          └── 04 April/

如果你只有平铺的 .log 文件，把它们放到 test_logs/ 目录，
脚本会根据 log 内的 wipe_date 自动分类到对应子目录。
"""
import sys, os, json, shutil
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
from modules.wipe.parser import parse_log
from modules.wipe.scanner import WipeScanner, MONTH_DIRS
from modules.wipe.db import get_conn, stats_summary, query_period

BASE     = Path(__file__).parent / "test_wipe_data"
DB_PATH  = str(BASE / "wipe_test.db")
LOG_ROOT = str(BASE)

# ── Step 1: 从 test_logs/ 自动分类到正确子目录 ──────────────────────────────
flat_dir = Path(__file__).parent / "test_logs"
if flat_dir.exists():
    moved = 0
    skipped = 0
    for f in flat_dir.glob("*.log"):
        r = parse_log(f)
        if r and r.get("wipe_date"):
            y, m, _ = r["wipe_date"].split("-")
            month_name = MONTH_DIRS[int(m)]
            dest_dir = BASE / "logs" / y / month_name
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / f.name
            if not dest.exists():
                shutil.copy2(f, dest)
                moved += 1
                print(f"  placed: {f.name} → {y}/{month_name}/")
            else:
                skipped += 1
        else:
            print(f"  skip (no date): {f.name}")
    if moved:
        print(f"\nAuto-classified {moved} files into test_wipe_data/logs/")

# ── Step 2: 检查有哪些文件 ──────────────────────────────────────────────────
print("\n── Directory structure ──────────────────────────────────────")
logs_root = BASE / "logs"
total_files = 0
if logs_root.exists():
    for year_dir in sorted(logs_root.iterdir()):
        if not year_dir.is_dir(): continue
        for month_dir in sorted(year_dir.iterdir()):
            if not month_dir.is_dir(): continue
            count = len(list(month_dir.glob("*.log")))
            total_files += count
            print(f"  {year_dir.name}/{month_dir.name}/  → {count} files")
else:
    print("  (no logs found — please add files to test_wipe_data/logs/YYYY/MM MonthName/)")

print(f"  Total: {total_files} .log files")

if total_files == 0:
    print("\nNo log files found. Please add files and re-run.")
    sys.exit(0)

# ── Step 3: 运行全量扫描 ────────────────────────────────────────────────────
print("\n── Running full scan ────────────────────────────────────────")
if Path(DB_PATH).exists():
    Path(DB_PATH).unlink()   # 每次测试从头开始

scanner = WipeScanner(
    log_root=LOG_ROOT,
    db_path=DB_PATH,
    win_share_root=r"\\SERVER\EPS",
)

all_files = scanner.collect_all()
print(f"collect_all() found: {len(all_files)} files")

result = scanner.run_full()
print(f"inserted: {result['inserted']}  skipped: {result['skipped']}  errors: {result['errors']}")

# ── Step 4: 查询统计 ────────────────────────────────────────────────────────
print("\n── Query results ────────────────────────────────────────────")
conn = get_conn(DB_PATH)
all_records = query_period(conn, "2000-01-01", "2099-12-31")
conn.close()

stats = stats_summary(all_records)
print(f"Total records in DB : {stats['total']}")
print(f"Passed              : {stats['passed']}")
print(f"Failed              : {stats['failed']}")
print(f"Warning             : {stats['warning']}")
print(f"Pass rate           : {stats['pass_rate']}%")
print(f"Avg duration        : {stats['avg_duration']} min")

# ── Step 5: 打印前5条样本 ──────────────────────────────────────────────────
print("\n── Sample records (first 5) ─────────────────────────────────")
for r in all_records[:5]:
    print(f"  {r['drive_sn']:20s}  {r['result']:6s}  {r['wipe_date']}  "
          f"{r['sys_manufacturer'] or '':15s}  {r['win_path'] or ''}")

# ── Step 6: 打印错误文件 ───────────────────────────────────────────────────
conn = get_conn(DB_PATH)
errors = conn.execute("SELECT log_path, error_msg FROM scan_errors").fetchall()
conn.close()
if errors:
    print(f"\n── Parse errors ({len(errors)}) ───────────────────────────────────")
    for e in errors:
        print(f"  {Path(e['log_path']).name}: {e['error_msg']}")

print("\nDone.")
