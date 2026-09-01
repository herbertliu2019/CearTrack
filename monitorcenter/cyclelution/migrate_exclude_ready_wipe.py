"""One-time bulk operation: move every T-Hard Drive (wipe) record currently
sitting in `ready` into `excluded`, tagged with a fixed reason.

Context: these records were already pushed into Cyclelution through the old
manual process before this automated pipeline existed, so re-exporting them
would be a duplicate. Rather than clicking "Exclude" one at a time on the
Ready page for every row, this does it in bulk with one shared reason.

Only ever touches wipe's `ready` rows — never pending/synced/excluded rows,
and never another production. Uses the same sync_state.set_status() path
the UI's own Exclude button uses, so the result is indistinguishable from a
manual exclude (same "excluded: <reason>" note shape, shows in the Excluded
tab, fully reversible by an operator the same way any other exclude is
inspectable/correctable).

Safe to re-run: after the first run, `ready` is empty, so later runs are a
no-op.

Run once, from monitorcenter/:
    python -m cyclelution.migrate_exclude_ready_wipe
"""

import sys

from . import sync_state

_SYNC_MODULE = "wipe"
_REASON = "already impoted into Cyclelution manually"

# Make the reason's non-ASCII text safe to print regardless of the console's
# codepage (a Windows terminal defaulting to cp1252 raises UnicodeEncodeError
# on Chinese text; the production server's Ubuntu locale is UTF-8 and would
# never hit this, but there's no reason to let a print() failure be possible
# at all). Never touches the actual data written to sync_state, which is
# always proper Unicode regardless of console encoding.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _safe_print(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"))


def migrate(db_path=None, reason=_REASON) -> dict:
    rows = sync_state.list_by_status("ready", module=_SYNC_MODULE, db_path=db_path)
    note = f"excluded: {reason}"

    summary = {"found": len(rows), "excluded": 0, "errors": 0}
    for row in rows:
        hp = row["history_path"]
        sn = row.get("sn") or "?"
        # The state-changing call and its own success/failure tracking are
        # deliberately kept separate from the print below — a console
        # encoding hiccup while *logging* a result must never be counted as
        # the migration operation itself having failed.
        try:
            sync_state.set_status(hp, "excluded", note=note, module=_SYNC_MODULE, db_path=db_path)
            summary["excluded"] += 1
        except Exception as e:
            summary["errors"] += 1
            _safe_print(f"[migrate] ERROR {sn}: {e}")
            continue
        _safe_print(f"[migrate] {sn}: ready -> excluded ({reason})")

    return summary


def main() -> None:
    s = migrate()
    print(f"[OK] migrate_exclude_ready_wipe complete: {s}")


if __name__ == "__main__":
    main()
