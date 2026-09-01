"""Phase 2 verification: normalizer + gate + config-driven behaviour.

Runnable directly (python test_cyclelution_phase2.py) or via pytest.

Covers the Phase 2 acceptance criteria:
  * golden case: real sample 5CG01809VM.json maps to the expected 81-col
    values verbatim, gate = ready
  * SKILL section 7 golden shape (5CG0101FDR-like): 8 GB / 66.2% /
    PHHP945005MJ512C, overall FAIL -> gate ready with TEST_FAIL soft flag
  * reverse examples: normalizer still names the stuck field for Grade
    empty / memory 130 GB / device_type garbage, but per the relaxed gate
    (gate.py's _BLOCKING_FIELDS) only wipe FAILED actually blocks Ready —
    the others go ready with an INCOMPLETE flag and a blank column
  * no-disk branch: storage columns blank, ddl005 = ND-No Data, NO_DISK flag
  * config-driven: change one memory domain value -> output changes
"""

import copy
import json
from pathlib import Path

from cyclelution import normalizer, gate

_SAMPLE = Path(__file__).resolve().parents[1] / ".claude" / "reference" / "5CG01809VM.json"


def _wipe_pass(sn):
    # Any known drive -> a passing 512GB M.2 NVMe record.
    known = {"S3ZHNA0M538153", "PHHP945005MJ512C"}
    if sn in known:
        return {"capacity": "512GB", "device_type": "M.2 NVMe SSD",
                "protocol": "SCSI 6", "result": "PASSED", "drive_sn": sn}
    return None


GOLDEN_5CG01809VM = {
    "ProductName": "T - Laptop", "Office": "05 Testing/Resale", "Qty": "1",
    "QtyBase": "Unit", "Weight": "3.38", "RTS": "N", "TDM": "N",
    "SerialNumber": "5CG01809VM", "BusID": "IT23041900028",
    "Condition": "C5 - Used Very Good", "Manufacturer": "HP",
    "Model": "PROBOOK 640 G5", "Color": "Gray", "Size": "14 inch",
    "Grade": "Grade C", "ddlProperty001": "16 GB", "ddlProperty002": "Testing Area",
    "ddlProperty003": "512 GB", "ddlProperty004": "M.2 SSD NVME",
    "ddlProperty005": "Pass", "ddlProperty006": "03 Tested", "ddlProperty007": "No OS",
    "ddlProperty008": "Laptop", "ddlProperty009": "F3 - Key Functions Working",
    "ddlProperty010": "Intel Core i7", "ddlProperty011": "1.9 GHz",
    "ddlProperty012": "No", "ddlProperty013": "C-R2 Controlled Streams",
    "ddlProperty014": "Commodity Storage", "ddlProperty015": "Pass",
    "ddlProperty032": "Laptops", "TxtProperty001": "Scratches on lid",
    "TxtProperty003": "S3ZHNA0M538153", "TxtProperty005": "64.6%",
    "TxtProperty006": "8665U",
}


def _load_sample():
    return json.loads(_SAMPLE.read_text(encoding="utf-8"))


def _mini_env(**over):
    """Minimal valid laptop envelope; override sub-dicts via kwargs."""
    payload = {
        "system": {"vendor": "HP", "model": "HP ProBook 640 G5", "serial_number": "SN123"},
        "cpu": {"model": "Intel(R) Core(TM) i7-8665U CPU @ 1.90GHz"},
        "memory": {"total_gb": "7.5"},
        "battery": {"health_percent": "66.2"},
        "storage": [{"serial": "PHHP945005MJ512C"}],
        "manual_input": {"weight_lbs": "4.5", "grade": "Grade B",
                         "condition": "C4 - Used Good", "color": "Black",
                         "screen_size_inch": "14 inch", "mark": "", "cddvd_present": "No"},
        "overall_result": "PASS",
    }
    payload.update(over)
    return {"overall_result": payload["overall_result"], "payload": payload}


def _checks():
    # 1. golden real sample -> exact values + gate ready
    env = _load_sample()
    res = normalizer.normalize(env, wipe_fn=_wipe_pass)
    assert not res.exceptions, res.exceptions
    for col, want in GOLDEN_5CG01809VM.items():
        assert res.values[col] == want, f"{col}: {res.values[col]!r} != {want!r}"
    g = gate.evaluate(res, wipe_fn=_wipe_pass)
    assert g.status == "ready" and g.note is None, (g.status, g.note)

    # 2. SKILL section 7 shape: 8 GB / 66.2% / drive SN, overall FAIL -> soft
    env2 = _mini_env(memory={"total_gb": "7.5"}, overall_result="FAIL")
    r2 = normalizer.normalize(env2, wipe_fn=_wipe_pass)
    assert r2.values["ddlProperty001"] == "8 GB", r2.values["ddlProperty001"]
    assert r2.values["ddlProperty003"] == "512 GB"
    assert r2.values["ddlProperty004"] == "M.2 SSD NVME"
    assert r2.values["ddlProperty005"] == "Pass"
    assert r2.values["ddlProperty010"] == "Intel Core i7"
    assert r2.values["ddlProperty011"] == "1.9 GHz"
    assert r2.values["TxtProperty003"] == "PHHP945005MJ512C"
    assert r2.values["TxtProperty005"] == "66.2%"
    assert r2.values["TxtProperty006"] == "8665U"
    g2 = gate.evaluate(r2, wipe_fn=_wipe_pass)
    assert g2.status == "ready", g2  # FAIL is soft, still ready
    assert "TEST_FAIL" in g2.soft_flags and "TEST_FAIL" in g2.note

    # 3a. wipe FAILED -> gate pending, note mentions wipe
    def wipe_failed(sn):
        return {"result": "FAILED", "capacity": "512GB", "device_type": "M.2 NVMe SSD", "drive_sn": sn}
    r3 = normalizer.normalize(_mini_env(), wipe_fn=wipe_failed)
    g3 = gate.evaluate(r3, wipe_fn=wipe_failed)
    assert g3.status == "pending" and "wipe" in g3.note.lower(), g3

    # 3b. Grade empty -> normalizer still names Grade, but Grade isn't a
    #     blocking field -> gate ready with an INCOMPLETE flag, blank Grade
    env_ng = _mini_env()
    env_ng["payload"]["manual_input"]["grade"] = ""
    r4 = normalizer.normalize(env_ng, wipe_fn=_wipe_pass)
    assert any(e["field"] == "Grade" for e in r4.exceptions), r4.exceptions
    g4 = gate.evaluate(r4, wipe_fn=_wipe_pass)
    assert g4.status == "ready" and "INCOMPLETE" in g4.soft_flags, g4

    # 3c. memory 130 GB -> over-max exception on ddlProperty001
    r5 = normalizer.normalize(_mini_env(memory={"total_gb": "130"}), wipe_fn=_wipe_pass)
    assert any(e["field"] == "ddlProperty001" for e in r5.exceptions), r5.exceptions

    # 3d. device_type garbage -> exception on ddlProperty004
    def wipe_garbage(sn):
        return {"result": "PASSED", "capacity": "512GB", "device_type": "ZZZ QUANTUM CUBE", "drive_sn": sn}
    r6 = normalizer.normalize(_mini_env(), wipe_fn=wipe_garbage)
    assert any(e["field"] == "ddlProperty004" for e in r6.exceptions), r6.exceptions

    # 4. no-disk branch: Storage Size = "No Storage", Type/HDD-SN blank,
    #    ddl005 ND-No Data, NO_DISK flag
    r7 = normalizer.normalize(_mini_env(storage=[]), wipe_fn=_wipe_pass)
    assert r7.values["ddlProperty003"] == "No Storage", r7.values["ddlProperty003"]
    assert r7.values["ddlProperty004"] == "" and r7.values["TxtProperty003"] == ""
    assert r7.values["ddlProperty005"] == "ND-No Data"
    g7 = gate.evaluate(r7, wipe_fn=_wipe_pass)
    assert g7.status == "ready" and "NO_DISK" in g7.soft_flags, g7

    # 4a. diskless placeholder, operator CONFIRMED no disk -> safe, ready+NO_DISK
    ph_ok = [{"device": "none", "model": "NOT DETECTED", "fail_reason": "NO_DISK_CONFIRMED"}]
    r7a = normalizer.normalize(_mini_env(storage=ph_ok), wipe_fn=_wipe_pass)
    assert r7a.values["ddlProperty003"] == "No Storage" and r7a.values["ddlProperty005"] == "ND-No Data"
    assert not r7a.exceptions, r7a.exceptions
    g7a = gate.evaluate(r7a, wipe_fn=_wipe_pass)
    assert g7a.status == "ready" and "NO_DISK" in g7a.soft_flags, g7a

    # 4b. Enter-skipped diskless (detected none, unconfirmed) -> Ready with a
    #     louder NO_DISK_UNCONFIRMED flag; Storage Size still "No Storage"
    for fr in ("NO_STORAGE_DETECTED", "DELL_RAID_MODE"):
        ph = [{"device": "none", "model": "NOT DETECTED", "fail_reason": fr}]
        rb = normalizer.normalize(_mini_env(storage=ph), wipe_fn=_wipe_pass)
        assert rb.values["ddlProperty003"] == "No Storage", (fr, rb.values["ddlProperty003"])
        gb = gate.evaluate(rb, wipe_fn=_wipe_pass)
        assert gb.status == "ready" and "NO_DISK_UNCONFIRMED" in gb.soft_flags, (fr, gb)

    # 4b2. no battery (script emits only {"status": "NOT_FOUND"}) -> not a fail:
    #      TxtProperty005 = "NO BATTERY", record still Ready
    r_nb = normalizer.normalize(_mini_env(battery={"status": "NOT_FOUND"}), wipe_fn=_wipe_pass)
    assert r_nb.values["TxtProperty005"] == "NO BATTERY", r_nb.values["TxtProperty005"]
    assert not any(e["field"] == "TxtProperty005" for e in r_nb.exceptions), r_nb.exceptions
    assert gate.evaluate(r_nb, wipe_fn=_wipe_pass).status == "ready"

    # 4c. operator answered a disk IS installed but hidden -> blocked
    ph = [{"device": "none", "model": "NOT DETECTED", "fail_reason": "DISK_PRESENT_BUT_HIDDEN"}]
    gb = gate.evaluate(normalizer.normalize(_mini_env(storage=ph), wipe_fn=_wipe_pass),
                       wipe_fn=_wipe_pass)
    assert gb.status == "pending" and "not verified" in gb.note, gb

    # 5. config-driven: drop 16 from the memory domain -> 15.4 now buckets to 24
    cfg = copy.deepcopy(normalizer.load_config())
    cfg["domains"]["memory"] = [g for g in cfg["domains"]["memory"] if g != 16]
    r8 = normalizer.normalize(_load_sample(), config=cfg, wipe_fn=_wipe_pass)
    assert r8.values["ddlProperty001"] == "24 GB", r8.values["ddlProperty001"]


def test_phase2():
    _checks()


if __name__ == "__main__":
    _checks()
    print("PASS: all Phase 2 checks green")
