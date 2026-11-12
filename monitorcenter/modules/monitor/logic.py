"""Monitor manual-entry rules. No Flask here."""

# Cyclelution value strings are shared with the console module so the two never drift.
from modules.console.logic import CONDITIONS, FUNCTIONALITY, GRADE_LABELS, default_qc_note  # noqa: F401

STATUSES = ["Pass", "Fail", "N/A"]

# code, label, type. A Fail on a "key" item (or too many dead pixels) fails the unit.
ITEMS = [
    ("power",     "Power",             "key"),
    ("picture",   "Picture / signal",  "key"),
    ("backlight", "Backlight",         "key"),
    ("ports",     "Video ports",       "key"),
    ("osd",       "OSD buttons",       "secondary"),
    ("speakers",  "Speakers",          "secondary"),
]

# Missing accessories -> Marks (fixed order, exact wording used in Cyclelution).
MISSING_OPTIONS = ["No Speaker", "No stand", "No Power Adapter/Cord"]

SIZE_SUGGESTIONS = ["15 inch", "17 inch", "19 inch", "20 inch", "21.5 inch", "22 inch", "23 inch",
                    "23.8 inch", "24 inch", "25 inch", "27 inch", "28 inch", "29 inch", "30 inch",
                    "32 inch", "34 inch", "49 inch"]


def compute_result(items: list[dict], dead_pixels: int, max_dead: int) -> str:
    if dead_pixels > max_dead:
        return "Fail"
    if any(i["type"] == "key" and i["status"] == "Fail" for i in items):
        return "Fail"
    return "Pass"


def build_marks(missing: list[str]) -> str:
    """Only missing accessories, in the fixed option order."""
    return ", ".join(m for m in MISSING_OPTIONS if m in missing)
