import logging
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


def get_poll_state() -> dict:
    return {
        "poller_running": _poll_thread is not None and _poll_thread.is_alive(),
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
