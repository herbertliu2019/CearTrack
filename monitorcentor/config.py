import os
from pathlib import Path

BASE_DIR = Path("/opt/monitorcenter/data")
STATIC_DIR = Path("/opt/monitorcenter/static")
TEMPLATE_DIR = Path("/opt/monitorcenter/templates")

INDEX_DB_PATH = BASE_DIR / "_index.sqlite"

HOST = "0.0.0.0"
PORT = 5004
DEBUG = os.getenv("MONITORCENTER_DEBUG", "0") == "1"

# latest/ keeps only files whose mtime is today (local date).
# Purged on app startup and by a daily midnight sweeper thread.
