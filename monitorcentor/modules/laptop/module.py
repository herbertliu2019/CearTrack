"""Laptop test module — handles laptop_test.sh uploads."""

import json
from pathlib import Path
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify, render_template

import config
from modules.base import TestModule
from core.envelope import build_envelope
from core import storage, index_db

SCHEMA_PATH = Path(__file__).parent / "schema.json"


class LaptopModule(TestModule):
    name = "laptop"
    display_name = "Laptop Test"
    icon = "laptop"

    def extract_envelope(self, raw_payload: dict) -> dict:
        system = raw_payload.get("system", {})
        test_info = raw_payload.get("test_info", {})

        sn = system.get("serial_number", "unknown")
        timestamp = (
            test_info.get("test_time")
            or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        )
        hostname = test_info.get("hostname", "unknown")
        overall = str(raw_payload.get("overall_result", "UNKNOWN")).upper()

        envelope = build_envelope(
            module_name=self.name,
            sn=sn,
            timestamp=timestamp,
            overall_result=overall,
            summary="",
            hostname=hostname,
            payload=raw_payload,
        )

        verdict = self.compute_verdict(envelope)
        envelope["summary"] = verdict["summary"]
        envelope["warnings"] = verdict.get("warnings", [])
        return envelope

    def compute_verdict(self, envelope: dict) -> dict:
        payload = envelope.get("payload", {})
        overall = envelope.get("overall_result", "UNKNOWN")

        warnings = []
        cam_status = payload.get("camera", {}).get("device_status", "")
        if cam_status == "HARDWARE_DETECTED":
            warnings.append("Camera driver init failed — verify in OEM OS")
        bat_cond = payload.get("battery", {}).get("battery_condition", "")
        if bat_cond == "DATA_UNAVAILABLE":
            warnings.append("Battery data unreadable — verify manually")

        if overall == "FAIL":
            failed = []
            for section_name, section in payload.items():
                if isinstance(section, dict):
                    for k, v in section.items():
                        if isinstance(v, str) and v == "FAIL":
                            failed.append(f"{section_name}.{k}")
            summary = f"{len(failed)} check(s) failed: {', '.join(failed[:3])}"
            if len(failed) > 3:
                summary += f" (+{len(failed) - 3} more)"
        elif warnings:
            summary = f"PASS with {len(warnings)} warning(s)"
        else:
            summary = "All tests passed"

        return {"result": overall, "summary": summary, "warnings": warnings}

    def get_display_schema(self) -> dict:
        with open(SCHEMA_PATH, encoding="utf-8") as f:
            return json.load(f)

    def validate(self, raw_payload: dict):
        if not isinstance(raw_payload, dict):
            return False, "Payload is not a JSON object"
        if "system" not in raw_payload:
            return False, "Missing 'system' section"
        if "serial_number" not in raw_payload.get("system", {}):
            return False, "Missing 'system.serial_number'"
        if "overall_result" not in raw_payload:
            return False, "Missing 'overall_result'"
        return True, "OK"

    def extract_searchable_sns(self, envelope: dict) -> list[dict]:
        """System SN + every storage-device serial."""
        sns: list[dict] = [{"sn": envelope.get("sn", ""), "kind": "system"}]
        payload = envelope.get("payload", {}) or {}
        for dev in payload.get("storage", []) or []:
            serial = (dev.get("serial") or "").strip()
            if serial and serial.lower() not in ("", "unknown"):
                sns.append({"sn": serial, "kind": "storage"})
        return sns


_module = LaptopModule()
blueprint = Blueprint(
    "laptop",
    __name__,
    template_folder="templates",
    static_folder=None,
)


@blueprint.route("/")
def dashboard():
    return render_template(
        "module.html",
        module_name=_module.name,
        display_name=_module.display_name,
    )


@blueprint.route("/api/upload", methods=["POST"])
def api_upload():
    raw = request.get_json(silent=True)
    if raw is None:
        return jsonify({"error": "Invalid or missing JSON"}), 400

    ok, msg = _module.validate(raw)
    if not ok:
        return jsonify({"error": msg}), 400

    envelope = _module.extract_envelope(raw)
    paths = storage.write_envelope(_module.name, envelope["sn"], envelope)
    index_db.upsert(
        _module.name,
        envelope,
        _module.extract_searchable_sns(envelope),
        paths["history_path"],
    )

    return jsonify({
        "status": "ok",
        "sn": envelope["sn"],
        "result": envelope["overall_result"],
        "summary": envelope["summary"],
    }), 201


@blueprint.route("/api/latest")
def api_latest():
    records = storage.read_latest(_module.name)
    records.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return jsonify(records)


@blueprint.route("/api/search")
def api_search():
    sn = request.args.get("sn", "").strip()
    if not sn:
        return jsonify({"error": "sn parameter required"}), 400
    results = storage.search_sn(_module.name, sn)
    results.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return jsonify(results)


@blueprint.route("/api/schema")
def api_schema():
    return jsonify(_module.get_display_schema())


@blueprint.route("/api/stats")
def api_stats():
    records = storage.read_latest(_module.name)
    total = len(records)
    pass_count = sum(1 for r in records if r.get("overall_result") == "PASS")
    fail_count = sum(1 for r in records if r.get("overall_result") == "FAIL")
    return jsonify({
        "total_today": total,
        "pass": pass_count,
        "fail": fail_count,
        "pass_rate": round(pass_count / total * 100, 1) if total else 0,
    })


@blueprint.route("/api/stats/range")
def api_stats_range():
    """Aggregate stats over a date range.

    Query params:
      range=week   → last 7 days
      range=month  → last 30 days
      from=YYYY-MM-DD&to=YYYY-MM-DD → custom range
    """
    from datetime import timedelta
    import calendar

    range_param = request.args.get("range")
    from_param = request.args.get("from")
    to_param = request.args.get("to")

    today = datetime.now().date()

    if range_param == "week":
        # Calendar week: Monday 00:00 to Sunday 23:59
        weekday = today.weekday()  # Monday=0, Sunday=6
        date_from = today - timedelta(days=weekday)
        date_to = date_from + timedelta(days=6)
    elif range_param == "month":
        # Calendar month: 1st to last day of current month
        date_from = today.replace(day=1)
        last_day = calendar.monthrange(today.year, today.month)[1]
        date_to = today.replace(day=last_day)
    elif from_param and to_param:
        try:
            date_from = datetime.strptime(from_param, "%Y-%m-%d").date()
            date_to = datetime.strptime(to_param, "%Y-%m-%d").date()
        except ValueError:
            return jsonify({"error": "Invalid date format, use YYYY-MM-DD"}), 400
    else:
        return jsonify({"error": "Provide range=week|month or from+to params"}), 400

    base = config.BASE_DIR / "laptop" / "history"
    records = []
    current = date_from
    while current <= date_to:
        year = current.strftime("%Y")
        mmdd = current.strftime("%m-%d")
        day_dir = base / year / mmdd
        if day_dir.exists():
            for f in day_dir.glob("*.json"):
                try:
                    with open(f, encoding="utf-8") as fh:
                        records.append(json.load(fh))
                except Exception:
                    pass
        current += timedelta(days=1)

    total = len(records)
    passed = sum(1 for r in records if r.get("overall_result") == "PASS")
    failed = total - passed

    brands: dict[str, int] = {}
    for r in records:
        vendor = r.get("payload", {}).get("system", {}).get("vendor", "Unknown")
        if "Dell" in vendor:
            vendor = "Dell"
        elif "HP" in vendor or "Hewlett" in vendor:
            vendor = "HP"
        elif "Lenovo" in vendor:
            vendor = "Lenovo"
        elif "Microsoft" in vendor:
            vendor = "Microsoft"
        elif "Apple" in vendor:
            vendor = "Apple"
        brands[vendor] = brands.get(vendor, 0) + 1

    fail_reasons: dict[str, int] = {}
    for r in records:
        if r.get("overall_result") != "FAIL":
            continue
        payload = r.get("payload", {})
        checks = [
            ("Screen",        payload.get("screen", {}).get("dead_pixel_check")),
            ("Camera",        payload.get("camera", {}).get("device_status")),
            ("Speaker",       payload.get("audio", {}).get("speaker_quality_check")),
            ("Microphone",    payload.get("audio", {}).get("mic_record_check")),
            ("Keyboard",      payload.get("keyboard", {}).get("keys_check")),
            ("Touchpad",      payload.get("keyboard", {}).get("touchpad_check")),
            ("Battery",       payload.get("battery", {}).get("status")),
            ("Network",       payload.get("network", {}).get("internet_test")),
            ("Ports",         payload.get("ports", {}).get("physical_check")),
            ("Appearance",    payload.get("appearance", {}).get("scratch_check")),
            ("Kernel Health", payload.get("kernel_health", {}).get("status")),
        ]
        for label, val in checks:
            if val == "FAIL":
                fail_reasons[label] = fail_reasons.get(label, 0) + 1

    brands_sorted = sorted(brands.items(), key=lambda x: x[1], reverse=True)
    fail_reasons_sorted = sorted(fail_reasons.items(), key=lambda x: x[1], reverse=True)

    record_list = [
        {
            "sn":             r.get("sn"),
            "timestamp":      r.get("timestamp"),
            "overall_result": r.get("overall_result"),
            "model":          r.get("payload", {}).get("system", {}).get("model", ""),
            "vendor":         r.get("payload", {}).get("system", {}).get("vendor", ""),
            "summary":        r.get("summary", ""),
            "payload":        r.get("payload", {}),
        }
        for r in sorted(records, key=lambda x: x.get("timestamp", ""), reverse=True)
    ]

    return jsonify({
        "date_from":    str(date_from),
        "date_to":      str(date_to),
        "total":        total,
        "passed":       passed,
        "failed":       failed,
        "pass_rate":    round(passed / total * 100, 1) if total else 0,
        "brands":       brands_sorted,
        "fail_reasons": fail_reasons_sorted,
        "records":      record_list,
    })
