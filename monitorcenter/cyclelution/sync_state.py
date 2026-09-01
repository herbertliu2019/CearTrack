"""<module>_sync — per-record sync state for the CearTrack -> Cyclelution flow.

One table per production module (`laptop_sync`, `gpu_sync`, ...), all stored
inside the existing _index.sqlite, keyed by history_path (the same UNIQUE key
index_db uses for envelopes). This is deliberate: index_db.rebuild_all() wipes
only the `envelopes` and `envelope_sns` tables, never the `*_sync` tables, so
sync state survives an index rebuild. Because history_path is derived from
the file location, the join back to a rebuilt `envelopes` row stays valid.

State machine: pending (default) -> ready -> synced. `excluded` is a side
branch for machines that must never enter Cyclelution.

Every function takes `module` (default "laptop" for backward compatibility)
and operates on that module's own `<module>_sync` table. `module` is always
code-controlled (never user input), but is still checked against
_VALID_MODULES before being interpolated into SQL/table names.
"""

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from . import paths

VALID_STATES = {"pending", "ready", "synced", "excluded"}

# Productions with a wired-up sync table. Add here when a new module gets
# Cyclelution support — module name must match TestModule.name / envelopes.module.
# "wipe" has no envelopes.module row (its source is wipe_records, not an
# upload) — see cyclelution/wipe_sync.py.
_VALID_MODULES = {"laptop", "gpu", "wipe"}

# Statuses that count as "live" for per-SN dedup (a machine can only have one).
_ACTIVE_STATES = ("ready", "pending")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _table(module: str) -> str:
    if module not in _VALID_MODULES:
        raise ValueError(f"unknown cyclelution module: {module!r}")
    return f"{module}_sync"


def _schema(table: str) -> str:
    return f"""
    CREATE TABLE IF NOT EXISTS {table} (
        history_path TEXT PRIMARY KEY,
        sn           TEXT,
        sync_status  TEXT NOT NULL DEFAULT 'pending',
        sync_note    TEXT,
        synced_at    TEXT,
        updated_at   TEXT,
        record_ts    TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_{table}_status ON {table}(sync_status);
    CREATE INDEX IF NOT EXISTS idx_{table}_sn     ON {table}(sn);
    """


def _ensure_columns(conn, table: str) -> None:
    """Add columns introduced after the first release to pre-existing DBs."""
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    if "record_ts" not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN record_ts TEXT")


# (db_path, table) pairs that have already had WAL mode + schema DDL applied
# in this process. Guards against re-running executescript()/PRAGMA
# journal_mode on every single _open() call — under concurrent load (the
# wipe_sync background thread doing thousands of writes while the UI polls
# reads) that redundant per-call DDL was itself the thing racing and
# producing "database is locked", even with WAL already active.
_initialized: set[tuple[str, str]] = set()
_init_lock = threading.Lock()


def _open(module="laptop", db_path=None) -> sqlite3.Connection:
    table = _table(module)
    p = Path(db_path) if db_path else paths.index_db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=30.0)
    conn.row_factory = sqlite3.Row
    # busy_timeout is per-connection (not persisted like journal_mode), so it
    # has to be set every time — cheap, no lock needed.
    conn.execute("PRAGMA busy_timeout=30000")

    key = (str(p), table)
    if key not in _initialized:
        with _init_lock:
            if key not in _initialized:
                # WAL: readers (api_queue/api_counts) no longer block behind
                # a writer. journal_mode is persisted in the db file itself,
                # so this only needs to run once per file, ever — but is
                # gated per-process too since re-issuing it under concurrent
                # first-time access is exactly the kind of DDL race this is
                # meant to eliminate.
                conn.execute("PRAGMA journal_mode=WAL")
                conn.executescript(_schema(table))  # idempotent; guarantees the table exists
                _ensure_columns(conn, table)        # migrate older DBs
                _initialized.add(key)
    return conn


def init_schema(module="laptop", db_path=None) -> None:
    """Create the <module>_sync table if absent. Safe to call repeatedly."""
    _open(module, db_path).close()


def ensure_pending(history_path, sn=None, record_ts=None, module="laptop", db_path=None) -> None:
    """Insert a default 'pending' row for this record if none exists.
    No-op when the record already has a row (status is preserved)."""
    table = _table(module)
    conn = _open(module, db_path)
    try:
        with conn:
            conn.execute(
                f"INSERT OR IGNORE INTO {table} "
                "(history_path, sn, sync_status, record_ts, updated_at) "
                "VALUES (?, ?, 'pending', ?, ?)",
                (history_path, sn, record_ts, _now()),
            )
    finally:
        conn.close()


def get(history_path, module="laptop", db_path=None):
    table = _table(module)
    conn = _open(module, db_path)
    try:
        row = conn.execute(
            f"SELECT * FROM {table} WHERE history_path=?", (history_path,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def set_status(history_path, status, note=None, synced_at=None, sn=None,
               record_ts=None, module="laptop", db_path=None) -> None:
    """Upsert the sync status for a record. synced_at/sn/record_ts are only
    overwritten when a non-null value is supplied (COALESCE keeps existing)."""
    if status not in VALID_STATES:
        raise ValueError(f"invalid sync_status: {status!r}")
    table = _table(module)
    conn = _open(module, db_path)
    try:
        with conn:
            conn.execute(
                f"INSERT INTO {table} "
                "(history_path, sn, sync_status, sync_note, synced_at, record_ts, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(history_path) DO UPDATE SET "
                "  sync_status = excluded.sync_status, "
                "  sync_note   = excluded.sync_note, "
                f"  synced_at   = COALESCE(excluded.synced_at, {table}.synced_at), "
                f"  sn          = COALESCE(excluded.sn, {table}.sn), "
                f"  record_ts   = COALESCE(excluded.record_ts, {table}.record_ts), "
                "  updated_at  = excluded.updated_at",
                (history_path, sn, status, note, synced_at, record_ts, _now()),
            )
    finally:
        conn.close()


def list_by_status(status, module="laptop", db_path=None):
    table = _table(module)
    conn = _open(module, db_path)
    try:
        rows = conn.execute(
            f"SELECT * FROM {table} WHERE sync_status=? ORDER BY updated_at DESC",
            (status,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_by_sn(sn, module="laptop", db_path=None):
    """All rows (any status) for one SN, oldest first. Used by wipe_sync.py
    to check whether a drive_sn's current wipe record is already 'synced'
    before re-deriving its envelope (synced rows must never be touched)."""
    table = _table(module)
    conn = _open(module, db_path)
    try:
        rows = conn.execute(
            f"SELECT * FROM {table} WHERE sn=? ORDER BY rowid", (sn,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def counts(module="laptop", db_path=None) -> dict:
    table = _table(module)
    conn = _open(module, db_path)
    try:
        rows = conn.execute(
            f"SELECT sync_status, COUNT(*) AS c FROM {table} GROUP BY sync_status"
        ).fetchall()
        return {r["sync_status"]: r["c"] for r in rows}
    finally:
        conn.close()


def backfill_pending(module="laptop", db_path=None) -> int:
    """Ensure every envelope of this module in the index has a *_sync row
    defaulting to 'pending'. Idempotent (INSERT OR IGNORE). Returns the
    number of new rows created. Requires the `envelopes` table to exist in
    the same database (it always does at runtime). Also backfills record_ts
    from envelopes.timestamp for any row still missing it."""
    table = _table(module)
    conn = _open(module, db_path)
    try:
        with conn:
            cur = conn.execute(
                f"INSERT OR IGNORE INTO {table} "
                "(history_path, sn, sync_status, record_ts, updated_at) "
                "SELECT e.history_path, e.sn, 'pending', e.timestamp, ? "
                "FROM envelopes e WHERE e.module = ?",
                (_now(), module),
            )
            conn.execute(
                f"UPDATE {table} SET record_ts = ("
                "  SELECT e.timestamp FROM envelopes e "
                f"  WHERE e.history_path = {table}.history_path) "
                "WHERE (record_ts IS NULL OR record_ts = '') "
                "  AND EXISTS (SELECT 1 FROM envelopes e "
                f"              WHERE e.history_path = {table}.history_path)"
            )
            return cur.rowcount
    finally:
        conn.close()


def reconcile_sn(sn, module="laptop", db_path=None) -> list:
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
    table = _table(module)
    conn = _open(module, db_path)
    try:
        rows = conn.execute(
            f"SELECT rowid AS rid, history_path FROM {table} "
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
                    f"UPDATE {table} SET sync_status = 'excluded', "
                    "sync_note = ?, updated_at = ? WHERE history_path = ?",
                    (note, now, r["history_path"]),
                )
                superseded.append(r["history_path"])
        return superseded
    finally:
        conn.close()


def reconcile_all(module="laptop", db_path=None) -> int:
    """Reconcile every SN that currently has more than one active
    (ready/pending) row. Use to clean up duplicates that already sat in the
    queue before dedup existed. Returns the total superseded. Idempotent."""
    table = _table(module)
    conn = _open(module, db_path)
    try:
        dup_sns = [
            r["sn"] for r in conn.execute(
                f"SELECT sn FROM {table} "
                "WHERE sync_status IN ('ready', 'pending') "
                "  AND sn IS NOT NULL AND sn != '' "
                "GROUP BY sn HAVING COUNT(*) > 1"
            )
        ]
    finally:
        conn.close()
    return sum(len(reconcile_sn(sn, module=module, db_path=db_path)) for sn in dup_sns)
