import os
from pathlib import Path

# In production: /opt/monitorcenter/  In dev: wherever this file lives.
_ROOT = Path(__file__).parent

BASE_DIR    = Path(os.getenv("MONITORCENTER_DATA_DIR",    str(_ROOT / "data")))
STATIC_DIR  = Path(os.getenv("MONITORCENTER_STATIC_DIR",  str(_ROOT / "static")))
TEMPLATE_DIR = Path(os.getenv("MONITORCENTER_TEMPLATE_DIR", str(_ROOT / "templates")))

INDEX_DB_PATH = BASE_DIR / "_index.sqlite"

# Monitor module
MONITOR_DB_PATH = BASE_DIR / "monitor" / "monitor.db"
MONITOR_MAX_DEAD_PIXELS = 2   # keep in sync with MAX_DEAD_PIXELS in monitor_test.sh
MONITOR_TIMEZONE = "America/Los_Angeles"

# Console module (game console test entry + QC)
CONSOLE_DB_PATH = BASE_DIR / "console" / "console.db"
CONSOLE_PHOTO_DIR = BASE_DIR / "console_photos"
CONSOLE_EXTERNAL_DIR = BASE_DIR / "console" / "external"   # raw JSON/PDF from /console/api/upload
CONSOLE_API_KEY = os.getenv("CONSOLE_API_KEY", "ceartrack-upload-2026")   # X-API-Key for external uploads

HOST = "0.0.0.0"
PORT = 5004
DEBUG = os.getenv("MONITORCENTER_DEBUG", "0") == "1"

# latest/ keeps only files whose mtime is today (local date).
# Purged on app startup and by a daily midnight sweeper thread.
