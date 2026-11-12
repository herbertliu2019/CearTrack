#!/usr/bin/env python3
"""Seed the monitor module through its upload API with sample reports.

Usage: python scripts/seed_monitor_samples.py [http://127.0.0.1:5004]

Test times are relative to now, so the samples land in the default "today" view.
Each run therefore adds new tests for the same SNs.
"""

import copy
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta

BASE_URL = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:5004"
UPLOAD_URL = f"{BASE_URL}/monitor/api/upload"
NOW = datetime.now().astimezone().replace(microsecond=0)


def base_report(sn, minutes_ago=0, vendor="Dell", pnp="DEL", model="P2419H", size=23.8,
                native="1920x1080", refresh=60.0, operator="T01"):
    return {
        "report_type": "monitor",
        "test_info": {
            "test_time": (NOW - timedelta(minutes=minutes_ago)).isoformat(),
            "operator_id": operator,
            "duration_seconds": 245,
            "script_version": "1.0.0",
            "station_hostname": "monitor-rig-01",
            "station_gpu": "Intel Corporation UHD Graphics 620",
        },
        "identity": {
            "label_sn": sn, "edid_serial_str": sn, "edid_serial_num": 0, "sn_match": "MATCH",
            "vendor": vendor, "vendor_pnp": pnp, "model": model, "product_code": "A0F1",
            "mfg_week": 22, "mfg_year": 2021, "edid_checksum_ok": True,
            "edid_fingerprint": f"{pnp}+A0F1+0+{sn}", "edid_raw_hex": "00ffffffffffff00",
        },
        "display": {
            "native_resolution": native, "native_refresh": refresh,
            "achieved_resolution": native, "achieved_refresh": refresh,
            "resolution_check": "PASS", "station_limited": False, "no_signal": False,
            "size_inch_edid": size, "dead_pixel_count": 0, "max_dead_pixels_allowed": 2,
            "dead_pixel_check": "PASS", "backlight_check": "PASS",
            "patterns_shown": ["red", "green", "blue", "white", "black", "gray50", "grid", "gradient", "checker"],
        },
        "ports": [{"type": "DP", "index": 1, "result": "PASS", "station_connector": "DP-1"},
                  {"type": "HDMI", "index": 1, "result": "PASS", "station_connector": "HDMI-A-1"}],
        "appearance": {"cosmetic_check": "PASS", "defects": [], "defect_note": "",
                       "osd_buttons_check": "PASS", "stand_included": "Yes"},
        "manual_input": {"weight_lbs": "11.5", "grade": "Grade B", "condition": "C4 - Used Good",
                         "color": "Black", "screen_size_inch": f"{size:g} inch", "mark": ""},
        "network": {"ethernet_status": "PASS", "ethernet_device": "enp0s31f6"},
        "result_reasons": [],
        "overall_result": "PASS",
    }


def tweak(report, overall, **sections):
    out = copy.deepcopy(report)
    out["overall_result"] = overall
    for section, values in sections.items():
        if isinstance(values, dict):
            out[section].update(values)
        else:
            out[section] = values
    return out


def samples():
    lg = base_report("906NTZN4G765", 1, "LG", "GSM", "27UD58", 27.0, "3840x2160")
    lg["identity"].update({"product_code": "5B09", "mfg_week": 23, "mfg_year": 2019})
    lg["manual_input"]["screen_size_inch"] = "27 inch"
    lg["ports"] = [{"type": "DP", "index": 1, "result": "PASS", "station_connector": "DP-1"},
                   {"type": "HDMI", "index": 1, "result": "PASS", "station_connector": "HDMI-A-1"},
                   {"type": "HDMI", "index": 2, "result": "PASS", "station_connector": "HDMI-A-1"}]
    yield lg

    yield base_report("SEED-PASS-001", 5, "ASUS", "ACI", "VG248", 24.0)
    yield tweak(base_report("SEED-DEAD-2", 8, "HP", "HWP", "E243"), "PASS",
                display={"dead_pixel_count": 2})
    yield tweak(base_report("SEED-DEAD-3", 10, "HP", "HWP", "E243"), "FAIL",
                display={"dead_pixel_count": 3, "dead_pixel_check": "FAIL"})
    yield tweak(base_report("SEED-CRACK", 12, "Lenovo", "LEN", "T24i"), "FAIL",
                appearance={"cosmetic_check": "FAIL", "defects": ["crack"]})
    yield tweak(base_report("SEED-BURNIN", 14, "Samsung", "SAM", "S24R"), "FAIL",
                appearance={"cosmetic_check": "FAIL", "defects": ["burn-in", "other"],
                            "defect_note": "ghost taskbar"})
    yield tweak(base_report("SEED-PORTFAIL", 16), "FAIL",
                ports=[{"type": "DP", "index": 1, "result": "PASS", "station_connector": "DP-1"},
                       {"type": "HDMI", "index": 1, "result": "FAIL", "station_connector": ""}])
    yield tweak(base_report("SEED-PORTNT", 18, "Acer", "ACR", "V247"), "WARN",
                ports=[{"type": "DP", "index": 1, "result": "PASS", "station_connector": "DP-1"},
                       {"type": "VGA", "index": 1, "result": "NOT_TESTED", "station_connector": ""}])
    yield tweak(base_report("SEED-STATION", 20, "LG", "GSM", "27UK650", 27.0, "3840x2160"), "WARN",
                display={"achieved_refresh": 30.0, "resolution_check": "WARN", "station_limited": True})
    yield tweak(base_report("SEED-SNMISMATCH", 22, "BenQ", "BNQ", "GW2480"), "WARN",
                identity={"edid_serial_str": "ZZZ999", "sn_match": "MISMATCH"})
    yield tweak(base_report("SEED-EDIDEMPTY", 24, "AOC", "AOC", "24B2XH"), "WARN",
                identity={"edid_serial_str": "", "edid_serial_num": 0, "sn_match": "EDID_EMPTY"})
    yield tweak(base_report("SEED-TAMPERED", 26, "Philips", "PHL", "241V8"), "PASS",
                display={"dead_pixel_count": 9, "dead_pixel_check": "FAIL"})
    yield tweak(base_report("SEED-NOSIGNAL", 28, "ViewSonic", "VSC", "VA2405"), "FAIL",
                identity={"edid_serial_str": "", "sn_match": "EDID_EMPTY"},
                display={"no_signal": True, "dead_pixel_count": None, "dead_pixel_check": "NOT_TESTED",
                         "backlight_check": "NOT_TESTED", "resolution_check": "FAIL",
                         "achieved_resolution": "", "achieved_refresh": 0, "patterns_shown": []},
                ports=[])

    # Same SN tested 3 times: fail, fail, pass (latest).
    yield tweak(base_report("SEED-RETEST", 90), "FAIL",
                display={"dead_pixel_count": 4, "dead_pixel_check": "FAIL"})
    yield tweak(base_report("SEED-RETEST", 60), "FAIL",
                appearance={"cosmetic_check": "FAIL", "defects": ["bezel_damaged"]})
    yield base_report("SEED-RETEST", 30, operator="T02")


def post(report):
    req = urllib.request.Request(UPLOAD_URL, data=json.dumps(report).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def main():
    failures = 0
    for report in samples():
        code, body = post(report)
        sn = report["identity"]["label_sn"]
        print(f"{code}  {sn:<20} client={report['overall_result']:<5} server={body.get('result', body)}"
              f"{'  MISMATCH' if body.get('result_mismatch') else ''}")
        if code not in (200, 201):
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
