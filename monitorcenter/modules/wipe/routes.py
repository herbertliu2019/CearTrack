import threading
from datetime import date, timedelta

from flask import Blueprint, current_app, jsonify, render_template, request

from modules.wipe.db import (
    get_conn, get_scan_status, upsert_scan_status,
    query_by_sn, query_period, query_today,
    stats_summary, by_manufacturer, fail_reasons, by_device_type,
)
from modules.wipe.scanner import WipeScanner
from modules.wipe.scheduler import get_poll_state

wipe_bp = Blueprint("wipe", __name__, url_prefix="/wipe",
                    template_folder="templates")


def _db_path() -> str:
    return current_app.config["WIPE_DB"]


@wipe_bp.get("/")
def dashboard():
    return render_template("wipe/dashboard.html")


@wipe_bp.get("/api/today")
def api_today():
    conn = get_conn(_db_path())
    records = query_today(conn)
    conn.close()
    return jsonify({
        "stats": stats_summary(records),
        "by_device_type": by_device_type(records),
        "records": records,
    })


@wipe_bp.get("/api/stats")
def api_stats():
    period = request.args.get("period", "week")
    today = date.today()

    if period == "week":
        # Week: Sunday–Saturday  (weekday(): Mon=0 … Sun=6)
        days_since_sunday = (today.weekday() + 1) % 7
        week_start = today - timedelta(days=days_since_sunday)
        week_end   = week_start + timedelta(days=6)
        start = str(week_start)
        end   = str(week_end)
    elif period == "month":
        import calendar
        month_start = today.replace(day=1)
        last_day    = calendar.monthrange(today.year, today.month)[1]
        month_end   = today.replace(day=last_day)
        start = month_start.isoformat()
        end   = month_end.isoformat()
    else:  # custom
        start = request.args.get("start", str(today))
        end = request.args.get("end", str(today))

    conn = get_conn(_db_path())
    records = query_period(conn, start, end)
    conn.close()

    # daily breakdown
    daily_map: dict[str, dict] = {}
    for r in records:
        d = r.get("wipe_date") or "unknown"
        if d not in daily_map:
            daily_map[d] = {"date": d, "total": 0, "passed": 0, "failed": 0}
        daily_map[d]["total"] += 1
        if r.get("result") == "PASSED":
            daily_map[d]["passed"] += 1
        elif r.get("result") == "FAILED":
            daily_map[d]["failed"] += 1
    daily = sorted(daily_map.values(), key=lambda x: x["date"])

    return jsonify({
        "period": period,
        "start": start,
        "end": end,
        "stats": stats_summary(records),
        "daily": daily,
        "by_device_type": by_device_type(records),
        "by_manufacturer": by_manufacturer(records),
        "fail_reasons": fail_reasons(records),
        "records": records,
    })


@wipe_bp.get("/api/search")
def api_search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "q is required"}), 400
    conn = get_conn(_db_path())
    results = query_by_sn(conn, q)
    conn.close()
    return jsonify({"query": q, "count": len(results), "results": results})


@wipe_bp.post("/api/scan")
def api_scan():
    db_path = _db_path()
    conn = get_conn(db_path)
    status = get_scan_status(conn)

    if status["running"]:
        # Check whether the scan thread is actually still alive.
        # If the server restarted or the thread crashed, running=1 stays
        # stuck in the DB forever and blocks every future scan.
        thread_alive = any(
            t.name == "wipe-full-scan" and t.is_alive()
            for t in threading.enumerate()
        )
        if thread_alive:
            conn.close()
            return jsonify({"status": "already_running",
                            "done": status.get("done", 0),
                            "total": status.get("total", 0)})
        # Thread is gone but flag is stuck — reset it before starting a new scan
        upsert_scan_status(conn, running=0)

    conn.close()
    cfg = current_app.config["WIPE_CFG"]
    scanner = WipeScanner(cfg["log_root"], db_path, cfg["win_share_root"])

    force = request.args.get("force", "0") == "1"

    def _run():
        if force:
            scanner.run_force()
        else:
            scanner.run_full()

    threading.Thread(target=_run, daemon=True, name="wipe-full-scan").start()
    return jsonify({"status": "started", "force": force})


@wipe_bp.get("/api/scan/status")
def api_scan_status():
    conn = get_conn(_db_path())
    db_status = get_scan_status(conn)
    conn.close()
    return jsonify({**db_status, **get_poll_state()})
