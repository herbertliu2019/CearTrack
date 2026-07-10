"""Per-SN dedup verification: one live record per SN, newest test wins.

Runnable directly or via pytest. Covers:
  * a second test of the same SN supersedes the first (older -> excluded)
  * dedup spans ready AND pending/exceptions
  * newest wins regardless of evaluation order (record_ts, not order)
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

    # two tests of the same SN, both ready; newer record_ts must win
    old = "h/2026/07-08/SNX_20260708.json"
    new = "h/2026/07-09/SNX_20260709.json"
    sync_state.set_status(old, "ready", sn="SNX", record_ts="2026-07-08T10:00:00Z", db_path=idx)
    sync_state.set_status(new, "ready", sn="SNX", record_ts="2026-07-09T10:00:00Z", db_path=idx)
    superseded = sync_state.reconcile_sn("SNX", db_path=idx)
    assert superseded == [old], superseded
    assert sync_state.get(new, db_path=idx)["sync_status"] == "ready"
    assert sync_state.get(old, db_path=idx)["sync_status"] == "excluded"
    assert "superseded" in sync_state.get(old, db_path=idx)["sync_note"]

    # dedup spans ready + pending (a stale exception is superseded too)
    p_old = "h/2026/07-08/SNY_a.json"
    p_new = "h/2026/07-09/SNY_b.json"
    sync_state.set_status(p_old, "pending", sn="SNY", note="Grade empty",
                          record_ts="2026-07-08T09:00:00Z", db_path=idx)
    sync_state.set_status(p_new, "ready", sn="SNY", record_ts="2026-07-09T09:00:00Z", db_path=idx)
    sync_state.reconcile_sn("SNY", db_path=idx)
    assert sync_state.get(p_new, db_path=idx)["sync_status"] == "ready"
    assert sync_state.get(p_old, db_path=idx)["sync_status"] == "excluded"

    # order independence: reconcile again after "re-evaluating" the OLD one
    sync_state.set_status(old, "ready", sn="SNX", record_ts="2026-07-08T10:00:00Z", db_path=idx)
    sync_state.reconcile_sn("SNX", db_path=idx)
    assert sync_state.get(new, db_path=idx)["sync_status"] == "ready"   # newest still wins
    assert sync_state.get(old, db_path=idx)["sync_status"] == "excluded"

    # synced (exported) rows are never superseded
    syn = "h/2026/07-01/SNZ_old.json"
    rdy = "h/2026/07-09/SNZ_new.json"
    sync_state.set_status(syn, "synced", sn="SNZ", record_ts="2026-07-01T10:00:00Z",
                          synced_at="2026-07-01T11:00:00Z", db_path=idx)
    sync_state.set_status(rdy, "ready", sn="SNZ", record_ts="2026-07-09T10:00:00Z", db_path=idx)
    sync_state.reconcile_sn("SNZ", db_path=idx)
    assert sync_state.get(syn, db_path=idx)["sync_status"] == "synced", "synced must survive"
    assert sync_state.get(rdy, db_path=idx)["sync_status"] == "ready"


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
