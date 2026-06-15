import logging
import threading
from datetime import datetime, timedelta

from modules.cpu.db import get_scan_status
from modules.cpu.scanner import CpuScanner

logger = logging.getLogger("cpu.scheduler")

_poll_thread:      threading.Thread | None = None
_stop_event      = threading.Event()
_last_scan_at:   str | None = None
_next_scan_at:   str | None = None
_current_interval: int = 1800


def get_poll_state() -> dict:
    return {
        "poller_running": _poll_thread is not None and _poll_thread.is_alive(),
        "last_scan_at":   _last_scan_at,
        "next_scan_at":   _next_scan_at,
        "interval":       _current_interval,
    }


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
            if result["inserted"] > 0:
                logger.info(
                    f"[CpuPoller] inserted={result['inserted']} "
                    f"skipped={result['skipped']} errors={result['errors']}"
                )
            # no new files → silent (avoid log spam every 30 min)
        except Exception as e:
            logger.error(f"[CpuPoller] poll error: {e}")


def start_poll_scheduler(root_dir: str, db_path: str, interval: int = 1800) -> None:
    global _poll_thread, _stop_event, _current_interval

    if _poll_thread is not None and _poll_thread.is_alive():
        logger.warning("[CpuPoller] already running, skip")
        return

    _current_interval = interval
    _stop_event.clear()
    _poll_thread = threading.Thread(
        target=_poll_loop,
        args=(root_dir, db_path, interval),
        daemon=True,
        name="cpu-poller",
    )
    _poll_thread.start()


def stop_poll_scheduler() -> None:
    global _poll_thread
    _stop_event.set()
    if _poll_thread is not None:
        _poll_thread.join(timeout=10)
        _poll_thread = None
    logger.info("[CpuPoller] stopped")
