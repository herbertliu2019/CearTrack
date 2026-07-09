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
    conn = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(_SQL, (sn,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
