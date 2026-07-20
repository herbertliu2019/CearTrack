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

# Only these checks can fail the whole device. Any other FAIL is downgraded
# to WARNING (both in overall_result and the stored field value) so it
# renders as a warning everywhere instead of a hard failure.
CRITICAL_FAIL_FIELDS = {
    ("keyboard", "keys_check"),
    ("keyboard", "touchpad_check"),
}


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

        self._downgrade_noncritical_fails(raw_payload)
        overall = self._compute_overall_result(raw_payload)

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

    @staticmethod
    def _downgrade_noncritical_fails(payload: dict) -> None:
        """In-place: any FAIL outside CRITICAL_FAIL_FIELDS becomes WARNING.

        Only screen/keyboard/touchpad/internet failures define an overall
        device FAIL. Everything else (camera, speaker, mic, battery, ports,
        appearance, kernel health, ...) is a warning, not a failure — this
        keeps the stored payload consistent with that rule so downstream
        rendering (Test Results grid, status dots, fail_reasons stats)
        doesn't need any special-casing.
        """
        for section_name, section in payload.items():
            if not isinstance(section, dict):
                continue
            for k, v in section.items():
                if v == "FAIL" and (section_name, k) not in CRITICAL_FAIL_FIELDS:
                    section[k] = "WARNING"

    @staticmethod
    def _compute_overall_result(payload: dict) -> str:
        """FAIL only if a critical field is FAIL; WARN if anything else
        warns; else PASS. Call after _downgrade_noncritical_fails()."""
        has_fail = False
        has_warn = False
        for section_name, section in payload.items():
            if not isinstance(section, dict):
                continue
            for k, v in section.items():
                if not isinstance(v, str):
                    continue
                if v == "FAIL" and (section_name, k) in CRITICAL_FAIL_FIELDS:
                    has_fail = True
                elif v in ("WARN", "WARNING"):
                    has_warn = True
        if has_fail:
            return "FAIL"
        if has_warn:
            return "WARN"
        return "PASS"

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
        bat_status = payload.get("battery", {}).get("status", "")
        bat_health = payload.get("battery", {}).get("health_percent", "")
        if bat_status == "WARNING":
            health_str = f" ({bat_health}%)" if bat_health and bat_health != "unknown" else ""
            warnings.append(f"Battery low{health_str} — mark note in Cyclelution")

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
        elif overall == "WARN":
            warned = []
            for section_name, section in payload.items():
                if isinstance(section, dict):
                    for k, v in section.items():
                        if isinstance(v, str) and v in ("WARN", "WARNING"):
                            warned.append(f"{section_name}.{k}")
            summary = f"{len(warned)} warning(s): {', '.join(warned[:3])}"
            if len(warned) > 3:
                summary += f" (+{len(warned) - 3} more)"
        elif warnings:
            summary = f"PASS — {len(warnings)} warning(s): {'; '.join(warnings[:2])}"
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


def _compute_by_grade(records):
    """Grade distribution in fixed order A, B, C. Records without a grade
    field are skipped entirely (not counted in numerator or denominator).

    Raw value is like "Grade B" — take the trailing letter.
    """
    counts = {"A": 0, "B": 0, "C": 0}
    for r in records:
        raw = r.get("payload", {}).get("manual_input", {}).get("grade", "")
        grade = (raw or "").strip().split()[-1] if raw else ""
        if grade in counts:
            counts[grade] += 1

    total_graded = sum(counts.values())
    result = []
    for g in ["A", "B", "C"]:
        count = counts[g]
        pct = round(count / total_graded * 100) if total_graded else 0
        result.append({"grade": g, "count": count, "pct": pct})
    return result


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

    # Cyclelution flow: register the record and evaluate it immediately so it
    # lands in Ready or Exceptions right away (no manual Rescan needed).
    # Best-effort — a failure here must never block the upload; ensure_pending
    # runs first so a broken evaluate still leaves a pending row for Rescan.
    try:
        from cyclelution import sync_state, scan
        hp = paths["history_path"]
        sync_state.ensure_pending(hp, sn=envelope["sn"], record_ts=envelope.get("timestamp"))
        scan.evaluate_one(hp, envelope=envelope)
    except Exception as e:
        print(f"[laptop] cyclelution evaluate failed (non-fatal): {e}")

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
    warn_count = sum(1 for r in records if r.get("overall_result") == "WARN")
    fail_count = sum(1 for r in records if r.get("overall_result") == "FAIL")
    return jsonify({
        "total_today": total,
        "pass": pass_count,
        "warning": warn_count,
        "fail": fail_count,
        "pass_rate": round(pass_count / total * 100, 1) if total else 0,
        "by_grade": _compute_by_grade(records),
    })


@blueprint.route("/api/stats/total")
def api_stats_total():
    """Total count of all laptop history records ever (across all dates)."""
    base = config.BASE_DIR / "laptop" / "history"
    total = sum(1 for _ in base.rglob("*.json")) if base.exists() else 0
    return jsonify({"total": total})


@blueprint.route("/api/stats/range")
def api_stats_range():
    """Aggregate stats over a date range.

    Query params:
      range=week   → last 7 days
      range=month  → last 30 days
      from=YYYY-MM-DD&to=YYYY-MM-DD → custom range
    """
    from datetime import timedelta

    range_param = request.args.get("range")
    from_param = request.args.get("from")
    to_param = request.args.get("to")

    today = datetime.now().date()

    if range_param == "week":
        # This week so far: Sunday → today (no future days)
        weekday = (today.weekday() + 1) % 7  # Sunday=0, Monday=1, ..., Saturday=6
        date_from = today - timedelta(days=weekday)
        date_to = today
    elif range_param == "month":
        # This month so far: 1st → today (no future days)
        date_from = today.replace(day=1)
        date_to = today
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
    passed  = sum(1 for r in records if r.get("overall_result") == "PASS")
    warned  = sum(1 for r in records if r.get("overall_result") == "WARN")
    failed  = sum(1 for r in records if r.get("overall_result") == "FAIL")

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

    from collections import defaultdict
    daily_map = defaultdict(lambda: {'total': 0, 'passed': 0, 'warned': 0, 'failed': 0})
    for r in records:
        day = r.get('timestamp', '')[:10]
        daily_map[day]['total'] += 1
        result = r.get('overall_result', '')
        if result == 'PASS':
            daily_map[day]['passed'] += 1
        elif result == 'WARN':
            daily_map[day]['warned'] += 1
        else:
            daily_map[day]['failed'] += 1
    daily = [
        {'date': d, 'total': v['total'], 'passed': v['passed'],
         'warned': v['warned'], 'failed': v['failed']}
        for d, v in sorted(daily_map.items())
    ]

    brands_sorted = sorted(brands.items(), key=lambda x: x[1], reverse=True)
    fail_reasons_sorted = sorted(fail_reasons.items(), key=lambda x: x[1], reverse=True)
    by_grade = _compute_by_grade(records)

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
        "warned":       warned,
        "failed":       failed,
        "pass_rate":    round(passed / total * 100, 1) if total else 0,
        "brands":       brands_sorted,
        "by_grade":     by_grade,
        "fail_reasons": fail_reasons_sorted,
        "daily":        daily,
        "records":      record_list,
    })
