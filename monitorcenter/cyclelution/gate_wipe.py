"""Pre-check gate (wipe / T-Hard Drive).

  NO_GRADE (special, not a hard-fail exception — see TASK_wipe_export.md
  section 2/3): wipe.grade empty -> status='excluded', note='NO_GRADE',
  checked BEFORE anything else and short-circuiting past every other
  exception. Grade is auto-measured by the erasure software, not operator
  -fixable, so a missing value is not a data problem to surface on the
  Exceptions list — it simply never becomes exportable. A non-empty but
  unrecognized grade (e.g. "GRADE F", seen in real wipe_records data) is
  NOT covered by this branch and falls through to the normal exception
  path via the Grade column's table:map converter in mapping_t_hard_drive
  .yaml failing to find it in the map.

  HARD (must pass, else stays pending -> exception list):
    * SerialNumber / Storage Type / Storage Size / Grade (normalizer exceptions)
    * result == PASSED (wipe's own hard rule: a failed erasure never ships)
    * manufacturer / drive_model non-empty

  No soft flags: wipe has no operator judgement call (no overall_result).
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
    ctx = norm.context
    wipe = ctx.get("wipe", {}) or {}

    grade_raw = str(wipe.get("grade") or "").strip()
    if not grade_raw:
        return GateResult(status="excluded", note="NO_GRADE", exceptions=[], soft_flags=[])

    exceptions = list(norm.exceptions)

    result = str(wipe.get("result") or "").strip().upper()
    if result != "PASSED":
        exceptions.append({
            "field": "wipe.result",
            "reason": f"result={wipe.get('result')!r} (need PASSED)",
        })

    if not str(wipe.get("manufacturer") or "").strip():
        exceptions.append({"field": "wipe.manufacturer", "reason": "manufacturer empty"})

    if not str(wipe.get("drive_model") or "").strip():
        exceptions.append({"field": "wipe.drive_model", "reason": "drive_model empty"})

    if exceptions:
        note = "; ".join(f"{e['field']}: {e['reason']}" for e in exceptions)
        return GateResult(status="pending", note=note, exceptions=exceptions, soft_flags=[])

    return GateResult(status="ready", note=None, exceptions=[], soft_flags=[])
