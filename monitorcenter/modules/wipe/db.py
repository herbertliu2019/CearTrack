import sqlite3
from datetime import datetime


def init_db(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS wipe_records (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                drive_sn         TEXT NOT NULL,
                system_sn        TEXT,
                wipe_date        TEXT,
                wipe_datetime    TEXT,
                duration_min     REAL,
                method           TEXT,
                result           TEXT,
                health_score     REAL,
                grade            TEXT,
                ssd_life         INTEGER,
                power_on_hrs     INTEGER,
                manufacturer     TEXT,
                drive_model      TEXT,
                capacity         TEXT,
                device_type      TEXT,
                sys_manufacturer TEXT,
                sys_model        TEXT,
                sys_chassis      TEXT,
                win_path         TEXT,
                log_path         TEXT UNIQUE,
                indexed_at       TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_drive_sn  ON wipe_records(drive_sn);
            CREATE INDEX IF NOT EXISTS idx_system_sn ON wipe_records(system_sn);
            CREATE INDEX IF NOT EXISTS idx_wipe_date ON wipe_records(wipe_date);
            CREATE INDEX IF NOT EXISTS idx_sys_mfr   ON wipe_records(sys_manufacturer);
            CREATE INDEX IF NOT EXISTS idx_result    ON wipe_records(result);

            CREATE TABLE IF NOT EXISTS scan_status (
                id         INTEGER PRIMARY KEY CHECK (id = 1),
                total      INTEGER DEFAULT 0,
                done       INTEGER DEFAULT 0,
                errors     INTEGER DEFAULT 0,
                inserted   INTEGER DEFAULT 0,
                skipped    INTEGER DEFAULT 0,
                running    INTEGER DEFAULT 0,
                scan_type  TEXT,
                started_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS scan_errors (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                log_path     TEXT,
                error_msg    TEXT,
                attempted_at TEXT
            );
        """)
        conn.commit()
        # 迁移：为已有数据库添加新字段（幂等）
        _migrate_add_columns(conn)
        _migrate_scan_status(conn)
        conn.commit()
    finally:
        conn.close()


_NEW_COLUMNS = [
    ("firmware",         "TEXT"),
    ("protocol",         "TEXT"),
    ("software_version", "TEXT"),
    ("log_hash",         "TEXT"),
    ("location1",        "TEXT"),
    ("location2",        "TEXT"),
    ("erasure_rule",     "TEXT"),
    ("failure_reason",   "TEXT"),
]


def _migrate_add_columns(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(wipe_records)").fetchall()}
    for col, col_type in _NEW_COLUMNS:
        if col not in existing:
            conn.execute(f"ALTER TABLE wipe_records ADD COLUMN {col} {col_type}")


def _migrate_scan_status(conn: sqlite3.Connection) -> None:
    """Idempotently add inserted/skipped columns to scan_status for existing databases."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(scan_status)").fetchall()}
    for col, col_type in [("inserted", "INTEGER"), ("skipped", "INTEGER")]:
        if col not in existing:
            conn.execute(f"ALTER TABLE scan_status ADD COLUMN {col} {col_type} DEFAULT 0")


def get_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def insert_record(conn: sqlite3.Connection, record: dict) -> bool:
    fields = [
        "drive_sn", "system_sn", "wipe_date", "wipe_datetime", "duration_min",
        "method", "result", "health_score", "grade", "ssd_life", "power_on_hrs",
        "manufacturer", "drive_model", "capacity", "device_type",
        "sys_manufacturer", "sys_model", "sys_chassis",
        "win_path", "log_path", "indexed_at",
        "firmware", "protocol", "software_version", "log_hash",
        "location1", "location2", "erasure_rule", "failure_reason",
    ]
    values = [record.get(f) for f in fields]
    placeholders = ", ".join("?" * len(fields))
    col_list = ", ".join(fields)
    cur = conn.execute(
        f"INSERT OR IGNORE INTO wipe_records ({col_list}) VALUES ({placeholders})",
        values,
    )
    conn.commit()
    return cur.rowcount == 1


def _rows_to_dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]


def query_today(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM wipe_records WHERE wipe_date = date('now', 'localtime') ORDER BY wipe_datetime DESC"
    ).fetchall()
    return _rows_to_dicts(rows)


def query_period(conn: sqlite3.Connection, start: str, end: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM wipe_records WHERE wipe_date BETWEEN ? AND ? ORDER BY wipe_datetime DESC",
        (start, end),
    ).fetchall()
    return _rows_to_dicts(rows)


def query_by_sn(conn: sqlite3.Connection, q: str) -> list[dict]:
    pattern = f"%{q}%"
    rows = conn.execute(
        "SELECT * FROM wipe_records WHERE UPPER(drive_sn) LIKE UPPER(?) OR UPPER(system_sn) LIKE UPPER(?) ORDER BY wipe_datetime DESC",
        (pattern, pattern),
    ).fetchall()
    return _rows_to_dicts(rows)


def stats_summary(records: list[dict]) -> dict:
    total = len(records)
    passed = sum(1 for r in records if r.get("result") == "PASSED")
    failed = sum(1 for r in records if r.get("result") == "FAILED")
    durations = [r["duration_min"] for r in records if r.get("duration_min") is not None]
    avg_duration = round(sum(durations) / len(durations), 2) if durations else None
    pass_rate = round(passed / total * 100, 1) if total else 0.0
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": pass_rate,
        "avg_duration": avg_duration,
    }


def by_device_type(records: list[dict]) -> dict:
    """Classify drives into HDD / SSD / NVMe based on device_type field."""
    counts: dict[str, int] = {"HDD": 0, "SSD": 0, "NVMe": 0}
    for r in records:
        dt = (r.get("device_type") or "").upper()
        if "NVME" in dt:
            counts["NVMe"] += 1
        elif "SSD" in dt:
            counts["SSD"] += 1
        else:
            counts["HDD"] += 1
    return counts


def by_manufacturer(records: list[dict]) -> list[dict]:
    counts: dict[str, int] = {}
    for r in records:
        name = r.get("manufacturer") or "Unknown"   # drive manufacturer (TOSHIBA, Seagate …)
        counts[name] = counts.get(name, 0) + 1
    return sorted(
        [{"name": k, "count": v} for k, v in counts.items()],
        key=lambda x: x["count"],
        reverse=True,
    )


def fail_reasons(records: list[dict]) -> list[dict]:
    counts: dict[str, int] = {}
    for r in records:
        if r.get("result") == "FAILED":
            reason = r.get("failure_reason") or r.get("method") or "Unknown"
            counts[reason] = counts.get(reason, 0) + 1
    return sorted(
        [{"reason": k, "count": v} for k, v in counts.items()],
        key=lambda x: x["count"],
        reverse=True,
    )


def get_scan_status(conn: sqlite3.Connection) -> dict:
    row = conn.execute("SELECT * FROM scan_status WHERE id=1").fetchone()
    if row is None:
        return {
            "running": 0, "total": 0, "done": 0, "errors": 0,
            "scan_type": None, "started_at": None, "updated_at": None,
        }
    return dict(row)


def upsert_scan_status(conn: sqlite3.Connection, **kwargs) -> None:
    kwargs["id"] = 1
    kwargs["updated_at"] = datetime.now().isoformat()
    fields = list(kwargs.keys())
    placeholders = ", ".join("?" * len(fields))
    col_list = ", ".join(fields)
    conn.execute(
        f"INSERT OR REPLACE INTO scan_status ({col_list}) VALUES ({placeholders})",
        [kwargs[f] for f in fields],
    )
    conn.commit()
