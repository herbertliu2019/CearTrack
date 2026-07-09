"""Pre-check gate (T-Laptop).

Decides whether a normalized record may enter the `ready` queue. Two levels:

  HARD (must pass, else stays pending -> exception list):
    * SerialNumber present (required-field check happens in normalizer)
    * every ddl value in its domain / parseable  (normalizer exceptions)
    * capacity >= 16 GB when a disk is present    (normalizer exception)
    * Grade / Condition / Weight present + numeric (normalizer exceptions)
    * wipe: each installed drive has a wipe_records row with result=PASSED

  SOFT (still ready, but flagged so the queue can highlight it):
    * overall_result == FAIL      -> note TEST_FAIL
    * no disk installed           -> note NO_DISK

Hard failures come from two places and are merged: the normalizer's own
`exceptions` (domain/parse/required) plus this gate's per-disk wipe check.
"""

from dataclasses import dataclass, field


@dataclass
class GateResult:
    status: str                       # 'ready' or 'pending'
    note: str = None                  # sync_note (soft flags or exception summary)
    exceptions: list = field(default_factory=list)   # hard failures (field, reason)
    soft_flags: list = field(default_factory=list)   # NO_DISK / TEST_FAIL


def evaluate(norm, wipe_fn) -> GateResult:
    """norm: NormResult from normalizer.normalize(). wipe_fn(drive_sn)->dict|None.

    Uses norm.context for storage + overall_result and norm.exceptions for the
    normalization-level hard failures.
    """
    exceptions = list(norm.exceptions)   # start with normalizer's hard failures
    soft = []
    ctx = norm.context
    storage = ctx.get("storage") or []

    # ---- wipe hard check (conditional on disk presence) ----
    if storage:
        for dev in storage:
            sn = (dev.get("serial") or "").strip()
            rec = wipe_fn(sn) if sn else None
            if not rec:
                exceptions.append(
                    {"field": "wipe", "reason": f"drive {sn or '?'} not found in wipe_records"}
                )
            elif str(rec.get("result", "")).upper() != "PASSED":
                exceptions.append(
                    {"field": "wipe", "reason": f"drive {sn} wipe result={rec.get('result')!r} (need PASSED)"}
                )
    else:
        soft.append("NO_DISK")

    # ---- soft: laptop test overall FAIL ----
    if str(ctx.get("overall_result", "")).upper() == "FAIL":
        soft.append("TEST_FAIL")

    if exceptions:
        note = "; ".join(f"{e['field']}: {e['reason']}" for e in exceptions)
        return GateResult(status="pending", note=note, exceptions=exceptions, soft_flags=soft)

    note = " | ".join(soft) if soft else None
    return GateResult(status="ready", note=note, exceptions=[], soft_flags=soft)
