import json
import logging
import os

from .db import init_db
from .scheduler import start_poll_scheduler

logger = logging.getLogger("cpu.integration")


def register_cpu_module(app) -> None:
    """Load config, init DB, register blueprint, start scheduler.
    Silently disables itself if config or root_dir is missing."""

    config_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "config", "cpu_paths.json")
    )

    if not os.path.exists(config_path):
        logger.warning(f"CPU config not found at {config_path} — module disabled")
        return

    with open(config_path, encoding="utf-8") as f:
        cfg = json.load(f)

    root_dir = cfg.get("cpu_root_dir", "")
    db_path  = cfg.get("cpu_db_path", "")
    interval = int(cfg.get("poll_interval_sec", 1800))  # default 30 min

    if not root_dir or not os.path.isdir(root_dir):
        logger.warning(f"CPU root_dir '{root_dir}' not accessible — module disabled")
        return

    if not db_path:
        logger.warning("CPU db_path not set in config — module disabled")
        return

    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    init_db(db_path)

    app.config["CPU_DB_PATH"] = db_path
    app.config["CPU_ROOT_DIR"] = root_dir

    from .routes import cpu_bp
    app.register_blueprint(cpu_bp)

    start_poll_scheduler(root_dir=root_dir, db_path=db_path, interval=interval)
    logger.info(f"CPU module registered — root={root_dir}  db={db_path}  poll={interval}s")
