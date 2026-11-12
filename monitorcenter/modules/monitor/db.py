"""SQLite storage for the monitor (manual entry) module. Same pattern as modules/console/db.py."""

import json
import sqlite3
from datetime import datetime

_SCHEMA = """
CREATE TABLE IF NOT EXISTS monitor_models (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  manufacturer TEXT NOT NULL,
  model        TEXT NOT NULL,
  size         TEXT,
  UNIQUE(manufacturer, model)
);

CREATE TABLE IF NOT EXISTS monitor_tests (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  traveler_id   TEXT,
  serial_no     TEXT NOT NULL,
  model_id      INTEGER NOT NULL REFERENCES monitor_models(id),
  size          TEXT,
  color         TEXT,
  weight        REAL,
  dead_pixels   INTEGER NOT NULL DEFAULT 0,
  missing_flags TEXT NOT NULL DEFAULT '[]',
  grade         TEXT,
  condition     TEXT,
  functionality TEXT,
  inv_notes     TEXT,
  notes         TEXT,
  result        TEXT NOT NULL,
  marks         TEXT NOT NULL DEFAULT '',
  tested_by     TEXT,
  tested_at     TEXT NOT NULL,
  superseded_by INTEGER
);
CREATE INDEX IF NOT EXISTS idx_mt_serial   ON monitor_tests(serial_no);
CREATE INDEX IF NOT EXISTS idx_mt_traveler ON monitor_tests(traveler_id);
CREATE INDEX IF NOT EXISTS idx_mt_tested   ON monitor_tests(tested_at);

CREATE TABLE IF NOT EXISTS monitor_test_items (
  test_id INTEGER NOT NULL REFERENCES monitor_tests(id) ON DELETE CASCADE,
  code    TEXT NOT NULL,
  label   TEXT NOT NULL,
  type    TEXT NOT NULL,
  status  TEXT NOT NULL,
  PRIMARY KEY (test_id, code)
);

CREATE TABLE IF NOT EXISTS monitor_qc (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  test_id    INTEGER NOT NULL UNIQUE REFERENCES monitor_tests(id),
  status     TEXT NOT NULL,            -- Passed | Rejected
  note       TEXT,
  qc_by      TEXT NOT NULL,            -- QC operator ID
  qc_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mqc_at ON monitor_qc(qc_at);

CREATE TABLE IF NOT EXISTS monitor_audit_log (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  ts      TEXT NOT NULL,
  actor   TEXT,
  action  TEXT NOT NULL,
  test_id INTEGER,
  sn      TEXT,
  detail  TEXT
);
CREATE INDEX IF NOT EXISTS idx_ma_sn ON monitor_audit_log(sn);
"""

_initialized: set[str] = set()


def get_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: str) -> None:
    if db_path in _initialized:
        return
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()
    _initialized.add(db_path)


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def audit(conn, actor, action, test_id=None, sn=None, detail=None) -> None:
    conn.execute(
        "INSERT INTO monitor_audit_log(ts,actor,action,test_id,sn,detail) VALUES (?,?,?,?,?,?)",
        (now_iso(), actor or "", action, test_id, sn,
         json.dumps(detail, ensure_ascii=False) if detail is not None else None))


# ── Models (free-text entry; find-or-create) ────────────────────────────

def list_models(conn) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM monitor_models ORDER BY manufacturer, model")]


def find_model(conn, manufacturer, model) -> dict | None:
    r = conn.execute(
        "SELECT * FROM monitor_models WHERE LOWER(manufacturer)=LOWER(?) AND LOWER(model)=LOWER(?)",
        (manufacturer, model)).fetchone()
    return dict(r) if r else None


def get_or_create_model(conn, manufacturer, model, size) -> tuple[int, bool]:
    """Returns (model_id, created). Remembers the size on first use. Caller commits."""
    found = find_model(conn, manufacturer, model)
    if found:
        if size and not found["size"]:
            conn.execute("UPDATE monitor_models SET size=? WHERE id=?", (size, found["id"]))
        return found["id"], False
    mid = conn.execute("INSERT INTO monitor_models(manufacturer,model,size) VALUES (?,?,?)",
                       (manufacturer, model, size or None)).lastrowid
    return mid, True


# ── Tests ───────────────────────────────────────────────────────────────

def insert_test(conn, data: dict, tested_at: str) -> int:
    """Insert a test + items and supersede earlier live records of the same SN. Caller commits."""
    tid = conn.execute(
        "INSERT INTO monitor_tests(traveler_id,serial_no,model_id,size,color,weight,dead_pixels,"
        "missing_flags,grade,condition,functionality,inv_notes,notes,result,marks,tested_by,tested_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (data["traveler_id"] or None, data["serial_no"], data["model_id"], data["size"] or None,
         data["color"] or None, data["weight"], data["dead_pixels"],
         json.dumps(data["missing"], ensure_ascii=False), data["grade"] or None,
         data["condition"] or None, data["functionality"] or None, data["inv_notes"] or None,
         data["notes"] or None, data["result"], data["marks"], data["operator"] or None,
         tested_at)).lastrowid
    conn.executemany(
        "INSERT INTO monitor_test_items(test_id,code,label,type,status) VALUES (?,?,?,?,?)",
        [(tid, i["code"], i["label"], i["type"], i["status"]) for i in data["items"]])
    data["_superseded"] = conn.execute(
        "UPDATE monitor_tests SET superseded_by=? WHERE id<>? AND superseded_by IS NULL "
        "AND UPPER(serial_no)=UPPER(?)", (tid, tid, data["serial_no"])).rowcount
    return tid


def active_by_serial(conn, serial_no) -> dict | None:
    r = conn.execute(
        "SELECT t.*, m.manufacturer, m.model FROM monitor_tests t "
        "JOIN monitor_models m ON m.id=t.model_id "
        "WHERE UPPER(t.serial_no)=UPPER(?) AND t.superseded_by IS NULL "
        "ORDER BY t.id DESC LIMIT 1", (serial_no,)).fetchone()
    return dict(r) if r else None


def get_test(conn, test_id) -> dict | None:
    r = conn.execute(
        "SELECT t.*, m.manufacturer, m.model FROM monitor_tests t "
        "JOIN monitor_models m ON m.id=t.model_id WHERE t.id=?", (test_id,)).fetchone()
    return dict(r) if r else None


def test_items(conn, test_id) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM monitor_test_items WHERE test_id=? ORDER BY (type='key') DESC, rowid", (test_id,))]


def query_tests(conn, date_from=None, date_to=None, result=None, q=None,
                include_superseded=False, limit=500) -> list[dict]:
    sql = ("SELECT t.*, m.manufacturer, m.model, c.status AS qc_status FROM monitor_tests t "
           "JOIN monitor_models m ON m.id=t.model_id "
           "LEFT JOIN monitor_qc c ON c.test_id=t.id WHERE 1=1")
    args: list = []
    if not include_superseded:
        sql += " AND t.superseded_by IS NULL"
    if date_from:
        sql += " AND date(t.tested_at) >= ?"; args.append(date_from)
    if date_to:
        sql += " AND date(t.tested_at) <= ?"; args.append(date_to)
    if result:
        sql += " AND t.result = ?"; args.append(result)
    if q:
        sql += (" AND (UPPER(t.serial_no) LIKE ? OR UPPER(t.traveler_id) LIKE ? "
                "OR UPPER(m.manufacturer || ' ' || m.model) LIKE ?)")
        p = f"%{q.upper()}%"; args += [p, p, p]
    sql += " ORDER BY t.tested_at DESC, t.id DESC LIMIT ?"
    args.append(limit)
    return [dict(r) for r in conn.execute(sql, args)]


def period_stats(conn, d_from: str, d_to: str, max_dead: int = 2) -> dict:
    """Stats for the latest test per SN (superseded excluded) tested in [d_from, d_to]."""
    from datetime import date, timedelta
    rows = [dict(r) for r in conn.execute(
        "SELECT t.id, date(t.tested_at) AS d, t.result, t.dead_pixels, m.manufacturer, m.model "
        "FROM monitor_tests t JOIN monitor_models m ON m.id=t.model_id "
        "WHERE t.superseded_by IS NULL AND date(t.tested_at) BETWEEN ? AND ?", (d_from, d_to))]
    total = len(rows)
    passed = sum(1 for r in rows if r["result"] == "Pass")

    start, end = date.fromisoformat(d_from), date.fromisoformat(d_to)
    daily, cur = {}, start
    while cur <= end:
        daily[str(cur)] = {"date": str(cur), "pass": 0, "fail": 0}
        cur += timedelta(days=1)
    by_model: dict = {}
    for r in rows:
        k = "pass" if r["result"] == "Pass" else "fail"
        daily[r["d"]][k] += 1
        name = f"{r['manufacturer']} {r['model']}"
        m = by_model.setdefault(name, {"model": name, "pass": 0, "fail": 0})
        m[k] += 1

    # Fail reasons: failed key items, plus too many dead pixels
    reasons: dict = {}
    failed = [r for r in rows if r["result"] != "Pass"]
    for r in failed:
        if (r["dead_pixels"] or 0) > max_dead:
            reasons["Dead pixels"] = reasons.get("Dead pixels", 0) + 1
    if failed:
        ids = [r["id"] for r in failed]
        q = ("SELECT label, COUNT(*) AS n FROM monitor_test_items WHERE type='key' AND status='Fail' "
             "AND test_id IN (%s) GROUP BY label" % ",".join("?" * len(ids)))
        for lab, n in conn.execute(q, ids):
            reasons[lab] = reasons.get(lab, 0) + n

    days = len(daily)
    return {
        "start": d_from, "end": d_to,
        "summary": {"total": total, "pass": passed, "fail": total - passed,
                    "pass_rate": round(100 * passed / total, 1) if total else None,
                    "avg_per_day": round(total / days, 1) if days else 0},
        "daily": list(daily.values()),
        "by_model": sorted(by_model.values(), key=lambda x: -(x["pass"] + x["fail"])),
        "fail_reasons": [{"reason": k, "count": v}
                         for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])],
    }


def test_timeline(conn, test) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM monitor_audit_log WHERE test_id=? OR UPPER(sn)=UPPER(?) ORDER BY id",
        (test["id"], test["serial_no"]))]


# ── QC (manual, by a separate QC operator) ──────────────────────────────

def qc_get(conn, test_id) -> dict | None:
    r = conn.execute("SELECT * FROM monitor_qc WHERE test_id=?", (test_id,)).fetchone()
    return dict(r) if r else None


def qc_upsert(conn, test_id, status, note, who) -> None:
    """One QC result per test; re-QC replaces it (the audit log keeps the history). Caller commits."""
    conn.execute(
        "INSERT INTO monitor_qc(test_id,status,note,qc_by,qc_at) VALUES (?,?,?,?,?) "
        "ON CONFLICT(test_id) DO UPDATE SET status=excluded.status, note=excluded.note, "
        "qc_by=excluded.qc_by, qc_at=excluded.qc_at",
        (test_id, status, note or None, who, now_iso()))


def qc_list(conn, d_from=None, d_to=None, status=None, qc_by=None) -> list[dict]:
    sql = ("SELECT c.*, t.serial_no, t.traveler_id, t.result AS test_result, t.marks, t.tested_at, "
           "t.tested_by, m.manufacturer, m.model FROM monitor_qc c "
           "JOIN monitor_tests t ON t.id=c.test_id JOIN monitor_models m ON m.id=t.model_id WHERE 1=1")
    args: list = []
    if d_from:
        sql += " AND date(c.qc_at) >= ?"; args.append(d_from)
    if d_to:
        sql += " AND date(c.qc_at) <= ?"; args.append(d_to)
    if status:
        sql += " AND c.status = ?"; args.append(status)
    if qc_by:
        sql += " AND UPPER(c.qc_by) = UPPER(?)"; args.append(qc_by)
    sql += " ORDER BY c.qc_at DESC, c.id DESC LIMIT 1000"
    return [dict(r) for r in conn.execute(sql, args)]


def qc_counts(conn, d_from, d_to) -> dict:
    """QC results in range, plus latest-per-SN tests in the same range for a rough coverage figure."""
    r = conn.execute(
        "SELECT COUNT(*), SUM(status='Passed'), SUM(status='Rejected') FROM monitor_qc "
        "WHERE date(qc_at) BETWEEN ? AND ?", (d_from, d_to)).fetchone()
    tested = conn.execute(
        "SELECT COUNT(*) FROM monitor_tests WHERE superseded_by IS NULL "
        "AND date(tested_at) BETWEEN ? AND ?", (d_from, d_to)).fetchone()[0]
    return {"qc": r[0] or 0, "passed": r[1] or 0, "rejected": r[2] or 0, "tested": tested}


# ── Cross-module hooks used by app.py (search + home-page counts) ───────

def count_unique_sn(db_path, d_from, d_to) -> int:
    conn = get_conn(db_path)
    try:
        return conn.execute(
            "SELECT COUNT(DISTINCT UPPER(serial_no)) FROM monitor_tests "
            "WHERE date(tested_at) BETWEEN ? AND ?", (d_from, d_to)).fetchone()[0]
    finally:
        conn.close()


def search(db_path, sn) -> list[dict]:
    conn = get_conn(db_path)
    try:
        return query_tests(conn, q=sn, include_superseded=True, limit=100)
    finally:
        conn.close()
