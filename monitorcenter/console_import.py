"""One-off import of Cyclelution Inbound/Outbound Inventory List exports into the console DB.

The .xls files are HTML tables. Outbound rows win over Inbound rows with the same SN.
Rows without SN are imported with a blank SN. SNs already present in console_tests are skipped (never overwritten).

Usage (dry-run by default, nothing is written):
  python console_import.py --inbound "Inbound+Inventory+List.xls" --outbound "Outbound+Inventory+List (2).xls"
  python console_import.py ... --db /opt/monitorcenter/console/console.db --apply
"""
import argparse
import collections
import json
import os
import sys
from datetime import datetime
from html.parser import HTMLParser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from modules.console import db, logic  # noqa: E402

ACTOR = "Cyclelution import"
MFR = {"XBOX": "Microsoft", "MICROSOFT": "Microsoft", "SONY": "Sony", "NINTENDO": "Nintendo"}
# Cyclelution model text (upper) -> existing console_models.model, where names differ.
MODEL_ALIAS = {
    "XBOX SERIES S": "Xbox Series S/X", "XBOX SERIES X": "Xbox Series S/X",
    "XBOX ONE S": "Xbox One S/X", "XBOX ONE X": "Xbox One S/X",
    "PLAYSTATION 4 PRO": "PlayStation 4 Pro", "XBOX ORIGINAL": "Original Xbox",
    "GAMEBOY ADVANCE SP AGS-001": "Game Boy Advance SP AGS-001",
    "DSI XL": "DSi XL", "VCS 2600": "VCS 2600", "AIRPODS 1ST GEN": "AirPods 1st Gen",
}


class _P(HTMLParser):
    def __init__(self):
        super().__init__(); self.rows = []; self.r = None; self.c = None

    def handle_starttag(self, t, a):
        if t == "tr": self.r = []
        if t in ("td", "th"): self.c = ""

    def handle_endtag(self, t):
        if t in ("td", "th") and self.r is not None:
            self.r.append(" ".join(self.c.split())); self.c = None
        if t == "tr" and self.r is not None:
            self.rows.append(self.r); self.r = None

    def handle_data(self, d):
        if self.c is not None: self.c += d


def read_table(path):
    p = _P()
    p.feed(open(path, encoding="utf-8", errors="replace").read())
    rows = [r for r in p.rows if any(r)]
    h = next(r for r in rows if "Serial No." in r)
    first = {}
    for i, name in enumerate(h):
        first.setdefault(name, i)          # duplicate "Model" column: keep the first
    return [{k: (r[i] if i < len(r) else "") for k, i in first.items()}
            for r in rows[rows.index(h) + 1:]]


def sn_key(sn):
    return sn.strip().upper().lstrip("0")


def title_model(m):
    t = m.title()
    for a, b in (("Playstation", "PlayStation"), ("3Ds", "3DS"), ("Dsi", "DSi"), ("Ds ", "DS "), ("Ds", "DS"), ("Nes-", "NES-"), ("Sns-", "SNES-"), ("Super Nes", "Super NES")):
        t = t.replace(a, b)
    return t


def sanitize_map(v):
    """Cyclelution Data Sanitization -> (method, result)."""
    return {
        "Pass": ("Factory Reset", "Pass"),
        "Fail": ("Factory Reset", "Fail"),
        "ND-No Data": ("No data", "N/A"),
        "D-Pre-Sanitization": ("Pre-Sanitization", "Pass"),
    }.get(v, ("No data", "N/A"))


def parse_date(*vals):
    for v in vals:
        for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
            try:
                return datetime.strptime(v, fmt).replace(hour=12).isoformat()
            except (ValueError, TypeError):
                pass
    return db.now_iso()


def traveler_date(tid):
    """Traveler ID like TZZ260211-000076 -> 2026-02-11T12:00:00 (None if not that format)."""
    import re
    m = re.match(r"^TZZ(\d{2})(\d{2})(\d{2})-", tid or "")
    if not m:
        return None
    try:
        return datetime(2000 + int(m[1]), int(m[2]), int(m[3]), 12).isoformat()
    except ValueError:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inbound"); ap.add_argument("--outbound")
    ap.add_argument("--db", default=None); ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if not a.db:
        import config
        a.db = str(config.CONSOLE_DB_PATH)

    merged, src = {}, collections.Counter()
    skipped_nosn = 0
    for path, label in ((a.inbound, "inbound"), (a.outbound, "outbound")):   # outbound last = wins
        if not path:
            continue
        for r in read_table(path):
            if not r.get("Serial No."):
                skipped_nosn += 1
                merged[f"NOSN:{label}:{skipped_nosn}"] = (label, r)   # imported with blank SN
                continue
            merged[sn_key(r["Serial No."])] = (label, r)
    for label, _ in merged.values():
        src[label] += 1

    db.init_db(a.db)
    conn = db.get_conn(a.db)
    models = {(m["manufacturer"].lower(), m["model"].lower()): m for m in db.list_models(conn, False)}
    existing = {r[0] for r in conn.execute("SELECT UPPER(serial_no) FROM console_tests")}
    existing_keys = {sn_key(s) for s in existing if s}
    blank_tids = {r[0] for r in conn.execute(
        "SELECT traveler_id FROM console_tests WHERE serial_no='' AND traveler_id IS NOT NULL")}

    new_models, skipped_exist, plan = collections.Counter(), 0, []
    for key, (label, r) in merged.items():
        if key in existing_keys or (key.startswith("NOSN:") and r["Traveler ID"] in blank_tids):
            skipped_exist += 1; continue
        mfr = MFR.get(r["Manufacturer"].upper(), r["Manufacturer"].title()) or "Unknown"
        mu = r["Model"].upper()
        mname = MODEL_ALIAS.get(mu) or title_model(r["Model"]) or "Unknown"
        m = models.get((mfr.lower(), mname.lower()))
        if not m:
            new_models[f"{mfr} / {mname}"] += 1
        plan.append((label, r, mfr, mname))

    print(f"rows without SN (imported with blank SN, deduped by Traveler ID): {skipped_nosn}")
    print(f"unique SN: {len(merged)}  (inbound-only {src['inbound']}, outbound {src['outbound']})")
    print(f"already in DB, skipped: {skipped_exist}   to import: {len(plan)}")
    print("models to be created:")
    for k, n in sorted(new_models.items()):
        print(f"  {n:4d}  {k}")
    if not a.apply:
        print("\nDRY RUN — nothing written. Add --apply to import.")
        return

    done = 0
    for label, r, mfr, mname in plan:
        m = models.get((mfr.lower(), mname.lower()))
        if m:
            mid = m["id"]
        else:
            mid = db.create_model(conn, mfr, mname, "fixed", 1)
            models[(mfr.lower(), mname.lower())] = {"id": mid, "manufacturer": mfr, "model": mname}
            db.audit(conn, ACTOR, "model_created", None, None, {"model_id": mid, "model": f"{mfr} {mname}"})
        method, s_res = sanitize_map(r["Data Sanitization"])
        grade = r["Grade"].replace("Grade", "").strip()
        result = "Fail" if (s_res == "Fail" or grade in ("D", "F")) else "Pass"
        notes = r["Mark"] or None
        marks = r["Mark"] or method + (" - failed" if s_res == "Fail" else "")
        try:
            weight = float(r["Weight"]) if r["Weight"] else None
        except ValueError:
            weight = None
        tested_at = (parse_date(r.get("Process Date", ""), r.get("Received Date", "")) if (r.get("Process Date") or r.get("Received Date"))
                     else (traveler_date(r["Traveler ID"]) or db.now_iso()))
        size, typ = r["Storage Size"], r["Storage Type"]
        cur = conn.execute(
            "INSERT INTO console_tests(traveler_id,serial_no,model_id,color,cosmetic_flags,"
            "sanitize_method,sanitize_result,sanitize_date,storage_desc,result,marks,notes,tested_by,"
            "tested_at,weight,grade,condition,functionality,storage_size,storage_type,cd_dvd,part_no,"
            "hdd_sn,hdd_traveler_id) VALUES (?,?,?,?,'[]',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (r["Traveler ID"] or None, r["Serial No."], mid, r["Color"] or None, method, s_res,
             None, " ".join(p for p in (size, typ) if p) or None, result, marks, notes, ACTOR,
             tested_at, weight, grade or None, r["Condition"] or None, r["Functionality"] or None,
             size or None, typ or None, r["CD/DVD Drive"] or None, r["Part No."] or None,
             r["HDD SN"] or None, r["HDD TravelerID"] or None))
        db.audit(conn, ACTOR, "test_imported", cur.lastrowid, r["Serial No."], {"source": label})
        done += 1
    conn.commit()
    print(f"\nIMPORTED {done} records.")


if __name__ == "__main__":
    main()
