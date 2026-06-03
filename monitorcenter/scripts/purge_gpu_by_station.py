"""Purge GPU records whose payload.test_info.test_station matches any of
the given names (case-insensitive). Empty / missing station counts as "Unknown".

Deletes:
  - data/gpu/history/YYYY/MM-DD/<sn>_<ts>.json
  - data/gpu/latest/<sn>.json (if present)
  - data/gpu/pdf/<sn>.pdf       (if present)
  - matching rows in _index.sqlite (envelopes + envelope_sns via cascade)

Run from /opt/monitorcenter/:
    # Dry-run (no delete, just list)
    /opt/monitorcenter/venv/bin/python3 scripts/purge_gpu_by_station.py test Unknown

    # Real delete (add --yes to skip confirmation)
    /opt/monitorcenter/venv/bin/python3 scripts/purge_gpu_by_station.py test Unknown --apply
"""

import sys
import json
import argparse
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import config


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stations", nargs="+",
                    help='Station names to purge (case-insensitive). Use "Unknown" to also match empty.')
    ap.add_argument("--apply", action="store_true",
                    help="Actually delete files + index rows (default is dry-run)")
    ap.add_argument("--yes", action="store_true",
                    help="Skip confirmation prompt")
    args = ap.parse_args()

    target_set = {s.strip().lower() for s in args.stations if s.strip()}
    match_unknown = "unknown" in target_set

    history_root = config.BASE_DIR / "gpu" / "history"
    latest_dir   = config.BASE_DIR / "gpu" / "latest"
    pdf_dir      = config.BASE_DIR / "gpu" / "pdf"

    if not history_root.exists():
        print(f"No history dir at {history_root}")
        sys.exit(0)

    print(f"Scanning {history_root} for stations: {sorted(target_set)}")
    print(f"Mode: {'DELETE' if args.apply else 'DRY-RUN'}\n")

    to_delete = []  # (history_path, sn, station)
    for p in sorted(history_root.rglob("*.json")):
        try:
            env = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  [SKIP] {p}: {e}")
            continue
        st = ((env.get("payload", {}) or {}).get("test_info", {}) or {}).get("test_station") or ""
        st_norm = st.strip().lower()
        matched = False
        if st_norm and st_norm in target_set:
            matched = True
        elif not st_norm and match_unknown:
            matched = True
            st_norm = "(empty)"
        if not matched:
            continue
        sn = env.get("sn", "")
        to_delete.append((p, sn, st or "(empty)"))
        print(f"  [{('DEL' if args.apply else 'WOULD-DEL')}]  station={st or '(empty)':<24}  sn={sn:<32}  {p.relative_to(history_root)}")

    if not to_delete:
        print("\nNo matching records.")
        sys.exit(0)

    print(f"\nMatched {len(to_delete)} record(s).")

    if not args.apply:
        print("Dry-run mode — nothing changed. Re-run with --apply to delete.")
        sys.exit(0)

    if not args.yes:
        ans = input(f"Delete {len(to_delete)} records? [y/N]: ").strip().lower()
        if ans != "y":
            print("Aborted.")
            sys.exit(1)

    # Open SQLite once
    conn = sqlite3.connect(str(config.INDEX_DB_PATH))
    conn.execute("PRAGMA foreign_keys = ON")

    deleted_files = deleted_latest = deleted_pdf = deleted_rows = 0
    for hist_path, sn, _ in to_delete:
        # 1) delete history file
        try:
            hist_path.unlink(missing_ok=True)
            deleted_files += 1
        except OSError as e:
            print(f"  ERROR removing {hist_path}: {e}")
            continue
        # cleanup empty MM-DD/ and YYYY/ dirs
        for parent in (hist_path.parent, hist_path.parent.parent):
            try:
                parent.rmdir()
            except OSError:
                break
        # 2) delete SQLite row(s) for that history_path
        cur = conn.execute("DELETE FROM envelopes WHERE history_path = ?", (str(hist_path),))
        deleted_rows += cur.rowcount
        # 3) delete latest cache (if SN matches)
        if sn:
            lp = latest_dir / f"{sn}.json"
            if lp.exists():
                lp.unlink(missing_ok=True)
                deleted_latest += 1
            # 4) delete pdf cache
            pp = pdf_dir / f"{sn}.pdf"
            if pp.exists():
                pp.unlink(missing_ok=True)
                deleted_pdf += 1

    conn.commit()
    conn.close()

    print(f"\nDone.")
    print(f"  history files removed: {deleted_files}")
    print(f"  latest files removed:  {deleted_latest}")
    print(f"  pdf files removed:     {deleted_pdf}")
    print(f"  SQLite rows removed:   {deleted_rows}")


if __name__ == "__main__":
    main()
