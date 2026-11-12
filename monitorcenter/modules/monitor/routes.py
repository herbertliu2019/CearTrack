import csv
import io
import json
from datetime import date, timedelta

from flask import (Blueprint, Response, abort, current_app, jsonify, render_template, request)

from modules.monitor import db, logic

monitor_bp = Blueprint("monitor", __name__, url_prefix="/monitor")

# Cyclelution fixed values (not shown on the entry page).
DATA_SANITIZATION = "ND-No Data"
DISPOSITION = "O3 Tested"


def _conn():
    return db.get_conn(current_app.config["MONITOR_DB_PATH"])


def _s(name: str) -> str:
    return (request.form.get(name) or "").strip()


def _collect(strict: bool):
    """Parse the entry form -> (data, errors)."""
    errors: list[str] = []
    mfr, model, size = _s("manufacturer"), _s("model"), _s("size")

    items = []
    for code, label, typ in logic.ITEMS:
        st = request.form.get(f"item_{code}", "Pass")
        items.append({"code": code, "label": label, "type": typ,
                      "status": st if st in logic.STATUSES else "Pass"})

    raw_dp = _s("dead_pixels") or "0"
    try:
        dead = int(raw_dp)
        if dead < 0 or dead > 9999:
            raise ValueError
    except ValueError:
        dead = 0
        errors.append("Dead pixel count must be a whole number")

    try:
        weight = float(_s("weight")) if _s("weight") else None
        if weight is not None and weight < 0:
            raise ValueError
    except ValueError:
        weight = None
        errors.append("Weight must be a positive number")

    missing = [m for m in request.form.getlist("missing") if m in logic.MISSING_OPTIONS]
    max_dead = current_app.config["MONITOR_MAX_DEAD_PIXELS"]

    data = {
        "traveler_id": _s("traveler_id"), "serial_no": _s("serial_no"),
        "manufacturer": mfr, "model": model, "model_id": 0, "size": size,
        "color": _s("color"), "weight": weight, "dead_pixels": dead, "missing": missing,
        "items": items, "grade": _s("grade"), "condition": _s("condition"),
        "functionality": _s("functionality"), "inv_notes": _s("inv_notes"), "notes": _s("notes"),
        "operator": _s("operator"), "max_dead": max_dead,
    }
    data["result"] = logic.compute_result(items, dead, max_dead)
    data["marks"] = logic.build_marks(missing)

    if strict:
        if not data["operator"]:
            errors.append("Operator ID is required")
        if not data["serial_no"]:
            errors.append("Serial number is required")
        if not mfr or not model:
            errors.append("Enter manufacturer and model")
        if data["grade"] and data["grade"] not in logic.GRADE_LABELS:
            errors.append("Invalid grade")
        if data["condition"] and data["condition"] not in logic.CONDITIONS.values():
            errors.append("Invalid condition")
        if data["functionality"] and data["functionality"] not in logic.FUNCTIONALITY:
            errors.append("Invalid functionality")
    return data, errors


# ── Entry page + fragments ──────────────────────────────────────────────

@monitor_bp.get("/")
def entry():
    conn = _conn()
    try:
        return render_template(
            "monitor/entry.html", models=db.list_models(conn), items=logic.ITEMS,
            missing_options=logic.MISSING_OPTIONS, sizes=logic.SIZE_SUGGESTIONS,
            conditions=logic.CONDITIONS, grade_labels=logic.GRADE_LABELS,
            functionality=logic.FUNCTIONALITY,
            max_dead=current_app.config["MONITOR_MAX_DEAD_PIXELS"])
    finally:
        conn.close()


@monitor_bp.get("/sn-check")
def sn_check():
    sn = (request.args.get("serial_no") or "").strip()
    existing = None
    if sn:
        conn = _conn()
        try:
            existing = db.active_by_serial(conn, sn)
        finally:
            conn.close()
    return render_template("monitor/_sn_check.html", existing=existing)


@monitor_bp.post("/marks-preview")
def marks_preview():
    data, _ = _collect(strict=False)
    return render_template("monitor/_marks.html", marks=data["marks"], result=data["result"],
                           dead=data["dead_pixels"], max_dead=data["max_dead"])


# ── Save ────────────────────────────────────────────────────────────────

@monitor_bp.post("/tests")
def save_test():
    conn = _conn()
    try:
        data, errors = _collect(strict=True)
        if errors:
            return jsonify({"ok": False, "errors": errors}), 400

        existing = db.active_by_serial(conn, data["serial_no"])
        if existing and request.form.get("confirm_retest") != "1":
            return jsonify({
                "ok": False, "needs_confirm": True,
                "message": (f"SN {data['serial_no']} already tested {existing['tested_at']} "
                            f"({existing['result']}). Save as retest?"),
            }), 409

        data["model_id"], created = db.get_or_create_model(
            conn, data["manufacturer"], data["model"], data["size"])
        if created:
            db.audit(conn, data["operator"], "model_created", None, data["serial_no"],
                     {"model": f"{data['manufacturer']} {data['model']}"})

        tid = db.insert_test(conn, data, db.now_iso())
        old = data["_superseded"]
        db.audit(conn, data["operator"], "test_created", tid, data["serial_no"], {
            "result": data["result"], "marks": data["marks"], "dead_pixels": data["dead_pixels"],
            "retest": bool(old)})
        if old:
            db.audit(conn, data["operator"], "test_superseded", tid, data["serial_no"], {"count": old})
        conn.commit()
        return jsonify({"ok": True, "id": tid, "result": data["result"], "marks": data["marks"],
                        "new_model": created})
    except Exception:
        conn.rollback()
        current_app.logger.exception("monitor save failed")
        return jsonify({"ok": False, "errors": ["Server error while saving"]}), 500
    finally:
        conn.close()


# ── List / CSV / detail ─────────────────────────────────────────────────

@monitor_bp.get("/tests")
def list_tests():
    a = request.args
    today = date.today()
    wk_from = today - timedelta(days=(today.weekday() + 1) % 7)       # Sunday start
    f = {
        "date_from": a.get("date_from") or str(wk_from),
        "date_to": a.get("date_to") or str(wk_from + timedelta(days=6)),
        "result": a.get("result") or "",
        "q": (a.get("q") or "").strip(),
        "include_superseded": a.get("all") == "1",
    }
    LIMIT = 500
    conn = _conn()
    try:
        rows = db.query_tests(conn, **f, limit=5000 if a.get("format") == "csv" else LIMIT + 1)
        if a.get("format") == "csv":
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["tested_at", "traveler_id", "serial_no", "manufacturer", "model", "size",
                        "color", "weight", "grade", "condition", "functionality",
                        "key_functions_test", "data_sanitization", "disposition", "mark",
                        "inventory_notes", "dead_pixels", "result", "tested_by", "superseded"])
            for r in rows:
                w.writerow([r["tested_at"], r["traveler_id"], r["serial_no"], r["manufacturer"],
                            r["model"], r["size"], r["color"], r["weight"], r["grade"],
                            r["condition"], r["functionality"], r["result"], DATA_SANITIZATION,
                            DISPOSITION, r["marks"], r["inv_notes"], r["dead_pixels"], r["result"],
                            r["tested_by"], "Y" if r["superseded_by"] else ""])
            return Response(buf.getvalue(), mimetype="text/csv", headers={
                "Content-Disposition": f"attachment; filename=monitor_tests_{today}.csv"})
        truncated = len(rows) > LIMIT
        return render_template("monitor/list.html", rows=rows[:LIMIT], f=f, truncated=truncated,
                               limit=LIMIT)
    finally:
        conn.close()


@monitor_bp.get("/tests/<int:test_id>")
def test_detail(test_id: int):
    conn = _conn()
    try:
        t = db.get_test(conn, test_id)
        if not t:
            abort(404)
        history = [dict(r) for r in conn.execute(
            "SELECT id, tested_at, result, superseded_by FROM monitor_tests "
            "WHERE UPPER(serial_no)=UPPER(?) ORDER BY id DESC", (t["serial_no"],))]
        qc = conn.execute("SELECT * FROM monitor_qc WHERE test_id=?", (test_id,)).fetchone()
        return render_template(
            "monitor/detail.html", t=t, items=db.test_items(conn, test_id),
            missing=json.loads(t["missing_flags"] or "[]"), history=history,
            qc=dict(qc) if qc else None, timeline=db.test_timeline(conn, t),
            max_dead=current_app.config["MONITOR_MAX_DEAD_PIXELS"])
    finally:
        conn.close()


# ── QC (done by a separate QC operator, picked by policy — not auto-sampled) ─────

@monitor_bp.get("/qc")
def qc_page():
    """view=today (QC done today) | history (date range)."""
    a = request.args
    view = a.get("view") if a.get("view") in ("today", "history") else "today"
    today = date.today()
    wk_from = today - timedelta(days=(today.weekday() + 1) % 7)       # Sunday start
    f = {"date_from": a.get("date_from") or str(wk_from),
         "date_to": a.get("date_to") or str(wk_from + timedelta(days=6)),
         "status": a.get("status") if a.get("status") in ("Passed", "Rejected") else "",
         "qc_by": (a.get("qc_by") or "").strip()}
    if view == "today":
        f["date_from"] = f["date_to"] = str(today)
        f["status"] = f["qc_by"] = ""
    conn = _conn()
    try:
        rows = db.qc_list(conn, f["date_from"], f["date_to"], f["status"] or None, f["qc_by"] or None)
        counts = db.qc_counts(conn, f["date_from"], f["date_to"])
        return render_template("monitor/qc.html", rows=rows, view=view, f=f, counts=counts,
                               today=str(today))
    finally:
        conn.close()


@monitor_bp.get("/qc/lookup")
def qc_lookup():
    """Fragment: the unit to be QC'd (latest live test for the SN) + any existing QC result."""
    sn = (request.args.get("serial_no") or "").strip()
    conn = _conn()
    try:
        t = db.active_by_serial(conn, sn) if sn else None
        qc = db.qc_get(conn, t["id"]) if t else None
        return render_template("monitor/_qc_unit.html", sn=sn, t=t, qc=qc)
    finally:
        conn.close()


@monitor_bp.post("/qc/submit")
def qc_submit():
    sn, status, who = _s("serial_no"), _s("status"), _s("operator")
    if not who:
        return jsonify({"ok": False, "errors": ["QC Operator ID is required"]}), 400
    if status not in ("Passed", "Rejected"):
        return jsonify({"ok": False, "errors": ["Invalid QC status"]}), 400
    conn = _conn()
    try:
        t = db.active_by_serial(conn, sn) if sn else None
        if not t:
            return jsonify({"ok": False, "errors": ["No active test for that SN"]}), 404
        prev = db.qc_get(conn, t["id"])
        if prev and request.form.get("confirm_overwrite") != "1":
            return jsonify({"ok": False, "needs_confirm": True,
                            "message": f"Already QC'd: {prev['status']} by {prev['qc_by']} "
                                       f"({prev['qc_at'].replace('T', ' ')}). Replace that result?"}), 409
        note = _s("note") or (logic.default_qc_note(who) if status == "Passed" else "")
        if status == "Rejected" and not note:
            return jsonify({"ok": False, "errors": ["Enter a note for the rejection"]}), 400
        db.qc_upsert(conn, t["id"], status, note, who)
        db.audit(conn, who, "qc_" + status.lower(), t["id"], t["serial_no"],
                 {"note": note, "replaced": prev["status"] if prev else None})
        conn.commit()
        return jsonify({"ok": True, "status": status, "serial_no": t["serial_no"]})
    finally:
        conn.close()
