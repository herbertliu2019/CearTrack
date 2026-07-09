"""Phase 1 verification for the Cyclelution integration layer.

Self-contained: builds fixture SQLite DBs in a temp dir so results are
deterministic and independent of the 30k-row production wipe mirror.
Runnable two ways:

    python test_cyclelution_phase1.py     # plain asserts, prints PASS/FAIL
    pytest test_cyclelution_phase1.py     # same checks as pytest cases

Covers the Phase 1 acceptance criteria:
  * migration is idempotent; all existing laptop records become 'pending'
  * wipe_lookup('PHHP945005MJ512C') -> capacity=512GB, result=PASSED
  * wipe_lookup('<missing>') -> None (no exception)
  * old JSON without manual_input reads without error (all fields None)
"""

import sqlite3
import tempfile
from pathlib import Path

from cyclelution import sync_state, wipe_lookup
from cyclelution.manual_input import read_manual_input


def _make_index_db(path):
    """Minimal envelopes table + 3 laptop rows + 1 non-laptop row."""
    conn = sqlite3.connect(str(path))
    conn.executescript(
        "CREATE TABLE envelopes ("
        " id INTEGER PRIMARY KEY, module TEXT, sn TEXT, hostname TEXT,"
        " overall_result TEXT, summary TEXT, timestamp TEXT,"
        " history_path TEXT UNIQUE);"
    )
    rows = [
        ("laptop", "SN-A", "h/2026/07-09/SN-A.json"),
        ("laptop", "SN-B", "h/2026/07-09/SN-B.json"),
        ("laptop", "SN-C", "h/2026/07-08/SN-C.json"),
        ("gpu",    "GPU-1", "h/2026/07-09/GPU-1.json"),  # must be ignored
    ]
    conn.executemany(
        "INSERT INTO envelopes (module, sn, history_path) VALUES (?, ?, ?)", rows
    )
    conn.commit()
    conn.close()


def _make_wipe_db(path):
    conn = sqlite3.connect(str(path))
    conn.executescript(
        "CREATE TABLE wipe_records ("
        " id INTEGER PRIMARY KEY, drive_sn TEXT, capacity TEXT, device_type TEXT,"
        " protocol TEXT, result TEXT, wipe_datetime TEXT);"
    )
    conn.executemany(
        "INSERT INTO wipe_records "
        "(drive_sn, capacity, device_type, protocol, result, wipe_datetime) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            # Golden case (SKILL.md section 7) + an older duplicate to prove
            # ORDER BY wipe_datetime DESC picks the newest.
            ("PHHP945005MJ512C", "512GB", "M.2 NVMe SSD", "SCSI 6", "PASSED", "2026-07-01T10:00:00"),
            ("PHHP945005MJ512C", "512GB", "M.2 NVMe SSD", "SCSI 6", "FAILED", "2026-06-01T10:00:00"),
        ],
    )
    conn.commit()
    conn.close()


def _checks():
    tmp = Path(tempfile.mkdtemp(prefix="cyc_p1_"))
    idx = tmp / "_index.sqlite"
    wipe = tmp / "wipe_index.db"
    _make_index_db(idx)
    _make_wipe_db(wipe)

    # 1. migration idempotent; all laptop rows pending, gpu ignored
    n1 = sync_state.backfill_pending(db_path=idx)
    n2 = sync_state.backfill_pending(db_path=idx)  # second run: no new rows
    counts = sync_state.counts(db_path=idx)
    assert n1 == 3, f"first backfill should create 3, got {n1}"
    assert n2 == 0, f"second backfill should create 0 (idempotent), got {n2}"
    assert counts == {"pending": 3}, f"expected 3 pending, got {counts}"

    # status transitions
    sync_state.set_status("h/2026/07-09/SN-A.json", "ready", note="ok", db_path=idx)
    sync_state.set_status("h/2026/07-09/SN-B.json", "excluded", note="scrap", db_path=idx)
    row = sync_state.get("h/2026/07-09/SN-A.json", db_path=idx)
    assert row["sync_status"] == "ready" and row["sync_note"] == "ok"
    assert sync_state.counts(db_path=idx) == {"pending": 1, "ready": 1, "excluded": 1}

    # invalid status rejected
    try:
        sync_state.set_status("h/2026/07-09/SN-C.json", "bogus", db_path=idx)
        raise AssertionError("invalid status should raise ValueError")
    except ValueError:
        pass

    # 2. wipe_lookup golden -> newest PASSED record
    rec = wipe_lookup.lookup("PHHP945005MJ512C", db_path=wipe)
    assert rec is not None, "golden drive should be found"
    assert rec["capacity"] == "512GB", rec
    assert rec["result"] == "PASSED", rec  # newest row, not the older FAILED
    assert rec["device_type"] == "M.2 NVMe SSD", rec

    # 3. missing SN and empty SN -> None, no exception
    assert wipe_lookup.lookup("DOES-NOT-EXIST", db_path=wipe) is None
    assert wipe_lookup.lookup("", db_path=wipe) is None
    assert wipe_lookup.lookup(None, db_path=wipe) is None

    # 4. manual_input backward compat
    mi_new = read_manual_input({"manual_input": {"weight_lbs": "3.38", "grade": "Grade C"}})
    assert mi_new["weight_lbs"] == "3.38" and mi_new["grade"] == "Grade C"
    assert mi_new["color"] is None  # not supplied
    mi_old = read_manual_input({"system": {}})  # pre-v2.1.3, no block
    assert all(v is None for v in mi_old.values()), mi_old


# --- pytest entrypoints -------------------------------------------------
def test_phase1():
    _checks()


if __name__ == "__main__":
    _checks()
    print("PASS: all Phase 1 checks green")
