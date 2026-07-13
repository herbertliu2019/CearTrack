"""Flask blueprint for the Cyclelution export UI (Phase 4).

A single centre page at /cyclelution/ with three views (Ready / Exceptions /
Exported), decoupled from the test modules. It only reads laptop records +
the laptop_sync table and drives the Phase 2/3 engine (scan, export).

Multi-production ready: everything is keyed on `production` (only 'T-Laptop'
today). Auth can later filter the queue by the logged-in operator without
touching the page — the row shape already carries operator_id.
"""

import json
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request, send_from_directory

from . import sync_state, scan as _scan, exporter

blueprint = Blueprint(
    "cyclelution", __name__,
    template_folder="templates",
    url_prefix="/cyclelution",
)

# Productions this export centre serves. Only `active` ones have a wired-up
# data source today (laptop_sync). The others are placeholders so the
# operator sees the roadmap and the UI is ready — when their test module
# ships, add its sync source and flip active to True. No page change needed.
PRODUCTIONS = [
    {"id": "T-Laptop",     "label": "T-Laptop",     "active": True},
    {"id": "T-Desktop",    "label": "T-Desktop",    "active": False},
    {"id": "T-Video Card", "label": "T-Video Card", "active": False},
]


def _is_active(pid: str) -> bool:
    return any(p["id"] == pid and p["active"] for p in PRODUCTIONS)


def _row_display(row: dict) -> dict:
    """Enrich a laptop_sync row with the fields the queue shows, read from
    the record JSON. Missing file -> minimal row so the queue never breaks."""
    hp = row["history_path"]
    base = {
        "history_path": hp,
        "sn": row.get("sn") or "",
        "vendor": "", "model": "", "grade": "", "operator": "",
        "date": "", "note": row.get("sync_note") or "",
        "synced_at": row.get("synced_at") or "",
    }
    try:
        env = json.loads(Path(hp).read_text(encoding="utf-8"))
        pl = env.get("payload", {}) or {}
        base["sn"] = env.get("sn") or base["sn"]
        base["vendor"] = (pl.get("system", {}) or {}).get("vendor", "")
        base["model"] = (pl.get("system", {}) or {}).get("model", "")
        base["grade"] = ((pl.get("manual_input", {}) or {}).get("grade") or "")
        base["operator"] = (pl.get("test_info", {}) or {}).get("operator_id", "") or "—"
        base["date"] = (env.get("timestamp", "") or "")[:10]
    except Exception:
        base["operator"] = base["operator"] or "—"
    return base


@blueprint.route("/")
def dashboard():
    return render_template("cyclelution.html")


@blueprint.route("/api/productions")
def api_productions():
    return jsonify({"productions": PRODUCTIONS})


@blueprint.route("/api/queue")
def api_queue():
    """status=ready -> operator-grouped; exceptions/exported -> flat list.
    Inactive productions have no data source yet -> empty result."""
    status = request.args.get("status", "ready")
    production = request.args.get("production", "T-Laptop")

    if not _is_active(production):
        return jsonify({"groups": [], "records": [], "total": 0})

    if status == "ready":
        rows = [_row_display(r) for r in sync_state.list_by_status("ready")]
        groups: dict[str, list] = {}
        for r in rows:
            r["flags"] = [f for f in (r["note"].split(" | ") if r["note"] else []) if f]
            groups.setdefault(r["operator"], []).append(r)
        out = [
            {"operator": op, "count": len(recs), "records": recs}
            for op, recs in sorted(groups.items())
        ]
        return jsonify({"groups": out, "total": len(rows)})

    if status == "exceptions":
        rows = [_row_display(r) for r in sync_state.list_by_status("pending")]
        rows = [r for r in rows if r["note"]]   # only records with a stuck reason
        return jsonify({"records": rows, "total": len(rows)})

    if status == "exported":
        rows = [_row_display(r) for r in sync_state.list_by_status("synced")]
        for r in rows:
            r["file"] = r["note"].replace("exported: ", "") if r["note"].startswith("exported: ") else ""
        return jsonify({"records": rows, "total": len(rows)})

    if status == "excluded":
        rows = [_row_display(r) for r in sync_state.list_by_status("excluded")]
        for r in rows:
            # note is "excluded: <reason>" or "superseded by a newer test upload"
            r["reason"] = r["note"].replace("excluded: ", "") if r["note"].startswith("excluded: ") else r["note"]
        return jsonify({"records": rows, "total": len(rows)})

    return jsonify({"error": "unknown status"}), 400


@blueprint.route("/api/counts")
def api_counts():
    production = request.args.get("production", "T-Laptop")
    if not _is_active(production):
        return jsonify({"ready": 0, "exceptions": 0, "exported": 0, "excluded": 0})
    c = sync_state.counts()
    return jsonify({
        "ready": c.get("ready", 0),
        "exceptions": c.get("pending", 0),
        "exported": c.get("synced", 0),
        "excluded": c.get("excluded", 0),
    })


@blueprint.route("/api/rescan", methods=["POST"])
def api_rescan():
    data = request.get_json(silent=True) or {}
    production = data.get("production", "T-Laptop")
    if not _is_active(production):
        return jsonify({"scanned": 0, "ready": 0, "pending": 0,
                        "missing_file": 0, "errors": 0})
    summary = _scan.scan_pending()
    return jsonify(summary)


@blueprint.route("/api/export", methods=["POST"])
def api_export():
    data = request.get_json(silent=True) or {}
    paths = data.get("history_paths") or []
    try:
        result = exporter.export_ready(paths)
    except exporter.ExportError as e:
        return jsonify({"error": str(e)}), 400
    fname = Path(result["file"]).name
    result["download_url"] = f"/cyclelution/api/download/{fname}"
    return jsonify(result)


@blueprint.route("/api/download/<path:filename>")
def api_download(filename):
    out_dir = exporter._default_out_dir()
    return send_from_directory(str(out_dir), filename, as_attachment=True)


@blueprint.route("/api/exclude", methods=["POST"])
def api_exclude():
    data = request.get_json(silent=True) or {}
    hp = data.get("history_path")
    reason = (data.get("reason") or "").strip()
    if not hp:
        return jsonify({"error": "history_path required"}), 400
    if not reason:
        return jsonify({"error": "a reason is required to exclude"}), 400
    sync_state.set_status(hp, "excluded", note=f"excluded: {reason}")
    return jsonify({"status": "ok", "history_path": hp, "reason": reason})
