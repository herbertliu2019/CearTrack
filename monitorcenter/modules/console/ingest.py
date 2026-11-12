"""Parse an externally produced console test JSON into the form-equivalent `data` dict.

No Flask here. Entry point: parse_external(conn, raw) -> (data, errors).

!! The field names below are the CearTrack *canonical* upload format. They are a placeholder until
!! the colleague's real sample JSON is available — adapt `_normalize()` (the only place that knows
!! the external field names) to that sample; everything after it is format-independent.

Canonical format:
{
  "serial_no": "ABC123",            required
  "manufacturer": "Sony",           required (with "model")
  "model": "PlayStation 4",
  "operator": "tech01",             required
  "traveler_id": "T-1001",
  "result": "Pass",                 tool's own verdict; stored as ext_result, never trusted
  "items": {"Power": "Pass", "Video (HDMI)": "Fail"}      or [{"name": "...", "status": "..."}]
  "cosmetic": ["Scratches"],
  "sanitize": {"method": "Factory Reset", "result": "Pass", "date": "2026-11-11",
               "storage_type": "HDD", "storage_size": "500 GB", "hdd_sn": "", "hdd_traveler_id": ""},
  "grade": "", "condition": "", "functionality": "", "cd_dvd": "", "part_no": "", "color": "",
  "weight": 0.0, "notes": ""
}
"""

from modules.console import db, logic


def _norm(s) -> str:
    return " ".join(str(s or "").lower().split())


def _text(v) -> str:
    return str(v).strip() if v is not None else ""


def _normalize(raw: dict) -> dict:
    """External JSON -> canonical dict. Adapt here for the colleague's real format."""
    san = raw.get("sanitize") or {}
    items = raw.get("items") or {}
    if isinstance(items, list):
        items = {_text(i.get("name")): _text(i.get("status")) for i in items if isinstance(i, dict)}
    return {
        "serial_no": _text(raw.get("serial_no")), "traveler_id": _text(raw.get("traveler_id")),
        "manufacturer": _text(raw.get("manufacturer")), "model": _text(raw.get("model")),
        "operator": _text(raw.get("operator")), "ext_result": _text(raw.get("result")),
        "items": items, "cosmetic": [_text(c) for c in (raw.get("cosmetic") or []) if _text(c)],
        "method": _text(san.get("method")), "s_result": _text(san.get("result")),
        "s_date": _text(san.get("date")), "storage_type": _text(san.get("storage_type")),
        "storage_size": _text(san.get("storage_size")), "hdd_sn": _text(san.get("hdd_sn")),
        "hdd_traveler_id": _text(san.get("hdd_traveler_id")),
        "grade": _text(raw.get("grade")), "condition": _text(raw.get("condition")),
        "functionality": _text(raw.get("functionality")), "cd_dvd": _text(raw.get("cd_dvd")),
        "part_no": _text(raw.get("part_no")), "color": _text(raw.get("color")),
        "weight": raw.get("weight"), "notes": _text(raw.get("notes")),
    }


def parse_external(conn, raw: dict) -> tuple[dict, list[str]]:
    """Build the same `data` dict routes._collect() produces. Result/Marks are recomputed here."""
    errors: list[str] = []
    if not isinstance(raw, dict):
        return {}, ["JSON root must be an object"]
    n = _normalize(raw)

    if not n["serial_no"]:
        errors.append("serial_no is required")
    if not n["operator"]:
        errors.append("operator is required")
    if not n["manufacturer"] or not n["model"]:
        errors.append("manufacturer and model are required")
    if errors:
        return {}, errors

    # Model: reuse existing, otherwise create with the generic item set (same as the "Other" entry option).
    model = db.find_model(conn, n["manufacturer"], n["model"])
    new_model = None
    if model:
        src = db.model_items(conn, model["id"])
    else:
        new_model = {"manufacturer": n["manufacturer"], "model": n["model"],
                     "storage_kind": "fixed", "has_data": 1}
        model = {"id": 0, **new_model}
        src = db.generic_items(conn)

    # Items: match reported names to the model's items by label or code; unreported -> N/A.
    reported = {_norm(k): v for k, v in n["items"].items()}
    used: set[str] = set()
    items = []
    for it in src:
        key = next((k for k in (_norm(it["label"]), _norm(it["code"])) if k in reported), None)
        st = "N/A"
        if key:
            used.add(key)
            v = _norm(reported[key])
            st = {"pass": "Pass", "passed": "Pass", "ok": "Pass", "fail": "Fail", "failed": "Fail",
                  "n/a": "N/A", "na": "N/A", "skip": "N/A"}.get(v, "")
            if not st:
                errors.append(f"item '{it['label']}': unknown status '{reported[key]}'")
                st = "N/A"
        items.append({**it, "status": st})
    extra = [k for k in n["items"] if _norm(k) not in used]
    notes = n["notes"]
    if extra:
        notes = (notes + " " if notes else "") + "[unmapped items: " + ", ".join(extra) + "]"

    method = n["method"] or "Factory Reset"
    s_result = n["s_result"] or logic.default_sanitize_result(method)
    if method == "Locked":
        s_result = "Fail"
    elif method == "No data":
        s_result = "N/A"
    s_date = "" if method in ("No data", "Locked") else n["s_date"]

    weight = None
    if n["weight"] not in (None, ""):
        try:
            weight = float(n["weight"])
            if weight < 0:
                raise ValueError
        except (TypeError, ValueError):
            errors.append("weight must be a positive number")

    errors += logic.validate_sanitize(method, s_result, s_date or "x", n["hdd_sn"], n["hdd_traveler_id"])
    if n["grade"] and n["grade"] not in logic.GRADE_LABELS:
        errors.append("invalid grade")
    if n["condition"] and n["condition"] not in logic.CONDITIONS.values():
        errors.append("invalid condition")

    data = {
        "model": model, "model_id": model["id"], "new_model": new_model, "items": items,
        "traveler_id": n["traveler_id"], "serial_no": n["serial_no"], "color": n["color"],
        "cosmetic": n["cosmetic"], "sanitize_method": method, "sanitize_result": s_result,
        "sanitize_date": s_date, "storage_size": n["storage_size"], "storage_type": n["storage_type"],
        "storage_desc": " ".join(p for p in (n["storage_size"], n["storage_type"]) if p),
        "weight": weight, "grade": n["grade"], "condition": n["condition"],
        "functionality": n["functionality"], "cd_dvd": n["cd_dvd"], "part_no": n["part_no"],
        "hdd_sn": n["hdd_sn"], "hdd_traveler_id": n["hdd_traveler_id"], "notes": notes,
        "operator": n["operator"], "ext_result": n["ext_result"], "photo": None,
    }
    data["result"] = logic.compute_result(items, method, s_result)
    data["marks"] = logic.build_marks(method, s_result, s_date, n["cosmetic"], items, n["storage_type"])
    return data, errors
