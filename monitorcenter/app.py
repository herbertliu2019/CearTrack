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
        print(f"\u2713 Rebuilt SN index from {n} history envelope(s)")


# Startup sweep: drop anything in <module>/latest/ that isn't from today.
_startup_purged = {m: storage.purge_stale_latest(m) for m in MODULES}
_n = sum(_startup_purged.values())
if _n:
    print(f"\u2713 Purged {_n} stale latest/ file(s) on startup: {_startup_purged}")


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
                print(f"\u2713 Midnight sweep purged {n} latest/ file(s): {counts}")
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

    results.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return jsonify(results)


@app.route("/api/admin/rebuild_index", methods=["POST"])
def admin_rebuild_index():
    """Manual full rebuild of the SQLite index from history files."""
    n = index_db.rebuild_all(_extract_sns_for_module)
    return jsonify({"rebuilt": n, "total": index_db.count()})


from modules.wipe.integration import register_wipe_module
register_wipe_module(app)

if __name__ == "__main__":
    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG)
