import sys, os, tempfile
sys.path.insert(0, os.path.dirname(__file__))
from modules.wipe.db import (
    init_db, get_conn, insert_record, query_today, query_period,
    query_by_sn, stats_summary, by_manufacturer, fail_reasons,
    get_scan_status, upsert_scan_status,
)

with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
    db_path = f.name

init_db(db_path)
print("init_db OK")

conn = get_conn(db_path)

# insert two records
r1 = {
    "drive_sn": "AAA111", "system_sn": "SYS001",
    "wipe_date": "2026-04-30", "wipe_datetime": "2026-04-30T10:00:00",
    "duration_min": 25.0, "method": "NIST 800-88 rev1 Clear",
    "result": "PASSED", "health_score": 55.0, "ssd_life": 80,
    "sys_manufacturer": "Dell Inc", "log_path": "/logs/AAA111.log",
    "indexed_at": "2026-04-30T10:01:00",
}
r2 = {
    "drive_sn": "BBB222", "system_sn": "SYS001",
    "wipe_date": "2026-04-30", "wipe_datetime": "2026-04-30T11:00:00",
    "duration_min": 5.5, "method": "NIST 800-88 rev1 Clear",
    "result": "FAILED", "health_score": 90.0, "ssd_life": 95,
    "sys_manufacturer": "Dell Inc", "log_path": "/logs/BBB222.log",
    "indexed_at": "2026-04-30T11:01:00",
}
r3 = {
    "drive_sn": "CCC333", "system_sn": "SYS002",
    "wipe_date": "2026-04-30", "wipe_datetime": "2026-04-30T12:00:00",
    "duration_min": 10.0, "method": "NIST 800-88 rev1 Purge",
    "result": "PASSED", "health_score": 40.0, "ssd_life": 30,
    "sys_manufacturer": "HP", "log_path": "/logs/CCC333.log",
    "indexed_at": "2026-04-30T12:01:00",
}

assert insert_record(conn, r1) == True,  "first insert should return True"
assert insert_record(conn, r1) == False, "duplicate should return False"
assert insert_record(conn, r2) == True
assert insert_record(conn, r3) == True
print("insert_record OK")

# query_today
today = query_today(conn)
assert len(today) == 3, f"expected 3 today records, got {len(today)}"
print("query_today OK")

# query_period
period = query_period(conn, "2026-04-01", "2026-04-30")
assert len(period) == 3
print("query_period OK")

# query_by_sn
by_sn = query_by_sn(conn, "aaa111")
assert len(by_sn) == 1 and by_sn[0]["drive_sn"] == "AAA111"
by_sys = query_by_sn(conn, "SYS001")
assert len(by_sys) == 2
print("query_by_sn OK")

# stats_summary
records = query_today(conn)
stats = stats_summary(records)
assert stats["total"] == 3
assert stats["passed"] == 2
assert stats["failed"] == 1
# r3: PASSED, health_score=40 (<70) → warning; r1: PASSED, health_score=55 (<70) → warning
assert stats["warning"] == 2, f"expected 2 warnings, got {stats['warning']}"
assert stats["pass_rate"] == 66.7
print(f"stats_summary OK: {stats}")

# by_manufacturer
mfr = by_manufacturer(records)
assert mfr[0]["name"] == "Dell Inc" and mfr[0]["count"] == 2
print(f"by_manufacturer OK: {mfr}")

# fail_reasons
fr = fail_reasons(records)
assert fr[0]["reason"] == "NIST 800-88 rev1 Clear" and fr[0]["count"] == 1
print(f"fail_reasons OK: {fr}")

# scan_status default
status = get_scan_status(conn)
assert status["running"] == 0 and status["total"] == 0
print("get_scan_status (default) OK")

# upsert_scan_status
upsert_scan_status(conn, running=1, total=100, done=0, errors=0, scan_type="full", started_at="2026-04-30T10:00:00")
status = get_scan_status(conn)
assert status["running"] == 1 and status["total"] == 100
assert status["scan_type"] == "full"
assert status["updated_at"] is not None
print(f"upsert_scan_status OK: {status}")

conn.close()
os.unlink(db_path)
print("\nAll tests PASSED")
