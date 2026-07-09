"""laptop_sync — per-record sync state for the CearTrack -> Cyclelution flow.

Stored as a SEPARATE table inside the existing _index.sqlite, keyed by
history_path (the same UNIQUE key index_db uses for envelopes). This is
deliberate: index_db.rebuild_all() wipes only the `envelopes` and
`envelope_sns` tables, never `laptop_sync`, so sync state survives an
index rebuild. Because history_path is derived from the file location, the
join back to a rebuilt `envelopes` row stays valid.

State machine: pending (default) -> ready -> synced. `excluded` is a side
branch for machines that must never enter Cyclelution.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import paths

VALID_STATES = {"pending", "ready", "synced", "excluded"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS laptop_sync (
    history_path TEXT PRIMARY KEY,
    sn           TEXT,
    sync_status  TEXT NOT NULL DEFAULT 'pending',
    sync_note    TEXT,
    synced_at    TEXT,
    updated_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_laptop_sync_status ON laptop_sync(sync_status);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _open(db_path=None) -> sqlite3.Connection:
    p = Path(db_path) if db_path else paths.index_db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)  # idempotent; guarantees the table exists
    return conn


def init_schema(db_path=None) -> None:
    """Create the laptop_sync table if absent. Safe to call repeatedly."""
    _open(db_path).close()


def ensure_pending(history_path, sn=None, db_path=None) -> None:
    """Insert a default 'pending' row for this record if none exists.
    No-op when the record already has a row (status is preserved)."""
    conn = _open(db_path)
    try:
        with conn:
            conn.execute(
                "INSERT OR IGNORE INTO laptop_sync "
                "(history_path, sn, sync_status, updated_at) VALUES (?, ?, 'pending', ?)",
                (history_path, sn, _now()),
            )
    finally:
        conn.close()


def get(history_path, db_path=None):
    conn = _open(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM laptop_sync WHERE history_path=?", (history_path,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def set_status(history_path, status, note=None, synced_at=None, sn=None, db_path=None) -> None:
    """Upsert the sync status for a record. synced_at/sn are only overwritten
    when a non-null value is supplied (COALESCE keeps the existing one)."""
    if status not in VALID_STATES:
        raise ValueError(f"invalid sync_status: {status!r}")
    conn = _open(db_path)
    try:
        with conn:
            conn.execute(
                "INSERT INTO laptop_sync "
                "(history_path, sn, sync_status, sync_note, synced_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(history_path) DO UPDATE SET "
                "  sync_status = excluded.sync_status, "
                "  sync_note   = excluded.sync_note, "
                "  synced_at   = COALESCE(excluded.synced_at, laptop_sync.synced_at), "
                "  sn          = COALESCE(excluded.sn, laptop_sync.sn), "
                "  updated_at  = excluded.updated_at",
                (history_path, sn, status, note, synced_at, _now()),
            )
    finally:
        conn.close()


def list_by_status(status, db_path=None):
    conn = _open(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM laptop_sync WHERE sync_status=? ORDER BY updated_at DESC",
            (status,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def counts(db_path=None) -> dict:
    conn = _open(db_path)
    try:
        rows = conn.execute(
            "SELECT sync_status, COUNT(*) AS c FROM laptop_sync GROUP BY sync_status"
        ).fetchall()
        return {r["sync_status"]: r["c"] for r in rows}
    finally:
        conn.close()


def backfill_pending(db_path=None) -> int:
    """Ensure every laptop envelope in the index has a laptop_sync row
    defaulting to 'pending'. Idempotent (INSERT OR IGNORE). Returns the
    number of new rows created. Requires the `envelopes` table to exist in
    the same database (it always does at runtime)."""
    conn = _open(db_path)
    try:
        with conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO laptop_sync "
                "(history_path, sn, sync_status, updated_at) "
                "SELECT e.history_path, e.sn, 'pending', ? "
                "FROM envelopes e WHERE e.module = 'laptop'",
                (_now(),),
            )
            return cur.rowcount
    finally:
        conn.close()
