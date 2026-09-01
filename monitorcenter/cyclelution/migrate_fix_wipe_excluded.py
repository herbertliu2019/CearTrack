"""One-time migration: fix wipe_sync rows mislabeled `excluded` by the now
-removed pre-cutoff sweep in wipe_sync.py (see
tasks/Cyclelution/TASK_export_page_refactor.md section 0/1).

That sweep used to reclassify any ready/pending wipe_sync row dated before
the scan_since cutoff as `excluded`, conflating "system: out of scan scope"
with what `excluded` actually means — an operator manually
scrapping/repairing/sampling a drive on the Ready/Exceptions page. This
script finds every row still carrying that sweep's distinctive marker note
and re-runs a full, unrestricted evaluation (ignoring scan_since and
ready_window_days entirely, via the normal cyclelution.scan.evaluate_one()
path against the record's already-written envelope file) to write back its
TRUE status — exactly as if the sweep had never run.

NOTE: a genuine NO_GRADE record also has sync_status='excluded' (with
note="NO_GRADE", an unrelated, pre-existing, intentional design — see
gate_wipe.py) — that's a correct outcome if a re-evaluated row lands there
again, not something this script is fixing.

Safe to run repeatedly: a row whose note no longer starts with the sweep's
marker (already fixed, or a genuine manual exclude that never had it) is
left untouched.

Run once, from monitorcenter/:
    python -m cyclelution.migrate_fix_wipe_excluded
"""

from pathlib import Path

from . import sync_state, scan, context_wipe, gate_wipe
from . import normalizer as _normalizer

_MARKER = "excluded: before scan cutoff"
_SYNC_MODULE = "wipe"


def migrate(db_path=None) -> dict:
    cfg = _normalizer.load_config(context_wipe.CONFIG_PATH)
    rows = [
        r for r in sync_state.list_by_status("excluded", module=_SYNC_MODULE, db_path=db_path)
        if (r.get("sync_note") or "").startswith(_MARKER)
    ]

    summary = {"found": len(rows), "fixed": 0, "missing_file": 0, "errors": 0,
               "by_new_status": {}}

    for row in rows:
        hp = row["history_path"]
        sn = row.get("sn") or "?"
        if not Path(hp).exists():
            summary["missing_file"] += 1
            print(f"[migrate] SKIP {sn}: history file missing ({hp})")
            continue
        try:
            after = scan.evaluate_one(
                hp, config=cfg, module=_SYNC_MODULE,
                context_builder=context_wipe.build_context, gate_fn=gate_wipe.evaluate,
                db_path=db_path,
            )
            summary["fixed"] += 1
            summary["by_new_status"][after] = summary["by_new_status"].get(after, 0) + 1
            print(f"[migrate] {sn}: excluded (mislabeled) -> {after}")
        except Exception as e:
            summary["errors"] += 1
            print(f"[migrate] ERROR {sn}: {e}")

    return summary


def main() -> None:
    s = migrate()
    print(f"[OK] migrate_fix_wipe_excluded complete: {s}")


if __name__ == "__main__":
    main()
