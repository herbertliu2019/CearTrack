import os
import threading
from datetime import date, timedelta

from flask import Blueprint, current_app, jsonify, render_template, request, send_file

from modules.cpu import db
from modules.cpu.scanner import CpuScanner

cpu_bp = Blueprint("cpu", __name__, url_prefix="/cpu",
                   template_folder="templates")


def _db_path() -> str:
    return current_app.config["CPU_DB_PATH"]


def _root_dir() -> str:
    return current_app.config["CPU_ROOT_DIR"]


def _sanitize(records: list[dict]) -> list[dict]:
    """Replace raw image_path with has_image bool for every record."""
    out = []
    for r in records:
        r = dict(r)
        r["has_image"] = bool(r.get("image_path") and os.path.isfile(r["image_path"]))
        r.pop("image_path", None)
        out.append(r)
    return out


# ── Dashboard ──────────────────────────────────────────────────────────────

@cpu_bp.get("/")
def dashboard():
    return render_template("cpu/dashboard.html")


# ── Today ──────────────────────────────────────────────────────────────────

@cpu_bp.get("/api/today")
def api_today():
    records = db.query_today(_db_path())
    return jsonify({
        "records": _sanitize(records),
        "count": len(records),
    })


# ── Stats ──────────────────────────────────────────────────────────────────

@cpu_bp.get("/api/stats")
def api_stats():
    period = request.args.get("period", "week")
    today = date.today()

    if period == "week":
        # Start from this week's Sunday (weekday: Mon=0 ... Sun=6)
        days_since_sunday = (today.weekday() + 1) % 7
        start = str(today - timedelta(days=days_since_sunday))
        end = str(today)
    elif period == "month":
        start = today.replace(day=1).isoformat()
        end = str(today)
    else:  # custom
        start = request.args.get("start", str(today))
        end = request.args.get("end", str(today))

    db_path = _db_path()
    return jsonify({
        "period":          period,
        "start":           start,
        "end":             end,
        "total_all_time":  db.total_all_time(db_path),
        "summary":         db.stats_summary(db_path, start, end),
        "by_series":       db.by_series(db_path, start, end),
        "by_generation":   db.by_generation(db_path, start, end),
        "by_model":        db.by_model(db_path, start, end),
        "by_core_count":   db.by_core_count(db_path, start, end),
        "daily":           db.daily_counts(db_path, start, end),
    })


# ── Records for a specific date (used by Daily Breakdown expand) ───────────

@cpu_bp.get("/api/day/<date_str>")
def api_day(date_str):
    records = db.query_period(_db_path(), date_str, date_str)
    sanitized = _sanitize(records)
    pass_c = sum(1 for r in records if r.get("overall_result") == "Pass")
    fail_c = sum(1 for r in records if r.get("overall_result") == "Fail")
    return jsonify({
        "date":    date_str,
        "records": sanitized,
        "total":   len(records),
        "passed":  pass_c,
        "failed":  fail_c,
    })


# ── All Tests page ─────────────────────────────────────────────────────────

@cpu_bp.get("/all")
def all_tests():
    return render_template("cpu/all_tests.html")


# ── Records (paginated) ─────────────────────────────────────────────────────

@cpu_bp.get("/api/records")
def api_records():
    try:
        offset = max(0, int(request.args.get("offset", 0)))
        limit  = min(200, max(1, int(request.args.get("limit", 50))))
    except ValueError:
        offset, limit = 0, 50
    records, total = db.query_records(_db_path(), offset=offset, limit=limit)
    return jsonify({
        "records": _sanitize(records),
        "total":   total,
        "offset":  offset,
        "limit":   limit,
    })


# ── Search ─────────────────────────────────────────────────────────────────

@cpu_bp.get("/api/search")
def api_search():
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify({"error": "q must be at least 2 characters"}), 400
    results = db.query_by_sn(_db_path(), q)
    return jsonify({
        "query": q,
        "count": len(results),
        "results": _sanitize(results),
    })


# ── Scan trigger ───────────────────────────────────────────────────────────

SCAN_THREAD = "cpu-scan"


@cpu_bp.post("/api/scan")
def api_scan():
    """Trigger incremental scan (default) or full scan (?full=1).

    Incremental: only re-scans top-level subdirs whose mtime changed.
    Full: scans all log files (use after first deployment or data migration).
    """
    db_path = _db_path()
    status = db.get_scan_status(db_path)

    if status.get("status") == "running":
        thread_alive = any(
            t.name == SCAN_THREAD and t.is_alive()
            for t in threading.enumerate()
        )
        if thread_alive:
            return jsonify({
                "status": "already_running",
                "done": status.get("done", 0),
                "total": status.get("total", 0),
            }), 409
        db.set_scan_status(db_path, status="idle")

    root_dir = _root_dir()
    full = request.args.get("full", "0") == "1"

    def _run():
        scanner = CpuScanner(root_dir=root_dir, db_path=db_path)
        if full:
            scanner.run_full()
        else:
            scanner.run_incremental()

    threading.Thread(target=_run, daemon=True, name=SCAN_THREAD).start()
    return jsonify({"status": "started", "mode": "full" if full else "incremental"})


# ── Scan status ────────────────────────────────────────────────────────────

@cpu_bp.get("/api/scan/status")
def api_scan_status():
    return jsonify(db.get_scan_status(_db_path()))


# ── Auto-poll status ────────────────────────────────────────────────────────

@cpu_bp.get("/api/poll/status")
def api_poll_status():
    from modules.cpu.scheduler import get_poll_state
    return jsonify(get_poll_state())


# ── Image ──────────────────────────────────────────────────────────────────

@cpu_bp.get("/api/image/<int:record_id>")
def api_image(record_id):
    conn = db.get_conn(_db_path())
    try:
        row = conn.execute(
            "SELECT sn, image_path FROM cpu_records WHERE id = ?", (record_id,)
        ).fetchone()
    finally:
        conn.close()

    if not row or not row["image_path"]:
        return "", 404
    path = row["image_path"]
    if not os.path.isfile(path):
        return "", 404
    if request.args.get("download") == "1":
        # Force browser download with SN-based filename
        ext = os.path.splitext(path)[1] or ".png"
        name = (row["sn"] or str(record_id)) + ext
        return send_file(path, as_attachment=True, download_name=name, max_age=0)
    return send_file(path, max_age=86400)
