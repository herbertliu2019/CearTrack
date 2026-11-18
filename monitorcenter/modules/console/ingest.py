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

Inspection-tool format (also accepted): brand / serial / model / tech / outcome / dataSanitization
("ND-No Data") / mark ("-scratch -dirty" -> cosmetic) / storageSize / storageType / hddSn / hddTravelerId,
"results": [{"id": "video_port", "label": "Video Port", "type": "Key", "result": "pass"}, ...].
With "results", every reported item is stored (ids mapped via _ALIASES, unknown ids auto-create a
check item); the model's configured item list is not used as a filter.
"""

from modules.console import db, logic


def _norm(s) -> str:
    return " ".join(str(s or "").lower().split())


def _text(v) -> str:
    return str(v).strip() if v is not None else ""


def _grade(v) -> str:
    """Accept 'B', 'Grade B', 'grade b', or a full label 'B - Passed ...' -> 'B'. Unknown kept as-is."""
    s = _text(v)
    if not s:
        return ""
    t = s.split(" - ", 1)[0].strip()
    if t.lower().startswith("grade"):
        t = t[5:].strip(" :-")
    t = t.upper()
    return t if t in logic.GRADE_LABELS else s


# Inspection-tool result id -> existing console_check_items.code. Unknown ids get their own check item.
_ALIASES = {
    "power_port": "power", "video_port": "video", "hard_drive": "hdd_slot", "sd_card_slot": "sd_slot",
    "screen": "screen", "controller_ports": "controller", "memory_ports": "memory_port",
    "accessory_ports": "accessory", "wifi_network": "wifi", "usb_ports": "usb",
    "expansion_slot": "expansion", "headphone_jack": "headphone", "ethernet_port": "ethernet",
}

_STATUS = {"pass": "Pass", "passed": "Pass", "ok": "Pass", "fail": "Fail", "failed": "Fail",
           "n/a": "N/A", "na": "N/A", "skip": "N/A"}

# dataSanitization code prefix ("ND-No Data") -> logic.METHODS
_SAN_CODES = {"ND": "No data", "FR": "Factory Reset", "EPS": "EPS", "MD": "Manual Delete",
              "PS": "Pre-Sanitization", "LK": "Locked", "LOCKED": "Locked"}


def _first(raw: dict, *keys):
    """First non-empty value among `keys` (canonical name first, inspection-tool name after)."""
    for k in keys:
        v = raw.get(k)
        if v not in (None, ""):
            return v
    return None


def _method(v) -> str:
    """'ND-No Data' / 'No data' / 'Factory Reset' -> logic.METHODS entry; unknown kept as-is (validated later)."""
    s = _text(v)
    if not s:
        return ""
    by_name = {_norm(m): m for m in logic.METHODS}
    if _norm(s) in by_name:
        return by_name[_norm(s)]
    code, _, rest = s.partition("-")
    return _SAN_CODES.get(code.strip().upper()) or by_name.get(_norm(rest)) or s


def _cosmetic(raw: dict) -> list[str]:
    c = raw.get("cosmetic")
    if c:
        return [_text(x) for x in c if _text(x)]
    # inspection tool: "mark": "-minor scratches/blemishes -faceplate is dirty"
    mark = _text(raw.get("mark"))
    if not mark:
        return []
    parts = [p.strip() for p in mark.split(" -")] if mark.startswith("-") else [mark]
    return [p.lstrip("-").strip() for p in parts if p.lstrip("-").strip()]


def _normalize(raw: dict) -> dict:
    """External JSON -> canonical dict. Accepts the canonical format and the inspection-tool format
    (brand/serial/tech/results/dataSanitization/outcome/mark)."""
    san = raw.get("sanitize") or {}
    items = raw.get("items") or {}
    if isinstance(items, list):
        items = {_text(i.get("name")): _text(i.get("status")) for i in items if isinstance(i, dict)}
    results = [r for r in (raw.get("results") or []) if isinstance(r, dict) and _text(r.get("id"))]
    return {
        "serial_no": _text(_first(raw, "serial_no", "serial")),
        "traveler_id": _text(_first(raw, "traveler_id", "travelerId")),
        "manufacturer": _text(_first(raw, "manufacturer", "brand")), "model": _text(raw.get("model")),
        "operator": _text(_first(raw, "operator", "tech")),
        "ext_result": _text(_first(raw, "result", "outcome")),
        "items": items, "results": results, "cosmetic": _cosmetic(raw),
        "method": _method(_first(san, "method") or raw.get("dataSanitization")),
        "s_result": _text(san.get("result")),
        "s_date": _text(san.get("date")),
        "storage_type": _text(_first(san, "storage_type") or raw.get("storageType")),
        "storage_size": _text(_first(san, "storage_size") or raw.get("storageSize")),
        "hdd_sn": _text(_first(san, "hdd_sn") or raw.get("hddSn")),
        "hdd_traveler_id": _text(_first(san, "hdd_traveler_id") or raw.get("hddTravelerId")),
        "grade": _grade(raw.get("grade")), "condition": _text(raw.get("condition")),
        "functionality": _text(raw.get("functionality")), "cd_dvd": _text(raw.get("cd_dvd")),
        "part_no": _text(raw.get("part_no")), "color": _text(raw.get("color")),
        "weight": raw.get("weight"), "notes": _text(raw.get("notes")),
    }


def _items_from_results(conn, results: list[dict], errors: list[str]) -> list[dict]:
    """Every reported result becomes a test item (model config is not a filter for API uploads)."""
    out, seen = [], set()
    for r in results:
        rid = _norm(r.get("id")).replace(" ", "_")
        code = _ALIASES.get(rid, rid)
        label = _text(r.get("label")) or rid
        typ = "key" if _norm(r.get("type")) == "key" else "secondary"
        iid = db.ensure_check_item(conn, code, label, typ)
        if iid in seen:
            errors.append(f"duplicate result id '{r.get('id')}'")
            continue
        seen.add(iid)
        st = _STATUS.get(_norm(r.get("result")), "")
        if not st:
            errors.append(f"item '{label}': unknown result '{r.get('result')}'")
            st = "N/A"
        out.append({"id": iid, "code": code, "type": typ, "label": label, "status": st})
    return out


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
        src = db.entry_items(conn, model["id"])
    else:
        new_model = {"manufacturer": n["manufacturer"], "model": n["model"],
                     "storage_kind": "fixed", "has_data": 1}
        model = {"id": 0, **new_model}
        src = db.entry_items(conn)

    notes = n["notes"]
    model_items = None
    if n["results"]:
        # Inspection-tool format: show every reported result as-is.
        items = _items_from_results(conn, n["results"], errors)
        if new_model:   # new model gets the reported set instead of the generic one
            model_items = [{"id": i["id"], "type": i["type"], "label_override": i["label"]} for i in items]
    else:
        # Canonical format: match reported names to the model's items by label or code; unreported -> N/A.
        reported = {_norm(k): v for k, v in n["items"].items()}
        used: set[str] = set()
        items = []
        for it in src:
            key = next((k for k in (_norm(it["label"]), _norm(it["code"])) if k in reported), None)
            st = "N/A"
            if key:
                used.add(key)
                st = _STATUS.get(_norm(reported[key]), "")
                if not st:
                    errors.append(f"item '{it['label']}': unknown status '{reported[key]}'")
                    st = "N/A"
            items.append({**it, "status": st})
        extra = [k for k in n["items"] if _norm(k) not in used]
        if extra:
            notes = (notes + " " if notes else "") + "[unmapped items: " + ", ".join(extra) + "]"

    if n["method"] and n["method"] not in logic.METHODS:
        errors.append(f"unknown sanitize method '{n['method']}'")
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
        errors.append(f"invalid grade '{n['grade']}' (expected A-F, e.g. 'B' or 'Grade B')")
    if n["condition"] and n["condition"] not in logic.CONDITIONS.values():
        errors.append("invalid condition")

    data = {
        "model": model, "model_id": model["id"], "new_model": new_model, "items": items,
        "model_items": model_items,
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
