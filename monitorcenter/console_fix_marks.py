"""One-off: strip the wrongly stamped import date from imported records' marks.

Imported rows without a Cyclelution Mark got "<method> on <import date>" (e.g. "Factory Reset on 11/06/26").
Dry-run by default; add --apply to update.
  python3 console_fix_marks.py [--db /opt/monitorcenter/console/console.db] [--apply]
"""
import argparse, re, sqlite3, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ap = argparse.ArgumentParser(); ap.add_argument("--db"); ap.add_argument("--apply", action="store_true")
a = ap.parse_args()
if not a.db:
    import config; a.db = str(config.CONSOLE_DB_PATH)
conn = sqlite3.connect(a.db, timeout=30)
rows = conn.execute("SELECT id, marks, sanitize_result FROM console_tests WHERE tested_by='Cyclelution import' "
                    "AND notes IS NULL AND marks LIKE '% on __/__/__%'").fetchall()
n = 0
for i, marks, res in rows:
    new = re.sub(r" on \d\d/\d\d/\d\d", "", marks)
    new = new.replace(", data sanitization failed", " - failed")
    if new != marks:
        n += 1
        if a.apply:
            conn.execute("UPDATE console_tests SET marks=? WHERE id=?", (new, i))
print(f"{n} records {'updated' if a.apply else 'would be updated'}; e.g. {rows[0][1]!r} -> {re.sub(r' on \d\d/\d\d/\d\d','',rows[0][1])!r}" if rows else "nothing to fix")
if a.apply: conn.commit()
