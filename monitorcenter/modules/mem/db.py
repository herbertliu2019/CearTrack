"""SQLite storage for the mem (MemTest86) module.

Concurrency pattern follows modules/wipe/db.py (not modules/cpu/db.py,
which lacks it): journal_mode=WAL is set exactly once at init time (it's
persisted in the DB file itself), and every connection gets a 30s connect
timeout + PRAGMA busy_timeout so a concurrent gunicorn worker never sees a
bare "database is locked" error.
"""

import sqlite3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS mem_reports (
  report_uid        TEXT PRIMARY KEY,
  file_sha256       TEXT NOT NULL UNIQUE,
  source_dir        TEXT NOT NULL,
  source_file       TEXT NOT NULL,
  source_full_path  TEXT NOT NULL,
  archived_path     TEXT,
  file_mtime        TEXT,
  imported_at       TEXT NOT NULL,

  report_date       TEXT,
  generated_by      TEXT,
  overall_result    TEXT,
  system_mfr        TEXT,
  system_product    TEXT,
  system_sn         TEXT,
  baseboard_mfr     TEXT,
  baseboard_product TEXT,
  baseboard_sn      TEXT,
  cpu_type          TEXT,
  ram_config        TEXT,

  slots_count       INTEGER,
  modules_count     INTEGER,
  test_start        TEXT,
  test_date         TEXT,
  elapsed           TEXT,
  elapsed_sec       INTEGER,
  mem_range         TEXT,
  mem_size_mb       INTEGER,
  cpu_sel_mode      TEXT,
  cpu_temp_min      INTEGER,
  cpu_temp_max      INTEGER,
  cpu_temp_avg      INTEGER,
  mem_speed_low     TEXT,
  mem_speed_high    TEXT,
  ecc_polling       TEXT,
  tests_completed   TEXT,
  tests_passed      TEXT,
  ecc_ce            INTEGER DEFAULT 0,
  ecc_ue            INTEGER DEFAULT 0,

  has_unattributed_errors INTEGER DEFAULT 0,
  unparsed_error_lines    INTEGER DEFAULT 0,
  parse_ok          INTEGER DEFAULT 1,
  parse_note        TEXT,
  excluded          INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_rep_date ON mem_reports(test_date);
CREATE INDEX IF NOT EXISTS idx_rep_sysn ON mem_reports(system_sn);

CREATE TABLE IF NOT EXISTS mem_module_tests (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  report_uid     TEXT NOT NULL REFERENCES mem_reports(report_uid) ON DELETE CASCADE,
  module_sn      TEXT NOT NULL,
  dimm_slot      TEXT,
  channel        INTEGER,
  spd_slot       INTEGER,
  size_gb        INTEGER,
  mem_type       TEXT,
  rank_org       TEXT,
  is_ecc         INTEGER,
  pc_class       TEXT,
  spec_raw       TEXT,
  vendor         TEXT,
  part_number    TEXT,
  smbios_profile TEXT,
  test_start     TEXT NOT NULL,
  test_date      TEXT NOT NULL,
  module_status  TEXT NOT NULL,
  err_total      INTEGER DEFAULT 0,
  err_ecc_ce     INTEGER DEFAULT 0,
  err_ecc_ue     INTEGER DEFAULT 0,
  parse_ok       INTEGER DEFAULT 1,
  UNIQUE(report_uid, module_sn, dimm_slot)
);
CREATE INDEX IF NOT EXISTS idx_mt_sn     ON mem_module_tests(module_sn);
CREATE INDEX IF NOT EXISTS idx_mt_date   ON mem_module_tests(test_date);
CREATE INDEX IF NOT EXISTS idx_mt_status ON mem_module_tests(module_status);

CREATE TABLE IF NOT EXISTS mem_modules (
  module_sn        TEXT PRIMARY KEY,
  vendor           TEXT,
  part_number      TEXT,
  size_gb          INTEGER,
  mem_type         TEXT,
  rank_org         TEXT,
  is_ecc           INTEGER,
  pc_class         TEXT,
  smbios_profile   TEXT,
  first_tested_at  TEXT,
  last_tested_at   TEXT,
  last_report_uid  TEXT,
  last_dimm_slot   TEXT,
  test_count       INTEGER DEFAULT 0,
  current_status   TEXT,
  ever_fail        INTEGER DEFAULT 0,
  ever_warn        INTEGER DEFAULT 0,
  package_id       INTEGER,
  note             TEXT
);
CREATE INDEX IF NOT EXISTS idx_mod_status ON mem_modules(current_status);
CREATE INDEX IF NOT EXISTS idx_mod_last   ON mem_modules(last_tested_at);
CREATE INDEX IF NOT EXISTS idx_mod_vendor ON mem_modules(vendor);
CREATE INDEX IF NOT EXISTS idx_mod_size   ON mem_modules(size_gb);

CREATE TABLE IF NOT EXISTS mem_tests (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  report_uid  TEXT NOT NULL REFERENCES mem_reports(report_uid) ON DELETE CASCADE,
  test_no     INTEGER,
  test_name   TEXT,
  passed_raw  TEXT,
  passed_pct  INTEGER,
  errors      INTEGER
);
CREATE INDEX IF NOT EXISTS idx_tests_rep ON mem_tests(report_uid);

CREATE TABLE IF NOT EXISTS mem_errors (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  report_uid     TEXT NOT NULL REFERENCES mem_reports(report_uid) ON DELETE CASCADE,
  err_time       TEXT,
  err_type       TEXT,
  test_no        INTEGER,
  channel        INTEGER, slot INTEGER, rank INTEGER,
  bank           INTEGER, row INTEGER, col INTEGER,
  ecc_corrected  INTEGER,
  syndrome       TEXT,
  channel_slot   TEXT,
  module_sn      TEXT,
  raw_line       TEXT NOT NULL,
  parse_ok       INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_err_sn  ON mem_errors(module_sn);
CREATE INDEX IF NOT EXISTS idx_err_rep ON mem_errors(report_uid);

CREATE TABLE IF NOT EXISTS mem_dimm_issues (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  report_uid  TEXT NOT NULL REFERENCES mem_reports(report_uid) ON DELETE CASCADE,
  dimm_slot   TEXT,
  spec_raw    TEXT,
  reason      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dimm_issues_rep ON mem_dimm_issues(report_uid);

-- Phase 5 (package + Cyclelution export) — schema reserved now, unused
-- until the package UI/API ships. See TASK_memory_module.md §9.
CREATE TABLE IF NOT EXISTS mem_packages (
  package_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  package_no     TEXT UNIQUE NOT NULL,
  status         TEXT NOT NULL,
  spec_size_gb   INTEGER,
  spec_mem_type  TEXT,
  spec_is_ecc    INTEGER,
  spec_speed     TEXT,
  grade          TEXT,
  data_sanitization TEXT DEFAULT 'ND-No Data',
  location       TEXT DEFAULT 'Testing Area',
  qty            INTEGER DEFAULT 0,
  weight_calc_lb REAL,
  weight_final_lb REAL,
  weight_overridden INTEGER DEFAULT 0,
  created_at     TEXT, created_by  TEXT,
  sealed_at      TEXT, sealed_by   TEXT,
  exported_at    TEXT, exported_by TEXT,
  export_batch   TEXT,
  cyclelution_tid TEXT,
  voided_at      TEXT, voided_by  TEXT, void_reason TEXT,
  note           TEXT
);
CREATE INDEX IF NOT EXISTS idx_pkg_status ON mem_packages(status);
CREATE INDEX IF NOT EXISTS idx_pkg_tid    ON mem_packages(cyclelution_tid);

CREATE TABLE IF NOT EXISTS mem_package_members (
  package_id  INTEGER NOT NULL REFERENCES mem_packages(package_id),
  module_sn   TEXT NOT NULL,
  added_at    TEXT NOT NULL,
  added_by    TEXT,
  PRIMARY KEY (package_id, module_sn)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_pm_sn_active ON mem_package_members(module_sn);

CREATE TABLE IF NOT EXISTS mem_package_events (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  package_id INTEGER NOT NULL,
  ts         TEXT NOT NULL,
  actor      TEXT,
  action     TEXT NOT NULL,
  detail     TEXT
);
CREATE INDEX IF NOT EXISTS idx_pe_pkg ON mem_package_events(package_id);

CREATE TABLE IF NOT EXISTS scan_status (
  id              INTEGER PRIMARY KEY CHECK (id = 1),
  status          TEXT DEFAULT 'idle',
  started_at      TEXT,
  finished_at     TEXT,
  total           INTEGER DEFAULT 0,
  done            INTEGER DEFAULT 0,
  inserted        INTEGER DEFAULT 0,
  skipped         INTEGER DEFAULT 0,
  errors          INTEGER DEFAULT 0,
  mount_ok        INTEGER DEFAULT 1,
  mount_error     TEXT,
  mount_checked_at TEXT
);

CREATE TABLE IF NOT EXISTS scan_errors (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  ts          TEXT NOT NULL,
  path        TEXT,
  reason      TEXT NOT NULL
);

-- Every file pushed via POST /mem/api/upload (any type), keyed by content
-- hash so a re-upload of the same bytes is recognised regardless of name/day.
CREATE TABLE IF NOT EXISTS mem_uploads (
  file_sha256  TEXT PRIMARY KEY,
  filename     TEXT NOT NULL,
  saved_as     TEXT NOT NULL,
  uploaded_at  TEXT NOT NULL
);
"""

_initialized: set[str] = set()


def init_db(db_path: str) -> None:
    if db_path in _initialized:
        return
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute("PRAGMA busy_timeout=30000")
        # journal_mode is persisted in the db file itself (unlike synchronous/
        # busy_timeout, which are per-connection) — set once here rather than
        # on every get_conn() call. See modules/wipe/db.py for the incident
        # this pattern fixes (spurious "disk I/O error" under write load).
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()
    _initialized.add(db_path)


def get_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _rows_to_dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Client uploads (dedup by content hash)
# ---------------------------------------------------------------------------

def find_upload(db_path: str, file_sha256: str) -> dict | None:
    conn = get_conn(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM mem_uploads WHERE file_sha256 = ?", (file_sha256,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def record_upload(db_path: str, file_sha256: str, filename: str,
                  saved_as: str, uploaded_at: str) -> bool:
    """Returns False if another request already recorded this hash (race)."""
    conn = get_conn(db_path)
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO mem_uploads (file_sha256, filename, saved_as, uploaded_at) "
            "VALUES (?, ?, ?, ?)",
            (file_sha256, filename, saved_as, uploaded_at),
        )
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Report ingest
# ---------------------------------------------------------------------------

def find_report_by_hash(conn: sqlite3.Connection, file_sha256: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM mem_reports WHERE file_sha256 = ?", (file_sha256,)
    ).fetchone()
    return dict(row) if row else None


def update_report_source(conn: sqlite3.Connection, report_uid: str, source_dir: str,
                          source_file: str, source_full_path: str, file_mtime: str) -> None:
    """A file was renamed/moved but content is unchanged — update location only."""
    conn.execute(
        """UPDATE mem_reports
           SET source_dir=?, source_file=?, source_full_path=?, file_mtime=?
           WHERE report_uid=?""",
        (source_dir, source_file, source_full_path, file_mtime, report_uid),
    )
    conn.commit()


def upsert_report(conn: sqlite3.Connection, report: dict, excluded: bool = False) -> None:
    """Insert a new report, or overwrite an existing report_uid whose
    file_sha256 changed (re-exported report) — cascades to child tables."""
    conn.execute("DELETE FROM mem_reports WHERE report_uid = ?", (report["report_uid"],))

    fields = [
        "report_uid", "file_sha256", "source_dir", "source_file", "source_full_path",
        "archived_path", "file_mtime", "imported_at",
        "report_date", "generated_by", "overall_result",
        "system_mfr", "system_product", "system_sn",
        "baseboard_mfr", "baseboard_product", "baseboard_sn",
        "cpu_type", "ram_config",
        "slots_count", "modules_count", "test_start", "test_date",
        "elapsed", "elapsed_sec", "mem_range", "mem_size_mb", "cpu_sel_mode",
        "cpu_temp_min", "cpu_temp_max", "cpu_temp_avg",
        "mem_speed_low", "mem_speed_high", "ecc_polling",
        "tests_completed", "tests_passed", "ecc_ce", "ecc_ue",
        "has_unattributed_errors", "unparsed_error_lines", "parse_ok", "parse_note",
        "excluded",
    ]
    values = [report.get(f) for f in fields]
    placeholders = ", ".join("?" * len(fields))
    conn.execute(
        f"INSERT INTO mem_reports ({', '.join(fields)}) VALUES ({placeholders})",
        values,
    )

    for t in report.get("tests", []):
        conn.execute(
            """INSERT INTO mem_tests (report_uid, test_no, test_name, passed_raw, passed_pct, errors)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (report["report_uid"], t.get("test_no"), t.get("test_name"),
             t.get("passed_raw"), t.get("passed_pct"), t.get("errors")),
        )

    for e in report.get("errors", []):
        conn.execute(
            """INSERT INTO mem_errors
               (report_uid, err_time, err_type, test_no, channel, slot, rank, bank, row, col,
                ecc_corrected, syndrome, channel_slot, module_sn, raw_line, parse_ok)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (report["report_uid"], e.get("err_time"), e.get("err_type"), e.get("test_no"),
             e.get("channel"), e.get("slot"), e.get("rank"), e.get("bank"), e.get("row"), e.get("col"),
             e.get("ecc_corrected"), e.get("syndrome"), e.get("channel_slot"),
             e.get("module_sn"), e.get("raw_line"), e.get("parse_ok")),
        )

    for d in report.get("modules_failed", []):
        conn.execute(
            """INSERT INTO mem_dimm_issues (report_uid, dimm_slot, spec_raw, reason)
               VALUES (?, ?, ?, ?)""",
            (report["report_uid"], d.get("dimm_slot"), d.get("spec_raw"),
             "missing or invalid module_sn/vendor — DIMM not imported"),
        )

    for m in report.get("modules", []):
        st = report["_statuses"].get(m["module_sn"], {})
        conn.execute(
            """INSERT INTO mem_module_tests
               (report_uid, module_sn, dimm_slot, channel, spd_slot, size_gb, mem_type,
                rank_org, is_ecc, pc_class, spec_raw, vendor, part_number, smbios_profile,
                test_start, test_date, module_status, err_total, err_ecc_ce, err_ecc_ue, parse_ok)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (report["report_uid"], m["module_sn"], m.get("dimm_slot"),
             (report.get("spd_map", {}).get(m["module_sn"]) or {}).get("channel"),
             (report.get("spd_map", {}).get(m["module_sn"]) or {}).get("slot"),
             m.get("size_gb"), m.get("mem_type"), m.get("rank_org"), m.get("is_ecc"),
             m.get("pc_class"), m.get("spec_raw"), m.get("vendor"), m.get("part_number"),
             m.get("smbios_profile"), report.get("test_start"), report.get("test_date"),
             st.get("status", "PASS"), st.get("err_total", 0), st.get("err_ecc_ce", 0),
             st.get("err_ecc_ue", 0), 1),
        )

    conn.commit()


def recompute_module(conn: sqlite3.Connection, module_sn: str) -> None:
    """Rebuild mem_modules aggregate for one SN from its full test history.
    Materialized (not computed at page load) per the spec's red line #3."""
    rows = conn.execute(
        """SELECT * FROM mem_module_tests
           WHERE module_sn = ?
             AND report_uid IN (SELECT report_uid FROM mem_reports WHERE excluded = 0)
           ORDER BY test_start ASC""",
        (module_sn,),
    ).fetchall()

    if not rows:
        conn.execute("DELETE FROM mem_modules WHERE module_sn = ?", (module_sn,))
        conn.commit()
        return

    latest = rows[-1]
    first = rows[0]
    ever_fail = any(r["module_status"] in ("FAIL", "SUSPECT") for r in rows)
    ever_warn = any(r["module_status"] == "WARN" for r in rows)

    conn.execute(
        """INSERT INTO mem_modules
           (module_sn, vendor, part_number, size_gb, mem_type, rank_org, is_ecc, pc_class,
            smbios_profile, first_tested_at, last_tested_at, last_report_uid, last_dimm_slot,
            test_count, current_status, ever_fail, ever_warn)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(module_sn) DO UPDATE SET
             vendor=excluded.vendor, part_number=excluded.part_number, size_gb=excluded.size_gb,
             mem_type=excluded.mem_type, rank_org=excluded.rank_org, is_ecc=excluded.is_ecc,
             pc_class=excluded.pc_class, smbios_profile=excluded.smbios_profile,
             first_tested_at=excluded.first_tested_at, last_tested_at=excluded.last_tested_at,
             last_report_uid=excluded.last_report_uid, last_dimm_slot=excluded.last_dimm_slot,
             test_count=excluded.test_count, current_status=excluded.current_status,
             ever_fail=excluded.ever_fail, ever_warn=excluded.ever_warn""",
        (module_sn, latest["vendor"], latest["part_number"], latest["size_gb"],
         latest["mem_type"], latest["rank_org"], latest["is_ecc"], latest["pc_class"],
         latest["smbios_profile"], first["test_start"], latest["test_start"],
         latest["report_uid"], latest["dimm_slot"], len(rows), latest["module_status"],
         1 if ever_fail else 0, 1 if ever_warn else 0),
    )
    conn.commit()


def delete_report_and_recompute(conn: sqlite3.Connection, report_uid: str) -> list[str]:
    """Used when a report_uid is being overwritten by a re-export. Returns
    the list of module_sn that need mem_modules recomputed afterward."""
    rows = conn.execute(
        "SELECT DISTINCT module_sn FROM mem_module_tests WHERE report_uid = ?", (report_uid,)
    ).fetchall()
    return [r["module_sn"] for r in rows]


# ---------------------------------------------------------------------------
# Queries — DIMMS tab
# ---------------------------------------------------------------------------

def query_modules(db_path: str, status: str | None = None, ever_err: str | None = None,
                   size_gb: int | None = None, mem_type: str | None = None,
                   vendor: str | None = None, q: str | None = None,
                   page: int = 1, per_page: int = 50) -> tuple[list[dict], int]:
    conn = get_conn(db_path)
    try:
        where = []
        params: list = []
        if status:
            where.append("current_status = ?")
            params.append(status)
        if ever_err == "yes":
            where.append("(ever_fail = 1 OR ever_warn = 1)")
        elif ever_err == "no":
            where.append("(ever_fail = 0 AND ever_warn = 0)")
        if size_gb:
            where.append("size_gb = ?")
            params.append(size_gb)
        if mem_type:
            where.append("mem_type = ?")
            params.append(mem_type)
        if vendor:
            where.append("vendor = ?")
            params.append(vendor)
        if q:
            where.append("(UPPER(module_sn) LIKE UPPER(?) OR UPPER(part_number) LIKE UPPER(?))")
            params.extend([f"%{q}%", f"%{q}%"])

        clause = f"WHERE {' AND '.join(where)}" if where else ""
        total = conn.execute(f"SELECT COUNT(*) FROM mem_modules {clause}", params).fetchone()[0]

        per_page = min(500, max(1, per_page))
        offset = (max(1, page) - 1) * per_page
        rows = conn.execute(
            f"""SELECT * FROM mem_modules {clause}
                ORDER BY last_tested_at DESC
                LIMIT ? OFFSET ?""",
            [*params, per_page, offset],
        ).fetchall()
        return _rows_to_dicts(rows), total
    finally:
        conn.close()


def query_module_detail(db_path: str, module_sn: str) -> dict | None:
    conn = get_conn(db_path)
    try:
        module = conn.execute(
            "SELECT * FROM mem_modules WHERE module_sn = ?", (module_sn.upper(),)
        ).fetchone()
        if not module:
            return None
        tests = conn.execute(
            """SELECT mt.*, r.source_dir, r.source_file, r.source_full_path,
                      r.system_mfr, r.system_product, r.system_sn
               FROM mem_module_tests mt
               JOIN mem_reports r ON r.report_uid = mt.report_uid
               WHERE mt.module_sn = ?
               ORDER BY mt.test_start DESC""",
            (module_sn.upper(),),
        ).fetchall()
        test_dicts = _rows_to_dicts(tests)
        for t in test_dicts:
            errs = conn.execute(
                "SELECT * FROM mem_errors WHERE report_uid = ? AND module_sn = ? ORDER BY err_time",
                (t["report_uid"], module_sn.upper()),
            ).fetchall()
            t["errors"] = _rows_to_dicts(errs)
        return {"module": dict(module), "tests": test_dicts}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Queries — REPORTS tab
# ---------------------------------------------------------------------------

def query_reports(db_path: str, start: str | None = None, end: str | None = None,
                   q: str | None = None, page: int = 1, per_page: int = 50) -> tuple[list[dict], int]:
    conn = get_conn(db_path)
    try:
        where = ["excluded = 0"]
        params: list = []
        if start and end:
            where.append("test_date BETWEEN ? AND ?")
            params.extend([start, end])
        if q:
            where.append(
                "(UPPER(system_sn) LIKE UPPER(?) OR UPPER(source_file) LIKE UPPER(?) "
                "OR report_uid IN (SELECT report_uid FROM mem_module_tests WHERE UPPER(module_sn) LIKE UPPER(?)))"
            )
            params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
        clause = f"WHERE {' AND '.join(where)}"
        total = conn.execute(f"SELECT COUNT(*) FROM mem_reports {clause}", params).fetchone()[0]

        per_page = min(500, max(1, per_page))
        offset = (max(1, page) - 1) * per_page
        rows = conn.execute(
            f"""SELECT * FROM mem_reports {clause}
                ORDER BY test_start DESC
                LIMIT ? OFFSET ?""",
            [*params, per_page, offset],
        ).fetchall()
        return _rows_to_dicts(rows), total
    finally:
        conn.close()


def query_report_detail(db_path: str, report_uid: str) -> dict | None:
    conn = get_conn(db_path)
    try:
        report = conn.execute("SELECT * FROM mem_reports WHERE report_uid = ?", (report_uid,)).fetchone()
        if not report:
            return None
        modules = conn.execute(
            "SELECT * FROM mem_module_tests WHERE report_uid = ? ORDER BY dimm_slot",
            (report_uid,),
        ).fetchall()
        tests = conn.execute(
            "SELECT * FROM mem_tests WHERE report_uid = ? ORDER BY test_no", (report_uid,)
        ).fetchall()
        errors = conn.execute(
            "SELECT * FROM mem_errors WHERE report_uid = ? ORDER BY err_time", (report_uid,)
        ).fetchall()
        issues = conn.execute(
            "SELECT * FROM mem_dimm_issues WHERE report_uid = ?", (report_uid,)
        ).fetchall()
        return {
            "report": dict(report),
            "modules": _rows_to_dicts(modules),
            "tests": _rows_to_dicts(tests),
            "errors": _rows_to_dicts(errors),
            "dimm_issues": _rows_to_dicts(issues),
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Summary / stats widgets
# ---------------------------------------------------------------------------

def stats_summary(db_path: str, start: str, end: str) -> dict:
    conn = get_conn(db_path)
    try:
        row = conn.execute(
            """SELECT
                COUNT(*)                                                AS total,
                SUM(CASE WHEN module_status='PASS' THEN 1 ELSE 0 END)    AS pass_count,
                SUM(CASE WHEN module_status='WARN' THEN 1 ELSE 0 END)    AS warn_count,
                SUM(CASE WHEN module_status='FAIL' THEN 1 ELSE 0 END)    AS fail_count,
                SUM(CASE WHEN module_status='SUSPECT' THEN 1 ELSE 0 END) AS suspect_count,
                SUM(COALESCE(size_gb,0))                                 AS total_capacity_gb
               FROM mem_module_tests
               WHERE test_date BETWEEN ? AND ?
                 AND report_uid IN (SELECT report_uid FROM mem_reports WHERE excluded = 0)""",
            (start, end),
        ).fetchone()
        return {
            "total":            row["total"] or 0,
            "pass_count":       row["pass_count"] or 0,
            "warn_count":       row["warn_count"] or 0,
            "fail_count":       row["fail_count"] or 0,
            "suspect_count":    row["suspect_count"] or 0,
            "total_capacity_gb": row["total_capacity_gb"] or 0,
        }
    finally:
        conn.close()


def total_all_time(db_path: str) -> int:
    conn = get_conn(db_path)
    try:
        return conn.execute(
            f"SELECT COUNT(*) FROM mem_module_tests WHERE {_NOT_EXCLUDED}"
        ).fetchone()[0] or 0
    finally:
        conn.close()


_NOT_EXCLUDED = "report_uid IN (SELECT report_uid FROM mem_reports WHERE excluded = 0)"


def by_capacity(db_path: str, start: str, end: str) -> list[dict]:
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            f"""SELECT size_gb, COUNT(*) AS count FROM mem_module_tests
               WHERE test_date BETWEEN ? AND ? AND size_gb IS NOT NULL AND {_NOT_EXCLUDED}
               GROUP BY size_gb ORDER BY count DESC""",
            (start, end),
        ).fetchall()
        return _rows_to_dicts(rows)
    finally:
        conn.close()


def by_type(db_path: str, start: str, end: str) -> list[dict]:
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            f"""SELECT mem_type, is_ecc, COUNT(*) AS count FROM mem_module_tests
               WHERE test_date BETWEEN ? AND ? AND mem_type IS NOT NULL AND {_NOT_EXCLUDED}
               GROUP BY mem_type, is_ecc ORDER BY count DESC""",
            (start, end),
        ).fetchall()
        return _rows_to_dicts(rows)
    finally:
        conn.close()


def by_vendor(db_path: str, start: str, end: str) -> list[dict]:
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            f"""SELECT vendor, COUNT(*) AS count FROM mem_module_tests
               WHERE test_date BETWEEN ? AND ? AND vendor IS NOT NULL AND {_NOT_EXCLUDED}
               GROUP BY vendor ORDER BY count DESC""",
            (start, end),
        ).fetchall()
        return _rows_to_dicts(rows)
    finally:
        conn.close()


def top_part_numbers(db_path: str, start: str, end: str) -> list[dict]:
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            f"""SELECT part_number, COUNT(*) AS count FROM mem_module_tests
               WHERE test_date BETWEEN ? AND ? AND part_number IS NOT NULL AND {_NOT_EXCLUDED}
               GROUP BY part_number ORDER BY count DESC LIMIT 15""",
            (start, end),
        ).fetchall()
        return _rows_to_dicts(rows)
    finally:
        conn.close()


def daily_counts(db_path: str, start: str, end: str) -> list[dict]:
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            f"""SELECT test_date AS date,
                      COUNT(DISTINCT report_uid) AS reports,
                      COUNT(*) AS dimms,
                      SUM(CASE WHEN module_status='PASS' THEN 1 ELSE 0 END) AS passed,
                      SUM(CASE WHEN module_status='WARN' THEN 1 ELSE 0 END) AS warn,
                      SUM(CASE WHEN module_status IN ('FAIL','SUSPECT') THEN 1 ELSE 0 END) AS failed
               FROM mem_module_tests
               WHERE test_date BETWEEN ? AND ? AND {_NOT_EXCLUDED}
               GROUP BY test_date ORDER BY test_date ASC""",
            (start, end),
        ).fetchall()
        return _rows_to_dicts(rows)
    finally:
        conn.close()


def query_day(db_path: str, date_str: str) -> list[dict]:
    """Used by the Daily Breakdown expand — every DIMM tested on one date."""
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            """SELECT mt.*, r.source_dir, r.source_file, r.system_sn
               FROM mem_module_tests mt
               JOIN mem_reports r ON r.report_uid = mt.report_uid
               WHERE mt.test_date = ? AND r.excluded = 0
               ORDER BY mt.test_start DESC, mt.dimm_slot""",
            (date_str,),
        ).fetchall()
        return _rows_to_dicts(rows)
    finally:
        conn.close()


def packageable_stats(db_path: str) -> dict:
    """Phase 5 placeholder stat: PASS modules not yet in a package."""
    conn = get_conn(db_path)
    try:
        row = conn.execute(
            """SELECT COUNT(*) AS count, SUM(COALESCE(size_gb,0)) AS total_capacity_gb
               FROM mem_modules WHERE current_status = 'PASS' AND package_id IS NULL"""
        ).fetchone()
        retest_row = conn.execute(
            """SELECT COUNT(*) AS count FROM mem_modules
               WHERE current_status IN ('WARN','FAIL','SUSPECT') AND package_id IS NULL"""
        ).fetchone()
        return {
            "packageable_count": row["count"] or 0,
            "packageable_capacity_gb": row["total_capacity_gb"] or 0,
            "needs_retest_count": retest_row["count"] or 0,
        }
    finally:
        conn.close()


def parse_issues(db_path: str) -> dict:
    conn = get_conn(db_path)
    try:
        bad_reports = conn.execute(
            """SELECT report_uid, source_file, source_dir, unparsed_error_lines, parse_note
               FROM mem_reports WHERE parse_ok = 0 OR unparsed_error_lines > 0"""
        ).fetchall()
        dimm_issues = conn.execute(
            """SELECT di.*, r.source_file, r.source_dir
               FROM mem_dimm_issues di
               JOIN mem_reports r ON r.report_uid = di.report_uid"""
        ).fetchall()
        return {
            "bad_reports": _rows_to_dicts(bad_reports),
            "dimm_issues": _rows_to_dicts(dimm_issues),
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Scan status / health
# ---------------------------------------------------------------------------

def get_scan_status(db_path: str) -> dict:
    conn = get_conn(db_path)
    try:
        row = conn.execute("SELECT * FROM scan_status WHERE id = 1").fetchone()
        if row is None:
            return {
                "status": "idle", "total": 0, "done": 0, "inserted": 0,
                "skipped": 0, "errors": 0, "started_at": None, "finished_at": None,
                "mount_ok": 1, "mount_error": None, "mount_checked_at": None,
            }
        return dict(row)
    finally:
        conn.close()


def set_scan_status(db_path: str, **kwargs) -> None:
    kwargs["id"] = 1
    fields = list(kwargs.keys())
    conn = get_conn(db_path)
    try:
        conn.execute(
            f"INSERT OR REPLACE INTO scan_status ({', '.join(fields)}) VALUES ({', '.join('?' * len(fields))})",
            [kwargs[f] for f in fields],
        )
        conn.commit()
    finally:
        conn.close()


def log_scan_error(db_path: str, ts: str, path: str | None, reason: str) -> None:
    conn = get_conn(db_path)
    try:
        conn.execute(
            "INSERT INTO scan_errors (ts, path, reason) VALUES (?, ?, ?)", (ts, path, reason)
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Search (used by app.py's cross-module search)
# ---------------------------------------------------------------------------

def search_module_sn(db_path: str, q: str) -> list[dict]:
    conn = get_conn(db_path)
    try:
        pattern = f"%{q.upper()}%"
        rows = conn.execute(
            """SELECT * FROM mem_modules
               WHERE UPPER(module_sn) LIKE ? OR UPPER(part_number) LIKE ?
               ORDER BY last_tested_at DESC LIMIT 100""",
            (pattern, pattern),
        ).fetchall()
        return _rows_to_dicts(rows)
    finally:
        conn.close()
