import sqlite3
from datetime import datetime, date


def init_db(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        # Step 1: create tables (without cpu_series index — added after migration)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS cpu_records (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                sn                TEXT NOT NULL,
                log_path          TEXT NOT NULL UNIQUE,
                image_path        TEXT,
                manufacturer      TEXT,
                cpu_series        TEXT,
                cpu_family        TEXT,
                cpu_model         TEXT,
                cpu_generation    INTEGER,
                cpu_full_name     TEXT,
                processor_name    TEXT,
                speed_ghz         REAL,
                physical_cores    INTEGER,
                logical_cores     INTEGER,
                l3_cache_kb       INTEGER,
                memory_gb         REAL,
                expected_freq_ghz REAL,
                measured_freq_ghz REAL,
                freq_ratio        REAL,
                prime_ops_per_sec INTEGER,
                mflops            REAL,
                overall_result    TEXT,
                fail_module       TEXT,
                test_date         TEXT,
                start_time        TEXT,
                end_time          TEXT,
                duration_sec      INTEGER,
                ipdt_revision     TEXT,
                os_info           TEXT,
                graphics_info     TEXT,
                inserted_at       TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_cpu_sn         ON cpu_records(sn);
            CREATE INDEX IF NOT EXISTS idx_cpu_test_date  ON cpu_records(test_date);
            CREATE INDEX IF NOT EXISTS idx_cpu_family     ON cpu_records(cpu_family);
            CREATE INDEX IF NOT EXISTS idx_cpu_generation ON cpu_records(cpu_generation);
            CREATE INDEX IF NOT EXISTS idx_cpu_full_name  ON cpu_records(cpu_full_name);
            CREATE INDEX IF NOT EXISTS idx_cpu_result     ON cpu_records(overall_result);

            CREATE TABLE IF NOT EXISTS scan_status (
                id          INTEGER PRIMARY KEY CHECK (id = 1),
                status      TEXT DEFAULT 'idle',
                started_at  TEXT,
                finished_at TEXT,
                total       INTEGER DEFAULT 0,
                done        INTEGER DEFAULT 0,
                inserted    INTEGER DEFAULT 0,
                skipped     INTEGER DEFAULT 0,
                errors      INTEGER DEFAULT 0
            );
        """)
        conn.commit()

        # Step 2: migrate schema (adds cpu_series column if missing, backfills)
        _migrate_schema(conn)

        # Step 3: create cpu_series index now that the column is guaranteed to exist
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cpu_series ON cpu_records(cpu_series)")
        conn.commit()
    finally:
        conn.close()


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Add columns that didn't exist in older schema versions."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(cpu_records)").fetchall()}
    if "cpu_series" not in existing:
        conn.execute("ALTER TABLE cpu_records ADD COLUMN cpu_series TEXT")
        conn.commit()
        # Backfill existing rows from processor_name + cpu_family
        conn.execute("""
            UPDATE cpu_records SET cpu_series =
                CASE
                    WHEN processor_name LIKE '%Xeon%Platinum%' THEN 'Xeon Platinum'
                    WHEN processor_name LIKE '%Xeon%Gold%'     THEN 'Xeon Gold'
                    WHEN processor_name LIKE '%Xeon%Silver%'   THEN 'Xeon Silver'
                    WHEN processor_name LIKE '%Xeon%Bronze%'   THEN 'Xeon Bronze'
                    WHEN processor_name LIKE '%Xeon%E7%'       THEN 'Xeon E7'
                    WHEN processor_name LIKE '%Xeon%E5%'       THEN 'Xeon E5'
                    WHEN processor_name LIKE '%Xeon%E3%'       THEN 'Xeon E3'
                    WHEN processor_name LIKE '%Xeon%'          THEN 'Xeon Other'
                    WHEN cpu_family = 'i3'  THEN 'Core i3'
                    WHEN cpu_family = 'i5'  THEN 'Core i5'
                    WHEN cpu_family = 'i7'  THEN 'Core i7'
                    WHEN cpu_family = 'i9'  THEN 'Core i9'
                    ELSE 'Other'
                END
            WHERE cpu_series IS NULL
        """)
        conn.commit()


def get_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def insert_record(db_path: str, record: dict) -> str:
    """Insert or update a parsed record keyed on log_path.

    Returns 'inserted' | 'updated' | 'skipped'.
    Same log_path with identical content → skipped (rowcount 0 after no-op replace).
    Same log_path with changed content (e.g. re-tested file) → updated.
    """
    fields = [
        "sn", "log_path", "image_path",
        "manufacturer", "cpu_series", "cpu_family", "cpu_model", "cpu_generation",
        "cpu_full_name", "processor_name", "speed_ghz",
        "physical_cores", "logical_cores", "l3_cache_kb", "memory_gb",
        "expected_freq_ghz", "measured_freq_ghz", "freq_ratio",
        "prime_ops_per_sec", "mflops",
        "overall_result", "fail_module",
        "test_date", "start_time", "end_time", "duration_sec",
        "ipdt_revision", "os_info", "graphics_info",
    ]
    values = [record.get(f) for f in fields]
    placeholders = ", ".join("?" * len(fields))
    col_list = ", ".join(fields)

    # Build the UPDATE clause for all fields except log_path (the conflict key)
    update_cols = [f for f in fields if f != "log_path"]
    update_clause = ", ".join(f"{c}=excluded.{c}" for c in update_cols)

    conn = get_conn(db_path)
    try:
        # Check if record already exists to distinguish insert vs update
        existing = conn.execute(
            "SELECT start_time FROM cpu_records WHERE log_path = ?",
            (record.get("log_path"),),
        ).fetchone()

        cur = conn.execute(
            f"""INSERT INTO cpu_records ({col_list}) VALUES ({placeholders})
                ON CONFLICT(log_path) DO UPDATE SET {update_clause}
                WHERE excluded.start_time IS NOT cpu_records.start_time
                   OR excluded.overall_result IS NOT cpu_records.overall_result
                   OR excluded.image_path IS NOT cpu_records.image_path""",
            values,
        )
        conn.commit()

        if cur.rowcount == 0:
            return "skipped"
        return "updated" if existing else "inserted"
    finally:
        conn.close()


def _rows_to_dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]


def query_today(db_path: str) -> list[dict]:
    today = date.today().isoformat()
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM cpu_records WHERE test_date = ? ORDER BY start_time DESC",
            (today,),
        ).fetchall()
        return _rows_to_dicts(rows)
    finally:
        conn.close()


def query_period(db_path: str, start: str, end: str) -> list[dict]:
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM cpu_records WHERE test_date BETWEEN ? AND ? ORDER BY start_time DESC",
            (start, end),
        ).fetchall()
        return _rows_to_dicts(rows)
    finally:
        conn.close()


def query_by_sn(db_path: str, q: str) -> list[dict]:
    pattern = f"%{q}%"
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            """SELECT * FROM cpu_records
               WHERE UPPER(sn) LIKE UPPER(?)
                  OR UPPER(cpu_full_name) LIKE UPPER(?)
                  OR UPPER(processor_name) LIKE UPPER(?)
               ORDER BY start_time DESC
               LIMIT 100""",
            (pattern, pattern, pattern),
        ).fetchall()
        return _rows_to_dicts(rows)
    finally:
        conn.close()


def stats_summary(db_path: str, start: str, end: str) -> dict:
    """Counts are per log file (each scanned file = 1 test record)."""
    conn = get_conn(db_path)
    try:
        row = conn.execute(
            """SELECT
                COUNT(*)                                                  AS total,
                SUM(CASE WHEN overall_result = 'Pass' THEN 1 ELSE 0 END) AS pass_count,
                SUM(CASE WHEN overall_result = 'Fail' THEN 1 ELSE 0 END) AS fail_count,
                SUM(CASE WHEN freq_ratio IS NOT NULL
                          AND freq_ratio < 0.5  THEN 1 ELSE 0 END)       AS freq_anomaly_count,
                AVG(duration_sec)                                         AS avg_duration_sec
               FROM cpu_records
               WHERE test_date BETWEEN ? AND ?""",
            (start, end),
        ).fetchone()
        return {
            "total":              row["total"] or 0,
            "pass_count":         row["pass_count"] or 0,
            "fail_count":         row["fail_count"] or 0,
            "freq_anomaly_count": row["freq_anomaly_count"] or 0,
            "avg_duration_sec":   round(row["avg_duration_sec"], 1) if row["avg_duration_sec"] else None,
        }
    finally:
        conn.close()


def total_all_time(db_path: str) -> int:
    """Total log file count across all records."""
    conn = get_conn(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM cpu_records").fetchone()[0] or 0
    finally:
        conn.close()


def by_series(db_path: str, start: str, end: str) -> list[dict]:
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            """SELECT cpu_series AS series, COUNT(*) AS count
               FROM cpu_records
               WHERE test_date BETWEEN ? AND ?
                 AND cpu_series IS NOT NULL
               GROUP BY cpu_series
               ORDER BY count DESC""",
            (start, end),
        ).fetchall()
        return _rows_to_dicts(rows)
    finally:
        conn.close()


def by_core_count(db_path: str, start: str, end: str) -> list[dict]:
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            """SELECT
                CASE
                    WHEN physical_cores <= 2  THEN '1-2'
                    WHEN physical_cores <= 4  THEN '4'
                    WHEN physical_cores <= 6  THEN '6'
                    WHEN physical_cores <= 8  THEN '8'
                    WHEN physical_cores <= 12 THEN '10-12'
                    ELSE '16+'
                END AS core_group,
                COUNT(*) AS count,
                MIN(physical_cores) AS sort_key
               FROM cpu_records
               WHERE test_date BETWEEN ? AND ?
                 AND physical_cores IS NOT NULL
               GROUP BY core_group
               ORDER BY sort_key ASC""",
            (start, end),
        ).fetchall()
        return _rows_to_dicts(rows)
    finally:
        conn.close()


def query_records(db_path: str, offset: int = 0, limit: int = 50) -> tuple[list[dict], int]:
    conn = get_conn(db_path)
    try:
        total = conn.execute("SELECT COUNT(*) FROM cpu_records").fetchone()[0] or 0
        rows = conn.execute(
            "SELECT * FROM cpu_records ORDER BY start_time DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return _rows_to_dicts(rows), total
    finally:
        conn.close()


def by_family(db_path: str, start: str, end: str) -> list[dict]:
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            """SELECT cpu_family AS family, COUNT(*) AS count
               FROM cpu_records
               WHERE test_date BETWEEN ? AND ?
                 AND cpu_family IS NOT NULL
               GROUP BY cpu_family
               ORDER BY count DESC""",
            (start, end),
        ).fetchall()
        return _rows_to_dicts(rows)
    finally:
        conn.close()


def by_generation(db_path: str, start: str, end: str) -> list[dict]:
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            """SELECT cpu_generation AS generation, COUNT(*) AS count
               FROM cpu_records
               WHERE test_date BETWEEN ? AND ?
                 AND cpu_generation IS NOT NULL
               GROUP BY cpu_generation
               ORDER BY cpu_generation ASC""",
            (start, end),
        ).fetchall()
        return _rows_to_dicts(rows)
    finally:
        conn.close()


def by_model(db_path: str, start: str, end: str) -> list[dict]:
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            """SELECT cpu_full_name, COUNT(*) AS count
               FROM cpu_records
               WHERE test_date BETWEEN ? AND ?
                 AND cpu_full_name IS NOT NULL
               GROUP BY cpu_full_name
               ORDER BY count DESC
               LIMIT 15""",
            (start, end),
        ).fetchall()
        return _rows_to_dicts(rows)
    finally:
        conn.close()


def daily_counts(db_path: str, start: str, end: str) -> list[dict]:
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            """SELECT test_date AS date,
                      COUNT(*) AS total,
                      SUM(CASE WHEN overall_result = 'Pass' THEN 1 ELSE 0 END) AS passed,
                      SUM(CASE WHEN overall_result = 'Fail' THEN 1 ELSE 0 END) AS failed
               FROM cpu_records
               WHERE test_date BETWEEN ? AND ?
               GROUP BY test_date
               ORDER BY test_date ASC""",
            (start, end),
        ).fetchall()
        return _rows_to_dicts(rows)
    finally:
        conn.close()


def delete_missing_paths(db_path: str, existing_paths: set[str]) -> int:
    """Delete records whose log_path is no longer on disk. Returns count deleted."""
    conn = get_conn(db_path)
    try:
        rows = conn.execute("SELECT id, log_path FROM cpu_records").fetchall()
        to_delete = [r["id"] for r in rows if r["log_path"] not in existing_paths]
        if to_delete:
            conn.execute(
                f"DELETE FROM cpu_records WHERE id IN ({','.join('?' * len(to_delete))})",
                to_delete,
            )
            conn.commit()
        return len(to_delete)
    finally:
        conn.close()


def get_scan_status(db_path: str) -> dict:
    conn = get_conn(db_path)
    try:
        row = conn.execute("SELECT * FROM scan_status WHERE id = 1").fetchone()
        if row is None:
            return {
                "status": "idle", "total": 0, "done": 0,
                "inserted": 0, "skipped": 0, "errors": 0,
                "started_at": None, "finished_at": None,
            }
        return dict(row)
    finally:
        conn.close()


def set_scan_status(db_path: str, **kwargs) -> None:
    kwargs["id"] = 1
    fields = list(kwargs.keys())
    placeholders = ", ".join("?" * len(fields))
    col_list = ", ".join(fields)
    conn = get_conn(db_path)
    try:
        conn.execute(
            f"INSERT OR REPLACE INTO scan_status ({col_list}) VALUES ({placeholders})",
            [kwargs[f] for f in fields],
        )
        conn.commit()
    finally:
        conn.close()
