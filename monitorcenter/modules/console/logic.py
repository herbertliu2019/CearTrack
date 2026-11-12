"""Pure business rules for the console module (no Flask, no DB)."""

import io
import math
import os
import random
from datetime import date, datetime

METHODS = ["EPS", "Factory Reset", "Manual Delete", "Pre-Sanitization", "No data", "Locked"]
STATUSES = ["Pass", "Fail", "N/A"]
SANITIZE_RESULTS = ["Pass", "Fail", "N/A"]
COSMETIC_OPTIONS = [
    "Minor scratches/blemishes", "Scratches", "Dents", "Cracked case", "Missing faceplate", "Missing cover",
    "Missing feet", "Discoloration", "Heavy wear",
]
PHOTO_MAX_EDGE = 1600

# Cyclelution-only fields (part no, color, weight, grade, condition, functionality,
# CD/DVD, storage size/type) are filled in Cyclelution, not by testers.
# Set True to show them again on the entry page and results list.
SHOW_SALES_FIELDS = True

# Cyclelution value strings (exact format used in exported data).
CONDITIONS = {
    "C1": "C1 - Damaged",
    "C2": "C2 - Used Poor",
    "C3": "C3 - Used Fair",
    "C4": "C4 - Used Good",
    "C5": "C5 - Used Very Good",
    "C6": "C6 - Used Excellent",
    "C7": "C7 - Certified Pre-Owned (Seller or Manufacturer Refurbished)",
    "C8": "C8 - Unused",
    "C9": "C9 - New Open-Box",
}
FUNCTIONALITY = ["F3 - Key Functions Working", "F4 - Hardware Functional",
                 "F2 - Verified Specialty", "F1 - Collectible/Specialty"]
FUNC_PASS = ("F3", "F4")
CD_DVD_OPTIONS = ["Yes", "No"]
STORAGE_TYPES = ['HDD', "Flash Storage", '2.5" HDD', '3.5" HDD', 'SSD', 'eMMC', 'NAND', 'Internal Flash']

# Grade rules (Cyclelution definitions). func: "pass" = F3/F4, "none" = must be empty, "any".
# result: required unit result ("Pass"/"Fail") or None for no constraint.
GRADE_RULES = {
    # A-D condition ranges per CEAR grade definitions (A: C4-C9, B: C3-C4, C: C2-C9, D: C1-C9).
    "A": {"conditions": ["C4", "C5", "C6", "C7", "C8", "C9"], "func": "pass", "result": "Pass"},
    "B": {"conditions": ["C3", "C4"], "func": "pass", "result": "Pass"},
    "C": {"conditions": ["C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9"], "func": "pass", "result": "Pass"},
    "D": {"conditions": ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9"], "func": "any", "result": "Fail"},
    "E": {"conditions": ["C2", "C6"], "func": "none", "result": None},                      # Evaluated Untested
    "F": {"conditions": ["C1"], "func": "none", "result": None},                            # Evaluated Damaged
}
GRADE_LABELS = {
    "A": "A - Passed full testing, Good condition or better (C4-C9)",
    "B": "B - Passed full testing, Poor/Fair condition (C3-C4)",
    "C": "C - Passed key function testing or untested (C2-C9)",
    "D": "D - Damaged or not working (C1-C9)",
    "E": "E - Evaluated Untested", "F": "F - Evaluated Damaged",
}
# Collectible/Specialty (R2 REC doc): functionality F1/F2 are graded by cosmetic range, not A-F.
SPECIALTY_CONDITIONS = {"F1": ["C3", "C4", "C5", "C6"], "F2": ["C6", "C7"]}


def grade_rules_json() -> dict:
    """Grade -> list of full condition strings, for the entry-form JS."""
    return {g: [CONDITIONS[c] for c in r["conditions"]] for g, r in GRADE_RULES.items()}


def validate_grade(grade: str, condition: str, functionality: str, result: str) -> list[str]:
    errs = []
    if grade and grade not in GRADE_RULES:
        return ["Invalid grade"]
    if condition and condition not in CONDITIONS.values():
        errs.append("Invalid condition")
    fcode = functionality[:2]
    if fcode in SPECIALTY_CONDITIONS:
        if condition and condition[:2] not in SPECIALTY_CONDITIONS[fcode]:
            errs.append(f"{fcode} allows only " + ", ".join(SPECIALTY_CONDITIONS[fcode]))
        return errs
    if not grade:
        return errs
    rule = GRADE_RULES[grade]
    if condition and condition[:2] not in rule["conditions"]:
        errs.append(f"Grade {grade} does not allow condition '{condition}'")
    if rule["func"] == "pass" and fcode not in FUNC_PASS:
        errs.append(f"Grade {grade} requires functionality F3/F4")
    elif rule["func"] == "none" and functionality:
        errs.append(f"Grade {grade} requires empty functionality")
    if rule["result"] and result != rule["result"]:
        errs.append(f"Grade {grade} requires unit result {rule['result']} (currently {result})")
    return errs


def compute_result(items: list[dict], sanitize_method: str, sanitize_result: str) -> str:
    """Fail if any key item Fail, or Locked, or sanitize Fail. Secondary Fail never fails the unit."""
    if sanitize_method == "Locked" or sanitize_result == "Fail":
        return "Fail"
    if any(i["type"] == "key" and i["status"] == "Fail" for i in items):
        return "Fail"
    return "Pass"


def _fmt_date(iso: str | None) -> str:
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%m/%d/%y")
    except (TypeError, ValueError):
        return datetime.now().strftime("%m/%d/%y")


def build_marks(method: str, sanitize_result: str, sanitize_date: str | None,
                cosmetic: list[str], items: list[dict], storage_type: str = "") -> str:
    """`<method> on <MM/DD/YY>, <storage type>, <cosmetic...>, <fail items> not working` (fixed order)."""
    if method == "Locked":
        parts = ["Locked - cannot reset"]
    elif method == "No data":
        parts = ["No data"]
    else:
        parts = [f"{method} on {_fmt_date(sanitize_date)}"]
        if sanitize_result == "Fail":
            parts.append("data sanitization failed")
        if storage_type:                      # SOP D: record the type of storage installed
            parts.append(storage_type)
    parts += [c for c in cosmetic if c]
    failed = [i["label"] for i in items if i["status"] == "Fail"]
    if failed:
        parts.append(" and ".join(failed) + " not working")
    return ", ".join(parts)


def default_sanitize_result(method: str) -> str:
    return {"Locked": "Fail", "No data": "N/A"}.get(method, "Pass")


def validate_sanitize(method: str, sanitize_result: str, sanitize_date: str,
                      hdd_sn: str, hdd_tid: str) -> list[str]:
    """Reset photo for Factory Reset is optional (evidence is recorded manually)."""
    errs = []
    if method not in METHODS:
        errs.append("Invalid sanitize method")
        return errs
    if sanitize_result not in SANITIZE_RESULTS:
        errs.append("Invalid sanitize result")
    if method == "EPS":
        if not hdd_sn:
            errs.append("EPS requires HDD SN")
        if not hdd_tid:
            errs.append("EPS requires HDD Traveler ID")
        if not sanitize_date:
            errs.append("EPS requires erase date")
    return errs


def qc_sample_size(n_candidates: int, pct: float = 0.05) -> int:
    if n_candidates <= 0:
        return 0
    return max(1, math.ceil(n_candidates * pct))


def pick_sample(candidate_ids: list[int], k: int) -> list[int]:
    return random.sample(candidate_ids, min(k, len(candidate_ids)))


def default_qc_note(name: str, when: date | None = None) -> str:
    when = when or date.today()
    return f"Verified Functionality and Data Erasure by {name}, {when.strftime('%m/%d/%y')}"


def save_photo(data: bytes, dest_path: str) -> None:
    """Resize long edge to 1600px and write JPEG. Falls back to raw bytes without Pillow."""
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    try:
        from PIL import Image, ImageOps
    except ImportError:
        with open(dest_path, "wb") as f:
            f.write(data)
        return
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)
    img.thumbnail((PHOTO_MAX_EDGE, PHOTO_MAX_EDGE))
    img.convert("RGB").save(dest_path, "JPEG", quality=85)
