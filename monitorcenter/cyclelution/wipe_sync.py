"""Bridge from wipe_records (wipe_index.db) into the Cyclelution sync
pipeline.

T-Laptop and T-Video Card get a new envelope per test-script upload, which
triggers cyclelution.scan.evaluate_one() directly from the upload route.
The wipe production has no upload event at all — its data already lives in
wipe_records, written by the separate modules/wipe log-import module. This
module is wipe's equivalent of "an upload happened": sync_all() walks every
drive_sn currently in the wipe DB, and for each one re-derives a *synthetic*
envelope (module="wipe", the drive_sn as the SN, one wipe_records row as
payload.wipe) from its latest wipe_records row, then feeds it through the
exact same unmodified pipeline (core.storage.write_envelope +
cyclelution.scan.evaluate_one) laptop/gpu use — so gate/normalize/export/UI
code stays 100% shared, no flow-layer duplication.

Read-only against wipe_index.db (via wipe_lookup, which opens it in SQLite
read-only URI mode). Writes only to its own cache module "wipe_cyclelution"
under BASE_DIR — never the wipe_records DB itself, and never the real
"wipe" module's own data/wipe/ directory (used by the log-scanning module;
a different thing with the same name as this pipeline's `module="wipe"`
sync-table key).

Idempotent and safe to call repeatedly (e.g. on every operator Rescan click,
or once at app startup): a drive_sn whose latest wipe_datetime hasn't
changed since it was last marked 'synced' is skipped outright — synced
records must never be re-evaluated.

Only scans drive_sns whose LATEST wipe is on/after the LATER of two floors
(see cyclelution/recency.py):
  * mapping_t_hard_drive.yaml's `scan_since` — a fixed, permanent date;
    historical drives before it were handled through the old manual
    Cyclelution process and are permanently out of scope here.
  * `ready_window_days` — a rolling "last N days" recency window, purely a
    performance optimization so a Rescan doesn't waste time re-evaluating
    years of history that would never show in Ready anyway (see web.py's
    api_queue, which applies the same rolling window as a *display* filter
    on top of whatever this function evaluates — that display filter is
    what actually keeps Ready small for every production; this discovery
    -time skip just avoids wasted work for wipe's specific giant backlog).

Per an explicit, discussed trade-off: unlike `scan_since`, the rolling
window here DOES mean a drive_sn that ages out before ever being scanned
once is not (re-)evaluated again — accepted knowingly in exchange for
Rescan not having to churn through the full historical table every time.
Nothing does an active status sweep for aged-out records anymore: a record
that already has a `ready`/`pending` status just keeps it (still correctly
counted in Exceptions' cumulative total if pending; ceases to be selected
by this discovery query, and — separately — stops appearing in the Ready
tab once web.py's own display-time window filter excludes it). See
migrate_fix_wipe_excluded.py for the one-time fix of records that were
previously mislabeled `excluded` by a since-removed sweep that used to live
here.

Measured against a real production-mirrored wipe_index.db: ~40ms/drive_sn
(dominated by per-row sqlite connect/close overhead in wipe_lookup +
sync_state, each opening its own short-lived connection — the same
per-record cost laptop/gpu pay too, but they only ever pay it once per
upload, never in a loop). At ~28,800 distinct drive_sns that is ~20
minutes for a full run — far too slow to run inline on an HTTP request or
block Flask startup. sync_all() is therefore always invoked via
run_in_background() (a daemon thread), never called directly from a
request handler. _LOCK prevents two runs overlapping (a second caller gets
{"busy": True} back immediately rather than corrupting/duplicating work).
"""

import threading
from datetime import datetime, timedelta

from core import storage
from . import sync_state, wipe_lookup, context_wipe, gate_wipe, scan, recency
from . import normalizer as _normalizer

_CACHE_MODULE = "wipe_cyclelution"   # core.storage module name for the synthetic envelope cache
_SYNC_MODULE = "wipe"                # cyclelution sync_state / mapping module name

_LOCK = threading.Lock()


def _build_envelope(rec: dict) -> dict:
    return {
        "module": "wipe",
        "sn": rec.get("drive_sn", ""),
        "timestamp": rec.get("wipe_datetime") or "",
        "payload": {"wipe": rec},
    }


def sync_all(db_path=None) -> dict:
    """Re-derive sync state for every drive_sn currently in the wipe DB.
    Returns a summary dict of outcome counts. Takes 10s of minutes against
    the full production table (see module docstring) — call via
    run_in_background(), not directly from a request handler.

    Returns {"busy": True} immediately, doing nothing, if another sync_all()
    is already running (e.g. the startup thread hasn't finished yet and an
    operator clicks Rescan)."""
    if not _LOCK.acquire(blocking=False):
        return {"busy": True}

    try:
        cfg = _normalizer.load_config(context_wipe.CONFIG_PATH)
        scan_since = cfg.get("scan_since")
        rolling_cutoff = recency.cutoff_date(cfg.get("ready_window_days", 30))
        # Later (more restrictive) of the two floors — see module docstring.
        effective_since = max(filter(None, (scan_since, rolling_cutoff)))
        summary = {"scanned": 0, "ready": 0, "pending": 0, "excluded": 0,
                   "skipped_synced": 0, "errors": 0}

        for sn in wipe_lookup.list_drive_sns(since=effective_since, db_path=db_path):
            try:
                rec = wipe_lookup.lookup_full(sn, db_path=db_path)
                if not rec:
                    continue
                summary["scanned"] += 1
                record_ts = rec.get("wipe_datetime") or ""

                # Never touch a drive_sn whose current wipe record was
                # already exported — even if we re-derive its envelope, its
                # history_path would collide with the synced one
                # (write_envelope's filename is deterministic from sn +
                # timestamp).
                already_synced = any(
                    r["sync_status"] == "synced" and (r.get("record_ts") or "") == record_ts
                    for r in sync_state.list_by_sn(sn, module=_SYNC_MODULE, db_path=db_path)
                )
                if already_synced:
                    summary["skipped_synced"] += 1
                    continue

                envelope = _build_envelope(rec)
                paths_out = storage.write_envelope(_CACHE_MODULE, sn, envelope)
                hp = paths_out["history_path"]

                sync_state.ensure_pending(hp, sn=sn, record_ts=record_ts,
                                           module=_SYNC_MODULE, db_path=db_path)
                status = scan.evaluate_one(
                    hp, envelope=envelope, config=cfg, module=_SYNC_MODULE,
                    context_builder=context_wipe.build_context, gate_fn=gate_wipe.evaluate,
                    db_path=db_path,
                )
                summary[status] = summary.get(status, 0) + 1
            except Exception as e:
                summary["errors"] += 1
                print(f"[wipe_sync] error on drive_sn={sn}: {e}")

        return summary
    finally:
        _LOCK.release()


def run_in_background(db_path=None) -> threading.Thread:
    """Fire-and-forget sync_all() on a daemon thread. Use this from request
    handlers / app startup — never call sync_all() directly where something
    is waiting on the result (see module docstring for why)."""
    t = threading.Thread(target=sync_all, kwargs={"db_path": db_path}, daemon=True)
    t.start()
    return t


# --- periodic poller ------------------------------------------------------
# Mirrors modules/wipe/scheduler.py's poll loop (same wait-then-run shape).
# Without this, T-Hard Drive only syncs at Flask boot or a manual Rescan
# click — and Rescan just starts sync_all() in a background thread that the
# page only polls for ~2 minutes, so a drive wiped between syncs (or a run
# that silently didn't fire) sits invisible in Ready with no error anywhere.
# sync_all()'s own _LOCK makes an overlapping poll tick a safe no-op, so this
# can run unconditionally alongside manual Rescan clicks and the boot seed.
_poll_thread: threading.Thread = None
_stop_event = threading.Event()
_last_sync_at = None
_next_sync_at = None
_current_interval = 600


def get_poll_state() -> dict:
    return {
        "poller_running": _poll_thread is not None and _poll_thread.is_alive(),
        "last_sync_at": _last_sync_at,
        "next_sync_at": _next_sync_at,
        "interval": _current_interval,
    }


def _poll_loop(interval: int, db_path=None) -> None:
    global _last_sync_at, _next_sync_at
    print(f"[wipe_sync] poller started, interval={interval}s")

    while not _stop_event.is_set():
        _next_sync_at = (datetime.now().replace(microsecond=0) + timedelta(seconds=interval)).isoformat()
        if _stop_event.wait(timeout=interval):
            break
        try:
            summary = sync_all(db_path=db_path)
            _last_sync_at = datetime.now().replace(microsecond=0).isoformat()
            if summary.get("busy"):
                print("[wipe_sync] poller tick skipped: a sync is already running")
            else:
                print(f"[wipe_sync] poller tick: {summary}")
        except Exception as e:
            print(f"[wipe_sync] poller tick error: {e}")


def start_poll_scheduler(interval=None, db_path=None) -> None:
    """Start the periodic poller once (idempotent — a second call while one
    is already running is a no-op). interval defaults to mapping_t_hard_drive
    .yaml's `sync_poll_interval_seconds` (read once at start, like
    modules/wipe/scheduler.py's own interval)."""
    global _poll_thread, _current_interval

    if _poll_thread is not None and _poll_thread.is_alive():
        return

    if interval is None:
        cfg = _normalizer.load_config(context_wipe.CONFIG_PATH)
        interval = int(cfg.get("sync_poll_interval_seconds", 600))
    _current_interval = interval

    _stop_event.clear()
    _poll_thread = threading.Thread(
        target=_poll_loop, args=(interval,), kwargs={"db_path": db_path},
        daemon=True, name="wipe-cyclelution-poller",
    )
    _poll_thread.start()


def stop_poll_scheduler() -> None:
    global _poll_thread
    _stop_event.set()
    if _poll_thread is not None:
        _poll_thread.join(timeout=10)
        _poll_thread = None


def main() -> None:
    s = sync_all()
    print(f"[OK] wipe_sync complete: {s}")


if __name__ == "__main__":
    main()
