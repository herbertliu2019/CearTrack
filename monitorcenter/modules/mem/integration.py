import json
import logging
import os

from .db import init_db

logger = logging.getLogger("mem.integration")

_DEFAULTS = {
    "go_live_date": "1970-01-01",
    "poll_interval_sec": 900,
    "file_globs": ["*.html", "*.htm"],
    "exclude_dir_patterns": ["*_files"],
    "archive_raw": True,
    "max_file_mb": 10,
}


def register_mem_module(app) -> None:
    """Load config, init DB, register blueprint.

    Only a missing config file or db_path disables registration.
    """
    config_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "config", "mem_paths.json")
    )

    if not os.path.exists(config_path):
        logger.warning(f"Mem config not found at {config_path} — module disabled")
        return

    with open(config_path, encoding="utf-8") as f:
        cfg = {**_DEFAULTS, **json.load(f)}

    db_path = cfg.get("mem_db_path", "")
    if not db_path:
        logger.warning("Mem db_path not set in config — module disabled")
        return

    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    init_db(db_path)

    # Reports pushed via POST /mem/api/upload land here (not in scan_root,
    # which is the read-only SharePoint mount).
    cfg.setdefault("upload_root", os.path.join(os.path.dirname(db_path), "uploads"))

    app.config["MEM_DB_PATH"] = db_path
    app.config["MEM_CFG"] = cfg

    from .routes import mem_bp
    app.register_blueprint(mem_bp)

    # Reports now arrive only via POST /mem/api/upload — the SharePoint
    # scan_root poller (scheduler.py) is no longer started.
    logger.info(f"Mem module registered — upload_root={cfg['upload_root']} db={db_path}")
