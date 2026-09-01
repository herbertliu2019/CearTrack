"""Pre-check gate (GPU / T-Video Card).

Much simpler than the laptop gate: a GPU never holds user data (Data
Sanitization is a fixed "ND-No Data" const in mapping_t_video_card.yaml,
no wipe/drive check needed) and has no disk/battery/screen to branch on.

  HARD (must pass, else stays pending -> exception list):
    * SerialNumber / Grade / Condition / Weight present (normalizer exceptions)
    * VRAM bucketable (normalizer exception)

  SOFT (still ready, but flagged):
    * overall_result == FAIL -> note TEST_FAIL
"""

from dataclasses import dataclass, field


@dataclass
class GateResult:
    status: str
    note: str = None
    exceptions: list = field(default_factory=list)
    soft_flags: list = field(default_factory=list)


def evaluate(norm, wipe_fn=None) -> GateResult:
    """wipe_fn is accepted (unused) only to match gate.evaluate(norm, wipe_fn)'s
    call signature in scan.py."""
    exceptions = list(norm.exceptions)
    soft = []
    ctx = norm.context

    if str(ctx.get("overall_result", "")).upper() == "FAIL":
        soft.append("TEST_FAIL")

    if exceptions:
        note = "; ".join(f"{e['field']}: {e['reason']}" for e in exceptions)
        return GateResult(status="pending", note=note, exceptions=exceptions, soft_flags=soft)

    note = " | ".join(soft) if soft else None
    return GateResult(status="ready", note=note, exceptions=[], soft_flags=soft)
