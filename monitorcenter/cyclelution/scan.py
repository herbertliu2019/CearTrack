"""Scan / evaluate entrypoint (T-Laptop).

`evaluate_one` normalizes + gates a single record and persists its status
(ready / pending + sync_note). It is called both at upload time (so a new
record lands in Ready or Exceptions immediately, no manual Rescan needed)
and by `scan_pending` for the batch re-scan.

`scan_pending` walks all `pending` records; `excluded`/`synced` are never
touched. Idempotent: re-running re-evaluates pending rows only, so a record
fixed at the source flips to ready next run.

Run from monitorcenter/:  python -m cyclelution.scan
"""

import json
from pathlib import Path

from . import sync_state, gate, wipe_lookup
from . import normalizer as _normalizer


def evaluate_one(history_path, envelope=None, config=None, wipe_fn=None, db_path=None) -> str:
    """Normalize + gate one record and persist its status. Returns the new
    status ('ready' or 'pending'). Pass `envelope` to skip re-reading the
    file (upload path already has it in memory)."""
    cfg = config or _normalizer.load_config()
    wipe_fn = wipe_fn or wipe_lookup.lookup
    if envelope is None:
        envelope = json.loads(Path(history_path).read_text(encoding="utf-8"))
    sn = envelope.get("sn")
    record_ts = envelope.get("timestamp")
    norm = _normalizer.normalize(envelope, config=cfg, wipe_fn=wipe_fn)
    result = gate.evaluate(norm, wipe_fn=wipe_fn)
    sync_state.set_status(history_path, result.status, note=result.note,
                          sn=sn, record_ts=record_ts, db_path=db_path)
    # One live record per SN: newest test wins, older ready/pending -> excluded.
    sync_state.reconcile_sn(sn, db_path=db_path)
    return result.status


def scan_pending(config=None, wipe_fn=None, db_path=None) -> dict:
    """Re-evaluate every pending record. Returns a summary dict."""
    cfg = config or _normalizer.load_config()
    wipe_fn = wipe_fn or wipe_lookup.lookup

    summary = {"scanned": 0, "ready": 0, "pending": 0, "missing_file": 0,
               "errors": 0, "superseded": 0}
    for row in sync_state.list_by_status("pending", db_path=db_path):
        hp = row["history_path"]
        summary["scanned"] += 1
        if not Path(hp).exists():
            summary["missing_file"] += 1
            continue
        try:
            status = evaluate_one(hp, config=cfg, wipe_fn=wipe_fn, db_path=db_path)
            summary[status] += 1
        except Exception as e:
            summary["errors"] += 1
            print(f"[scan] error on {hp}: {e}")

    # Also collapse any pre-existing duplicates already sitting as ready/pending
    # (evaluate_one above only reconciles the SNs it touched).
    summary["superseded"] = sync_state.reconcile_all(db_path=db_path)
    return summary


def main() -> None:
    s = scan_pending()
    print(f"[OK] scan complete: {s}")


if __name__ == "__main__":
    main()
