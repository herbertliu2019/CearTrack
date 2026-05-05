import json
import os

from modules.wipe.db import init_db
from modules.wipe.routes import wipe_bp
from modules.wipe.scheduler import start_poll_scheduler


def register_wipe_module(app):
    config_path = os.path.join(app.root_path, "config", "wipe_paths.json")
    with open(config_path, encoding="utf-8") as f:
        cfg = json.load(f)

    init_db(cfg["db_path"])
    app.config["WIPE_DB"] = cfg["db_path"]
    app.config["WIPE_CFG"] = cfg
    app.register_blueprint(wipe_bp)
    start_poll_scheduler(cfg)
