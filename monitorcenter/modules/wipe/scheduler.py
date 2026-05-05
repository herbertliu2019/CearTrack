import logging
import threading

from modules.wipe.db import get_conn, get_scan_status
from modules.wipe.scanner import WipeScanner

logger = logging.getLogger(__name__)

_poll_thread: threading.Thread | None = None
_stop_event = threading.Event()


def _poll_loop(cfg: dict, interval: int) -> None:
    scanner = WipeScanner(
        log_root=cfg["log_root"],
        db_path=cfg["db_path"],
        win_share_root=cfg["win_share_root"],
    )
    while not _stop_event.is_set():
        try:
            conn = get_conn(cfg["db_path"])
            status = get_scan_status(conn)
            conn.close()
            if status["running"] == 0:
                result = scanner.run_poll()
                if result["inserted"] > 0:
                    logger.info(f"Poll: {result['inserted']} new records")
        except Exception as e:
            logger.error(f"Poll error: {e}")
        _stop_event.wait(interval)


def start_poll_scheduler(cfg: dict) -> None:
    global _poll_thread, _stop_event
    interval = cfg.get("poll_interval", 600)
    _stop_event.clear()
    _poll_thread = threading.Thread(
        target=_poll_loop,
        args=(cfg, interval),
        daemon=True,
        name="wipe-poller",
    )
    _poll_thread.start()
    logger.info(f"Wipe poller started, interval={interval}s")


def stop_poll_scheduler() -> None:
    _stop_event.set()
