"""GPU test module — handles gpu_test.sh uploads."""

import json
import logging
import os
from datetime import datetime, timezone, timedelta, date
from pathlib import Path

from flask import Blueprint, request, jsonify, render_template, send_file, abort

import config
from modules.base import TestModule
from core.envelope import build_envelope
from core import storage, index_db

log = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).parent / "schema.json"


def _record_row(r: dict) -> dict:
    p = r.get("payload", {}) or {}
    gpu = p.get("gpu", {}) or {}
    vb = p.get("vulkan_benchmark", {}) or {}
    th = p.get("thermal", {}) or {}
    ti = p.get("test_info", {}) or {}
    return {
        "sn":             r.get("sn"),
        "gpu_name":       gpu.get("name", ""),
        "vendor":         gpu.get("vendor", ""),
        "vram_mb":        gpu.get("vram_mb", 0),
        "overall_result": r.get("overall_result", ""),
        "timestamp":      r.get("timestamp", ""),
        "glmark2_score":  vb.get("score", 0),
        "temp_max_c":     th.get("temp_max_c", 0),
        "test_station":   ti.get("test_station", ""),
        "total_duration_seconds":   ti.get("total_duration_seconds", 0),
        "burn_duration_seconds":    ti.get("burn_duration_seconds", 0),
        "glmark2_duration_seconds": ti.get("glmark2_duration_seconds", 0),
        "summary":        r.get("summary", ""),
        "payload":        p,
    }


SUBVENDOR_ALIASES = {
    "asustek":          "ASUS",
    "asus":             "ASUS",
    "micro-star":       "MSI",
    "microstar":        "MSI",
    "msi":              "MSI",
    "gigabyte":         "Gigabyte",
    "giga-byte":        "Gigabyte",
    "sapphire":         "Sapphire",
    "evga":             "EVGA",
    "pny":              "PNY",
    "zotac":            "ZOTAC",
    "palit":            "Palit",
    "gainward":         "Gainward",
    "inno3d":           "Inno3D",
    "colorful":         "Colorful",
    "leadtek":          "Leadtek",
    "asrock":           "ASRock",
    "xfx":              "XFX",
    "powercolor":       "PowerColor",
    "his":              "HIS",
    "club3d":           "Club 3D",
    "club 3d":          "Club 3D",
    "pc partner":       "PC Partner",
    "pcpartner":        "PC Partner",
    "shenzhen bitland": "Bitland",
    "shenzen bitland":  "Bitland",  # 拼写错误归一
    "bitland":          "Bitland",
    "dell":             "Dell",
    "hp":               "HP",
    "hewlett-packard":  "HP",
    "lenovo":           "Lenovo",
    "nvidia":           "NVIDIA",  # 公版
    "ati":              "AMD",
    "amd":              "AMD",
    "intel":            "Intel",
}


def _normalize_subvendor(raw: str) -> str:
    """Map messy subvendor strings to canonical brand names."""
    if not raw:
        return "Unknown"
    s = raw.lower().strip()
    # Direct match first
    if s in SUBVENDOR_ALIASES:
        return SUBVENDOR_ALIASES[s]
    # Substring match (handles "ASUSTeK Computer Inc. TU104 [...]")
    for key, canonical in SUBVENDOR_ALIASES.items():
        if key in s:
            return canonical
    # Fallback: first word, title-cased
    first = raw.strip().split()[0] if raw.strip() else "Unknown"
    return first[:20]



class GpuModule(TestModule):
    name = "gpu"
    display_name = "GPU Test"
    icon = "gpu"

    def extract_envelope(self, raw_payload: dict) -> dict:
        sn = self._extract_sn(raw_payload)
        timestamp = (
            raw_payload.get("timestamp")
            or datetime.now(timezone.utc).isoformat()
        )
        # hostname 已从客户端脚本移除；用 test_station 兜底
        ti = (raw_payload.get("payload", {}) or {}).get("test_info", {}) or {}
        hostname = (
            raw_payload.get("hostname")
            or ti.get("test_station")
            or "unknown"
        )
        overall = str(raw_payload.get("overall_result", "UNKNOWN")).upper()
        summary = raw_payload.get("summary", "")

        return build_envelope(
            module_name=self.name,
            sn=sn,
            timestamp=timestamp,
            overall_result=overall,
            summary=summary,
            hostname=hostname,
            payload=raw_payload.get("payload", {}),
        )

    def _extract_sn(self, raw: dict) -> str:
        payload = raw.get("payload", {}) or {}
        gpu = payload.get("gpu", {}) or {}

        gpu_sn = (gpu.get("gpu_sn") or "").strip()
        if gpu_sn:
            return gpu_sn

        top_sn = (raw.get("sn") or "").strip()
        if top_sn:
            return top_sn

        hostname = (raw.get("hostname") or "unknown").strip()
        ts = (raw.get("timestamp") or datetime.now().isoformat())[:16].replace(" ", "T")
        return f"GPU-{hostname}-{ts}"

    def compute_verdict(self, envelope: dict) -> dict:
        payload = envelope.get("payload", {}) or {}
        overall = envelope.get("overall_result", "UNKNOWN")
        warnings = []
        return {"result": overall, "summary": envelope.get("summary", ""), "warnings": warnings}

    def get_display_schema(self) -> dict:
        with open(SCHEMA_PATH, encoding="utf-8") as f:
            return json.load(f)

    def validate(self, raw_payload: dict):
        if not isinstance(raw_payload, dict):
            return False, "Payload is not a JSON object"
        for field in ("module", "sn", "timestamp", "overall_result", "payload"):
            if field not in raw_payload:
                return False, f"Missing required field: {field}"
        if "gpu" not in (raw_payload.get("payload") or {}):
            return False, "Missing payload.gpu section"
        return True, "OK"


_module = GpuModule()

blueprint = Blueprint(
    "gpu",
    __name__,
    template_folder="templates",
    static_folder=None,
)


# ── Upload ────────────────────────────────────────────────────────────────────

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

    try:
        from modules.gpu.pdf_generator import generate_pdf
        generate_pdf(envelope["sn"], envelope)
    except Exception as e:
        log.warning("GPU PDF generation failed for %s: %s", envelope["sn"], e)

    return jsonify({
        "status": "ok",
        "sn": envelope["sn"],
        "result": envelope["overall_result"],
        "summary": envelope["summary"],
    }), 201


# ── Dashboard ─────────────────────────────────────────────────────────────────

@blueprint.route("/")
def dashboard():
    return render_template("gpu/dashboard.html")


# ── Schema ────────────────────────────────────────────────────────────────────

@blueprint.route("/api/schema")
def api_schema():
    return jsonify(_module.get_display_schema())


# ── Today ─────────────────────────────────────────────────────────────────────

def _read_history_for_date(d: date) -> list[dict]:
    day_dir = config.BASE_DIR / "gpu" / "history" / d.strftime("%Y") / d.strftime("%m-%d")
    out = []
    if day_dir.exists():
        for f in day_dir.glob("*.json"):
            try:
                out.append(json.loads(f.read_text(encoding="utf-8")))
            except Exception:
                pass
    return out


@blueprint.route("/api/today")
def api_today():
    records = storage.read_latest(_module.name)
    records.sort(key=lambda r: r.get("timestamp", ""), reverse=True)

    rows = [_record_row(r) for r in records]
    total = len(rows)
    passed = sum(1 for r in rows if r["overall_result"] == "PASS")
    warned = sum(1 for r in rows if r["overall_result"] == "WARN")
    failed = sum(1 for r in rows if r["overall_result"] == "FAIL")
    pass_rate = round(passed / total * 100, 1) if total else 0.0

    # Avg total duration today (seconds), skip 0s
    durs = [r["total_duration_seconds"] for r in rows if r.get("total_duration_seconds")]
    avg_duration = round(sum(durs) / len(durs)) if durs else 0

    # By station breakdown (today)
    station_map: dict[str, dict] = {}
    for r in rows:
        st = r.get("test_station") or "Unknown"
        s = station_map.setdefault(st, {"name": st, "total": 0, "passed": 0, "failed": 0, "warned": 0})
        s["total"] += 1
        res = r.get("overall_result", "")
        if res == "PASS":   s["passed"] += 1
        elif res == "FAIL": s["failed"] += 1
        elif res == "WARN": s["warned"] += 1
    by_station = sorted(station_map.values(), key=lambda x: x["total"], reverse=True)

    # Fail-reason buckets (today)
    fail_reasons: dict[str, list[str]] = {}
    for r in rows:
        if r["overall_result"] != "FAIL":
            continue
        p = r.get("payload", {}) or {}
        if (p.get("vram_test", {}) or {}).get("errors", 0):
            fail_reasons.setdefault("VRAM_ERROR", []).append(r["sn"])
        if p.get("dmesg_gpu_errors"):
            fail_reasons.setdefault("DMESG_ERROR", []).append(r["sn"])
        if ((p.get("thermal", {}) or {}).get("temp_max_c") or 0) > 95:
            fail_reasons.setdefault("OVERHEAT", []).append(r["sn"])

    # By vendor + by subvendor (today)
    from collections import defaultdict as _dd
    by_vendor_map: dict[str, int] = {}
    subv_map: dict[str, dict] = _dd(
        lambda: {"name": "", "vendor": "", "total": 0, "passed": 0, "failed": 0, "warned": 0, "score_sum": 0, "score_n": 0}
    )
    for r in rows:
        p = r.get("payload", {}) or {}
        gpu = p.get("gpu", {}) or {}
        vendor = gpu.get("vendor", "Unknown")
        by_vendor_map[vendor] = by_vendor_map.get(vendor, 0) + 1

        subv_canonical = _normalize_subvendor(gpu.get("subvendor", ""))
        sv = subv_map[subv_canonical]
        sv["name"]   = subv_canonical
        sv["vendor"] = vendor
        sv["total"] += 1
        res_sv = r.get("overall_result", "")
        if res_sv == "PASS":   sv["passed"] += 1
        elif res_sv == "FAIL": sv["failed"] += 1
        elif res_sv == "WARN": sv["warned"] += 1
        score = ((p.get("vulkan_benchmark", {}) or {}).get("score") or 0)
        if score:
            sv["score_sum"] += score
            sv["score_n"]  += 1

    by_vendor = sorted(by_vendor_map.items(), key=lambda x: x[1], reverse=True)
    by_subvendor = []
    for sv in subv_map.values():
        t = sv["total"]
        by_subvendor.append({
            "name":      sv["name"],
            "vendor":    sv["vendor"],
            "count":     t,
            "passed":    sv["passed"],
            "failed":    sv["failed"],
            "warned":    sv["warned"],
            "pass_rate": round(sv["passed"] / t * 100, 1) if t else 0.0,
            "avg_score": round(sv["score_sum"] / sv["score_n"]) if sv["score_n"] else 0,
        })
    by_subvendor.sort(key=lambda x: x["count"], reverse=True)

    # VRAM yield tiers (today)
    yield_tiers = {"high": 0, "mid": 0, "entry": 0, "scrap": 0}
    for r in rows:
        if r["overall_result"] == "FAIL":
            yield_tiers["scrap"] += 1; continue
        vm = r.get("vram_mb") or 0
        if vm >= 10240:  yield_tiers["high"] += 1
        elif vm >= 6144: yield_tiers["mid"] += 1
        else:            yield_tiers["entry"] += 1

    # Compare vs yesterday + 7-day average
    today_date = date.today()
    yesterday_recs = _read_history_for_date(today_date - timedelta(days=1))
    yest_total  = len(yesterday_recs)
    yest_passed = sum(1 for r in yesterday_recs if r.get("overall_result") == "PASS")
    yest_pass_rate = round(yest_passed / yest_total * 100, 1) if yest_total else 0.0

    week_totals, week_pass_rates = [], []
    for i in range(1, 8):
        recs = _read_history_for_date(today_date - timedelta(days=i))
        if not recs: continue
        t = len(recs); pa = sum(1 for r in recs if r.get("overall_result") == "PASS")
        week_totals.append(t)
        week_pass_rates.append(pa / t * 100 if t else 0)
    week_avg_total = round(sum(week_totals) / len(week_totals)) if week_totals else 0
    week_avg_pass_rate = round(sum(week_pass_rates) / len(week_pass_rates), 1) if week_pass_rates else 0.0

    return jsonify({
        "stats": {
            "total":    total,
            "passed":   passed,
            "warned":   warned,
            "failed":   failed,
            "pass_rate": pass_rate,
            "avg_duration_seconds": avg_duration,
        },
        "compare": {
            "yesterday_total":     yest_total,
            "yesterday_pass_rate": yest_pass_rate,
            "week_avg_total":      week_avg_total,
            "week_avg_pass_rate":  week_avg_pass_rate,
        },
        "by_station":   by_station,
        "by_vendor":    by_vendor,
        "by_subvendor": by_subvendor,
        "fail_reasons": fail_reasons,
        "yield_tiers":  yield_tiers,
        "records":      rows,
    })


# ── Stats (range) ─────────────────────────────────────────────────────────────

@blueprint.route("/api/stats")
def api_stats():
    import calendar

    period = request.args.get("period", "week")
    from_param = request.args.get("start") or request.args.get("from")
    to_param = request.args.get("end") or request.args.get("to")

    today = date.today()
    if period == "week":
        weekday = (today.weekday() + 1) % 7
        date_from = today - timedelta(days=weekday)
        date_to = date_from + timedelta(days=6)
    elif period == "month":
        date_from = today.replace(day=1)
        last_day = calendar.monthrange(today.year, today.month)[1]
        date_to = today.replace(day=last_day)
    elif period == "custom" and from_param and to_param:
        try:
            date_from = datetime.strptime(from_param, "%Y-%m-%d").date()
            date_to = datetime.strptime(to_param, "%Y-%m-%d").date()
        except ValueError:
            return jsonify({"error": "Invalid date format, use YYYY-MM-DD"}), 400
    else:
        return jsonify({"error": "Provide period=week|month or period=custom&start=...&end=..."}), 400

    base = config.BASE_DIR / "gpu" / "history"
    records = []
    current = date_from
    while current <= date_to:
        day_dir = base / current.strftime("%Y") / current.strftime("%m-%d")
        if day_dir.exists():
            for f in day_dir.glob("*.json"):
                try:
                    records.append(json.loads(f.read_text(encoding="utf-8")))
                except Exception:
                    pass
        current += timedelta(days=1)

    total = len(records)
    passed = sum(1 for r in records if r.get("overall_result") == "PASS")
    warned = sum(1 for r in records if r.get("overall_result") == "WARN")
    failed = sum(1 for r in records if r.get("overall_result") == "FAIL")

    by_vendor: dict[str, int] = {}
    fail_reasons: dict[str, int] = {}
    from collections import defaultdict
    daily_map = defaultdict(lambda: {
        "total": 0, "passed": 0, "warned": 0, "failed": 0,
        "dur_sum": 0, "dur_n": 0,
        "stations": defaultdict(lambda: {"total": 0, "passed": 0, "failed": 0, "warned": 0}),
        "gpus":     defaultdict(lambda: {"total": 0, "passed": 0, "failed": 0, "warned": 0}),
        "failures": [],
        "times":    [],
    })
    subv_map: dict[str, dict] = defaultdict(
        lambda: {"name": "", "vendor": "", "total": 0, "passed": 0, "failed": 0, "warned": 0, "score_sum": 0, "score_n": 0}
    )

    for r in records:
        p = r.get("payload", {}) or {}
        gpu = p.get("gpu", {}) or {}
        vendor = gpu.get("vendor", "Unknown")
        by_vendor[vendor] = by_vendor.get(vendor, 0) + 1

        # ── Subvendor aggregation ────────────────────────────
        subv_canonical = _normalize_subvendor(gpu.get("subvendor", ""))
        sv = subv_map[subv_canonical]
        sv["name"] = subv_canonical
        # Keep most-seen vendor for this brand
        sv["vendor"] = vendor
        sv["total"] += 1
        res_sv = r.get("overall_result", "")
        if res_sv == "PASS":   sv["passed"] += 1
        elif res_sv == "FAIL": sv["failed"] += 1
        elif res_sv == "WARN": sv["warned"] += 1
        score = ((p.get("vulkan_benchmark", {}) or {}).get("score") or 0)
        if score:
            sv["score_sum"] += score
            sv["score_n"] += 1

        res = r.get("overall_result", "")
        if res == "FAIL":
            vram = (p.get("vram_test", {}) or {}).get("errors", 0)
            if vram:
                fail_reasons["VRAM_ERROR"] = fail_reasons.get("VRAM_ERROR", 0) + 1
            dmesg = p.get("dmesg_gpu_errors", []) or []
            if dmesg:
                fail_reasons["DMESG_ERROR"] = fail_reasons.get("DMESG_ERROR", 0) + 1
            th = p.get("thermal", {}) or {}
            if (th.get("temp_max_c") or 0) > 95:
                fail_reasons["OVERHEAT"] = fail_reasons.get("OVERHEAT", 0) + 1
        day = (r.get("timestamp") or "")[:10]
        dm = daily_map[day]
        dm["total"] += 1
        res_day = r.get("overall_result", "")
        if res_day == "PASS":   dm["passed"] += 1
        elif res_day == "WARN": dm["warned"] += 1
        elif res_day == "FAIL": dm["failed"] += 1

        ti_day = p.get("test_info", {}) or {}
        dur = ti_day.get("total_duration_seconds") or 0
        if dur:
            dm["dur_sum"] += dur
            dm["dur_n"]   += 1

        st = ti_day.get("test_station") or "Unknown"
        sd = dm["stations"][st]
        sd["total"] += 1
        if res_day == "PASS":   sd["passed"] += 1
        elif res_day == "WARN": sd["warned"] += 1
        elif res_day == "FAIL": sd["failed"] += 1

        gpu_name = (gpu.get("name") or "Unknown").strip()
        gd = dm["gpus"][gpu_name]
        gd["total"] += 1
        if res_day == "PASS":   gd["passed"] += 1
        elif res_day == "WARN": gd["warned"] += 1
        elif res_day == "FAIL": gd["failed"] += 1

        if res_day in ("FAIL", "WARN"):
            reason = None
            if (p.get("vram_test", {}) or {}).get("errors", 0):
                reason = "VRAM errors"
            elif p.get("dmesg_gpu_errors"):
                reason = "dmesg errors"
            else:
                tmax = (p.get("thermal", {}) or {}).get("temp_max_c") or 0
                if tmax > 95:   reason = f"Overheat {tmax}°C"
                elif tmax > 85: reason = f"Warm {tmax}°C"
            dm["failures"].append({
                "sn":       r.get("sn", ""),
                "gpu_name": gpu_name,
                "station":  st,
                "result":   res_day,
                "reason":   reason or "—",
                "time":     (r.get("timestamp") or "")[11:16],
            })
        dm["times"].append({
            "time":   (r.get("timestamp") or "")[11:16],
            "result": res_day,
            "sn":     r.get("sn", ""),
        })

    daily = []
    for d, v in sorted(daily_map.items()):
        stations_rows = sorted(
            ({"name": n, **info} for n, info in v["stations"].items()),
            key=lambda x: x["total"], reverse=True,
        )
        gpus_rows = sorted(
            ({"name": n, **info,
              "pass_rate": round(info["passed"] / info["total"] * 100, 1) if info["total"] else 0.0}
             for n, info in v["gpus"].items()),
            key=lambda x: x["total"], reverse=True,
        )[:5]
        for sr in stations_rows:
            sr["pass_rate"] = round(sr["passed"] / sr["total"] * 100, 1) if sr["total"] else 0.0
        daily.append({
            "date":      d,
            "total":     v["total"],
            "passed":    v["passed"],
            "warned":    v["warned"],
            "failed":    v["failed"],
            "pass_rate": round(v["passed"] / v["total"] * 100, 1) if v["total"] else 0.0,
            "avg_duration_seconds": round(v["dur_sum"] / v["dur_n"]) if v["dur_n"] else 0,
            "stations":  stations_rows,
            "top_gpus":  gpus_rows,
            "failures":  v["failures"][:10],
            "times":     sorted(v.get("times", []), key=lambda x: x["time"])[:100],
        })

    # Build subvendor rows, sorted by count desc, top 10 + Others
    sv_all = sorted(subv_map.values(), key=lambda x: x["total"], reverse=True)
    sv_rows = []
    for sv in sv_all[:10]:
        sv_rows.append({
            "name":      sv["name"],
            "vendor":    sv["vendor"],
            "count":     sv["total"],
            "passed":    sv["passed"],
            "failed":    sv["failed"],
            "warned":    sv["warned"],
            "pass_rate": round(sv["passed"] / sv["total"] * 100, 1) if sv["total"] else 0.0,
            "avg_score": round(sv["score_sum"] / sv["score_n"]) if sv["score_n"] else 0,
        })
    if len(sv_all) > 10:
        others = sv_all[10:]
        o_total  = sum(s["total"] for s in others)
        o_passed = sum(s["passed"] for s in others)
        o_score_sum = sum(s["score_sum"] for s in others)
        o_score_n   = sum(s["score_n"] for s in others)
        sv_rows.append({
            "name":      f"Others ({len(others)})",
            "vendor":    "—",
            "count":     o_total,
            "passed":    o_passed,
            "failed":    sum(s["failed"] for s in others),
            "warned":    sum(s["warned"] for s in others),
            "pass_rate": round(o_passed / o_total * 100, 1) if o_total else 0.0,
            "avg_score": round(o_score_sum / o_score_n) if o_score_n else 0,
        })

    return jsonify({
        "start":         str(date_from),
        "end":           str(date_to),
        "total":         total,
        "passed":        passed,
        "warned":        warned,
        "failed":        failed,
        "pass_rate":     round(passed / total * 100, 1) if total else 0.0,
        "by_vendor":     sorted(by_vendor.items(), key=lambda x: x[1], reverse=True),
        "by_subvendor":  sv_rows,
        "fail_reasons":  sorted(fail_reasons.items(), key=lambda x: x[1], reverse=True),
        "daily":         daily,
    })


@blueprint.route("/api/stats/total")
def api_stats_total():
    base = config.BASE_DIR / "gpu" / "history"
    total = sum(1 for _ in base.rglob("*.json")) if base.exists() else 0
    return jsonify({"total": total})


# ── Day records ──────────────────────────────────────────────────────────────

@blueprint.route("/api/day/<date_str>")
def api_day(date_str):
    try:
        day = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "Invalid date, use YYYY-MM-DD"}), 400
    records = _read_history_for_date(day)
    records.sort(key=lambda r: r.get("timestamp", ""))
    return jsonify({"date": date_str, "records": [_record_row(r) for r in records]})


@blueprint.route("/api/records")
def api_records():
    """Query-param endpoint: /api/records?date=YYYY-MM-DD
    Uses SQLite index (envelopes.timestamp LIKE 'YYYY-MM-DD%') — no dir scan.
    Falls back to filesystem if index is empty.
    """
    date_str = request.args.get("date", "").strip()
    if not date_str:
        return jsonify({"error": "date parameter required"}), 400
    try:
        day = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "Invalid date, use YYYY-MM-DD"}), 400

    # Try SQLite index first
    try:
        conn = index_db._open()
        try:
            rows = conn.execute(
                "SELECT history_path FROM envelopes "
                "WHERE module = ? AND timestamp LIKE ? "
                "ORDER BY timestamp ASC",
                ("gpu", date_str + "%"),
            ).fetchall()
        finally:
            conn.close()

        records = []
        for row in rows:
            p = Path(row["history_path"])
            if p.exists():
                try:
                    records.append(json.loads(p.read_text(encoding="utf-8")))
                except Exception:
                    pass
        if records:
            return jsonify({"date": date_str, "records": [_record_row(r) for r in records]})
    except Exception as e:
        log.warning("index_db query failed, falling back to filesystem: %s", e)

    # Fallback: filesystem scan
    records = _read_history_for_date(day)
    records.sort(key=lambda r: r.get("timestamp", ""))
    return jsonify({"date": date_str, "records": [_record_row(r) for r in records]})


# ── Drill-down filter (vendor / subvendor / fail_reason) ───────────────────────

def _matches_fail_reason(r: dict, reason: str) -> bool:
    """Return True if record r failed for the given reason key."""
    if r.get("overall_result") != "FAIL":
        return False
    p = r.get("payload", {}) or {}
    if reason == "VRAM_ERROR":
        return bool((p.get("vram_test", {}) or {}).get("errors", 0))
    if reason == "DMESG_ERROR":
        return bool(p.get("dmesg_gpu_errors"))
    if reason == "OVERHEAT":
        return ((p.get("thermal", {}) or {}).get("temp_max_c") or 0) > 95
    return False


@blueprint.route("/api/filter")
def api_filter():
    """Drill-down filter for vendor / subvendor / fail_reason within a period.
    Query params:
      period=today|week|month|custom   (required)
      start=YYYY-MM-DD, end=YYYY-MM-DD  (custom only)
      vendor=NVIDIA                     (optional)
      subvendor=ASUS                    (optional, canonical name)
      fail_reason=VRAM_ERROR|DMESG_ERROR|OVERHEAT  (optional)
    """
    import calendar
    period = request.args.get("period", "week")
    vendor    = request.args.get("vendor", "").strip()
    subvendor = request.args.get("subvendor", "").strip()
    reason    = request.args.get("fail_reason", "").strip()

    today = date.today()
    if period == "today":
        date_from = date_to = today
    elif period == "week":
        weekday = (today.weekday() + 1) % 7
        date_from = today - timedelta(days=weekday)
        date_to   = date_from + timedelta(days=6)
    elif period == "month":
        date_from = today.replace(day=1)
        last_day  = calendar.monthrange(today.year, today.month)[1]
        date_to   = today.replace(day=last_day)
    elif period == "custom":
        try:
            date_from = datetime.strptime(request.args.get("start", ""), "%Y-%m-%d").date()
            date_to   = datetime.strptime(request.args.get("end",   ""), "%Y-%m-%d").date()
        except ValueError:
            return jsonify({"error": "Invalid date, use YYYY-MM-DD"}), 400
    else:
        return jsonify({"error": "period required"}), 400

    # Load records via SQLite index for the date range
    records: list[dict] = []
    try:
        conn = index_db._open()
        try:
            rows = conn.execute(
                "SELECT history_path FROM envelopes "
                "WHERE module = ? AND substr(timestamp,1,10) BETWEEN ? AND ? "
                "ORDER BY timestamp ASC",
                ("gpu", date_from.isoformat(), date_to.isoformat()),
            ).fetchall()
        finally:
            conn.close()
        for row in rows:
            p = Path(row["history_path"])
            if p.exists():
                try:
                    records.append(json.loads(p.read_text(encoding="utf-8")))
                except Exception:
                    pass
    except Exception as e:
        log.warning("index_db filter failed, falling back: %s", e)
        cur = date_from
        while cur <= date_to:
            records.extend(_read_history_for_date(cur))
            cur += timedelta(days=1)

    # Apply filters
    if vendor:
        v_up = vendor.upper()
        records = [r for r in records
                   if ((r.get("payload",{}).get("gpu",{}) or {}).get("vendor","") or "").upper() == v_up]
    if subvendor:
        sv_up = subvendor.upper()
        records = [r for r in records
                   if _normalize_subvendor((r.get("payload",{}).get("gpu",{}) or {}).get("subvendor","")).upper() == sv_up]
    if reason:
        records = [r for r in records if _matches_fail_reason(r, reason)]

    records.sort(key=lambda r: r.get("timestamp", ""))
    return jsonify({
        "records": [_record_row(r) for r in records],
        "filter": {
            "period": period, "vendor": vendor, "subvendor": subvendor, "fail_reason": reason,
            "start": date_from.isoformat(), "end": date_to.isoformat(),
        },
    })


# ── Search ────────────────────────────────────────────────────────────────────

@blueprint.route("/api/search")
def api_search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "q parameter required"}), 400

    # Search by SN via index_db
    sn_results = storage.search_sn(_module.name, q)

    # Also search by GPU name in latest/
    latest = storage.read_latest(_module.name)
    name_hits = []
    for r in latest:
        gpu_name = (r.get("payload", {}) or {}).get("gpu", {}).get("name", "")
        if q.lower() in gpu_name.lower():
            name_hits.append(r)

    seen = {r.get("sn") for r in sn_results}
    combined = sn_results + [r for r in name_hits if r.get("sn") not in seen]
    combined.sort(key=lambda r: r.get("timestamp", ""), reverse=True)

    return jsonify({"results": [_record_row(r) for r in combined]})


# ── Latest (for /api/latest compatibility) ────────────────────────────────────

@blueprint.route("/api/latest")
def api_latest():
    records = storage.read_latest(_module.name)
    records.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return jsonify(records)


# ── PDF download ──────────────────────────────────────────────────────────────

@blueprint.route("/report/<sn>.pdf")
def download_pdf(sn):
    pdf_path = config.BASE_DIR / "gpu" / "pdf" / f"{sn}.pdf"
    if not pdf_path.exists():
        abort(404)
    return send_file(
        str(pdf_path),
        mimetype="application/pdf",
        download_name=f"gpu_report_{sn}.pdf",
    )
