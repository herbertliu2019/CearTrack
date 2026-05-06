import argparse
import json
from datetime import datetime
from pathlib import Path

from modules.wipe.parser import parse_log
from modules.wipe.db import (
    init_db, get_conn, insert_record,
    upsert_scan_status,
)

MONTH_DIRS = {
    1: "01 January",  2: "02 February", 3: "03 March",
    4: "04 April",    5: "05 May",      6: "06 June",
    7: "07 July",     8: "08 August",   9: "09 September",
    10: "10 October", 11: "11 November", 12: "12 December",
}


class WipeScanner:
    def __init__(self, log_root: str, db_path: str, win_share_root: str):
        self.log_root = Path(log_root)
        self.db_path = db_path
        self.win_share_root = win_share_root.rstrip("\\")
        init_db(db_path)

    def make_win_path(self, log_path: Path) -> str:
        rel = str(log_path).replace(str(self.log_root), "", 1)
        rel = rel.replace("/", "\\")
        if not rel.startswith("\\"):
            rel = "\\" + rel
        return self.win_share_root + rel

    def collect_all(self) -> list[Path]:
        files = []
        if not self.log_root.exists():
            return files
        for year_dir in sorted(self.log_root.iterdir()):
            if not year_dir.is_dir() or not year_dir.name.isdigit() or len(year_dir.name) != 4:
                continue
            for month_dir in sorted(year_dir.iterdir()):
                if not month_dir.is_dir() or month_dir.name not in MONTH_DIRS.values():
                    continue
                files.extend(sorted(month_dir.glob("*.log")))
        return files

    def collect_current_month(self) -> list[Path]:
        now = datetime.now()
        month_dir = self.log_root / str(now.year) / MONTH_DIRS[now.month]
        if not month_dir.exists():
            return []
        return sorted(month_dir.glob("*.log"))

    def _process_files(self, files: list[Path], scan_type: str,
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


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="WipeScanner CLI")
    ap.add_argument("--config", default="/opt/monitorcenter/config/wipe_paths.json")
    ap.add_argument("--full", action="store_true")
    args = ap.parse_args()

    with open(args.config, encoding="utf-8") as fh:
        cfg = json.load(fh)

    scanner = WipeScanner(
        log_root=cfg["log_root"],
        db_path=cfg["db_path"],
        win_share_root=cfg["win_share_root"],
    )

    if args.full:
        files = scanner.collect_all()
        print(f"Full scan: {len(files)} files found")
        result = scanner._process_files(files, "full", progress_every=500)
    else:
        result = scanner.run_poll()

    print(f"Done: total={result['total']} inserted={result['inserted']} "
          f"skipped={result['skipped']} errors={result['errors']}")
