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
    updated_at   TEXT,
    record_ts    TEXT
);
CREATE INDEX IF NOT EXISTS idx_laptop_sync_status ON laptop_sync(sync_status);
CREATE INDEX IF NOT EXISTS idx_laptop_sync_sn     ON laptop_sync(sn);
"""

# Statuses that count as "live" for per-SN dedup (a machine can only have one).
_ACTIVE_STATES = ("ready", "pending")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_columns(conn) -> None:
    """Add columns introduced after the first release to pre-existing DBs."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(laptop_sync)")}
    if "record_ts" not in cols:
        conn.execute("ALTER TABLE laptop_sync ADD COLUMN record_ts TEXT")


def _open(db_path=None) -> sqlite3.Connection:
    p = Path(db_path) if db_path else paths.index_db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)  # idempotent; guarantees the table exists
    _ensure_columns(conn)        # migrate older DBs
    return conn


def init_schema(db_path=None) -> None:
    """Create the laptop_sync table if absent. Safe to call repeatedly."""
    _open(db_path).close()


def ensure_pending(history_path, sn=None, record_ts=None, db_path=None) -> None:
    """Insert a default 'pending' row for this record if none exists.
    No-op when the record already has a row (status is preserved)."""
    conn = _open(db_path)
    try:
        with conn:
            conn.execute(
                "INSERT OR IGNORE INTO laptop_sync "
                "(history_path, sn, sync_status, record_ts, updated_at) "
                "VALUES (?, ?, 'pending', ?, ?)",
                (history_path, sn, record_ts, _now()),
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


def set_status(history_path, status, note=None, synced_at=None, sn=None,
               record_ts=None, db_path=None) -> None:
    """Upsert the sync status for a record. synced_at/sn/record_ts are only
    overwritten when a non-null value is supplied (COALESCE keeps existing)."""
    if status not in VALID_STATES:
        raise ValueError(f"invalid sync_status: {status!r}")
    conn = _open(db_path)
    try:
        with conn:
            conn.execute(
                "INSERT INTO laptop_sync "
                "(history_path, sn, sync_status, sync_note, synced_at, record_ts, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(history_path) DO UPDATE SET "
                "  sync_status = excluded.sync_status, "
                "  sync_note   = excluded.sync_note, "
                "  synced_at   = COALESCE(excluded.synced_at, laptop_sync.synced_at), "
                "  sn          = COALESCE(excluded.sn, laptop_sync.sn), "
                "  record_ts   = COALESCE(excluded.record_ts, laptop_sync.record_ts), "
                "  updated_at  = excluded.updated_at",
                (history_path, sn, status, note, synced_at, record_ts, _now()),
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
    the same database (it always does at runtime). Also backfills record_ts
    from envelopes.timestamp for any row still missing it."""
    conn = _open(db_path)
    try:
        with conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO laptop_sync "
                "(history_path, sn, sync_status, record_ts, updated_at) "
                "SELECT e.history_path, e.sn, 'pending', e.timestamp, ? "
                "FROM envelopes e WHERE e.module = 'laptop'",
                (_now(),),
            )
            conn.execute(
                "UPDATE laptop_sync SET record_ts = ("
                "  SELECT e.timestamp FROM envelopes e "
                "  WHERE e.history_path = laptop_sync.history_path) "
                "WHERE (record_ts IS NULL OR record_ts = '') "
                "  AND EXISTS (SELECT 1 FROM envelopes e "
                "              WHERE e.history_path = laptop_sync.history_path)"
            )
            return cur.rowcount
    finally:
        conn.close()


def reconcile_sn(sn, db_path=None) -> list:
    """Enforce one live record per SN: among the active (ready/pending) rows
    for this SN, keep the one that arrived LAST and set the earlier ones to
    'excluded' (viewable, note explains it).

    "Last" is arrival order, not test timestamp: the row's rowid increases
    monotonically with each new upload, so later-received always wins. This
    is immune to test-rig clock skew. rowid is preserved across status
    updates (upsert UPDATE keeps it) and order-preserving across VACUUM, so
    the result is deterministic and idempotent. Never touches
    synced/excluded rows. Returns the superseded history_paths."""
    if not sn:
        return []
    conn = _open(db_path)
    try:
        rows = conn.execute(
            "SELECT rowid AS rid, history_path FROM laptop_sync "
            "WHERE sn = ? AND sync_status IN ('ready', 'pending') "
            "ORDER BY rid",
            (sn,),
        ).fetchall()
        if len(rows) <= 1:
            return []
        # Highest rowid = latest arrival = winner; supersede the earlier ones.
        superseded = []
        now = _now()
        note = "superseded by a newer test upload"
        with conn:
            for r in rows[:-1]:
                conn.execute(
                    "UPDATE laptop_sync SET sync_status = 'excluded', "
                    "sync_note = ?, updated_at = ? WHERE history_path = ?",
                    (note, now, r["history_path"]),
                )
                superseded.append(r["history_path"])
        return superseded
    finally:
        conn.close()
