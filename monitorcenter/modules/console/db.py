"""SQLite storage for the console (game console test entry + QC) module.

Concurrency pattern follows modules/wipe/db.py: WAL set once at init,
30s connect timeout + busy_timeout on every connection.

Note: CearTrack currently has no auth layer / shared audit_log, so this
module keeps its own `console_audit_log` table and records the operator
name typed on the entry form (tested_by / qc_by are plain TEXT).
"""

import json
import sqlite3
from datetime import datetime

_SCHEMA = """
CREATE TABLE IF NOT EXISTS console_models (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  manufacturer TEXT NOT NULL,
  model        TEXT NOT NULL,
  storage_kind TEXT NOT NULL DEFAULT 'none',
  has_data     INTEGER NOT NULL DEFAULT 1,
  active       INTEGER NOT NULL DEFAULT 1,
  UNIQUE(manufacturer, model)
);

CREATE TABLE IF NOT EXISTS console_check_items (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  code         TEXT NOT NULL UNIQUE,
  label        TEXT NOT NULL,
  default_type TEXT NOT NULL DEFAULT 'secondary'
);

CREATE TABLE IF NOT EXISTS console_model_items (
  model_id       INTEGER NOT NULL REFERENCES console_models(id),
  item_id        INTEGER NOT NULL REFERENCES console_check_items(id),
  type           TEXT NOT NULL,
  label_override TEXT,
  sort           INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (model_id, item_id)
);

CREATE TABLE IF NOT EXISTS console_tests (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  traveler_id     TEXT,
  serial_no       TEXT NOT NULL,
  model_id        INTEGER NOT NULL REFERENCES console_models(id),
  color           TEXT,
  cosmetic_flags  TEXT NOT NULL DEFAULT '[]',
  sanitize_method TEXT NOT NULL,
  sanitize_result TEXT NOT NULL,
  sanitize_date   TEXT,
  storage_desc    TEXT,
  hdd_sn          TEXT,
  hdd_traveler_id TEXT,
  wipe_record_id  INTEGER,
  reset_photo     TEXT,
  result          TEXT NOT NULL,
  marks           TEXT NOT NULL,
  notes           TEXT,
  station         TEXT,
  tested_by       TEXT,
  tested_at       TEXT NOT NULL,
  superseded_by   INTEGER
);
CREATE INDEX IF NOT EXISTS idx_ct_traveler ON console_tests(traveler_id);
CREATE INDEX IF NOT EXISTS idx_ct_serial   ON console_tests(serial_no);
CREATE INDEX IF NOT EXISTS idx_ct_tested   ON console_tests(tested_at);

CREATE TABLE IF NOT EXISTS console_test_items (
  test_id INTEGER NOT NULL REFERENCES console_tests(id) ON DELETE CASCADE,
  item_id INTEGER NOT NULL REFERENCES console_check_items(id),
  type    TEXT NOT NULL,
  label   TEXT NOT NULL,
  status  TEXT NOT NULL,
  PRIMARY KEY (test_id, item_id)
);

CREATE TABLE IF NOT EXISTS console_qc (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  test_id    INTEGER NOT NULL UNIQUE REFERENCES console_tests(id),
  sampled_on TEXT NOT NULL,
  status     TEXT NOT NULL DEFAULT 'Pending',
  note       TEXT,
  qc_by      TEXT,
  qc_at      TEXT
);

CREATE TABLE IF NOT EXISTS console_audit_log (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  ts        TEXT NOT NULL,
  module    TEXT NOT NULL DEFAULT 'console',
  actor     TEXT,
  action    TEXT NOT NULL,
  test_id   INTEGER,
  sn        TEXT,
  detail    TEXT
);
CREATE INDEX IF NOT EXISTS idx_ca_sn   ON console_audit_log(sn);
CREATE INDEX IF NOT EXISTS idx_ca_test ON console_audit_log(test_id);
"""

# code, label, default_type — labels follow SOP 8.6.2.3-OP / the inspection tool wording
_ITEMS = [
    ("power",             "Power Port",                   "key"),
    ("video",             "Video Port",                   "key"),
    ("hdd_slot",          "Hard Drive / Hard Drive Slot", "key"),
    ("cartridge_optical", "Cartridge / Optical Drive",    "key"),
    ("sd_slot",           "SD Card Slot",                 "key"),
    ("screen",            "Screen",                       "key"),
    ("controller",        "Controller Ports",             "key"),
    ("memory_port",       "Memory Ports",                 "key"),
    ("accessory",         "Accessory Ports",              "key"),
    ("wifi",              "Wi-Fi Network",                "key"),
    ("usb",               "USB Ports",                    "secondary"),
    ("expansion",         "Expansion Slot",               "secondary"),
    ("headphone",         "Headphone Jack",               "secondary"),
    ("ethernet",          "Ethernet Port",                "secondary"),
    ("sensor_bar",        "Sensor bar",                   "key"),
]

# SOP item list, in SOP order. Entry always shows all of these; model config only sets defaults.
SOP_CODES = ["power", "video", "hdd_slot", "cartridge_optical", "sd_slot", "screen", "controller",
             "memory_port", "accessory", "wifi", "usb", "expansion", "headphone", "ethernet"]

# (manufacturer, model, storage_kind, has_data, [codes], {code: (type, label_override)})
# Starting point only — admin adjusts via /console/admin/models.
_MODELS = [
    ("Sony", "PlayStation 3", "removable", 1,
     ["power", "video", "cartridge_optical", "hdd_slot", "controller", "usb", "ethernet"], {}),
    ("Sony", "PlayStation 4", "removable", 1,
     ["power", "video", "cartridge_optical", "hdd_slot", "controller", "usb", "wifi", "ethernet"], {}),
    ("Sony", "PlayStation 4 Pro", "removable", 1,
     ["power", "video", "cartridge_optical", "hdd_slot", "controller", "usb", "wifi", "ethernet"], {}),
    ("Sony", "PlayStation 5", "fixed", 1,
     ["power", "video", "cartridge_optical", "controller", "usb", "wifi", "ethernet"], {}),
    ("Microsoft", "Xbox 360", "removable", 1,
     ["power", "video", "cartridge_optical", "hdd_slot", "controller", "memory_port", "usb", "ethernet"], {}),
    ("Microsoft", "Xbox One", "fixed", 1,
     ["power", "video", "cartridge_optical", "controller", "usb", "wifi", "ethernet"], {}),
    ("Microsoft", "Xbox One S/X", "fixed", 1,
     ["power", "video", "cartridge_optical", "controller", "usb", "wifi", "ethernet"], {}),
    ("Microsoft", "Xbox Series S/X", "fixed", 1,
     ["power", "video", "cartridge_optical", "controller", "usb", "expansion", "wifi", "ethernet"],
     {"cartridge_optical": ("secondary", "Cartridge / Optical Drive (Series X only)")}),
    ("Microsoft", "Original Xbox", "fixed", 1,
     ["power", "video", "cartridge_optical", "controller", "memory_port", "ethernet"], {}),
    ("Nintendo", "Wii", "fixed", 1,
     ["power", "video", "cartridge_optical", "controller", "memory_port", "sensor_bar", "accessory"], {}),
    ("Nintendo", "Wii U", "fixed", 1,
     ["power", "video", "cartridge_optical", "controller", "sd_slot", "usb", "sensor_bar", "wifi"], {}),
    ("Nintendo", "Switch", "fixed", 1,
     ["power", "screen", "cartridge_optical", "sd_slot", "controller", "headphone", "accessory"],
     {"power": ("key", "Power Port (USB-C)")}),
    ("Nintendo", "Switch Lite", "fixed", 1,
     ["power", "screen", "cartridge_optical", "sd_slot", "controller", "headphone"],
     {"power": ("key", "Power Port (USB-C)")}),
]

_initialized: set[str] = set()


def get_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: str) -> None:
    if db_path in _initialized:
        return
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)
        _migrate(conn)
        _seed(conn)
        conn.commit()
    finally:
        conn.close()
    _initialized.add(db_path)


_NEW_TEST_COLS = [
    ("weight", "REAL"), ("grade", "TEXT"), ("condition", "TEXT"), ("functionality", "TEXT"),
    ("storage_size", "TEXT"), ("storage_type", "TEXT"), ("cd_dvd", "TEXT"), ("part_no", "TEXT"),
    # external (API) uploads from other test tools
    ("source", "TEXT DEFAULT 'manual'"), ("ext_sha256", "TEXT"), ("ext_json_path", "TEXT"),
    ("ext_pdf_path", "TEXT"), ("ext_result", "TEXT"),
]


_SOP_KEY_CODES = ["wifi", "memory_port", "sd_slot", "hdd_slot", "sensor_bar"]


def _migrate(conn: sqlite3.Connection) -> None:
    have = {r[1] for r in conn.execute("PRAGMA table_info(console_tests)")}
    for col, typ in _NEW_TEST_COLS:
        if col not in have:
            conn.execute(f'ALTER TABLE console_tests ADD COLUMN "{col}" {typ}')
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ct_extsha ON console_tests(ext_sha256)")
    # v1: align check-item types with SOP 8.6.2.3-OP (these are Key functions). Runs once.
    if conn.execute("PRAGMA user_version").fetchone()[0] < 1:
        q = ",".join("?" * len(_SOP_KEY_CODES))
        conn.execute(f"UPDATE console_check_items SET default_type='key' WHERE code IN ({q})", _SOP_KEY_CODES)
        conn.execute(
            "UPDATE console_model_items SET type='key' WHERE type='secondary' AND item_id IN "
            f"(SELECT id FROM console_check_items WHERE code IN ({q}))", _SOP_KEY_CODES)
        conn.execute("PRAGMA user_version = 1")
    # v2: SOP item list — merge disc/cartridge into cartridge_optical, SOP labels, accessory = key.
    if conn.execute("PRAGMA user_version").fetchone()[0] < 2:
        _migrate_v2(conn)
        conn.execute("PRAGMA user_version = 2")


_SOP_LABELS = {code: label for code, label, _ in _ITEMS}
_SEED_OVERRIDES = {"Power (USB-C)": "Power Port (USB-C)",
                   "Disc drive (Series X only)": "Cartridge / Optical Drive (Series X only)"}


def _migrate_v2(conn: sqlite3.Connection) -> None:
    ids = {r[0]: r[1] for r in conn.execute("SELECT code, id FROM console_check_items")}
    target = ids.get("disc") or ids.get("cartridge_optical") or ids.get("cartridge")
    if target:
        for code in ("cartridge_optical", "cartridge", "disc"):
            old = ids.get(code)
            if not old or old == target:
                continue
            conn.execute("UPDATE OR IGNORE console_model_items SET item_id=? WHERE item_id=?", (target, old))
            conn.execute("DELETE FROM console_model_items WHERE item_id=?", (old,))   # model had both
            conn.execute("UPDATE OR IGNORE console_test_items SET item_id=? WHERE item_id=?", (target, old))
            if not conn.execute("SELECT 1 FROM console_test_items WHERE item_id=? LIMIT 1", (old,)).fetchone():
                conn.execute("DELETE FROM console_check_items WHERE id=?", (old,))
            else:   # a test recorded both (should not happen) — keep the row, free the code
                conn.execute("UPDATE console_check_items SET code=? WHERE id=?", (f"{code}_old", old))
        conn.execute("UPDATE console_check_items SET code='cartridge_optical' WHERE id=?", (target,))
    for code, label in _SOP_LABELS.items():
        conn.execute("UPDATE console_check_items SET label=? WHERE code=?", (label, code))
    for old_lab, new_lab in _SEED_OVERRIDES.items():
        conn.execute("UPDATE console_model_items SET label_override=? WHERE label_override=?", (new_lab, old_lab))
    conn.execute("UPDATE console_check_items SET default_type='key' WHERE code IN ('accessory','cartridge_optical')")
    conn.execute("UPDATE console_model_items SET type='key' WHERE type='secondary' AND item_id IN "
                 "(SELECT id FROM console_check_items WHERE code='accessory')")


def _seed(conn: sqlite3.Connection) -> None:
    """Seed only into an empty DB so admin edits are never overwritten."""
    if conn.execute("SELECT COUNT(*) FROM console_check_items").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO console_check_items(code,label,default_type) VALUES (?,?,?)", _ITEMS)
    if conn.execute("SELECT COUNT(*) FROM console_models").fetchone()[0] > 0:
        return
    item_ids = {r[0]: (r[1], r[2]) for r in conn.execute(
        "SELECT code,id,default_type FROM console_check_items")}
    for mfr, model, kind, has_data, codes, overrides in _MODELS:
        cur = conn.execute(
            "INSERT INTO console_models(manufacturer,model,storage_kind,has_data) VALUES (?,?,?,?)",
            (mfr, model, kind, has_data))
        mid = cur.lastrowid
        for i, code in enumerate(codes):
            iid, dtype = item_ids[code]
            typ, lab = overrides.get(code, (dtype, None))
            conn.execute(
                "INSERT INTO console_model_items(model_id,item_id,type,label_override,sort) "
                "VALUES (?,?,?,?,?)", (mid, iid, typ, lab, i))


def insert_test(conn: sqlite3.Connection, data: dict, tested_at: str, source: str = "manual",
                ext: dict | None = None) -> int:
    """Insert one console_tests row + its items and supersede earlier live records of the same SN.

    Shared by the manual entry form and the external upload API. Caller commits.
    `ext` (API only): ext_sha256 / ext_json_path / ext_pdf_path / ext_result.
    Returns the new test id; sets data["_superseded"] to the number of replaced records.
    """
    ext = ext or {}
    cur = conn.execute(
        "INSERT INTO console_tests(traveler_id,serial_no,model_id,color,cosmetic_flags,"
        "sanitize_method,sanitize_result,sanitize_date,storage_desc,hdd_sn,hdd_traveler_id,"
        "result,marks,notes,tested_by,tested_at,weight,grade,condition,functionality,"
        "storage_size,storage_type,cd_dvd,part_no,source,ext_sha256,ext_json_path,ext_pdf_path,ext_result) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (data["traveler_id"], data["serial_no"], data["model_id"], data["color"] or None,
         json.dumps(data["cosmetic"], ensure_ascii=False), data["sanitize_method"],
         data["sanitize_result"], data["sanitize_date"] or None,
         data["storage_desc"] or None, data["hdd_sn"] or None,
         data["hdd_traveler_id"] or None, data["result"], data["marks"],
         data["notes"] or None, data["operator"] or None,
         tested_at, data["weight"], data["grade"] or None, data["condition"] or None,
         data["functionality"] or None, data["storage_size"] or None,
         data["storage_type"] or None, data["cd_dvd"] or None, data["part_no"] or None,
         source, ext.get("ext_sha256"), ext.get("ext_json_path"), ext.get("ext_pdf_path"),
         ext.get("ext_result")))
    tid = cur.lastrowid
    conn.executemany(
        "INSERT INTO console_test_items(test_id,item_id,type,label,status) VALUES (?,?,?,?,?)",
        [(tid, i["id"], i["type"], i["label"], i["status"]) for i in data["items"]])
    data["_superseded"] = conn.execute(
        "UPDATE console_tests SET superseded_by=? WHERE id<>? AND superseded_by IS NULL "
        "AND UPPER(serial_no)=UPPER(?)", (tid, tid, data["serial_no"])).rowcount
    return tid


def find_by_ext_sha(conn: sqlite3.Connection, sha: str):
    return conn.execute("SELECT id, serial_no, result, marks FROM console_tests WHERE ext_sha256=? "
                        "ORDER BY id DESC LIMIT 1", (sha,)).fetchone()


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def audit(conn, actor, action, test_id=None, sn=None, detail=None) -> None:
    conn.execute(
        "INSERT INTO console_audit_log(ts,actor,action,test_id,sn,detail) VALUES (?,?,?,?,?,?)",
        (now_iso(), actor or "", action, test_id, sn,
         json.dumps(detail, ensure_ascii=False) if detail is not None else None))


# ── Config reads ────────────────────────────────────────────────────────

def list_models(conn, active_only=True) -> list[dict]:
    q = "SELECT * FROM console_models"
    if active_only:
        q += " WHERE active=1"
    q += " ORDER BY manufacturer, model"
    return [dict(r) for r in conn.execute(q)]


def get_model(conn, model_id) -> dict | None:
    r = conn.execute("SELECT * FROM console_models WHERE id=?", (model_id,)).fetchone()
    return dict(r) if r else None


def model_items(conn, model_id) -> list[dict]:
    """Check items for a model: id, code, type, label (override applied), sort."""
    rows = conn.execute(
        "SELECT i.id, i.code, mi.type, COALESCE(mi.label_override, i.label) AS label, mi.sort "
        "FROM console_model_items mi JOIN console_check_items i ON i.id = mi.item_id "
        "WHERE mi.model_id=? ORDER BY (mi.type='key') DESC, mi.sort, i.id", (model_id,))
    return [dict(r) for r in rows]


GENERIC_CODES = ["power", "video", "cartridge_optical", "controller", "memory_port", "wifi", "hdd_slot", "usb", "ethernet"]


def generic_items(conn) -> list[dict]:
    """Minimal check-item set for a model typed in manually (admin can refine later)."""
    q = ",".join("?" * len(GENERIC_CODES))
    rows = conn.execute(
        f"SELECT id, code, default_type AS type, label FROM console_check_items WHERE code IN ({q})",
        GENERIC_CODES).fetchall()
    order = {c: i for i, c in enumerate(GENERIC_CODES)}
    out = [{**dict(r), "sort": order[r["code"]]} for r in rows]
    return sorted(out, key=lambda x: (x["type"] != "key", x["sort"]))


def entry_items(conn, model_id=None) -> list[dict]:
    """Entry form items: every SOP item + any extra item the model uses, in SOP order.

    Items the model uses (or GENERIC_CODES for a new model) default to Pass with the model's
    type/label; the rest default to N/A with the check item's default type/label.
    """
    used = {it["id"]: it for it in (model_items(conn, model_id) if model_id else generic_items(conn))}
    cat = {r["code"]: dict(r) for r in conn.execute("SELECT * FROM console_check_items")}
    order = {c: i for i, c in enumerate(SOP_CODES)}
    out = []
    for code, ci in cat.items():
        u = used.get(ci["id"])
        if code not in order and not u:
            continue
        out.append({"id": ci["id"], "code": code,
                    "type": u["type"] if u else ci["default_type"],
                    "label": u["label"] if u else ci["label"],
                    "sort": order.get(code, len(order) + (u["sort"] if u else 0)),
                    "default": "Pass" if u else "N/A"})
    return sorted(out, key=lambda x: (x["type"] != "key", x["sort"]))


def find_model(conn, manufacturer, model) -> dict | None:
    r = conn.execute(
        "SELECT * FROM console_models WHERE LOWER(manufacturer)=LOWER(?) AND LOWER(model)=LOWER(?)",
        (manufacturer, model)).fetchone()
    return dict(r) if r else None


def create_model(conn, manufacturer, model, storage_kind, has_data, items=None) -> int:
    """Insert a model with `items` (API: the reported set) or the generic item set. Caller commits."""
    mid = conn.execute(
        "INSERT INTO console_models(manufacturer,model,storage_kind,has_data) VALUES (?,?,?,?)",
        (manufacturer, model, storage_kind, has_data)).lastrowid
    src = [{**it, "sort": i} for i, it in enumerate(items)] if items else generic_items(conn)
    for it in src:
        conn.execute(
            "INSERT INTO console_model_items(model_id,item_id,type,label_override,sort) "
            "VALUES (?,?,?,?,?)", (mid, it["id"], it["type"], it.get("label_override"), it["sort"]))
    return mid


def ensure_check_item(conn, code, label, default_type) -> int:
    """Return the check item id for `code`, creating it if missing. Caller commits."""
    r = conn.execute("SELECT id FROM console_check_items WHERE code=?", (code,)).fetchone()
    if r:
        return r[0]
    return conn.execute("INSERT INTO console_check_items(code,label,default_type) VALUES (?,?,?)",
                        (code, label, default_type)).lastrowid


def all_check_items(conn) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM console_check_items ORDER BY id")]


# ── Test reads ──────────────────────────────────────────────────────────

def active_by_serial(conn, serial_no) -> dict | None:
    r = conn.execute(
        "SELECT t.*, m.manufacturer, m.model FROM console_tests t "
        "JOIN console_models m ON m.id=t.model_id "
        "WHERE UPPER(t.serial_no)=UPPER(?) AND t.superseded_by IS NULL "
        "ORDER BY t.id DESC LIMIT 1", (serial_no,)).fetchone()
    return dict(r) if r else None


def get_test(conn, test_id) -> dict | None:
    r = conn.execute(
        "SELECT t.*, m.manufacturer, m.model, m.storage_kind FROM console_tests t "
        "JOIN console_models m ON m.id=t.model_id WHERE t.id=?", (test_id,)).fetchone()
    return dict(r) if r else None


def test_items(conn, test_id) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM console_test_items WHERE test_id=? ORDER BY (type='key') DESC, item_id",
        (test_id,))]


def query_tests(conn, date_from=None, date_to=None, result=None,
                model_id=None, q=None, include_superseded=False, limit=500) -> list[dict]:
    sql = ("SELECT t.*, m.manufacturer, m.model, c.status AS qc_status "
           "FROM console_tests t JOIN console_models m ON m.id=t.model_id "
           "LEFT JOIN console_qc c ON c.test_id=t.id WHERE 1=1")
    args: list = []
    if not include_superseded:
        sql += " AND t.superseded_by IS NULL"
    if date_from:
        sql += " AND date(t.tested_at) >= ?"; args.append(date_from)
    if date_to:
        sql += " AND date(t.tested_at) <= ?"; args.append(date_to)
    if result:
        sql += " AND t.result = ?"; args.append(result)
    if model_id:
        sql += " AND t.model_id = ?"; args.append(model_id)
    if q:
        sql += " AND (UPPER(t.serial_no) LIKE ? OR UPPER(t.traveler_id) LIKE ? OR UPPER(t.hdd_sn) LIKE ?)"
        p = f"%{q.upper()}%"; args += [p, p, p]
    sql += " ORDER BY t.tested_at DESC, t.id DESC LIMIT ?"
    args.append(limit)
    return [dict(r) for r in conn.execute(sql, args)]


def period_stats(conn, d_from: str, d_to: str) -> dict:
    """Stats for latest test per SN (superseded rows excluded) tested in [d_from, d_to]."""
    from datetime import date, timedelta
    rows = [dict(r) for r in conn.execute(
        "SELECT t.id, date(t.tested_at) AS d, t.result, t.sanitize_method, t.sanitize_result, "
        "m.manufacturer, m.model FROM console_tests t JOIN console_models m ON m.id=t.model_id "
        "WHERE t.superseded_by IS NULL AND date(t.tested_at) BETWEEN ? AND ?", (d_from, d_to))]
    total = len(rows)
    passed = sum(1 for r in rows if r["result"] == "Pass")

    # Daily buckets (every day in range, so empty days show as gaps)
    start, end = date.fromisoformat(d_from), date.fromisoformat(d_to)
    daily = {}
    cur = start
    while cur <= end:
        daily[str(cur)] = {"date": str(cur), "pass": 0, "fail": 0}
        cur += timedelta(days=1)
    by_model: dict = {}
    for r in rows:
        k = "pass" if r["result"] == "Pass" else "fail"
        daily[r["d"]][k] += 1
        m = by_model.setdefault(f"{r['manufacturer']} {r['model']}",
                                {"model": f"{r['manufacturer']} {r['model']}", "pass": 0, "fail": 0})
        m[k] += 1

    # Fail reasons: failed key items, plus sanitize failure / locked units
    reasons: dict = {}
    failed = [r for r in rows if r["result"] != "Pass"]
    for r in failed:
        if r["sanitize_method"] == "Locked":
            reasons["Locked"] = reasons.get("Locked", 0) + 1
        elif r["sanitize_result"] == "Fail":
            reasons["Data sanitization failed"] = reasons.get("Data sanitization failed", 0) + 1
    if failed:
        ids = [r["id"] for r in failed]
        # group by item (current catalog label) so renamed labels don't split the counts
        q = ("SELECT i.label, COUNT(*) AS n FROM console_test_items ti "
             "JOIN console_check_items i ON i.id = ti.item_id "
             "WHERE ti.type='key' AND ti.status='Fail' AND ti.test_id IN (%s) GROUP BY i.id"
             % ",".join("?" * len(ids)))
        for lab, n in conn.execute(q, ids):
            reasons[lab] = reasons.get(lab, 0) + n

    days = len(daily)
    return {
        "start": d_from, "end": d_to,
        "summary": {"total": total, "pass": passed, "fail": total - passed,
                    "pass_rate": round(100 * passed / total, 1) if total else None,
                    "avg_per_day": round(total / days, 1) if days else 0},
        "daily": list(daily.values()),
        "by_model": sorted(by_model.values(), key=lambda x: -(x["pass"] + x["fail"])),
        "fail_reasons": [{"reason": k, "count": v}
                         for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])],
    }


def test_timeline(conn, test) -> list[dict]:
    """Audit entries for this SN (all retests) plus this test id."""
    rows = conn.execute(
        "SELECT * FROM console_audit_log WHERE test_id=? OR UPPER(sn)=UPPER(?) ORDER BY id",
        (test["id"], test["serial_no"]))
    return [dict(r) for r in rows]


def count_unique_sn(db_path, d_from, d_to) -> int:
    conn = get_conn(db_path)
    try:
        return conn.execute(
            "SELECT COUNT(DISTINCT UPPER(serial_no)) FROM console_tests "
            "WHERE date(tested_at) BETWEEN ? AND ?", (d_from, d_to)).fetchone()[0]
    finally:
        conn.close()


def search(db_path, sn) -> list[dict]:
    conn = get_conn(db_path)
    try:
        return query_tests(conn, q=sn, include_superseded=True, limit=100)
    finally:
        conn.close()


# ── QC ──────────────────────────────────────────────────────────────────

def qc_get(conn, test_id) -> dict | None:
    r = conn.execute("SELECT * FROM console_qc WHERE test_id=?", (test_id,)).fetchone()
    return dict(r) if r else None


def qc_upsert(conn, test_id, status, note, who) -> None:
    """One QC result per test, recorded by the QC operator. Re-QC (or resolving a legacy Pending row)
    replaces it; the audit log keeps the history. sampled_on = QC date. Caller commits."""
    now = now_iso()
    conn.execute(
        "INSERT INTO console_qc(test_id,sampled_on,status,note,qc_by,qc_at) VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(test_id) DO UPDATE SET status=excluded.status, note=excluded.note, "
        "qc_by=excluded.qc_by, qc_at=excluded.qc_at",
        (test_id, now[:10], status, note or None, who, now))


def qc_list(conn, d_from=None, d_to=None, status=None, pending_only=False, qc_by=None) -> list[dict]:
    """QC records for the History / Pending views (all statuses, any date)."""
    sql = ("SELECT c.*, t.serial_no, t.traveler_id, t.result AS test_result, t.marks, t.tested_at, "
           "t.tested_by, m.manufacturer, m.model FROM console_qc c "
           "JOIN console_tests t ON t.id=c.test_id JOIN console_models m ON m.id=t.model_id WHERE 1=1")
    args: list = []
    if pending_only:
        sql += " AND c.status='Pending'"
    if d_from:
        sql += " AND c.sampled_on >= ?"; args.append(d_from)
    if d_to:
        sql += " AND c.sampled_on <= ?"; args.append(d_to)
    if status:
        sql += " AND c.status = ?"; args.append(status)
    if qc_by:
        sql += " AND UPPER(c.qc_by) = UPPER(?)"; args.append(qc_by)
    sql += " ORDER BY c.sampled_on DESC, (c.status='Pending') DESC, c.id DESC LIMIT 1000"
    return [dict(r) for r in conn.execute(sql, args)]


def qc_counts(conn, d_from, d_to) -> dict:
    """Totals for sampled_on in range, plus all-time pending."""
    r = conn.execute(
        "SELECT COUNT(*), SUM(status='Passed'), SUM(status='Rejected'), SUM(status='Pending') "
        "FROM console_qc WHERE sampled_on BETWEEN ? AND ?", (d_from, d_to)).fetchone()
    pend = conn.execute("SELECT COUNT(*) FROM console_qc WHERE status='Pending'").fetchone()[0]
    return {"sampled": r[0] or 0, "passed": r[1] or 0, "rejected": r[2] or 0,
            "pending_in_range": r[3] or 0, "pending_all": pend}


def qc_rows(conn, day) -> list[dict]:
    rows = conn.execute(
        "SELECT c.*, t.serial_no, t.traveler_id, t.result AS test_result, t.marks, t.tested_at, "
        "t.tested_by, m.manufacturer, m.model FROM console_qc c "
        "JOIN console_tests t ON t.id=c.test_id JOIN console_models m ON m.id=t.model_id "
        "WHERE c.sampled_on=? OR c.status='Pending' "
        "ORDER BY (c.status='Pending') DESC, c.id", (day,))
    return [dict(r) for r in rows]
