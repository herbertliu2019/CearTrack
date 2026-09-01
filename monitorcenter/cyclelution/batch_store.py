"""Server-side store for the scan-to-batch export workflow
(tasks/Cyclelution/TASK_export_batch.md).

Deliberately its own database (`data/batches.db`), separate from
`_index.sqlite` (envelopes + `*_sync` tables) and `wipe_index.db` (the
erasure software's own archive) — batches are CearTrack's own bookkeeping
for a physical scanning session, and must never be written into either
upstream database (task's hard rule #2).

One `export_batches` row per scanning session; `export_batch_items` holds
each record scanned into it. Both keyed by `production` the same way
cyclelution/web.py's `_PRODUCTION_INFO` is ("T-Hard Drive", "T-Laptop", ...).

This module only knows about batches — it never touches `sync_state`
(Ready-pool membership). Callers (web.py) are responsible for checking a
scanned SN is actually in that production's Ready pool before calling
add_item(); this module enforces only the invariant that's genuinely a
batch-table concern: "one open batch per SN" (no row-count cap — see the
task's hard rule #4, batches have no hard size limit, only an optional
UI-side warning threshold that lives in config, not this table)."""

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from . import paths

VALID_STATUSES = {"open", "exported", "cancelled"}

# batch_id prefix per module (task section "data model": WIPE / LAPTOP / GPU).
_PREFIX_BY_MODULE = {"wipe": "WIPE", "laptop": "LAPTOP", "gpu": "GPU"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS export_batches (
    batch_id      TEXT PRIMARY KEY,
    production    TEXT NOT NULL,
    status        TEXT NOT NULL,
    slot_numbers  INTEGER NOT NULL,
    operator_id   TEXT,
    created_at    TEXT NOT NULL,
    exported_at   TEXT,
    export_file   TEXT,
    -- Additive beyond the task doc's literal column list: a monotonic
    -- counter, separate from MAX(item.slot_no). Hard rule #8 requires a
    -- removed slot to stay permanently vacant, but remove_item() does a
    -- real DELETE — after removing the highest-numbered item, MAX() over
    -- what's left would silently go backward and the next add would reuse
    -- a number already written on a physical label. This counter only
    -- ever increases, remove or no remove.
    next_slot_no  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS export_batch_items (
    batch_id    TEXT NOT NULL,
    record_sn   TEXT NOT NULL,
    slot_no     INTEGER,
    added_at    TEXT NOT NULL,
    input_mode  TEXT NOT NULL,
    PRIMARY KEY (batch_id, record_sn)
);
CREATE INDEX IF NOT EXISTS idx_items_sn ON export_batch_items(record_sn);
CREATE INDEX IF NOT EXISTS idx_batches_status ON export_batches(production, status);
-- One open batch per production, enforced at the DB layer as a safety net
-- alongside create_batch()'s own pre-check (see its docstring for why a
-- hit here is disambiguated by re-querying rather than string-matching the
-- SQLite error message).
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_open_batch
    ON export_batches(production) WHERE status = 'open';
"""

_initialized: set[str] = set()
_init_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _open(db_path=None) -> sqlite3.Connection:
    p = Path(db_path) if db_path else paths.batches_db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")

    key = str(p)
    if key not in _initialized:
        with _init_lock:
            if key not in _initialized:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.executescript(_SCHEMA)
                _initialized.add(key)
    return conn


def init_schema(db_path=None) -> None:
    """Create the batches tables if absent. Safe to call repeatedly."""
    _open(db_path).close()


def prefix_for(module: str) -> str:
    return _PREFIX_BY_MODULE.get(module, module.upper())


class BatchConflictError(ValueError):
    """SN already claimed by another open batch, or an open batch already
    exists for this production. `batch_id` names the conflicting batch."""

    def __init__(self, message, batch_id=None):
        super().__init__(message)
        self.batch_id = batch_id


def get_batch(batch_id, db_path=None):
    conn = _open(db_path)
    try:
        row = conn.execute("SELECT * FROM export_batches WHERE batch_id=?", (batch_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_current(production, db_path=None):
    """The single `open` batch for this production, or None."""
    conn = _open(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM export_batches WHERE production=? AND status='open' "
            "ORDER BY created_at DESC LIMIT 1",
            (production,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def create_batch(production, module, slot_numbers, operator_id=None, db_path=None) -> dict:
    """Create a new open batch. Raises BatchConflictError if one is already
    open for this production (carries its batch_id — see api /create's 409).

    Called from two places: the retained POST /create endpoint (debug/
    manual reopen — not used by the normal UI flow), and api_batch_add()'s
    auto-create-on-first-scan path (task hard rule #5: the operator never
    sees a "new batch" action; /add creates one itself the moment there
    isn't an open batch to add into).

    batch_id = f"{PREFIX}-{YYYYMMDD}-{NN}", NN a same-day sequence. The
    common case (no concurrent creators) is handled by the up-front SELECT;
    a genuine race is handled by re-querying after IntegrityError rather
    than parsing the SQLite error string, so a real "already open" conflict
    is never mistaken for an ordinary batch_id collision (and vice versa)."""
    conn = _open(db_path)
    try:
        with conn:
            existing = conn.execute(
                "SELECT batch_id FROM export_batches WHERE production=? AND status='open'",
                (production,),
            ).fetchone()
            if existing:
                raise BatchConflictError("an open batch already exists", batch_id=existing["batch_id"])

            prefix = prefix_for(module)
            today = datetime.now().strftime("%Y%m%d")
            like = f"{prefix}-{today}-%"
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM export_batches WHERE batch_id LIKE ?", (like,)
            ).fetchone()
            next_seq = row["c"] + 1

            for attempt in range(50):
                batch_id = f"{prefix}-{today}-{next_seq + attempt:02d}"
                created_at = _now()
                try:
                    conn.execute(
                        "INSERT INTO export_batches "
                        "(batch_id, production, status, slot_numbers, "
                        " operator_id, created_at) VALUES (?, ?, 'open', ?, ?, ?)",
                        (batch_id, production, int(bool(slot_numbers)), operator_id, created_at),
                    )
                    # Build the result from known values rather than
                    # re-querying: a fresh get_batch() call opens its own
                    # connection, which under WAL can't see this insert
                    # until the `with conn:` block above commits it.
                    return {
                        "batch_id": batch_id, "production": production, "status": "open",
                        "slot_numbers": int(bool(slot_numbers)),
                        "operator_id": operator_id, "created_at": created_at,
                        "exported_at": None, "export_file": None, "next_slot_no": 0,
                    }
                except sqlite3.IntegrityError:
                    still_open = conn.execute(
                        "SELECT batch_id FROM export_batches WHERE production=? AND status='open'",
                        (production,),
                    ).fetchone()
                    if still_open:
                        raise BatchConflictError("an open batch already exists", batch_id=still_open["batch_id"])
                    continue  # batch_id collision only -> retry with next seq
            raise RuntimeError(f"could not allocate a batch_id for {prefix}-{today}")
    finally:
        conn.close()


def list_items(batch_id, db_path=None):
    """Newest scan first — what the UI's batch list shows. Falls back to
    added_at when slot_numbers is off (slot_no is NULL for every row)."""
    conn = _open(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM export_batch_items WHERE batch_id=? "
            "ORDER BY (slot_no IS NULL), slot_no DESC, added_at DESC",
            (batch_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_items_for_export(batch_id, db_path=None):
    """Slot order ascending — the xlsx row order (task section /export:
    "row order follows slot_no ascending")."""
    conn = _open(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM export_batch_items WHERE batch_id=? "
            "ORDER BY (slot_no IS NULL), slot_no ASC, added_at ASC",
            (batch_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def sn_open_batch(record_sn, production, db_path=None):
    """batch_id of the open batch (if any) already holding this SN in this
    production's namespace, else None. Used by /lookup's 0-candidate reason
    diagnosis; add_item() re-checks this itself atomically at insert time,
    so this standalone helper is advisory only (TOCTOU-safe for /add
    because add_item never trusts a prior call to this function)."""
    conn = _open(db_path)
    try:
        row = conn.execute(
            "SELECT i.batch_id FROM export_batch_items i "
            "JOIN export_batches b ON b.batch_id = i.batch_id "
            "WHERE i.record_sn = ? AND b.production = ? AND b.status = 'open'",
            (record_sn, production),
        ).fetchone()
        return row["batch_id"] if row else None
    finally:
        conn.close()


def add_item(batch_id, record_sn, slot_numbers, input_mode, production, db_path=None) -> dict:
    """Insert one scanned record. No capacity check — batches have no hard
    row-count cap (task hard rule #4; a batch this large only trips the
    UI's soft `large_batch_warn` banner, sourced from config, not enforced
    here). Raises:
    - ValueError if `batch_id` isn't currently open
    - BatchConflictError if `record_sn` is already in another open batch
      for this production
    - sqlite3.IntegrityError if `record_sn` is already in *this* batch
      (double scan of the same drive)

    Both checks + the insert run in one transaction so two scans racing at
    the same instant can't both slip past the per-SN-per-open-batch
    invariant."""
    conn = _open(db_path)
    try:
        with conn:
            batch = conn.execute(
                "SELECT * FROM export_batches WHERE batch_id=? AND status='open'", (batch_id,)
            ).fetchone()
            if not batch:
                raise ValueError(f"batch {batch_id} is not open")

            other = conn.execute(
                "SELECT i.batch_id FROM export_batch_items i "
                "JOIN export_batches b ON b.batch_id = i.batch_id "
                "WHERE i.record_sn = ? AND b.production = ? AND b.status = 'open'",
                (record_sn, production),
            ).fetchone()
            if other:
                raise BatchConflictError(f"already in batch {other['batch_id']}", batch_id=other["batch_id"])

            slot_no = None
            if slot_numbers:
                # Monotonic counter on the batch row, NOT MAX(item.slot_no)
                # — see the schema comment on next_slot_no for why a plain
                # MAX would reuse a number after its item is removed.
                conn.execute(
                    "UPDATE export_batches SET next_slot_no = next_slot_no + 1 WHERE batch_id=?",
                    (batch_id,),
                )
                slot_no = conn.execute(
                    "SELECT next_slot_no FROM export_batches WHERE batch_id=?", (batch_id,)
                ).fetchone()["next_slot_no"]

            conn.execute(
                "INSERT INTO export_batch_items (batch_id, record_sn, slot_no, added_at, input_mode) "
                "VALUES (?, ?, ?, ?, ?)",
                (batch_id, record_sn, slot_no, _now(), input_mode),
            )
            return {"batch_id": batch_id, "record_sn": record_sn, "slot_no": slot_no}
    finally:
        conn.close()


def remove_item(batch_id, record_sn, db_path=None) -> bool:
    """Delete one item. Per the task's hard rule #8, slot numbers are never
    reassigned/recycled on removal — add_item() draws the next number from
    the batch's own next_slot_no counter, not MAX(item.slot_no), so the
    removed slot's number stays permanently vacant for this batch."""
    conn = _open(db_path)
    try:
        with conn:
            cur = conn.execute(
                "DELETE FROM export_batch_items WHERE batch_id=? AND record_sn=?",
                (batch_id, record_sn),
            )
            return cur.rowcount > 0
    finally:
        conn.close()


def cancel_batch(batch_id, db_path=None) -> bool:
    """Mark a batch cancelled. No sync_state involvement needed to "release"
    members back to Ready — membership in an open batch never changed a
    record's sync_status in the first place (it's a claim overlay, not a
    state-machine transition; see module docstring)."""
    conn = _open(db_path)
    try:
        with conn:
            cur = conn.execute(
                "UPDATE export_batches SET status='cancelled' WHERE batch_id=? AND status='open'",
                (batch_id,),
            )
            return cur.rowcount > 0
    finally:
        conn.close()


def mark_exported(batch_id, export_file, db_path=None) -> None:
    conn = _open(db_path)
    try:
        with conn:
            conn.execute(
                "UPDATE export_batches SET status='exported', exported_at=?, export_file=? "
                "WHERE batch_id=?",
                (_now(), export_file, batch_id),
            )
    finally:
        conn.close()
