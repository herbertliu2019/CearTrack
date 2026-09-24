"""Background poller for the mem module.

Copies modules/wipe/scheduler.py's cross-process flock pattern, not
modules/cpu/scheduler.py's (cpu's poller has no such guard and will run
duplicate copies under gunicorn's multi-worker deployment — see the
research notes in TASK_memory_module.md's implementation history). Only
the process that wins the flock runs the poll loop; the OS releases it
automatically on process exit/crash, so another worker picks it up.
"""

import fcntl
import logging
import os
import threading
from datetime import datetime, timedelta

from modules.mem.scanner import MemScanner

logger = logging.getLogger("mem.scheduler")

_poll_thread: threading.Thread | None = None
_stop_event = threading.Event()
_last_scan_at: str | None = None
_next_scan_at: str | None = None
_current_interval = 900

_lock_fh = None
_lock_owner_pid: int | None = None


def _lock_path(db_path: str) -> str:
    return os.path.join(os.path.dirname(db_path), ".mem_poller.lock")


def _we_hold_lock() -> bool:
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


def get_poll_state(db_path: str | None = None) -> dict:
    my_thread_alive = _poll_thread is not None and _poll_thread.is_alive()
    if my_thread_alive:
        running = True
    elif _we_hold_lock():
        running = False
    elif db_path is not None:
        running = _is_owner_lock_held(_lock_path(db_path))
    else:
        running = False
    return {
        "poller_running": running,
        "last_scan_at": _last_scan_at,
        "next_scan_at": _next_scan_at,
        "interval": _current_interval,
    }


def _poll_loop(cfg: dict, db_path: str, interval: int) -> None:
    global _last_scan_at, _next_scan_at

    scanner = MemScanner(cfg, db_path)
    logger.info(f"[MemPoller] started, interval={interval}s, root={cfg.get('scan_root')}")

    while not _stop_event.is_set():
        _next_scan_at = (datetime.now().replace(microsecond=0) + timedelta(seconds=interval)).isoformat()
        if _stop_event.wait(timeout=interval):
            break
        try:
            result = scanner.run_scan()
            _last_scan_at = datetime.now().replace(microsecond=0).isoformat()
            if result.get("inserted") or not result.get("mount_ok", True):
                logger.info(f"[MemPoller] result={result}")
        except Exception as e:
            logger.error(f"[MemPoller] scan error: {e}")


def start_poll_scheduler(cfg: dict, db_path: str, interval: int) -> None:
    global _poll_thread, _current_interval

    if _poll_thread is not None and _poll_thread.is_alive():
        return

    if not _acquire_owner_lock(_lock_path(db_path)):
        logger.info("[MemPoller] another process already owns the poller, skip")
        return

    _current_interval = interval
    _stop_event.clear()
    _poll_thread = threading.Thread(
        target=_poll_loop, args=(cfg, db_path, interval), daemon=True, name="mem-poller",
    )
    _poll_thread.start()


def stop_poll_scheduler() -> None:
    global _poll_thread
    _stop_event.set()
    if _poll_thread is not None:
        _poll_thread.join(timeout=10)
        _poll_thread = None
