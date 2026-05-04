import sys, os, tempfile, shutil
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
from modules.wipe.scanner import WipeScanner, MONTH_DIRS
from modules.wipe.db import get_conn, query_today, get_scan_status

# ── build a fake log tree ────────────────────────────────────────────────────
tmp = Path(tempfile.mkdtemp())
db_path = str(tmp / "wipe.db")
log_root = tmp / "win_logs"

now = datetime.now()
cur_month_dir = log_root / "logs" / str(now.year) / MONTH_DIRS[now.month]
old_month_dir = log_root / "logs" / "2024" / "01 January"
cur_month_dir.mkdir(parents=True)
old_month_dir.mkdir(parents=True)

SAMPLE_LOG = """\

==================================================================
            Data Erasure Started  {date}  at 10:00:00
            XERASwin  v14.21.3
==================================================================

Device Information:
    Manufacturer  : Samsung
    Model         : 860 EVO
    Serial Number : {sn}
    Device Type   : 2.5 SATA3 SSD
    Capacity      : 500GB
    Health Score  : 85.0
    SSD Life      : 75
    Power on Hrs  : 1200
    Method        : NIST 800-88 rev1 Clear

System Information:
    System Serial Number : SYSSN001
    System Manufacturer  : Dell Inc
    System Model         : Latitude 5420
    System Chassis Type  : Notebook

============================================================================
 Erasure Results : NIST 800-88 rev1 Clear Passed!
                   {date} at 10:25:00 in  0 hrs 25.0 min
============================================================================
"""

date_str = now.strftime("%m/%d/%Y")
old_date_str = "01/15/2024"

for sn, d, dest in [
    ("CURMON001", date_str, cur_month_dir),
    ("CURMON002", date_str, cur_month_dir),
    ("OLD00001",  old_date_str, old_month_dir),
]:
    (dest / f"{sn}.log").write_text(SAMPLE_LOG.format(sn=sn, date=d))

# also drop one invalid log (no Erasure Results) → should go to scan_errors
(cur_month_dir / "BADLOG.log").write_text("just garbage, no erasure results here")

# ── scanner tests ────────────────────────────────────────────────────────────
scanner = WipeScanner(str(log_root), db_path, r"\\SERVER\EPS")

# collect_all: should find 3 valid + 1 bad = 4 files total
all_files = scanner.collect_all()
assert len(all_files) == 4, f"expected 4 files, got {len(all_files)}"
print(f"collect_all OK: {len(all_files)} files")

# collect_current_month: should find 3 files (2 valid + 1 bad)
cur_files = scanner.collect_current_month()
assert len(cur_files) == 3, f"expected 3 current-month files, got {len(cur_files)}"
print(f"collect_current_month OK: {len(cur_files)} files")

# make_win_path
sample_path = cur_month_dir / "CURMON001.log"
win_path = scanner.make_win_path(sample_path)
assert win_path.startswith(r"\\SERVER\EPS"), f"bad win_path: {win_path}"
assert "CURMON001.log" in win_path
print(f"make_win_path OK: {win_path}")

# run_full
result = scanner.run_full()
assert result["total"] == 4
assert result["inserted"] == 3  # 3 valid
assert result["errors"] == 1    # BADLOG
print(f"run_full OK: {result}")

# run_full again → all skipped (UNIQUE constraint)
result2 = scanner.run_full()
assert result2["inserted"] == 0
assert result2["skipped"] == 3
print(f"run_full (duplicate) OK: {result2}")

# DB state
conn = get_conn(db_path)
status = get_scan_status(conn)
assert status["running"] == 0
assert status["total"] == 4
print(f"scan_status OK: {status}")
conn.close()

shutil.rmtree(tmp)
print("\nAll scanner tests PASSED")
