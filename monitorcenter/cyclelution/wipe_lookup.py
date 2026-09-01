"""Read-only lookup into the wipe index DB (wipe_index.db).

storage-related fields (capacity / type / erase result / drive SN) are
authoritative from the wipe DB, not the laptop test JSON. Given a drive
serial, return the most recent wipe record. Never writes to the wipe DB
(opened read-only).
"""

import sqlite3
from pathlib import Path

from . import paths

# Fixed SELECT per SKILL.md section 2.
_SQL = (
    "SELECT capacity, device_type, protocol, result, drive_sn, wipe_datetime "
    "FROM wipe_records WHERE drive_sn = ? "
    "ORDER BY wipe_datetime DESC LIMIT 1"
)


def _ro_connect(p: Path) -> sqlite3.Connection:
    """Read-only URI connection with a busy timeout. wipe_index.db is also
    written to periodically by the wipe module's own background log-scanner
    (a separate writer we don't control) — without a timeout, a read landing
    in the brief window around that writer's commit raises "database is
    locked" immediately instead of just waiting the moment it takes to clear.
    wipe_sync.py now issues far more reads against this file per scan than
    before (one query per drive_sn), which raised the odds of that collision
    enough to matter in practice."""
    conn = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True, timeout=30.0)
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def lookup(drive_sn, db_path=None):
    """Return a dict of the newest wipe record for `drive_sn`, or None if
    the SN is empty, the DB is missing, or no record matches."""
    sn = (drive_sn or "").strip()
    if not sn:
        return None
    p = Path(db_path) if db_path else paths.wipe_db_path()
    if not p.exists():
        return None
    # Read-only URI connection: guarantees we never mutate the wipe DB.
    conn = _ro_connect(p)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(_SQL, (sn,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# --- T-Hard Drive (wipe) production support -----------------------------
# The wipe Cyclelution production needs more columns than `lookup()` above
# selects (that one is T-Laptop's storage-join query, tested against a
# narrower fixture schema by test_cyclelution_phase1/2/4.py — left alone).
# These two functions are purely additive.

_SQL_FULL = (
    "SELECT drive_sn, manufacturer, drive_model, capacity, device_type, "
    "protocol, result, grade, health_score, wipe_datetime "
    "FROM wipe_records WHERE drive_sn = ? "
    "ORDER BY wipe_datetime DESC LIMIT 1"
)


def lookup_full(drive_sn, db_path=None):
    """Like lookup(), but selects every column the wipe production's
    mapping needs (manufacturer/drive_model/grade/health_score too). Per
    TASK_wipe_export.md section 1's fixed query."""
    sn = (drive_sn or "").strip()
    if not sn:
        return None
    p = Path(db_path) if db_path else paths.wipe_db_path()
    if not p.exists():
        return None
    conn = _ro_connect(p)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(_SQL_FULL, (sn,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_drive_sns(since=None, db_path=None):
    """Every distinct non-empty drive_sn in the wipe DB whose LATEST
    wipe_datetime is on/after `since` (a "YYYY-MM-DD" or full ISO datetime
    string, compared as text the same way ORDER BY wipe_datetime already
    relies on ISO-string sortability elsewhere in this module). since=None
    -> unfiltered (today's behavior). Used by wipe_sync.sync_all() to
    discover records to (re-)evaluate. Empty list if the DB is missing.

    Filtering on MAX(wipe_datetime) rather than any row's datetime matters:
    it must match exactly what lookup_full() will pick as "the" record for
    that drive_sn (newest wins), so a drive_sn with an old pre-cutoff wipe
    and a newer post-cutoff wipe is correctly included, and one with only
    old wipes is correctly excluded.
    """
    p = Path(db_path) if db_path else paths.wipe_db_path()
    if not p.exists():
        return []
    conn = _ro_connect(p)
    try:
        if since:
            rows = conn.execute(
                "SELECT drive_sn FROM wipe_records "
                "WHERE drive_sn IS NOT NULL AND drive_sn != '' "
                "GROUP BY drive_sn HAVING MAX(wipe_datetime) >= ?",
                (since,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT DISTINCT drive_sn FROM wipe_records "
                "WHERE drive_sn IS NOT NULL AND drive_sn != ''"
            ).fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()
