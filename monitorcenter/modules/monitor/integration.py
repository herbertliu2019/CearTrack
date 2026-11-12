import logging
import os

import config

from .db import init_db

logger = logging.getLogger("monitor.integration")


def register_monitor_module(app) -> None:
    db_path = str(config.MONITOR_DB_PATH)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    init_db(db_path)

    app.config["MONITOR_DB_PATH"] = db_path
    app.config["MONITOR_MAX_DEAD_PIXELS"] = config.MONITOR_MAX_DEAD_PIXELS

    from .routes import monitor_bp
    app.register_blueprint(monitor_bp)

    logger.info(f"Monitor module registered — db={db_path}")
