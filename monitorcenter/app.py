"""Monitorcenter Flask entrypoint."""

import threading
from datetime import datetime, timedelta

from flask import Flask, jsonify, render_template, request

import config
from core.module_registry import register_modules
from core import storage, index_db

app = Flask(
    __name__,
    static_url_path='/laptop/static',
    static_folder=str(config.STATIC_DIR),
    template_folder=str(config.TEMPLATE_DIR),
)

MODULES = register_modules(app)


def _extract_sns_for_module(module_name: str, envelope: dict) -> list[dict]:
    inst = MODULES.get(module_name)
    if inst is not None and hasattr(inst, "extract_searchable_sns"):
        return inst.extract_searchable_sns(envelope)
    return [{"sn": envelope.get("sn", ""), "kind": "system"}]


index_db.init_schema()
if index_db.count() == 0:
    n = index_db.rebuild_all(_extract_sns_for_module)
    if n:
        print(f"[OK] Rebuilt SN index from {n} history envelope(s)")


# Startup sweep: drop anything in <module>/latest/ that isn't from today.
_startup_purged = {m: storage.purge_stale_latest(m) for m in MODULES}
_n = sum(_startup_purged.values())
if _n:
    print(f"[OK] Purged {_n} stale latest/ file(s) on startup: {_startup_purged}")


def _midnight_sweeper():
    """Background daemon: sleep until next local midnight, purge, repeat."""
    while True:
        now = datetime.now()
        # 00:00:05 to make sure we're past midnight and mtime-date comparison settles.
        nxt = (now + timedelta(days=1)).replace(hour=0, minute=0, second=5, microsecond=0)
        threading.Event().wait((nxt - now).total_seconds())
        try:
            counts = {m: storage.purge_stale_latest(m) for m in MODULES}
            n = sum(counts.values())
            if n:
                print(f"[OK] Midnight sweep purged {n} latest/ file(s): {counts}")
        except Exception as e:
            print(f"Midnight sweep error: {e}")


threading.Thread(target=_midnight_sweeper, name="latest-midnight-sweeper", daemon=True).start()


@app.route("/")
def index():
    return render_template("index.html", modules=list(MODULES.keys()))


@app.route("/search")
def search():
    """Cross-module SN search — returns {sn, count, results} envelope."""
    sn = (request.args.get("sn") or "").strip()
    results: list[dict] = []
    if sn:
        for m in MODULES:
            try:
                results.extend(storage.search_sn(m, sn))
            except Exception as e:
                print(f"Search error for {m}: {e}")
    results.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return jsonify({"sn": sn, "count": len(results), "results": results})


def _search_wipe_sqlite(sn: str) -> list[dict]:
    """Search wipe SQLite DB by drive_sn or system_sn. Skips silently if DB not found."""
    import sqlite3
    from pathlib import Path
    db_path_str = app.config.get("WIPE_DB")
    if not db_path_str:
        return []
    db_path = Path(db_path_str)
    if not db_path.exists():
        return []
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        pattern = f"%{sn.upper()}%"
        rows = conn.execute(
            "SELECT * FROM wipe_records "
            "WHERE UPPER(drive_sn) LIKE ? OR UPPER(system_sn) LIKE ? "
            "ORDER BY wipe_datetime DESC",
            (pattern, pattern),
        ).fetchall()
        conn.close()
        results = []
        for row in rows:
            r = dict(row)
            raw_result = (r.get("result") or "").upper()
            overall = "PASS" if raw_result == "PASSED" else ("FAIL" if raw_result == "FAILED" else raw_result)
            parts = [r.get("drive_model") or "—"]
            if r.get("capacity"):
                parts.append(r["capacity"])
            if r.get("health_score") is not None:
                parts.append(f"Health {r['health_score']}%")
            if r.get("grade"):
                parts.append(f"Grade {r['grade']}")
            results.append({
                "module":         "wipe",
                "sn":             r.get("drive_sn", sn),
                "system_sn":      r.get("system_sn", ""),
                "timestamp":      r.get("wipe_datetime") or r.get("wipe_date", ""),
                "overall_result": overall,
                "summary":        " | ".join(parts),
                "payload":        r,
            })
        return results
    except Exception as e:
        print(f"Wipe SQLite search error: {e}")
        return []


def _search_cpu_sqlite(sn: str) -> list[dict]:
    """Search CPU SQLite DB by SN (partial match). Skips silently if DB not found."""
    import sqlite3
    from pathlib import Path
    db_path_str = app.config.get("CPU_DB_PATH")
    if not db_path_str:
        return []
    db_path = Path(db_path_str)
    if not db_path.exists():
        return []
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        pattern = f"%{sn.upper()}%"
        rows = conn.execute(
            "SELECT * FROM cpu_records "
            "WHERE UPPER(sn) LIKE ? "
            "ORDER BY test_date DESC, start_time DESC",
            (pattern,),
        ).fetchall()
        conn.close()
        results = []
        for row in rows:
            r = dict(row)
            raw = (r.get("overall_result") or "").upper()
            overall = "PASS" if raw == "PASS" else ("FAIL" if raw == "FAIL" else (raw or "UNKNOWN"))
            cpu_name = r.get("cpu_full_name") or r.get("cpu_model") or "—"
            parts = [cpu_name]
            if r.get("speed_ghz"):
                parts.append(f"{r['speed_ghz']} GHz")
            if r.get("physical_cores"):
                parts.append(f"{r['physical_cores']}C/{r.get('logical_cores', '?')}T")
            timestamp = r.get("start_time") or r.get("test_date", "")
            results.append({
                "module":         "cpu",
                "sn":             r.get("sn", sn),
                "system_sn":      r.get("sn", ""),
                "timestamp":      timestamp,
                "overall_result": overall,
                "summary":        " | ".join(parts),
                "payload":        r,
            })
        return results
    except Exception as e:
        print(f"CPU SQLite search error: {e}")
        return []


@app.route("/api/search")
def api_search():
    """Cross-module SN search — returns a flat list of envelopes.

    Used by the landing-page global search. Individual module failures
    are logged and skipped so one broken module cannot break search.
    """
    sn = (request.args.get("sn") or "").strip()
    if not sn:
        return jsonify({"error": "sn parameter required"}), 400

    results: list[dict] = []
    for m in MODULES:
        try:
            results.extend(storage.search_sn(m, sn))
        except Exception as e:
            print(f"Search error for {m}: {e}")

    # Wipe uses SQLite instead of JSON files — query separately
    results.extend(_search_wipe_sqlite(sn))

    # CPU also uses SQLite — query separately
    results.extend(_search_cpu_sqlite(sn))

    results.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return jsonify(results)


@app.route("/api/summary")
def api_summary():
    """Homepage summary — today/week/month counts for all modules."""
    from datetime import timedelta, date
    import calendar, sqlite3
    from pathlib import Path

    today = date.today()
    days_since_sunday = (today.weekday() + 1) % 7
    week_start  = today - timedelta(days=days_since_sunday)
    week_end    = week_start + timedelta(days=6)
    month_start = today.replace(day=1)
    month_end   = today.replace(day=calendar.monthrange(today.year, today.month)[1])

    out = {}

    # ── Laptop (JSON history files) ──────────────────────────────────
    try:
        laptop_today = len(storage.read_latest("laptop"))
        base = config.BASE_DIR / "laptop" / "history"

        def _count(d_from, d_to):
            n, cur = 0, d_from
            while cur <= d_to:
                day_dir = base / cur.strftime("%Y") / cur.strftime("%m-%d")
                if day_dir.exists():
                    n += sum(1 for _ in day_dir.glob("*.json"))
                cur += timedelta(days=1)
            return n

        out["laptop"] = {
            "today": laptop_today,
            "week":  _count(week_start, week_end),
            "month": _count(month_start, month_end),
        }
    except Exception:
        out["laptop"] = {"today": 0, "week": 0, "month": 0}

    # ── Wipe (SQLite) ────────────────────────────────────────────────
    try:
        wp = app.config.get("WIPE_DB")
        if wp and Path(wp).exists():
            c = sqlite3.connect(wp)
            out["wipe"] = {
                "today": c.execute("SELECT COUNT(*) FROM wipe_records WHERE wipe_date=?", (str(today),)).fetchone()[0],
                "week":  c.execute("SELECT COUNT(*) FROM wipe_records WHERE wipe_date BETWEEN ? AND ?", (str(week_start), str(week_end))).fetchone()[0],
                "month": c.execute("SELECT COUNT(*) FROM wipe_records WHERE wipe_date BETWEEN ? AND ?", (str(month_start), str(month_end))).fetchone()[0],
            }
            c.close()
        else:
            out["wipe"] = {"today": 0, "week": 0, "month": 0}
    except Exception:
        out["wipe"] = {"today": 0, "week": 0, "month": 0}

    # ── CPU (SQLite) ─────────────────────────────────────────────────
    try:
        cp = app.config.get("CPU_DB_PATH")
        if cp and Path(cp).exists():
            c = sqlite3.connect(cp)
            out["cpu"] = {
                "today": c.execute("SELECT COUNT(*) FROM cpu_records WHERE test_date=?", (str(today),)).fetchone()[0],
                "week":  c.execute("SELECT COUNT(*) FROM cpu_records WHERE test_date BETWEEN ? AND ?", (str(week_start), str(week_end))).fetchone()[0],
                "month": c.execute("SELECT COUNT(*) FROM cpu_records WHERE test_date BETWEEN ? AND ?", (str(month_start), str(month_end))).fetchone()[0],
            }
            c.close()
        else:
            out["cpu"] = {"today": 0, "week": 0, "month": 0}
    except Exception:
        out["cpu"] = {"today": 0, "week": 0, "month": 0}

    # ── GPU (JSON history files) ─────────────────────────────────────
    try:
        gpu_today = len(storage.read_latest("gpu"))
        gpu_base = config.BASE_DIR / "gpu" / "history"

        def _count_gpu(d_from, d_to):
            n, cur = 0, d_from
            while cur <= d_to:
                day_dir = gpu_base / cur.strftime("%Y") / cur.strftime("%m-%d")
                if day_dir.exists():
                    n += sum(1 for _ in day_dir.glob("*.json"))
                cur += timedelta(days=1)
            return n

        out["gpu"] = {
            "today": gpu_today,
            "week":  _count_gpu(week_start, week_end),
            "month": _count_gpu(month_start, month_end),
        }
    except Exception:
        out["gpu"] = {"today": 0, "week": 0, "month": 0}

    return jsonify(out)


@app.route("/api/admin/rebuild_index", methods=["POST"])
def admin_rebuild_index():
    """Manual full rebuild of the SQLite index from history files."""
    n = index_db.rebuild_all(_extract_sns_for_module)
    return jsonify({"rebuilt": n, "total": index_db.count()})


from modules.wipe.integration import register_wipe_module
register_wipe_module(app)

from modules.cpu.integration import register_cpu_module
register_cpu_module(app)

if __name__ == "__main__":
    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG)
