"""Scans a SharePoint/OneDrive-mounted directory of MemTest86 HTML reports.

Idempotent and mount-drop-safe (§7 of the spec):
  - Dedup is by file content hash (file_sha256), not path — a renamed/moved
    file is never re-imported, only its location columns are updated.
  - If the mount point is unreadable, nothing already in the DB is touched;
    only a scan_error + a mount-health flag are recorded.
  - Reports of test_start earlier than `go_live_date` are stored but marked
    excluded=1 (kept for traceability, left out of module/report listings).
"""

import fnmatch
import logging
import os
import shutil
from datetime import datetime

from modules.mem import db
from modules.mem.parser import parse_file, compute_module_statuses

logger = logging.getLogger("mem.scanner")


class MemScanner:
    def __init__(self, cfg: dict, db_path: str):
        self.cfg = cfg
        self.db_path = db_path
        self.scan_root = cfg.get("scan_root", "")
        self.go_live_date = cfg.get("go_live_date", "1970-01-01")
        self.file_globs = cfg.get("file_globs", ["*.html", "*.htm"])
        self.exclude_dir_patterns = cfg.get("exclude_dir_patterns", ["*_files"])
        self.archive_raw = cfg.get("archive_raw", False)
        self.archive_root = cfg.get("archive_root", "")
        self.max_file_mb = cfg.get("max_file_mb", 10)

    # ------------------------------------------------------------------
    # Mount health
    # ------------------------------------------------------------------

    def check_mount(self) -> tuple[bool, str | None]:
        if not self.scan_root or not os.path.isdir(self.scan_root):
            return False, f"scan_root '{self.scan_root}' is not accessible"
        try:
            os.listdir(self.scan_root)
        except OSError as e:
            return False, str(e)
        return True, None

    # ------------------------------------------------------------------
    # Collection
    # ------------------------------------------------------------------

    def collect_files(self) -> list[str]:
        results = []
        try:
            for dirpath, dirnames, filenames in os.walk(self.scan_root):
                dirnames[:] = [
                    d for d in dirnames
                    if not any(fnmatch.fnmatch(d, pat) for pat in self.exclude_dir_patterns)
                ]
                for fname in filenames:
                    if any(fnmatch.fnmatch(fname, pat) for pat in self.file_globs):
                        results.append(os.path.join(dirpath, fname))
        except OSError as e:
            logger.warning(f"collect_files: cannot walk {self.scan_root}: {e}")
        return results

    # ------------------------------------------------------------------
    # Single-file processing
    # ------------------------------------------------------------------

    def _archive(self, path: str, file_sha256: str) -> str | None:
        if not self.archive_raw or not self.archive_root:
            return None
        try:
            ext = os.path.splitext(path)[1] or ".html"
            dest = os.path.join(self.archive_root, f"{file_sha256}{ext}")
            if not os.path.isfile(dest):
                os.makedirs(self.archive_root, exist_ok=True)
                shutil.copy2(path, dest)
            return dest
        except OSError as e:
            logger.warning(f"archive failed for {path}: {e}")
            return None

    def process_file(self, path: str) -> tuple[str, list[str]]:
        """Returns ('inserted'|'updated'|'skipped'|'error', [affected module_sn]).

        Cheap path: if we already have a report at this exact path with the
        same mtime, skip without reading the file at all.
        """
        try:
            st = os.stat(path)
        except OSError as e:
            db.log_scan_error(self.db_path, datetime.now().isoformat(), path, str(e))
            return "error", []

        if self.max_file_mb and st.st_size > self.max_file_mb * 1024 * 1024:
            db.log_scan_error(
                self.db_path, datetime.now().isoformat(), path,
                f"file exceeds max_file_mb ({self.max_file_mb}MB)",
            )
            return "error", []

        mtime_iso = datetime.fromtimestamp(st.st_mtime).isoformat()
        source_dir = os.path.dirname(os.path.relpath(path, self.scan_root))
        source_file = os.path.basename(path)

        conn = db.get_conn(self.db_path)
        try:
            existing_here = conn.execute(
                "SELECT report_uid, file_mtime FROM mem_reports WHERE source_full_path = ?",
                (path,),
            ).fetchone()
            if existing_here and existing_here["file_mtime"] == mtime_iso:
                return "skipped", []
        finally:
            conn.close()

        try:
            record = parse_file(path)
            file_hash = record["file_sha256"]
        except (OSError, UnicodeDecodeError) as e:
            db.log_scan_error(self.db_path, datetime.now().isoformat(), path, f"parse error: {e}")
            return "error", []

        conn = db.get_conn(self.db_path)
        try:
            # file_sha256 is content-derived and report_uid is derived from
            # fields decoded from that same content, so a hash match always
            # implies the same report_uid — this is the "file was renamed or
            # moved" case (§2.3): update location columns only, no re-parse.
            same_content = db.find_report_by_hash(conn, file_hash)
            if same_content:
                db.update_report_source(conn, same_content["report_uid"], source_dir,
                                         source_file, path, mtime_iso)
                return "updated", []

            # New content (new report, or a re-exported report overwriting
            # an existing report_uid with different bytes).
            affected_sns = db.delete_report_and_recompute(conn, record["report_uid"])

            statuses, has_unattributed = compute_module_statuses(record)
            record["_statuses"] = statuses

            test_date = (record.get("test_start") or "")[:10] or None
            excluded = 1 if (test_date and test_date < self.go_live_date) else 0
            archived_path = self._archive(path, file_hash)

            row = {
                **record,
                "source_dir": source_dir,
                "source_file": source_file,
                "source_full_path": path,
                "archived_path": archived_path,
                "file_mtime": mtime_iso,
                "imported_at": datetime.now().isoformat(),
                "test_date": test_date,
                "has_unattributed_errors": 1 if has_unattributed else 0,
                "parse_ok": 1 if record["parse_ok"] else 0,
                "excluded": excluded,
            }
            db.upsert_report(conn, row)

            all_affected = set(affected_sns) | {m["module_sn"] for m in record["modules"]}
            for sn in all_affected:
                db.recompute_module(conn, sn)

            return ("updated" if existing_here else "inserted"), list(all_affected)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Full scan
    # ------------------------------------------------------------------

    def run_scan(self) -> dict:
        mount_ok, mount_err = self.check_mount()
        now = datetime.now().isoformat()
        if not mount_ok:
            db.set_scan_status(
                self.db_path, status="idle", mount_ok=0, mount_error=mount_err,
                mount_checked_at=now,
            )
            db.log_scan_error(self.db_path, now, self.scan_root, mount_err or "mount unreadable")
            logger.warning(f"[MemScanner] mount unreadable, aborting scan without touching data: {mount_err}")
            return {"total": 0, "inserted": 0, "updated": 0, "skipped": 0, "errors": 0, "mount_ok": False}

        files = self.collect_files()
        total = len(files)
        inserted = updated = skipped = errors = 0

        db.set_scan_status(
            self.db_path, status="running", started_at=now, finished_at=None,
            total=total, done=0, inserted=0, skipped=0, errors=0,
            mount_ok=1, mount_error=None, mount_checked_at=now,
        )

        for i, path in enumerate(files, 1):
            outcome, _ = self.process_file(path)
            if outcome == "inserted":
                inserted += 1
            elif outcome == "updated":
                updated += 1
            elif outcome == "skipped":
                skipped += 1
            else:
                errors += 1

            if i % 25 == 0:
                db.set_scan_status(
                    self.db_path, status="running", total=total, done=i,
                    inserted=inserted + updated, skipped=skipped, errors=errors,
                )

        db.set_scan_status(
            self.db_path, status="done", finished_at=datetime.now().isoformat(),
            total=total, done=total, inserted=inserted + updated, skipped=skipped, errors=errors,
        )

        logger.info(
            f"[MemScanner] scan done: total={total} inserted={inserted} updated={updated} "
            f"skipped={skipped} errors={errors}"
        )
        return {
            "total": total, "inserted": inserted, "updated": updated,
            "skipped": skipped, "errors": errors, "mount_ok": True,
        }
