"""Single source of truth for "how recent is a candidate record" across
Cyclelution's Ready tab and the archive tabs (Exceptions/Exported/Excluded/
NO_GRADE). Both web.py (display-time filtering) and wipe_sync.py (wipe's
additional scan-time discovery filter) compute the cutoff via this one
function so the two layers can never drift on what "the window" means.

Deliberately date-only (not datetime) and computed fresh on every call from
the real wall clock — this is a ROLLING window (today minus N days), unlike
mapping_t_hard_drive.yaml's `scan_since`, which is a fixed, permanent floor.
The two are different concepts: `scan_since` marks a one-time historical
handoff point that never moves; this cutoff always trails "today" and is
recomputed on every request/scan.
"""

from datetime import date, timedelta


def cutoff_date(days: int) -> str:
    """ISO date string (YYYY-MM-DD) for `days` days before today. Compared
    as text against record_ts/wipe_datetime the same way the rest of
    Cyclelution relies on ISO-string sortability (e.g. wipe_lookup.py,
    sync_state.reconcile_sn)."""
    return (date.today() - timedelta(days=days)).isoformat()
