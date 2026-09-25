import hashlib
import os
from datetime import date, datetime, timedelta

from flask import Blueprint, Response, current_app, jsonify, render_template, request

from modules.mem import db
from modules.mem.parser import parse_file, parse_report, read_report_text
from modules.mem.scanner import MemScanner

mem_bp = Blueprint("mem", __name__, url_prefix="/mem", template_folder="templates")


def _db_path() -> str:
    return current_app.config["MEM_DB_PATH"]


def _cfg() -> dict:
    return current_app.config["MEM_CFG"]


def _resolve_range(period: str, frm: str | None, to: str | None) -> tuple[str, str]:
    today = date.today()
    if period == "week":
        days_since_sunday = (today.weekday() + 1) % 7
        return str(today - timedelta(days=days_since_sunday)), str(today)
    if period == "month":
        return today.replace(day=1).isoformat(), str(today)
    return frm or str(today), to or str(today)


def _period_range():
    period = request.args.get("range", request.args.get("period", "week"))
    start, end = _resolve_range(
        period,
        request.args.get("from", request.args.get("start")),
        request.args.get("to", request.args.get("end")),
    )
    return period, start, end


# ── Dashboard ────────────────────────────────────────────────────────────

@mem_bp.get("/")
def dashboard():
    return render_template("mem/dashboard.html")


# ── Summary (KPIs + distribution widgets) ───────────────────────────────

@mem_bp.get("/api/summary")
def api_summary():
    period, start, end = _period_range()
    db_path = _db_path()
    return jsonify({
        "period": period, "start": start, "end": end,
        "total_all_time": db.total_all_time(db_path),
        "summary": db.stats_summary(db_path, start, end),
        "by_capacity": db.by_capacity(db_path, start, end),
        "by_type": db.by_type(db_path, start, end),
        "by_vendor": db.by_vendor(db_path, start, end),
        "daily": db.daily_counts(db_path, start, end),
    })


# ── DIMMS tab ────────────────────────────────────────────────────────────

@mem_bp.get("/api/modules")
def api_modules():
    try:
        page = max(1, int(request.args.get("page", 1)))
        per_page = min(500, max(1, int(request.args.get("per_page", 50))))
    except ValueError:
        page, per_page = 1, 50

    size_gb = request.args.get("size")
    # "Last Tested" filter — independent of the dashboard Week/Month range; default all time
    last = request.args.get("last", "all")
    last_from = last_to = None
    if last in ("week", "month") or (last == "custom" and request.args.get("last_from")
                                     and request.args.get("last_to")):
        last_from, last_to = _resolve_range(
            last, request.args.get("last_from"), request.args.get("last_to"))
    rows, total = db.query_modules(
        _db_path(),
        status=request.args.get("status") or None,
        ever_err=request.args.get("ever_err") or None,
        size_gb=int(size_gb) if size_gb else None,
        mem_type=request.args.get("type") or None,
        vendor=request.args.get("vendor") or None,
        q=request.args.get("q") or None,
        last_from=last_from, last_to=last_to,
        page=page, per_page=per_page,
    )
    return jsonify({"modules": rows, "total": total, "page": page, "per_page": per_page})


@mem_bp.get("/api/day/<date_str>")
def api_day(date_str):
    rows = db.query_day(_db_path(), date_str)
    return jsonify({
        "date": date_str,
        "records": rows,
        "total": len(rows),
        "passed": sum(1 for r in rows if r["module_status"] == "PASS"),
        "warned": sum(1 for r in rows if r["module_status"] == "WARN"),
        "failed": sum(1 for r in rows if r["module_status"] in ("FAIL", "SUSPECT")),
    })


@mem_bp.get("/api/packageable")
def api_packageable():
    return jsonify(db.packageable_stats(_db_path()))


@mem_bp.get("/api/module/<sn>")
def api_module_detail(sn):
    detail = db.query_module_detail(_db_path(), sn)
    if detail is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(detail)


# ── REPORTS tab ──────────────────────────────────────────────────────────

@mem_bp.get("/api/reports")
def api_reports():
    try:
        page = max(1, int(request.args.get("page", 1)))
        per_page = min(500, max(1, int(request.args.get("per_page", 50))))
    except ValueError:
        page, per_page = 1, 50

    rows, total = db.query_reports(
        _db_path(),
        start=request.args.get("from") or None,
        end=request.args.get("to") or None,
        q=request.args.get("q") or None,
        page=page, per_page=per_page,
    )
    return jsonify({"reports": rows, "total": total, "page": page, "per_page": per_page})


@mem_bp.get("/api/report/<report_uid>")
def api_report_detail(report_uid):
    detail = db.query_report_detail(_db_path(), report_uid)
    if detail is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(detail)


# ── Raw log ──────────────────────────────────────────────────────────────

@mem_bp.get("/raw/<report_uid>")
def raw_report(report_uid):
    detail = db.query_report_detail(_db_path(), report_uid)
    if detail is None:
        return "", 404
    report = detail["report"]
    path = report.get("archived_path") or report.get("source_full_path")
    if not path or not os.path.isfile(path):
        return "", 404
    try:
        text = read_report_text(path)
    except OSError:
        return "", 404

    resp = Response(text, mimetype="text/html; charset=utf-8")
    if request.args.get("download") == "1":
        name = report.get("source_file") or f"{report_uid}.html"
        resp.headers["Content-Disposition"] = f'attachment; filename="{name}"'
    return resp


# ── Upload (client push) ─────────────────────────────────────────────────

_REPORT_EXTS = (".html", ".htm")


def _safe_upload_name(name: str) -> str:
    """Keep the client's filename as-is (spaces, suffix and all); only strip
    path components and control chars so it can't escape the upload dir."""
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in name if ch.isprintable()).strip()
    if name in ("", ".", ".."):
        name = f"upload_{datetime.now():%Y%m%d_%H%M%S}"
    return name


@mem_bp.get("/api/upload/check")
def api_upload_check():
    """Let a client skip sending a file it already pushed:
      curl "$UPLOAD_URL/check?sha256=$(sha256sum f | cut -d' ' -f1)"
    """
    sha = (request.args.get("sha256") or "").strip().lower()
    if len(sha) != 64:
        return jsonify({"error": "sha256 required"}), 400
    prev = db.find_upload(_db_path(), sha)
    return jsonify({"uploaded": bool(prev), **(prev or {})})


@mem_bp.post("/api/upload")
def api_upload():
    """Accept one file pushed by a MemTest86 test rig (.html report, .txt log,
    .bmp screenshot, ...).

    Two request shapes are accepted:
      curl -F "file=@report.html" $UPLOAD_URL
      curl --data-binary @report.html -H "X-Filename: report.html" $UPLOAD_URL

    Every file is saved under upload_root/YYYY-MM-DD/ with its original name.
    Only .html/.htm files that parse as a MemTest86 report are additionally
    fed through MemScanner.process_file() (same path as the SharePoint poller:
    content-hash dedup, status recompute, raw archiving); everything else is
    stored only.
    """
    cfg = _cfg()

    f = request.files.get("file")
    if f is not None and f.filename:
        filename = f.filename
        data = f.read()
    else:
        filename = request.headers.get("X-Filename") or ""
        data = request.get_data()

    if not data:
        return jsonify({"error": "empty upload"}), 400

    max_mb = cfg.get("max_file_mb", 10)
    if max_mb and len(data) > max_mb * 1024 * 1024:
        return jsonify({"error": f"file exceeds max_file_mb ({max_mb}MB)"}), 413

    # Same bytes already uploaded (any name, any day) -> don't store or
    # import again. 200 so a client retry loop treats it as done.
    sha = hashlib.sha256(data).hexdigest()
    prev = db.find_upload(_db_path(), sha)
    if prev:
        return jsonify({"status": "duplicate", "saved_as": prev["saved_as"],
                        "uploaded_at": prev["uploaded_at"]}), 200

    filename = _safe_upload_name(filename)
    upload_root = cfg["upload_root"]
    day_dir = os.path.join(upload_root, date.today().isoformat())
    os.makedirs(day_dir, exist_ok=True)
    dest = os.path.join(day_dir, filename)
    if os.path.exists(dest):
        stem, ext = os.path.splitext(filename)
        dest = os.path.join(day_dir, f"{stem}_{datetime.now():%H%M%S%f}{ext}")
    with open(dest, "wb") as out:
        out.write(data)

    if not db.record_upload(_db_path(), sha, filename, dest, datetime.now().isoformat()):
        # A concurrent request with the same bytes won the insert.
        os.remove(dest)
        prev = db.find_upload(_db_path(), sha) or {}
        return jsonify({"status": "duplicate", "saved_as": prev.get("saved_as"),
                        "uploaded_at": prev.get("uploaded_at")}), 200

    is_report = False
    if os.path.splitext(filename)[1].lower() in _REPORT_EXTS:
        if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
            text = data.decode("utf-16", errors="replace")
        else:
            text = data.decode("utf-8", errors="replace")
        is_report = bool(parse_report(text)["modules"])

    if not is_report:
        return jsonify({"status": "stored", "saved_as": dest}), 200

    # scan_root is overridden so source_dir is recorded relative to upload_root.
    scanner = MemScanner({**cfg, "scan_root": upload_root}, _db_path())
    outcome, affected = scanner.process_file(dest)
    if outcome == "error":
        return jsonify({"error": "failed to import report", "saved_as": dest}), 422

    try:
        record = parse_file(dest)
        uid, parse_ok = record["report_uid"], bool(record["parse_ok"])
    except (OSError, UnicodeDecodeError):
        uid, parse_ok = None, False

    return jsonify({
        "status": outcome,
        "report_uid": uid,
        "parse_ok": parse_ok,
        "modules": affected,
        "saved_as": dest,
    }), 200


# ── Parse issues ─────────────────────────────────────────────────────────

@mem_bp.get("/api/parse_issues")
def api_parse_issues():
    return jsonify(db.parse_issues(_db_path()))
