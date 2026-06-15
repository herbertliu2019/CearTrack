import logging
import threading
from datetime import datetime, timedelta

from modules.cpu.db import get_scan_status
from modules.cpu.scanner import CpuScanner

logger = logging.getLogger("cpu.scheduler")

# ── Incremental poll thread ────────────────────────────────────────────────
_poll_thread:      threading.Thread | None = None
_stop_event      = threading.Event()
_last_scan_at:   str | None = None
_next_scan_at:   str | None = None
_current_interval: int = 1800

# ── Nightly full-scan thread ───────────────────────────────────────────────
_night_thread:    threading.Thread | None = None
_night_stop      = threading.Event()
_last_full_at:   str | None = None
NIGHTLY_HOUR     = 4   # 4:00 AM local time


def get_poll_state() -> dict:
    return {
        "poller_running": _poll_thread is not None and _poll_thread.is_alive(),
        "last_scan_at":   _last_scan_at,
        "next_scan_at":   _next_scan_at,
        "interval":       _current_interval,
        "last_full_at":   _last_full_at,
        "next_full_at":   _next_nightly_str(),
    }


def _next_nightly_str() -> str:
    """ISO string for the next 4:00 AM."""
    now = datetime.now()
    nightly = now.replace(hour=NIGHTLY_HOUR, minute=0, second=0, microsecond=0)
    if nightly <= now:
        nightly += timedelta(days=1)
    return nightly.isoformat()


def _seconds_until_nightly() -> float:
    """Seconds until next 4:00 AM."""
    return (datetime.fromisoformat(_next_nightly_str()) - datetime.now()).total_seconds()


def _poll_loop(root_dir: str, db_path: str, interval: int) -> None:
    global _last_scan_at, _next_scan_at

    scanner = CpuScanner(root_dir=root_dir, db_path=db_path)
    logger.info(f"[CpuPoller] started, interval={interval}s, root={root_dir}")

    while not _stop_event.is_set():
        _next_scan_at = (
            datetime.now().replace(microsecond=0) + timedelta(seconds=interval)
        ).isoformat()

        # Sleep for interval; exit early if stop requested
        if _stop_event.wait(timeout=interval):
            break

        # Skip if a manual full-scan is running
        try:
            status = get_scan_status(db_path)
            if status.get("status") == "running":
                logger.info("[CpuPoller] skipped: manual scan in progress")
                continue
        except Exception as e:
            logger.warning(f"[CpuPoller] DB check failed, skipping: {e}")
            continue

        try:
            result = scanner.run_incremental()
            _last_scan_at = datetime.now().replace(microsecond=0).isoformat()
            if result.get("inserted", 0) + result.get("updated", 0) > 0:
                logger.info(
                    f"[CpuPoller] inserted={result.get('inserted',0)} "
                    f"updated={result.get('updated',0)} "
                    f"skipped={result.get('skipped',0)} errors={result.get('errors',0)}"
                )
        except Exception as e:
            logger.error(f"[CpuPoller] poll error: {e}")


def _nightly_loop(root_dir: str, db_path: str) -> None:
    """Wake at 4:00 AM every day and run a full scan (with stale-record cleanup)."""
    global _last_full_at

    scanner = CpuScanner(root_dir=root_dir, db_path=db_path)
    logger.info(f"[CpuNightly] started, fires at {NIGHTLY_HOUR:02d}:00 local time")

    while not _night_stop.is_set():
        wait_sec = _seconds_until_nightly()
        logger.info(f"[CpuNightly] next full scan in {wait_sec/3600:.1f}h "
                    f"({_next_nightly_str()})")

        # Sleep until 4 AM (or until stop signal)
        if _night_stop.wait(timeout=wait_sec):
            break

        # Double-check time (wait() may return a few seconds early/late)
        now = datetime.now()
        if not (NIGHTLY_HOUR - 1 <= now.hour < NIGHTLY_HOUR + 1):
            logger.debug("[CpuNightly] woke outside window, re-sleeping")
            continue

        logger.info("[CpuNightly] starting nightly full scan")
        try:
            result = scanner.run_full()
            _last_full_at = datetime.now().replace(microsecond=0).isoformat()
            logger.info(
                f"[CpuNightly] full scan done: "
                f"inserted={result.get('inserted',0)} updated={result.get('updated',0)} "
                f"deleted={result.get('deleted',0)} skipped={result.get('skipped',0)} "
                f"errors={result.get('errors',0)}"
            )
        except Exception as e:
            logger.error(f"[CpuNightly] full scan error: {e}")


def start_poll_scheduler(root_dir: str, db_path: str, interval: int = 1800) -> None:
    global _poll_thread, _stop_event, _current_interval
    global _night_thread, _night_stop

    # ── Incremental poller ──
    if _poll_thread is not None and _poll_thread.is_alive():
        logger.warning("[CpuPoller] already running, skip")
    else:
        _current_interval = interval
        _stop_event.clear()
        _poll_thread = threading.Thread(
            target=_poll_loop,
            args=(root_dir, db_path, interval),
            daemon=True,
            name="cpu-poller",
        )
        _poll_thread.start()

    # ── Nightly full-scan ──
    if _night_thread is not None and _night_thread.is_alive():
        logger.warning("[CpuNightly] already running, skip")
    else:
        _night_stop.clear()
        _night_thread = threading.Thread(
            target=_nightly_loop,
            args=(root_dir, db_path),
            daemon=True,
            name="cpu-nightly",
        )
        _night_thread.start()


def stop_poll_scheduler() -> None:
    global _poll_thread, _night_thread
    _stop_event.set()
    _night_stop.set()
    if _poll_thread is not None:
        _poll_thread.join(timeout=10)
        _poll_thread = None
    if _night_thread is not None:
        _night_thread.join(timeout=10)
        _night_thread = None
    logger.info("[CpuPoller] stopped")
