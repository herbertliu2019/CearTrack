"""Filesystem storage for test envelopes.

Layout under BASE_DIR:
    <module>/latest/<sn>.json             # most recent result per SN (24h TTL)
    <module>/history/YYYY/MM-DD/<sn>_<ts>.json

No database — JSON files only. Uses pathlib.Path throughout.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable

import config


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _module_root(module_name: str) -> Path:
    root = config.BASE_DIR / module_name
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_date_subdir(module_name: str, when: datetime | None = None) -> Path:
    """Return history/YYYY/MM-DD/ under the module, creating dirs as needed."""
    when = when or datetime.now(timezone.utc)
    sub = _module_root(module_name) / "history" / when.strftime("%Y") / when.strftime("%m-%d")
    sub.mkdir(parents=True, exist_ok=True)
    return sub


def get_latest_dir(module_name: str) -> Path:
    """Return latest/ under the module, creating it if needed."""
    d = _module_root(module_name) / "latest"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_base_history_dir(module_name: str) -> Path:
    """Return data/<module>/history/ root (not date-specific). Does not create."""
    return config.BASE_DIR / module_name / "history"


# ---------------------------------------------------------------------------
# SN sanitization — only allow filesystem-safe chars
# ---------------------------------------------------------------------------

_SN_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]")


def _safe_sn(sn: str) -> str:
    sn = (sn or "unknown").strip()
    return _SN_SAFE_RE.sub("_", sn) or "unknown"


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def write_envelope(module_name: str, sn: str, envelope: dict) -> dict:
    """Write envelope to latest/ AND history/, enforcing one-SN-one-record.

    Business rule: one SN = one laptop = one final test result.
    On re-upload of the same SN, every prior history file for that SN
    is deleted (and so are their SQLite index rows) before writing the
    new one. Empty MM-DD/ and YYYY/ dirs are then cleaned up.

    Returns {"history_path": str, "latest_path": str} of the new files.
    """
    # Local import to avoid a top-level circular dependency
    # (index_db.search delegates back to storage.search_sn).
    from core import index_db

    sn_safe = _safe_sn(sn)

    # Timestamp for history filename — prefer envelope timestamp, else now.
    ts_str = envelope.get("timestamp") or datetime.now(timezone.utc).isoformat()
    try:
        when = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except Exception:
        when = datetime.now(timezone.utc)

    payload = json.dumps(envelope, ensure_ascii=False, indent=2)

    # 1) latest/ — always overwrite
    latest_path = get_latest_dir(module_name) / f"{sn_safe}.json"
    latest_path.write_text(payload, encoding="utf-8")

    # 2) history/ — purge every prior file for this SN across all date dirs
    base_history = get_base_history_dir(module_name)
    if base_history.exists():
        for old in base_history.rglob(f"{sn_safe}_*.json"):
            try:
                index_db.delete_by_history_path(str(old))
            except Exception:
                pass
            try:
                old.unlink(missing_ok=True)
            except OSError:
                continue
            # Try removing now-empty MM-DD/, then YYYY/. break on first non-empty.
            for parent in (old.parent, old.parent.parent):
                try:
                    parent.rmdir()
                except OSError:
                    break

    # 3) Write the new history file
    history_dir = get_date_subdir(module_name, when)
    ts_tag = when.strftime("%Y%m%dT%H%M%S")
    history_path = history_dir / f"{sn_safe}_{ts_tag}.json"
    history_path.write_text(payload, encoding="utf-8")

    return {"history_path": str(history_path), "latest_path": str(latest_path)}


# ---------------------------------------------------------------------------
# Read — latest/ with 24h TTL
# ---------------------------------------------------------------------------

def purge_stale_latest(module_name: str) -> int:
    """Delete any file in latest/ whose mtime is not today (local date).

    Returns the number of files removed. Safe to call concurrently and
    repeatedly — missing dirs / files are no-ops.
    """
    latest_dir = get_latest_dir(module_name)
    today = date.today()
    removed = 0
    for p in latest_dir.glob("*.json"):
        try:
            if date.fromtimestamp(p.stat().st_mtime) != today:
                p.unlink(missing_ok=True)
                removed += 1
        except OSError:
            continue
    return removed


def purge_stale_latest_all() -> dict[str, int]:
    """Purge non-today files in every module's latest/. Returns {module: count}."""
    return {m: purge_stale_latest(m) for m in iter_modules_with_data()}


def read_latest(module_name: str) -> list[dict]:
    """Return all envelopes in latest/ whose mtime is today (local date).
    Stale (non-today) files are purged on the way through, so the dashboard
    never shows yesterday's results even if the midnight sweep was missed.
    """
    latest_dir = get_latest_dir(module_name)
    today = date.today()
    out: list[dict] = []

    for p in sorted(latest_dir.glob("*.json")):
        try:
            if date.fromtimestamp(p.stat().st_mtime) != today:
                p.unlink(missing_ok=True)
                continue
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            # Corrupt / unreadable — skip, don't crash the dashboard.
            continue
    return out


# ---------------------------------------------------------------------------
# Search by SN — recursive in history/
# ---------------------------------------------------------------------------

def search_sn(module_name: str, sn: str) -> list[dict]:
    """Fuzzy substring search for SN across history for one module.

    Delegates to the SQLite index (core.index_db). Matches both the
    system SN and every storage-device SN (or whatever kinds the module
    registers via `extract_searchable_sns`).
    """
    from core import index_db
    return index_db.search(sn, module=module_name)


# ---------------------------------------------------------------------------
# List history by date range
# ---------------------------------------------------------------------------

def list_history(
    module_name: str,
    date_range: tuple[datetime, datetime] | None = None,
) -> list[dict]:
    """List all envelopes under history/ whose bucket date lies inside the range.

    date_range is an inclusive (start, end) pair of datetimes; if None,
    returns everything.
    """
    history_root = _module_root(module_name) / "history"
    if not history_root.exists():
        return []

    start = end = None
    if date_range is not None:
        start, end = date_range

    results: list[dict] = []
    for p in sorted(history_root.rglob("*.json")):
        if start is not None or end is not None:
            # path like .../YYYY/MM-DD/<sn>_<ts>.json — reconstruct from parts
            try:
                yyyy = p.parent.parent.name
                md = p.parent.name  # MM-DD
                bucket = datetime.strptime(f"{yyyy}-{md}", "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except Exception:
                continue
            if start is not None and bucket < start:
                continue
            if end is not None and bucket > end:
                continue
        try:
            results.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    return results


def iter_modules_with_data() -> Iterable[str]:
    """Yield module directory names that exist under BASE_DIR."""
    if not config.BASE_DIR.exists():
        return []
    return [p.name for p in config.BASE_DIR.iterdir() if p.is_dir()]
