import os
from pathlib import Path

# In production: /opt/monitorcenter/  In dev: wherever this file lives.
_ROOT = Path(__file__).parent

BASE_DIR    = Path(os.getenv("MONITORCENTER_DATA_DIR",    str(_ROOT / "data")))
STATIC_DIR  = Path(os.getenv("MONITORCENTER_STATIC_DIR",  str(_ROOT / "static")))
TEMPLATE_DIR = Path(os.getenv("MONITORCENTER_TEMPLATE_DIR", str(_ROOT / "templates")))

INDEX_DB_PATH = BASE_DIR / "_index.sqlite"

HOST = "0.0.0.0"
PORT = 5004
DEBUG = os.getenv("MONITORCENTER_DEBUG", "0") == "1"

# latest/ keeps only files whose mtime is today (local date).
# Purged on app startup and by a daily midnight sweeper thread.
