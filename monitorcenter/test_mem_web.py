"""Route/template smoke test for the mem module.

Bypasses modules/mem/integration.py's config-file loading (which assumes a
Linux deployment layout) and modules/mem/scheduler.py (which imports the
POSIX-only `fcntl`) by stubbing fcntl in sys.modules before anything in
modules.mem is imported, and by wiring app.config directly instead of
going through register_mem_module(). This exercises real Flask routing +
Jinja2 template rendering against a real (temp) SQLite DB populated by an
actual scan of the sample MemTest86 logs — not just import/syntax checks.
"""

import os
import shutil
import sys
import tempfile
import types

# ── stub fcntl so modules.mem.scheduler (and its get_poll_state call inside
#    routes.api_scan_status) import cleanly on this Windows dev box ──────
fcntl_stub = types.ModuleType("fcntl")
fcntl_stub.LOCK_EX = 2
fcntl_stub.LOCK_NB = 4
fcntl_stub.LOCK_UN = 8
fcntl_stub.flock = lambda fd, op: None  # always "succeeds" for this test
sys.modules["fcntl"] = fcntl_stub

import config  # noqa: E402
from flask import Flask  # noqa: E402

from modules.mem import db  # noqa: E402
from modules.mem.routes import mem_bp  # noqa: E402
from modules.mem.scanner import MemScanner  # noqa: E402

ok = True


def check(label, cond):
    global ok
    status = "OK" if cond else "FAIL"
    if not cond:
        ok = False
    print(f"  [{status}] {label}")


tmpdir = tempfile.mkdtemp(prefix="mem_web_test_")
db_path = os.path.join(tmpdir, "mem_index.db")
cfg = {
    "scan_root": os.path.abspath(os.path.join("..", "Mem", "test_log")),
    "go_live_date": "1970-01-01",
    "file_globs": ["*.html", "*.htm"],
    "exclude_dir_patterns": ["*_files"],
    "archive_raw": True,
    "archive_root": os.path.join(tmpdir, "raw"),
    "max_file_mb": 10,
}

db.init_db(db_path)
MemScanner(cfg, db_path).run_scan()

app = Flask(__name__, template_folder=str(config.TEMPLATE_DIR), static_folder=str(config.STATIC_DIR))
app.config["MEM_DB_PATH"] = db_path
app.config["MEM_CFG"] = cfg
app.register_blueprint(mem_bp)
client = app.test_client()

print("=== routes ===")

r = client.get("/mem/")
check("GET /mem/ -> 200", r.status_code == 200)
check("dashboard HTML mentions MEMORY header", b"MEMORY" in r.data)
check("dashboard HTML wires memApp()", b"memApp()" in r.data)

r = client.get("/mem/api/summary?range=custom&from=2025-01-01&to=2025-12-31")
check("GET /mem/api/summary -> 200", r.status_code == 200)
summary = r.get_json()
check("summary.total_all_time == 16 (8 dimms x 2 reports)", summary["total_all_time"] == 16)
check("summary.summary.total == 16 for full-year custom range", summary["summary"]["total"] == 16)
check("summary.summary.warn_count == 1", summary["summary"]["warn_count"] == 1)
check("by_capacity has one 64GB bucket of 16", summary["by_capacity"] == [{"size_gb": 64, "count": 16}])

r = client.get("/mem/api/modules?per_page=50")
check("GET /mem/api/modules -> 200", r.status_code == 200)
mods = r.get_json()
check("8 modules total", mods["total"] == 8)

r = client.get("/mem/api/modules?q=35BA48C9")
check("GET /mem/api/modules?q=35BA48C9 -> 1 match", r.get_json()["total"] == 1)

r = client.get("/mem/api/module/35BA48C9")
check("GET /mem/api/module/35BA48C9 -> 200", r.status_code == 200)
detail = r.get_json()
check("module detail: current_status PASS, ever_warn 1", detail["module"]["current_status"] == "PASS" and detail["module"]["ever_warn"] == 1)
check("module detail: 2 test rows", len(detail["tests"]) == 2)
warn_test = next(t for t in detail["tests"] if t["module_status"] == "WARN")
check("module detail: warn test has 1 error with module_sn set", len(warn_test["errors"]) == 1 and warn_test["errors"][0]["module_sn"] == "35BA48C9")

r = client.get("/mem/api/reports")
check("GET /mem/api/reports -> 200 with 2 reports", r.status_code == 200 and r.get_json()["total"] == 2)

report_uid = r.get_json()["reports"][0]["report_uid"]
r = client.get(f"/mem/api/report/{report_uid}")
check("GET /mem/api/report/<uid> -> 200 with 8 modules", r.status_code == 200 and len(r.get_json()["modules"]) == 8)

r = client.get(f"/mem/raw/{report_uid}")
check("GET /mem/raw/<uid> -> 200, decoded UTF-8 HTML", r.status_code == 200 and "MemTest86" in r.get_data(as_text=True))

r = client.get("/mem/api/scan_status")
check("GET /mem/api/scan_status -> 200 (exercises fcntl-stubbed scheduler)", r.status_code == 200)
check("scan_status.mount_ok == 1", r.get_json()["mount_ok"] == 1)

r = client.get("/mem/api/parse_issues")
check("GET /mem/api/parse_issues -> 200, no issues on clean samples", r.status_code == 200 and not r.get_json()["bad_reports"])

r = client.get("/mem/api/packageable")
check("GET /mem/api/packageable -> 8 packageable (all PASS, no package yet)", r.status_code == 200 and r.get_json()["packageable_count"] == 8)

r = client.post("/mem/api/scan")
check("POST /mem/api/scan -> started", r.status_code == 200 and r.get_json()["status"] == "started")

import time
time.sleep(1)
r = client.get("/mem/api/scan_status")
check("scan finished with 0 inserted (idempotent re-scan)", r.get_json()["status"] == "done" and r.get_json()["inserted"] == 0)

shutil.rmtree(tmpdir, ignore_errors=True)
print("\n" + ("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED"))
