"""Per-SN dedup verification: one live record per SN, LAST-ARRIVED wins.

"Newest" = arrival order (rowid), not test timestamp — immune to test-rig
clock skew. Runnable directly or via pytest. Covers:
  * a second upload of the same SN supersedes the first (earlier -> excluded)
  * arrival order wins even when the later upload has an EARLIER test ts
  * dedup spans ready AND pending/exceptions
  * synced (already exported) rows are never superseded
  * ALTER migration: record_ts added to a pre-existing table
"""

import sqlite3
import tempfile
from pathlib import Path

from cyclelution import sync_state


def _checks():
    tmp = Path(tempfile.mkdtemp(prefix="cyc_dedup_"))
    idx = tmp / "_index.sqlite"

    # Arrival order decides: `second` is inserted after `first`, so it wins —
    # even though its record_ts is EARLIER (proves ts is not the criterion).
    first = "h/2026/07-09/SNX_first.json"
    second = "h/2026/07-08/SNX_second.json"
    sync_state.set_status(first, "ready", sn="SNX", record_ts="2026-07-09T10:00:00Z", db_path=idx)
    sync_state.set_status(second, "ready", sn="SNX", record_ts="2026-07-08T10:00:00Z", db_path=idx)
    superseded = sync_state.reconcile_sn("SNX", db_path=idx)
    assert superseded == [first], superseded              # earlier arrival superseded
    assert sync_state.get(second, db_path=idx)["sync_status"] == "ready"
    assert sync_state.get(first, db_path=idx)["sync_status"] == "excluded"
    assert "superseded" in sync_state.get(first, db_path=idx)["sync_note"]

    # dedup spans ready + pending (a stale exception is superseded too)
    p_old = "h/2026/07-08/SNY_a.json"
    p_new = "h/2026/07-09/SNY_b.json"
    sync_state.set_status(p_old, "pending", sn="SNY", note="Grade empty", db_path=idx)
    sync_state.set_status(p_new, "ready", sn="SNY", db_path=idx)   # arrives later
    sync_state.reconcile_sn("SNY", db_path=idx)
    assert sync_state.get(p_new, db_path=idx)["sync_status"] == "ready"
    assert sync_state.get(p_old, db_path=idx)["sync_status"] == "excluded"

    # order independence: re-evaluating the earlier row keeps its (lower) rowid
    sync_state.set_status(first, "ready", sn="SNX", db_path=idx)
    sync_state.reconcile_sn("SNX", db_path=idx)
    assert sync_state.get(second, db_path=idx)["sync_status"] == "ready"   # last-arrived still wins
    assert sync_state.get(first, db_path=idx)["sync_status"] == "excluded"

    # synced (exported) rows are never superseded
    syn = "h/2026/07-01/SNZ_old.json"
    rdy = "h/2026/07-09/SNZ_new.json"
    sync_state.set_status(syn, "synced", sn="SNZ",
                          synced_at="2026-07-01T11:00:00Z", db_path=idx)
    sync_state.set_status(rdy, "ready", sn="SNZ", db_path=idx)
    sync_state.reconcile_sn("SNZ", db_path=idx)
    assert sync_state.get(syn, db_path=idx)["sync_status"] == "synced", "synced must survive"
    assert sync_state.get(rdy, db_path=idx)["sync_status"] == "ready"

    # reconcile_all: two pre-existing READY dupes for one SN (the screenshot
    # case) collapse to just the last-arrived, without any re-evaluation.
    d1 = "h/2026/07-09/DUP_1.json"
    d2 = "h/2026/07-09/DUP_2.json"
    sync_state.set_status(d1, "ready", sn="DUPSN", db_path=idx)
    sync_state.set_status(d2, "ready", sn="DUPSN", db_path=idx)   # arrives later
    n = sync_state.reconcile_all(db_path=idx)
    assert n == 1, n
    assert sync_state.get(d1, db_path=idx)["sync_status"] == "excluded"
    assert sync_state.get(d2, db_path=idx)["sync_status"] == "ready"
    # idempotent: running again changes nothing
    assert sync_state.reconcile_all(db_path=idx) == 0


def _migration_check():
    """A DB created without record_ts gets the column added on next open."""
    tmp = Path(tempfile.mkdtemp(prefix="cyc_mig_"))
    db = tmp / "_index.sqlite"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        "CREATE TABLE laptop_sync (history_path TEXT PRIMARY KEY, sn TEXT,"
        " sync_status TEXT, sync_note TEXT, synced_at TEXT, updated_at TEXT);"
    )
    conn.execute("INSERT INTO laptop_sync (history_path, sn, sync_status) VALUES ('x','SN','ready')")
    conn.commit()
    conn.close()
    # opening via sync_state should ALTER in record_ts, no crash
    sync_state.set_status("x", "ready", sn="SN", record_ts="2026-07-09T10:00:00Z", db_path=db)
    assert sync_state.get("x", db_path=db)["record_ts"] == "2026-07-09T10:00:00Z"


def test_dedup():
    _checks()
    _migration_check()


if __name__ == "__main__":
    _checks()
    _migration_check()
    print("PASS: all dedup + migration checks green")
