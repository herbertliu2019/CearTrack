import logging
import os

import config

from .db import init_db

logger = logging.getLogger("console.integration")


def register_console_module(app) -> None:
    db_path = str(config.CONSOLE_DB_PATH)
    photo_dir = str(config.CONSOLE_PHOTO_DIR)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    os.makedirs(photo_dir, exist_ok=True)
    ext_dir = str(config.CONSOLE_EXTERNAL_DIR)
    os.makedirs(ext_dir, exist_ok=True)
    app.config["CONSOLE_EXTERNAL_DIR"] = ext_dir
    app.config["CONSOLE_API_KEY"] = config.CONSOLE_API_KEY
    init_db(db_path)

    app.config["CONSOLE_DB_PATH"] = db_path
    app.config["CONSOLE_PHOTO_DIR"] = photo_dir
    app.config.setdefault("MAX_CONTENT_LENGTH", 25 * 1024 * 1024)

    from .routes import console_bp
    app.register_blueprint(console_bp)

    logger.info(f"Console module registered — db={db_path} photos={photo_dir}")
