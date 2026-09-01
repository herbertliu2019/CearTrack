"""Filesystem / database path resolution for the Cyclelution layer.

Kept in one place so both runtime code and tests can point at real or
fixture databases without hardcoding. Mirrors how the app resolves the
wipe DB (config/wipe_paths.json), with a local-dev fallback.
"""

import json
from pathlib import Path

import config


def index_db_path() -> Path:
    """The shared _index.sqlite (holds envelopes + our laptop_sync table)."""
    return Path(config.INDEX_DB_PATH)


def wipe_db_path() -> Path:
    """Resolve wipe_index.db the same way modules/wipe/integration.py does:
    read config/wipe_paths.json. When the configured (production) path does
    not exist locally, fall back to the conventional data/ location so dev
    machines still work.
    """
    cfg = Path(config.__file__).parent / "config" / "wipe_paths.json"
    try:
        configured = Path(json.loads(cfg.read_text(encoding="utf-8"))["db_path"])
        if configured.exists():
            return configured
    except Exception:
        pass
    return Path(config.BASE_DIR) / "wipe" / "wipe_index.db"


def batches_db_path() -> Path:
    """The export-batch bookkeeping DB (TASK_export_batch.md). Deliberately
    separate from index_db_path() and wipe_db_path() — batches are
    CearTrack's own scan-session state, never written into either upstream
    database (see the task's hard rule #2)."""
    return Path(config.BASE_DIR) / "batches.db"
