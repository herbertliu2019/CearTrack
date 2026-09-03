import fcntl
import logging
import os
import threading
from datetime import datetime, timedelta

from modules.wipe.db import get_conn, get_scan_status
from modules.wipe.scanner import WipeScanner

logger = logging.getLogger(__name__)

_poll_thread:      threading.Thread | None = None
_stop_event      = threading.Event()
_last_scan_at:   str | None = None
_next_scan_at:   str | None = None
_current_interval: int = 1800

# Cross-process ownership lock: gunicorn runs multiple workers (plus the
# preload master, plus old/new generations overlapping during a restart),
# and each one imports this module independently. Without this lock every
# one of them started its own copy of the poll loop, all hammering the same
# wipe_index.db concurrently — that's what corrupted it (see
# readme/monitorcenter_mount_eps_troubleshoot.txt-adjacent incident,
# 2026-09-02/03). Only the process that wins this flock may run the loop.
# The OS releases the lock automatically on process exit/crash, so whichever
# process is still alive (or the next one that starts) picks it up again —
# no manual cleanup needed.
_lock_fh = None
_lock_owner_pid: int | None = None


def _lock_path(db_path: str) -> str:
    return os.path.join(os.path.dirname(db_path), ".wipe_poller.lock")


def _we_hold_lock() -> bool:
    """True if THIS process (not a fork ancestor) actually earned the lock.

    gunicorn's --preload forks workers from a master that already imported
    (and locked) this module. fork() duplicates _lock_fh into every worker,
    so a plain `_lock_fh is not None` check is fooled into thinking each
    worker already owns the lock it merely inherited a reference to. Gating
    on the owning pid forces every forked child to attempt (and correctly
    fail) a real acquire of its own.
    """
    return _lock_fh is not None and _lock_owner_pid == os.getpid()


def _acquire_owner_lock(lock_path: str) -> bool:
    global _lock_fh, _lock_owner_pid
    if _we_hold_lock():
        return True
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    fh = open(lock_path, "w")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return False
    _lock_fh = fh
    _lock_owner_pid = os.getpid()
    return True


def _is_owner_lock_held(lock_path: str) -> bool:
    """True if some process (this one or another) currently owns the poller."""
    if _we_hold_lock():
        return True
    try:
        fh = open(lock_path, "w")
    except OSError:
        return False
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return True
    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    fh.close()
    return False


def get_poll_state(cfg: dict | None = None) -> dict:
    my_thread_alive = _poll_thread is not None and _poll_thread.is_alive()
    if my_thread_alive:
        running = True
    elif _we_hold_lock():
        # We own the lock but our own thread died — report not-running so a
        # caller's self-heal restarts it (start_poll_scheduler is a cheap
        # no-op re-acquire for a process that already holds the lock).
        running = False
    elif cfg is not None:
        running = _is_owner_lock_held(_lock_path(cfg["db_path"]))
    else:
        running = False
    return {
        "poller_running": running,
        "last_scan_at":   _last_scan_at,
        "next_scan_at":   _next_scan_at,
        "interval":       _current_interval,
    }


def _poll_loop(cfg: dict, interval: int) -> None:
    global _last_scan_at, _next_scan_at

    log_roots = cfg.get("log_roots") or [{"path": cfg["log_root"], "win_share_root": cfg.get("win_share_root", "")}]
    scanner = WipeScanner(log_roots=log_roots, db_path=cfg["db_path"])

    roots_desc = ", ".join(str(r["path"]) for r in log_roots)
    logger.info(
        f"[WipePoller] started, interval={interval}s, roots=[{roots_desc}]"
    )

    while not _stop_event.is_set():
        # record next scheduled fire time
        _next_scan_at = (
            datetime.now().replace(microsecond=0) + timedelta(seconds=interval)
        ).isoformat()

        # wait interval seconds; returns True early if stop was requested
        if _stop_event.wait(timeout=interval):
            break

        # skip if a manual full-scan is running
        try:
            conn = get_conn(cfg["db_path"])
            status = get_scan_status(conn)
            conn.close()
            if status.get("running") == 1:
                logger.info("[WipePoller] skipped: full scan in progress")
                continue
        except Exception as e:
            logger.warning(f"[WipePoller] DB check failed, skipping: {e}")
            continue

        # run current-month poll
        try:
            result = scanner.run_poll()
            _last_scan_at = datetime.now().replace(microsecond=0).isoformat()
            if result["inserted"] > 0:
                logger.info(
                    f"[WipePoller] inserted={result['inserted']} "
                    f"skipped={result['skipped']} "
                    f"errors={result['errors']}"
                )
            # no new files -> silent (avoid log spam every 30 min)
        except Exception as e:
            logger.error(f"[WipePoller] poll error: {e}")
            # keep thread alive; retry next interval


def start_poll_scheduler(cfg: dict) -> None:
    global _poll_thread, _stop_event, _current_interval

    if _poll_thread is not None and _poll_thread.is_alive():
        logger.warning("[WipePoller] already running, skip")
        return

    if not _acquire_owner_lock(_lock_path(cfg["db_path"])):
        logger.info("[WipePoller] another process already owns the poller, skip")
        return

    _current_interval = int(cfg.get("poll_interval", 1800))
    _stop_event.clear()
    _poll_thread = threading.Thread(
        target  = _poll_loop,
        args    = (cfg, _current_interval),
        daemon  = True,
        name    = "wipe-poller",
    )
    _poll_thread.start()


def stop_poll_scheduler() -> None:
    global _poll_thread
    _stop_event.set()
    if _poll_thread is not None:
        _poll_thread.join(timeout=10)
        _poll_thread = None
    logger.info("[WipePoller] stopped")
