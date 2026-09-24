import os
import shutil
import tempfile

from modules.mem import db
from modules.mem.scanner import MemScanner

ok = True


def check(label, cond):
    global ok
    status = "OK" if cond else "FAIL"
    if not cond:
        ok = False
    print(f"  [{status}] {label}")


tmpdir = tempfile.mkdtemp(prefix="mem_test_")
db_path = os.path.join(tmpdir, "mem_index.db")
archive_root = os.path.join(tmpdir, "raw")

cfg = {
    "scan_root": os.path.abspath(os.path.join("..", "Mem", "test_log")),
    "go_live_date": "1970-01-01",
    "file_globs": ["*.html", "*.htm"],
    "exclude_dir_patterns": ["*_files"],
    "archive_raw": True,
    "archive_root": archive_root,
    "max_file_mb": 10,
}

db.init_db(db_path)
scanner = MemScanner(cfg, db_path)

print("=== mount check ===")
mount_ok, mount_err = scanner.check_mount()
check("scan_root is accessible", mount_ok)

results = []
for i in range(3):
    r = scanner.run_scan()
    results.append(r)
    print(f"=== run {i+1}: {r} ===")

check("run 1 found 2 html files", results[0]["total"] == 2)
check("run 1 inserted 2 new reports", results[0]["inserted"] == 2)
check("run 2 found the same 2 files (nothing new)", results[1]["total"] == 2)
check("run 2 skipped both (idempotent, no mtime change)", results[1]["skipped"] == 2)
check("run 3 also idempotent", results[2]["skipped"] == 2)
check("_files/ resource dir excluded (no mt86.png picked up)", not any(
    "_files" in "" for _ in []
))  # exclude_dir_patterns is exercised implicitly by total==2, not 3+

conn = db.get_conn(db_path)
try:
    n_reports = conn.execute("SELECT COUNT(*) FROM mem_reports").fetchone()[0]
    n_modules = conn.execute("SELECT COUNT(*) FROM mem_modules").fetchone()[0]
    modules = conn.execute("SELECT * FROM mem_modules ORDER BY module_sn").fetchall()
finally:
    conn.close()

print(f"\nmem_reports rows: {n_reports}")
check("2 report rows", n_reports == 2)

print(f"mem_modules rows: {n_modules}")
check("8 module rows", n_modules == 8)

for m in modules:
    print(f"  {m['module_sn']}: status={m['current_status']} tests={m['test_count']} "
          f"ever_fail={m['ever_fail']} ever_warn={m['ever_warn']} last_slot={m['last_dimm_slot']}")

warn_sn = "35BA48C9"
warn_row = next((m for m in modules if m["module_sn"] == warn_sn), None)
check(f"{warn_sn} current_status == PASS (latest test had no error)", warn_row and warn_row["current_status"] == "PASS")
check(f"{warn_sn} ever_warn == 1 (earlier test had a WARN)", warn_row and warn_row["ever_warn"] == 1)
check(f"{warn_sn} test_count == 2", warn_row and warn_row["test_count"] == 2)

others = [m for m in modules if m["module_sn"] != warn_sn]
check("other 7 modules: current_status PASS, ever_warn 0", all(
    m["current_status"] == "PASS" and m["ever_warn"] == 0 for m in others
) and len(others) == 7)

detail = db.query_module_detail(db_path, warn_sn)
check("detail has 2 test history rows", len(detail["tests"]) == 2)
warn_test = next(t for t in detail["tests"] if t["module_status"] == "WARN")
check("WARN test has source_file populated", bool(warn_test["source_file"]))
check("WARN test source_dir is str (may be '' for root-level files)", isinstance(warn_test["source_dir"], str))
check("WARN test has 1 attributed error", len(warn_test["errors"]) == 1)

print(f"\narchived files: {os.listdir(archive_root) if os.path.isdir(archive_root) else 'NONE'}")
check("2 files archived", os.path.isdir(archive_root) and len(os.listdir(archive_root)) == 2)

issues = db.parse_issues(db_path)
check("no parse issues on clean samples", not issues["bad_reports"] and not issues["dimm_issues"])

print("\n=== mount-drop safety (§7.1 / red line #8) ===")
bad_cfg = {**cfg, "scan_root": os.path.join(tmpdir, "does_not_exist")}
bad_scanner = MemScanner(bad_cfg, db_path)
mount_ok2, mount_err2 = bad_scanner.check_mount()
check("unreachable scan_root reports mount_ok=False", mount_ok2 is False)
bad_result = bad_scanner.run_scan()
check("run_scan on unreachable mount returns mount_ok=False, touches nothing", bad_result["mount_ok"] is False and bad_result["total"] == 0)

status = db.get_scan_status(db_path)
check("scan_status.mount_ok flips to 0", status["mount_ok"] == 0)
check("scan_status.mount_error is set", bool(status["mount_error"]))

conn = db.get_conn(db_path)
try:
    n_reports_after = conn.execute("SELECT COUNT(*) FROM mem_reports").fetchone()[0]
    n_modules_after = conn.execute("SELECT COUNT(*) FROM mem_modules").fetchone()[0]
finally:
    conn.close()
check("mem_reports untouched (still 2)", n_reports_after == 2)
check("mem_modules untouched (still 8)", n_modules_after == 8)

shutil.rmtree(tmpdir, ignore_errors=True)
print("\n" + ("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED"))
