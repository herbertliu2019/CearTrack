import json
import logging
import os
from datetime import datetime

from modules.cpu.parser import parse_log
from modules.cpu.db import insert_record, set_scan_status, get_scan_status, delete_missing_paths

logger = logging.getLogger("cpu.scanner")

# Sidecar file that stores per-subdir mtimes for incremental detection
_STATE_FILE = "cpu_scan_state.json"


class CpuScanner:
    def __init__(self, root_dir: str, db_path: str):
        self.root_dir = os.path.abspath(root_dir)
        self.db_path = db_path
        self._state_path = os.path.join(os.path.dirname(db_path), _STATE_FILE)

    # ------------------------------------------------------------------
    # Collection
    # ------------------------------------------------------------------

    def collect_log_paths(self, subtree: str = None) -> list[str]:
        """
        Recursively walk subtree (defaults to root_dir).
        Return absolute paths of all TESTRESULTS.TXT files found.
        Skips unreadable directories silently.
        """
        base = os.path.abspath(subtree) if subtree else self.root_dir
        results = []
        try:
            for dirpath, dirnames, filenames in os.walk(base):
                # case-insensitive match for safety
                for fname in filenames:
                    if fname.upper().endswith(".TXT"):
                        results.append(os.path.join(dirpath, fname))
                # skip hidden/system dirs
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        except OSError as e:
            logger.warning(f"collect_log_paths: cannot walk {base}: {e}")
        return results

    # ------------------------------------------------------------------
    # Single-file processing
    # ------------------------------------------------------------------

    def process_file(self, log_path: str) -> str:
        """
        Parse log_path and insert into DB.
        Returns 'inserted' | 'skipped' | 'error'.
        """
        try:
            record = parse_log(log_path)
            if record is None:
                return "error"
            return insert_record(self.db_path, record)  # 'inserted' | 'updated' | 'skipped'
        except Exception as e:
            logger.error(f"process_file error {log_path}: {e}")
            return "error"

    # ------------------------------------------------------------------
    # Full scan
    # ------------------------------------------------------------------

    def run_full(self) -> dict:
        """
        Scan entire root_dir. Updates scan_status in DB throughout.
        Returns {total, inserted, skipped, errors}.
        """
        files = self.collect_log_paths()
        total = len(files)
        inserted = updated = skipped = errors = 0

        set_scan_status(
            self.db_path,
            status="running",
            started_at=datetime.now().isoformat(),
            finished_at=None,
            total=total,
            done=0,
            inserted=0,
            skipped=0,
            errors=0,
        )

        for i, log_path in enumerate(files, 1):
            outcome = self.process_file(log_path)
            if outcome == "inserted":
                inserted += 1
            elif outcome == "updated":
                updated += 1
            elif outcome == "skipped":
                skipped += 1
            else:
                errors += 1

            # update progress every 50 files
            if i % 50 == 0:
                set_scan_status(
                    self.db_path,
                    status="running",
                    total=total,
                    done=i,
                    inserted=inserted + updated,
                    skipped=skipped,
                    errors=errors,
                )

        set_scan_status(
            self.db_path,
            status="done",
            finished_at=datetime.now().isoformat(),
            total=total,
            done=total,
            inserted=inserted + updated,
            skipped=skipped,
            errors=errors,
        )

        # Remove DB records whose files no longer exist on disk
        existing = set(os.path.abspath(p) for p in files)
        deleted = delete_missing_paths(self.db_path, existing)
        if deleted:
            logger.info(f"[CpuScanner] run_full: removed {deleted} stale record(s)")

        # Refresh state file after full scan so incremental starts clean
        self._save_state(self._current_mtimes())

        logger.info(
            f"run_full done: total={total} inserted={inserted} updated={updated} "
            f"skipped={skipped} errors={errors} deleted={deleted}"
        )
        return {"total": total, "inserted": inserted, "updated": updated, "skipped": skipped, "errors": errors, "deleted": deleted}

    # ------------------------------------------------------------------
    # Incremental scan
    # ------------------------------------------------------------------

    def run_incremental(self) -> dict:
        """Stat directories up to 3 levels deep; re-scan only changed subtrees.

        Directory structure: <root>/<tester>/<model>/<SN>/TESTRESULTS.TXT
          level-1 mtime changes → new tester dir or new model under existing tester
          level-2 mtime changes → new SN dir under existing model
          level-3 mtime changes → new/replaced file inside existing SN dir

        We stat all three levels (~1000 os.stat calls) instead of reading
        thousands of log files, so the check is fast even over a network mount.
        """
        saved   = self._load_state()
        current = self._deep_mtimes(max_depth=3)

        # Collect smallest changed subtrees (avoid rescanning parents of changed children)
        changed: set[str] = set()
        for path, mtime in current.items():
            if saved.get(path) != mtime:
                changed.add(path)

        # Remove any path whose ancestor is already in the set (scan parent covers it)
        minimal: list[str] = []
        for path in sorted(changed):
            if not any(path.startswith(ancestor + os.sep) for ancestor in minimal):
                minimal.append(path)

        if not minimal:
            logger.debug("[CpuScanner] incremental: no changes detected")
            set_scan_status(self.db_path, status="done",
                            finished_at=datetime.now().isoformat(),
                            total=0, done=0, inserted=0, skipped=0, errors=0)
            return {"total": 0, "inserted": 0, "skipped": 0, "errors": 0}

        logger.info(f"[CpuScanner] incremental: {len(minimal)} changed subtree(s): "
                    + ", ".join(os.path.basename(p) for p in minimal[:5]))

        # Collect all files first so we can report total
        all_files = []
        for subtree in minimal:
            all_files.extend(self.collect_log_paths(subtree))

        set_scan_status(self.db_path, status="running",
                        started_at=datetime.now().isoformat(),
                        finished_at=None,
                        total=len(all_files), done=0,
                        inserted=0, skipped=0, errors=0)

        total = inserted = updated = skipped = errors = 0
        for log_path in all_files:
            total += 1
            outcome = self.process_file(log_path)
            if outcome == "inserted":
                inserted += 1
            elif outcome == "updated":
                updated += 1
            elif outcome == "skipped":
                skipped += 1
            else:
                errors += 1

        set_scan_status(self.db_path, status="done",
                        finished_at=datetime.now().isoformat(),
                        total=total, done=total,
                        inserted=inserted + updated, skipped=skipped, errors=errors)

        self._save_state(current)
        logger.info(f"[CpuScanner] incremental done: "
                    f"total={total} inserted={inserted} updated={updated} "
                    f"skipped={skipped} errors={errors}")
        return {"total": total, "inserted": inserted, "updated": updated, "skipped": skipped, "errors": errors}

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------

    def _deep_mtimes(self, max_depth: int = 3) -> dict[str, float]:
        """Stat all subdirectories up to max_depth levels below root_dir.

        Returns {abs_path: mtime}. Skips hidden dirs and unreadable paths.
        On a network mount, stat-only is orders of magnitude faster than
        reading file content.
        """
        result: dict[str, float] = {}

        def _walk(path: str, depth: int) -> None:
            if depth > max_depth:
                return
            try:
                with os.scandir(path) as it:
                    for entry in it:
                        if not entry.is_dir(follow_symlinks=False):
                            continue
                        if entry.name.startswith("."):
                            continue
                        try:
                            result[entry.path] = entry.stat(follow_symlinks=False).st_mtime
                        except OSError:
                            continue
                        _walk(entry.path, depth + 1)
            except OSError as e:
                logger.warning(f"[CpuScanner] cannot scan {path}: {e}")

        _walk(self.root_dir, 1)
        return result

    def _current_mtimes(self) -> dict[str, float]:
        """Legacy: level-1 only. Use _deep_mtimes() for new code."""
        return self._deep_mtimes(max_depth=1)

    def _load_state(self) -> dict:
        try:
            with open(self._state_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_state(self, mtimes: dict) -> None:
        try:
            with open(self._state_path, "w", encoding="utf-8") as f:
                json.dump(mtimes, f, indent=2)
        except OSError as e:
            logger.warning(f"_save_state failed: {e}")

    # ------------------------------------------------------------------
    # Path utility
    # ------------------------------------------------------------------

    @staticmethod
    def make_server_path(local_path: str, path_map: dict | None = None) -> str:
        """
        Optionally remap a local dev path to the server path.
        path_map example: {"C:/Users/...": "/mnt/CPU"}
        """
        if not path_map:
            return local_path
        for local_prefix, server_prefix in path_map.items():
            if local_path.startswith(local_prefix):
                tail = local_path[len(local_prefix):]
                tail = tail.replace("\\", "/")
                return server_prefix.rstrip("/") + "/" + tail.lstrip("/")
        return local_path
