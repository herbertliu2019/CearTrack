"""Read the operator-entered `manual_input` block from a laptop payload.

Per MANUAL_INPUT_CONTRACT.md the client (laptop_test.sh >= v2.1.3) already
emits Cyclelution-ready strings (e.g. grade "Grade C", condition
"C5 - Used Very Good", screen_size_inch "14 inch"), so CearTrack reads them
directly with NO code-value remapping.

Backward compatibility: pre-v2.1.3 reports have no manual_input block; every
field then reads as None and nothing raises. Empty strings are normalized to
None (operator skipped the field).
"""

FIELDS = (
    "weight_lbs",
    "grade",
    "condition",
    "color",
    "screen_size_inch",
    "mark",
    "cddvd_present",
)


def read_manual_input(payload) -> dict:
    """Return the 7 manual_input fields, missing/empty -> None. Never raises."""
    block = (payload or {}).get("manual_input") or {}
    out = {}
    for k in FIELDS:
        v = block.get(k)
        out[k] = v if (v is not None and v != "") else None
    return out
