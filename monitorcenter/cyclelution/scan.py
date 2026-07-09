"""Batch scan entrypoint (T-Laptop).

Walks all `pending` laptop records, runs normalize -> gate, and writes the
resulting status (ready / pending) + sync_note back via sync_state.
`excluded` records are never touched. Idempotent: re-running re-evaluates
pending rows only, so a record fixed at the source flips to ready next run.

Run from monitorcenter/:  python -m cyclelution.scan
"""

import json
from pathlib import Path

from . import sync_state, gate, wipe_lookup
from . import normalizer as _normalizer


def scan_pending(config=None, wipe_fn=None, db_path=None) -> dict:
    """Re-evaluate every pending record. Returns a summary dict."""
    cfg = config or _normalizer.load_config()
    wipe_fn = wipe_fn or wipe_lookup.lookup

    summary = {"scanned": 0, "ready": 0, "pending": 0, "missing_file": 0, "errors": 0}
    for row in sync_state.list_by_status("pending", db_path=db_path):
        hp = row["history_path"]
        summary["scanned"] += 1
        p = Path(hp)
        if not p.exists():
            summary["missing_file"] += 1
            continue
        try:
            envelope = json.loads(p.read_text(encoding="utf-8"))
            norm = _normalizer.normalize(envelope, config=cfg, wipe_fn=wipe_fn)
            result = gate.evaluate(norm, wipe_fn=wipe_fn)
            sync_state.set_status(hp, result.status, note=result.note, db_path=db_path)
            summary[result.status] += 1
        except Exception as e:
            summary["errors"] += 1
            print(f"[scan] error on {hp}: {e}")
    return summary


def main() -> None:
    s = scan_pending()
    print(f"[OK] scan complete: {s}")


if __name__ == "__main__":
    main()
