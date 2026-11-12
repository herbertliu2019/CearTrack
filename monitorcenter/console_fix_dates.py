"""One-off: imported Outbound records got the import time as tested_at (Outbound has no date column).
Replace it with the date encoded in the Traveler ID (TZZ<YYMMDD>-nnnnnn), time 12:00:00.
Dry-run by default; add --apply to update.
  python3 console_fix_dates.py [--db /opt/monitorcenter/console/console.db] [--apply]
"""
import argparse, os, re, sqlite3, sys
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ap = argparse.ArgumentParser(); ap.add_argument("--db"); ap.add_argument("--apply", action="store_true")
a = ap.parse_args()
if not a.db:
    import config; a.db = str(config.CONSOLE_DB_PATH)
conn = sqlite3.connect(a.db, timeout=30)
rows = conn.execute(
    "SELECT t.id, t.traveler_id, t.tested_at FROM console_tests t "
    "JOIN console_audit_log l ON l.test_id=t.id AND l.action='test_imported' "
    "WHERE l.detail LIKE '%\"outbound\"%'").fetchall()
changed = skipped = 0
for i, tid, old in rows:
    m = re.match(r"^TZZ(\d{2})(\d{2})(\d{2})-", tid or "")
    try:
        new = datetime(2000 + int(m[1]), int(m[2]), int(m[3]), 12).isoformat() if m else None
    except ValueError:
        new = None
    if not new:
        skipped += 1; continue
    changed += 1
    if a.apply:
        conn.execute("UPDATE console_tests SET tested_at=? WHERE id=?", (new, i))
    if changed <= 3:
        print(f"  {tid}: {old} -> {new}")
if a.apply: conn.commit()
print(f"{len(rows)} outbound-imported records; {changed} {'updated' if a.apply else 'would be updated'}; {skipped} skipped (no date in Traveler ID)")
