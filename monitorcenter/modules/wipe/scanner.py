import argparse
import json
from datetime import datetime
from pathlib import Path

from modules.wipe.parser import parse_log
from modules.wipe.db import (
    init_db, get_conn, insert_record, upsert_record,
    upsert_scan_status, purge_missing_logs,
)

MONTH_DIRS = {
    1: "01 January",  2: "02 February", 3: "03 March",
    4: "04 April",    5: "05 May",      6: "06 June",
    7: "07 July",     8: "08 August",   9: "09 September",
    10: "10 October", 11: "11 November", 12: "12 December",
}

# Month names without numeric prefix (as found in actual log dirs)
_MONTH_NAMES = {
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
}

def _is_month_dir(name: str) -> bool:
    """Accept 'January', '01 January', '05 May', 'may', etc."""
    return name.lower().split()[-1] in _MONTH_NAMES


class WipeScanner:
    def __init__(self, log_roots: list[dict], db_path: str):
        """
        log_roots: list of {"path": str, "win_share_root": str}
        Backward compat: also accepts (log_root: str, db_path, win_share_root) positional args.
        """
        self.log_roots = [
            {"path": Path(r["path"]), "win_share_root": r["win_share_root"].rstrip("\\")}
            for r in log_roots
        ]
        self.db_path = db_path
        init_db(db_path)

    def make_win_path(self, log_path: Path) -> str:
        """Find which root this log belongs to and build the Windows UNC path."""
        for r in self.log_roots:
            try:
                rel = log_path.relative_to(r["path"])
                return r["win_share_root"] + "\\" + str(rel).replace("/", "\\")
            except ValueError:
                continue
        return str(log_path)  # fallback: return as-is

    def _find_year_dirs(self, root: Path) -> list[Path]:
        """Return all year directories under root, including inside sub-source dirs.

        Handles structures like:
          root/2026/May/          → direct year dir
          root/Makor/2026/May/    → one-level sub-source (Makor, Verify, logs_previous…)
        """
        year_dirs: list[Path] = []
        if not root.exists():
            return year_dirs
        for item in root.iterdir():
            if not item.is_dir():
                continue
            if item.name.isdigit() and len(item.name) == 4:
                year_dirs.append(item)          # direct: root/YYYY/
            else:
                # sub-source dir: root/Makor/, root/Verify/, root/logs_previous/ …
                for sub in item.iterdir():
                    if sub.is_dir() and sub.name.isdigit() and len(sub.name) == 4:
                        year_dirs.append(sub)   # root/Makor/YYYY/
        return year_dirs

    def _collect_from_root(self, root: Path) -> list[Path]:
        files = []
        for year_dir in sorted(self._find_year_dirs(root)):
            for month_dir in sorted(year_dir.iterdir()):
                if not month_dir.is_dir() or not _is_month_dir(month_dir.name):
                    continue
                # rglob catches: direct *.log, Logs/*.log, {SN}/*.log, etc.
                files.extend(sorted(month_dir.rglob("*.log")))
        return files

    def collect_all(self) -> list[Path]:
        files = []
        for r in self.log_roots:
            files.extend(self._collect_from_root(r["path"]))
        return files

    def collect_current_month(self) -> list[Path]:
        now = datetime.now()
        cur_year = str(now.year)
        cur_month = now.strftime("%B")   # e.g. "May" — matches bare month dir names
        files = []
        for r in self.log_roots:
            for year_dir in self._find_year_dirs(r["path"]):
                if year_dir.name != cur_year:
                    continue
                for month_dir in year_dir.iterdir():
                    if month_dir.is_dir() and _is_month_dir(month_dir.name) \
                            and month_dir.name.lower().endswith(cur_month.lower()):
                        files.extend(sorted(month_dir.rglob("*.log")))
        return files

    def _process_files(self, files: list[Path], scan_type: str,
                       force: bool = False,
                       progress_every: int = 0) -> dict:
        conn = get_conn(self.db_path)
        total = len(files)
        inserted = skipped = errors = 0

        upsert_scan_status(
            conn, running=1, total=total, done=0, errors=0,
            scan_type=scan_type, started_at=datetime.now().isoformat(),
        )

        for i, f in enumerate(files, 1):
            now_str = datetime.now().isoformat()
            record = parse_log(f)
            if record is None:
                conn.execute(
                    "INSERT INTO scan_errors (log_path, error_msg, attempted_at) VALUES (?,?,?)",
                    (str(f), "parse returned None", now_str),
                )
                conn.commit()
                errors += 1
            else:
                record["log_path"] = str(f)
                record["win_path"] = self.make_win_path(f)
                record["indexed_at"] = now_str
                if force:
                    upsert_record(conn, record)
                    inserted += 1
                else:
                    if insert_record(conn, record):
                        inserted += 1
                    else:
                        skipped += 1

            if i % 100 == 0:
                upsert_scan_status(conn, running=1, total=total, done=i,
                                   errors=errors, scan_type=scan_type)
            if progress_every and i % progress_every == 0:
                print(f"Scanning: {i}/{total}...")

        upsert_scan_status(conn, running=0, total=total, done=total,
                           errors=errors, scan_type=scan_type,
                           inserted=inserted, skipped=skipped)
        conn.close()
        return {"total": total, "inserted": inserted, "skipped": skipped, "errors": errors}

    def run_full(self) -> dict:
        return self._process_files(self.collect_all(), "full")

    def run_poll(self) -> dict:
        return self._process_files(self.collect_current_month(), "poll")

    def run_force(self) -> dict:
        """Re-parse every log file and remove DB records for deleted files."""
        files = self.collect_all()
        existing_paths = {str(f) for f in files}
        # purge records whose source file is gone
        conn = get_conn(self.db_path)
        purged = purge_missing_logs(conn, existing_paths)
        conn.close()
        result = self._process_files(files, "force", force=True)
        result["purged"] = purged
        return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="WipeScanner CLI")
    ap.add_argument("--config", default="/opt/monitorcenter/config/wipe_paths.json")
    ap.add_argument("--full", action="store_true")
    args = ap.parse_args()

    with open(args.config, encoding="utf-8") as fh:
        cfg = json.load(fh)

    # Support both new list format and legacy single-root format
    if "log_roots" in cfg:
        log_roots = cfg["log_roots"]
    else:
        log_roots = [{"path": cfg["log_root"], "win_share_root": cfg.get("win_share_root", "")}]

    scanner = WipeScanner(log_roots=log_roots, db_path=cfg["db_path"])

    if args.full:
        files = scanner.collect_all()
        print(f"Full scan: {len(files)} files found")
        result = scanner._process_files(files, "full", progress_every=500)
    else:
        result = scanner.run_poll()

    print(f"Done: total={result['total']} inserted={result['inserted']} "
          f"skipped={result['skipped']} errors={result['errors']}")
