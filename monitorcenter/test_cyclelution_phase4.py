"""Phase 4 verification: the /cyclelution/ web routes end-to-end.

Drives the real Flask blueprint with a test client against fixture
databases (temp MONITORCENTER_DATA_DIR). Covers:
  * counts + operator-grouped ready queue
  * generate export -> download url -> file downloads -> record becomes synced
  * exported tab lists the synced record with its file
  * re-export of a synced record is rejected (400)
  * exclude removes a record from the queues

Run: python test_cyclelution_phase4.py   (env is set before imports below)
"""

import os
import sqlite3
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="cyc_p4_"))
os.environ["MONITORCENTER_DATA_DIR"] = str(_TMP)   # before importing config

import config  # noqa: E402  picks up the temp data dir
from flask import Flask  # noqa: E402
from cyclelution import sync_state  # noqa: E402
from cyclelution.web import blueprint  # noqa: E402

_SAMPLE = Path(__file__).resolve().parents[1] / ".claude" / "reference" / "5CG01809VM.json"


def _seed_wipe_db():
    """Fixture wipe DB at the fallback location paths.wipe_db_path() resolves
    to (data/wipe/wipe_index.db), containing the sample's drive as PASSED."""
    wp = Path(config.BASE_DIR) / "wipe" / "wipe_index.db"
    wp.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(wp))
    conn.executescript(
        "CREATE TABLE wipe_records (drive_sn TEXT, capacity TEXT, device_type TEXT,"
        " protocol TEXT, result TEXT, wipe_datetime TEXT);"
    )
    conn.execute(
        "INSERT INTO wipe_records VALUES (?,?,?,?,?,?)",
        ("S3ZHNA0M538153", "512GB", "M.2 NVMe SSD", "SCSI 6", "PASSED", "2026-07-09T09:00:00"),
    )
    conn.commit()
    conn.close()


def _checks():
    _seed_wipe_db()

    # stage the sample as a ready record
    rec = _TMP / "5CG01809VM.json"
    rec.write_text(_SAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    hp = str(rec)
    sync_state.set_status(hp, "ready", sn="5CG01809VM")

    app = Flask(__name__)
    app.register_blueprint(blueprint)
    c = app.test_client()

    # counts
    counts = c.get("/cyclelution/api/counts").get_json()
    assert counts["ready"] == 1, counts

    # ready queue grouped by operator 0216
    q = c.get("/cyclelution/api/queue?status=ready").get_json()
    assert q["total"] == 1 and len(q["groups"]) == 1, q
    grp = q["groups"][0]
    assert grp["operator"] == "0216" and grp["count"] == 1, grp
    row = grp["records"][0]
    assert row["sn"] == "5CG01809VM" and row["grade"] == "Grade C", row

    # export the selected record
    r = c.post("/cyclelution/api/export", json={"history_paths": [hp]})
    assert r.status_code == 200, r.get_data(as_text=True)
    d = r.get_json()
    assert d["count"] == 1 and d["download_url"].endswith(".xlsx"), d

    # download the generated file
    dl = c.get(d["download_url"])
    assert dl.status_code == 200 and len(dl.data) > 2000, dl.status_code

    # record is now synced; shows in exported tab, gone from ready
    assert sync_state.get(hp)["sync_status"] == "synced"
    assert c.get("/cyclelution/api/counts").get_json()["ready"] == 0
    exp = c.get("/cyclelution/api/queue?status=exported").get_json()
    assert exp["total"] == 1 and exp["records"][0]["operator"] == "0216"
    assert exp["records"][0]["file"].endswith(".xlsx")

    # re-export of the synced record is rejected
    r2 = c.post("/cyclelution/api/export", json={"history_paths": [hp]})
    assert r2.status_code == 400 and "ready" in r2.get_json()["error"].lower(), r2.get_json()

    # empty selection rejected
    assert c.post("/cyclelution/api/export", json={"history_paths": []}).status_code == 400

    # exclude a fresh pending record -> requires a reason, stored in the note
    pend = _TMP / "pending.json"
    pend.write_text("{}", encoding="utf-8")
    sync_state.ensure_pending(str(pend), sn="PEND1")
    assert c.post("/cyclelution/api/exclude", json={"history_path": str(pend)}).status_code == 400
    ex = c.post("/cyclelution/api/exclude", json={"history_path": str(pend), "reason": "Shred"})
    assert ex.status_code == 200
    row = sync_state.get(str(pend))
    assert row["sync_status"] == "excluded" and row["sync_note"] == "excluded: Shred"


def test_phase4():
    _checks()


if __name__ == "__main__":
    _checks()
    print("PASS: all Phase 4 checks green")
