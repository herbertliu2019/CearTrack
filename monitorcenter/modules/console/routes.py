import csv
import io
import json
import os
from datetime import date, timedelta

from flask import (Blueprint, Response, abort, current_app, jsonify, render_template,
                   request, send_from_directory)

import hashlib
import hmac

from modules.console import db, ingest, logic

console_bp = Blueprint("console", __name__, url_prefix="/console")


def _db_path() -> str:
    return current_app.config["CONSOLE_DB_PATH"]


def _conn():
    return db.get_conn(_db_path())


def _s(name: str) -> str:
    return (request.form.get(name) or "").strip()


def _collect(conn, strict: bool):
    """Parse the entry form. Returns (data, errors). strict=True enforces save rules."""
    errors: list[str] = []
    raw_model = request.form.get("model_id", "")
    new_model = None  # manually typed model not yet in the DB
    try:
        model_id = int(raw_model)
    except ValueError:
        model_id = 0
    if raw_model == "__new__":
        mfr, name = _s("new_manufacturer"), _s("new_model")
        kind = _s("new_storage_kind")
        kind = kind if kind in ("removable", "fixed", "none") else "fixed"
        found = db.find_model(conn, mfr, name) if mfr and name else None
        if found:
            model_id = found["id"]          # typed text matches an existing model
        else:
            if not mfr or not name:
                errors.append("Enter manufacturer and model")
            new_model = {"manufacturer": mfr, "model": name, "storage_kind": kind,
                         "has_data": 1 if request.form.get("new_has_data", "1") == "1" else 0}
    model = db.get_model(conn, model_id) if model_id else None
    items = []
    if new_model is not None:
        model = {"id": 0, **new_model}
        src = db.generic_items(conn)
    elif model:
        src = db.model_items(conn, model_id)
    else:
        errors.append("Select a model")
        model = {"id": 0, "has_data": 1}
        src = []
    for it in src:
        st = request.form.get(f"item_{it['id']}", "Pass")
        items.append({**it, "status": st if st in logic.STATUSES else "Pass"})

    method = _s("sanitize_method") or "Factory Reset"
    s_result = _s("sanitize_result") or logic.default_sanitize_result(method)
    if method == "Locked":
        s_result = "Fail"
    elif method == "No data":
        s_result = "N/A"
    s_date = _s("sanitize_date")
    if method in ("No data", "Locked"):
        s_date = ""
    elif method != "EPS" and not s_date:
        s_date = str(date.today())

    cosmetic = [c.strip() for c in request.form.getlist("cosmetic") if c.strip()]
    other = _s("cosmetic_other")
    if other:
        cosmetic.append(other)

    try:
        weight = float(_s("weight")) if _s("weight") else None
        if weight is not None and weight < 0:
            raise ValueError
    except ValueError:
        weight = None
        errors.append("Weight must be a positive number")

    photo = request.files.get("reset_photo")
    has_photo = bool(photo and photo.filename)

    data = {
        "model": model, "model_id": model_id, "new_model": new_model, "items": items,
        "traveler_id": _s("traveler_id"), "serial_no": _s("serial_no"),
        "color": _s("color"), "cosmetic": cosmetic,
        "sanitize_method": method, "sanitize_result": s_result, "sanitize_date": s_date,
        "storage_size": _s("storage_size"), "storage_type": _s("storage_type"),
        "storage_desc": " ".join(p for p in (_s("storage_size"), _s("storage_type")) if p),
        "weight": weight, "grade": _s("grade"), "condition": _s("condition"),
        "functionality": _s("functionality"), "cd_dvd": _s("cd_dvd"), "part_no": _s("part_no"),
        "hdd_sn": _s("hdd_sn"),
        "hdd_traveler_id": _s("hdd_traveler_id"),
        "notes": _s("notes"), "operator": _s("operator"),
        "photo": photo if has_photo else None,
    }
    data["result"] = logic.compute_result(items, method, s_result)
    data["marks"] = logic.build_marks(method, s_result, s_date, cosmetic, items, _s("storage_type"))

    if strict:
        # Grade/Condition/Functionality combos are NOT enforced yet (pending sales confirmation);
        # only reject values outside the known lists. See logic.validate_grade for the strict rules.
        if data["grade"] and data["grade"] not in logic.GRADE_LABELS:
            errors.append("Invalid grade")
        if data["condition"] and data["condition"] not in logic.CONDITIONS.values():
            errors.append("Invalid condition")
        if not data["operator"]:
            errors.append("Operator ID is required")
        if not data["serial_no"]:
            errors.append("Serial number is required")
        errors += logic.validate_sanitize(method, s_result, s_date, data["hdd_sn"],
                                          data["hdd_traveler_id"])
    return data, errors


# ── Entry page + HTMX fragments ─────────────────────────────────────────

@console_bp.get("/")
def entry():
    conn = _conn()
    try:
        return render_template(
            "console/entry.html", models=db.list_models(conn),
            methods=logic.METHODS, cosmetic_options=logic.COSMETIC_OPTIONS,
            conditions=logic.CONDITIONS, grade_labels=logic.GRADE_LABELS, grade_rules=logic.grade_rules_json(), functionality=logic.FUNCTIONALITY,
            cd_dvd_options=logic.CD_DVD_OPTIONS, storage_types=logic.STORAGE_TYPES,
            show_sales_fields=logic.SHOW_SALES_FIELDS, today=str(date.today()))
    finally:
        conn.close()


@console_bp.get("/items")
def items_fragment():
    conn = _conn()
    try:
        if request.args.get("model_id") == "__new__":
            model, items = {"new": True}, db.generic_items(conn)
        else:
            mid = request.args.get("model_id", type=int)
            model = db.get_model(conn, mid) if mid else None
            items = db.model_items(conn, mid) if model else []
        return render_template("console/_items.html", model=model, items=items)
    finally:
        conn.close()


@console_bp.get("/sn-check")
def sn_check():
    sn = (request.args.get("sn") or request.args.get("serial_no") or "").strip()
    existing = None
    if sn:
        conn = _conn()
        try:
            existing = db.active_by_serial(conn, sn)
        finally:
            conn.close()
    return render_template("console/_sn_check.html", existing=existing)


@console_bp.post("/marks-preview")
def marks_preview():
    conn = _conn()
    try:
        data, _ = _collect(conn, strict=False)
    finally:
        conn.close()
    return render_template("console/_marks.html", marks=data["marks"], result=data["result"])


# ── Save ────────────────────────────────────────────────────────────────

@console_bp.post("/tests")
def save_test():
    conn = _conn()
    try:
        data, errors = _collect(conn, strict=True)
        if errors:
            return jsonify({"ok": False, "errors": errors}), 400

        existing = db.active_by_serial(conn, data["serial_no"])
        if existing and request.form.get("confirm_retest") != "1":
            return jsonify({
                "ok": False, "needs_confirm": True,
                "message": (f"SN {data['serial_no']} already tested {existing['tested_at']} "
                            f"({existing['result']}). Save as retest?"),
            }), 409

        if data["new_model"] is not None:
            nm = data["new_model"]
            data["model_id"] = db.create_model(conn, nm["manufacturer"], nm["model"],
                                               nm["storage_kind"], nm["has_data"])
            db.audit(conn, data["operator"], "model_created", None, data["serial_no"],
                     {"model_id": data["model_id"], "model": f"{nm['manufacturer']} {nm['model']}"})

        tested_at = db.now_iso()
        tid = db.insert_test(conn, data, tested_at)

        if data["photo"] is not None:
            rel = _store_photo(tid, tested_at, data["photo"].read())
            conn.execute("UPDATE console_tests SET reset_photo=? WHERE id=?", (rel, tid))

        old = data["_superseded"]
        db.audit(conn, data["operator"], "test_created", tid, data["serial_no"], {
            "result": data["result"], "marks": data["marks"], "model_id": data["model_id"],
            "retest": bool(old)})
        if old:
            db.audit(conn, data["operator"], "test_superseded", tid, data["serial_no"],
                     {"count": old})
        conn.commit()
        return jsonify({"ok": True, "id": tid, "result": data["result"], "marks": data["marks"],
                        "model_id": data["model_id"], "new_model": data["new_model"] is not None})
    except Exception:
        conn.rollback()
        current_app.logger.exception("console save failed")
        return jsonify({"ok": False, "errors": ["Server error while saving"]}), 500
    finally:
        conn.close()


def _store_photo(test_id: int, tested_at: str, raw: bytes) -> str:
    rel = f"{tested_at[:4]}/{tested_at[5:7]}/{test_id}.jpg"
    logic.save_photo(raw, os.path.join(current_app.config["CONSOLE_PHOTO_DIR"], rel))
    return rel


@console_bp.post("/tests/<int:test_id>/photo")
def upload_photo(test_id: int):
    f = request.files.get("reset_photo")
    if not f or not f.filename:
        return jsonify({"ok": False, "errors": ["No file"]}), 400
    conn = _conn()
    try:
        t = db.get_test(conn, test_id)
        if not t:
            abort(404)
        rel = _store_photo(test_id, t["tested_at"], f.read())
        conn.execute("UPDATE console_tests SET reset_photo=? WHERE id=?", (rel, test_id))
        db.audit(conn, _s("operator"), "photo_uploaded", test_id, t["serial_no"], {"path": rel})
        conn.commit()
        return jsonify({"ok": True, "path": rel})
    finally:
        conn.close()


@console_bp.get("/photos/<path:rel>")
def photo(rel: str):
    return send_from_directory(current_app.config["CONSOLE_PHOTO_DIR"], rel)


# ── External upload API (other test tools -> CearTrack) ─────────────────

@console_bp.get("/external/<path:rel>")
def external_file(rel: str):
    return send_from_directory(current_app.config["CONSOLE_EXTERNAL_DIR"], rel)


@console_bp.post("/api/upload")
def api_upload():
    """Accept a test result from another tool.

    curl -H "X-API-Key: <key>" -F json=@result.json [-F pdf=@result.pdf] http://host/console/api/upload
    curl -H "X-API-Key: <key>" -H "Content-Type: application/json" --data-binary @result.json http://host/console/api/upload
    Result/Marks are recomputed server-side; the tool's own verdict is stored as ext_result.
    """
    key = request.headers.get("X-API-Key", "")
    if not hmac.compare_digest(key.encode(), current_app.config["CONSOLE_API_KEY"].encode()):
        return jsonify({"ok": False, "errors": ["Invalid or missing X-API-Key"]}), 401

    jf, pf = request.files.get("json"), request.files.get("pdf")
    raw_bytes = jf.read() if jf and jf.filename else (request.get_data() if not request.files else b"")
    if not raw_bytes:
        return jsonify({"ok": False, "errors": ["Missing JSON (multipart field 'json' or raw body)"]}), 400
    try:
        raw = json.loads(raw_bytes.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        return jsonify({"ok": False, "errors": ["Invalid JSON"]}), 400
    pdf_bytes = pf.read() if pf and pf.filename else b""
    if pdf_bytes and not pdf_bytes.startswith(b"%PDF"):
        return jsonify({"ok": False, "errors": ["'pdf' is not a PDF file"]}), 400

    sha = hashlib.sha256(raw_bytes).hexdigest()
    conn = _conn()
    try:
        dup = db.find_by_ext_sha(conn, sha)
        if dup:
            return jsonify({"ok": True, "duplicate": True, "id": dup["id"], "result": dup["result"],
                            "marks": dup["marks"]}), 200

        data, errors = ingest.parse_external(conn, raw)
        if errors:
            return jsonify({"ok": False, "errors": errors}), 400

        if data["new_model"] is not None:
            nm = data["new_model"]
            data["model_id"] = db.create_model(conn, nm["manufacturer"], nm["model"],
                                               nm["storage_kind"], nm["has_data"])
            db.audit(conn, data["operator"], "model_created", None, data["serial_no"],
                     {"model_id": data["model_id"], "model": f"{nm['manufacturer']} {nm['model']}",
                      "source": "api"})

        tested_at = db.now_iso()
        tid = db.insert_test(conn, data, tested_at, source="api", ext={
            "ext_sha256": sha, "ext_result": data["ext_result"] or None})

        base = os.path.join(current_app.config["CONSOLE_EXTERNAL_DIR"], tested_at[:4], tested_at[5:7])
        os.makedirs(base, exist_ok=True)
        rel_json = f"{tested_at[:4]}/{tested_at[5:7]}/{tid}.json"
        with open(os.path.join(base, f"{tid}.json"), "wb") as fh:
            fh.write(raw_bytes)
        rel_pdf = None
        if pdf_bytes:
            rel_pdf = f"{tested_at[:4]}/{tested_at[5:7]}/{tid}.pdf"
            with open(os.path.join(base, f"{tid}.pdf"), "wb") as fh:
                fh.write(pdf_bytes)
        conn.execute("UPDATE console_tests SET ext_json_path=?, ext_pdf_path=? WHERE id=?",
                     (rel_json, rel_pdf, tid))

        old = data["_superseded"]
        db.audit(conn, data["operator"], "test_created", tid, data["serial_no"], {
            "result": data["result"], "marks": data["marks"], "model_id": data["model_id"],
            "retest": bool(old), "source": "api", "ext_result": data["ext_result"]})
        if old:
            db.audit(conn, data["operator"], "test_superseded", tid, data["serial_no"], {"count": old})
        conn.commit()
        return jsonify({"ok": True, "id": tid, "result": data["result"], "marks": data["marks"],
                        "retest": bool(old)})
    except Exception:
        conn.rollback()
        current_app.logger.exception("console api upload failed")
        return jsonify({"ok": False, "errors": ["Server error while saving"]}), 500
    finally:
        conn.close()


# ── List / detail ───────────────────────────────────────────────────────

@console_bp.get("/tests")
def list_tests():
    a = request.args
    today = str(date.today())
    # default range = this week (Sun–Sat), same as the stats panel
    wk_from = date.today() - timedelta(days=(date.today().weekday() + 1) % 7)
    f = {
        "date_from": a.get("date_from") or str(wk_from),
        "date_to": a.get("date_to") or str(wk_from + timedelta(days=6)),
        "result": a.get("result") or "",
        "model_id": a.get("model_id", type=int),
        "q": (a.get("q") or "").strip(),
        "include_superseded": a.get("all") == "1",
    }
    conn = _conn()
    try:
        LIMIT = 500
        rows = db.query_tests(conn, **f, limit=5000 if a.get("format") == "csv" else LIMIT + 1)
        if a.get("format") == "csv":
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["tested_at", "traveler_id", "serial_no", "manufacturer", "model", "result",
                        "marks", "sanitize_method", "sanitize_date", "hdd_sn", "hdd_traveler_id",
                        "tested_by", "qc_status", "superseded",
                        "weight", "grade", "color", "condition", "storage_size", "storage_type",
                        "cd_dvd", "functionality", "data_sanitization", "part_no", "mark"])
            for r in rows:
                w.writerow([r["tested_at"], r["traveler_id"], r["serial_no"], r["manufacturer"],
                            r["model"], r["result"], r["marks"], r["sanitize_method"],
                            r["sanitize_date"], r["hdd_sn"], r["hdd_traveler_id"],
                            r["tested_by"], r["qc_status"], "Y" if r["superseded_by"] else "",
                            r["weight"], r["grade"], r["color"], r["condition"],
                            r["storage_size"], r["storage_type"], r["cd_dvd"], r["functionality"],
                            "Pass" if (r["sanitize_method"] == "Factory Reset"
                                       and r["sanitize_result"] == "Pass") else "",
                            r["part_no"], r["notes"]])
            return Response(buf.getvalue(), mimetype="text/csv", headers={
                "Content-Disposition": f"attachment; filename=console_tests_{today}.csv"})
        truncated = len(rows) > LIMIT
        rows = rows[:LIMIT]
        for r in rows:
            try:
                r["cosmetic"] = ", ".join(json.loads(r["cosmetic_flags"] or "[]"))
            except ValueError:
                r["cosmetic"] = ""
        if a.get("fragment"):
            return render_template("console/_rows.html", rows=rows, truncated=truncated, limit=LIMIT,
                                   show_sales_fields=logic.SHOW_SALES_FIELDS)
        return render_template("console/list.html", rows=rows, f=f, truncated=truncated, limit=LIMIT,
                               show_sales_fields=logic.SHOW_SALES_FIELDS,
                               models=db.list_models(conn, active_only=False))
    finally:
        conn.close()


@console_bp.get("/api/stats")
def api_stats():
    """period=week (Sun-Sat) | month | custom; `ref` = any date inside the period (default today)."""
    a = request.args
    period = a.get("period", "week")
    try:
        ref = date.fromisoformat(a.get("ref") or str(date.today()))
        if period == "custom":
            d_from, d_to = date.fromisoformat(a["start"]), date.fromisoformat(a["end"])
            if d_to < d_from or (d_to - d_from).days > 366:
                return jsonify({"error": "Invalid range (max 366 days)"}), 400
        elif period == "month":
            d_from = ref.replace(day=1)
            nxt = (d_from + timedelta(days=32)).replace(day=1)
            d_to = nxt - timedelta(days=1)
        else:
            d_from = ref - timedelta(days=(ref.weekday() + 1) % 7)   # Sunday start
            d_to = d_from + timedelta(days=6)
    except (ValueError, KeyError):
        return jsonify({"error": "Invalid date"}), 400
    conn = _conn()
    try:
        return jsonify(db.period_stats(conn, str(d_from), str(d_to)))
    finally:
        conn.close()


@console_bp.get("/tests/<int:test_id>")
def test_detail(test_id: int):
    conn = _conn()
    try:
        t = db.get_test(conn, test_id)
        if not t:
            abort(404)
        qc = conn.execute("SELECT * FROM console_qc WHERE test_id=?", (test_id,)).fetchone()
        history = [dict(r) for r in conn.execute(
            "SELECT id, tested_at, result, superseded_by FROM console_tests "
            "WHERE UPPER(serial_no)=UPPER(?) ORDER BY id DESC", (t["serial_no"],))]
        return render_template(
            "console/detail.html", t=t, items=db.test_items(conn, test_id),
            cosmetic=json.loads(t["cosmetic_flags"] or "[]"),
            qc=dict(qc) if qc else None, history=history,
            timeline=db.test_timeline(conn, t))
    finally:
        conn.close()


# ── QC (done by a separate QC operator, picked by policy — not auto-sampled) ─────

@console_bp.get("/qc")
def qc_page():
    """view=today (QC done today + legacy pending) | pending (legacy auto-sampled, still open) | history."""
    a = request.args
    view = a.get("view") if a.get("view") in ("today", "pending", "history") else "today"
    today = date.today()
    wk_from = today - timedelta(days=(today.weekday() + 1) % 7)       # Sunday start, like Test Results
    f = {"date_from": a.get("date_from") or str(wk_from),
         "date_to": a.get("date_to") or str(wk_from + timedelta(days=6)),
         "status": a.get("status") if a.get("status") in ("Pending", "Passed", "Rejected") else "",
         "qc_by": (a.get("qc_by") or "").strip()}
    conn = _conn()
    try:
        if view == "pending":
            rows, rng = db.qc_list(conn, pending_only=True), (None, None)
        elif view == "history":
            rows = db.qc_list(conn, f["date_from"], f["date_to"], f["status"] or None, f["qc_by"] or None)
            rng = (f["date_from"], f["date_to"])
        else:
            rows, rng = db.qc_rows(conn, str(today)), (str(today), str(today))
            f["date_from"] = f["date_to"] = str(today)
        counts = db.qc_counts(conn, *(rng if rng[0] else ("0000-01-01", "9999-12-31")))
        tested = conn.execute(
            "SELECT COUNT(*) FROM console_tests WHERE superseded_by IS NULL "
            "AND date(tested_at) BETWEEN ? AND ?",
            (rng[0] or "0000-01-01", rng[1] or "9999-12-31")).fetchone()[0]
        return render_template("console/qc.html", rows=rows, view=view, f=f, counts=counts,
                               tested=tested, today=str(today))
    finally:
        conn.close()


@console_bp.get("/qc/lookup")
def qc_lookup():
    """Fragment: the unit to be QC'd (latest live test for the SN) + any existing QC result."""
    sn = (request.args.get("serial_no") or "").strip()
    conn = _conn()
    try:
        t = db.active_by_serial(conn, sn) if sn else None
        qc = db.qc_get(conn, t["id"]) if t else None
        return render_template("console/_qc_unit.html", sn=sn, t=t, qc=qc)
    finally:
        conn.close()


@console_bp.post("/qc/submit")
def qc_submit_sn():
    """QC result by SN: creates the QC record (or replaces an earlier result after confirmation)."""
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
        if prev and prev["status"] != "Pending" and request.form.get("confirm_overwrite") != "1":
            return jsonify({"ok": False, "needs_confirm": True,
                            "message": f"Already QC'd: {prev['status']} by {prev['qc_by']} "
                                       f"({(prev['qc_at'] or '').replace('T', ' ')}). Replace that result?"}), 409
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


@console_bp.post("/qc/<int:qc_id>")
def qc_submit(qc_id: int):
    """Resolve a legacy Pending record (created by the former automatic sampling)."""
    status = _s("status")
    who = _s("operator")
    if status not in ("Passed", "Rejected"):
        return jsonify({"ok": False, "errors": ["Invalid QC status"]}), 400
    if not who:
        return jsonify({"ok": False, "errors": ["Operator name required"]}), 400
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT c.*, t.serial_no FROM console_qc c JOIN console_tests t ON t.id=c.test_id "
            "WHERE c.id=?", (qc_id,)).fetchone()
        if not row:
            abort(404)
        note = _s("note") or (logic.default_qc_note(who) if status == "Passed" else "")
        conn.execute("UPDATE console_qc SET status=?, note=?, qc_by=?, qc_at=? WHERE id=?",
                     (status, note, who, db.now_iso(), qc_id))
        db.audit(conn, who, "qc_" + status.lower(), row["test_id"], row["serial_no"],
                 {"note": note})
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


# ── Admin: model + check-item config ────────────────────────────────────

@console_bp.route("/admin/models", methods=["GET", "POST"])
def admin_models():
    conn = _conn()
    try:
        msg = ""
        if request.method == "POST":
            msg = _admin_save(conn)
        models = db.list_models(conn, active_only=False)
        sel = request.values.get("id", type=int)
        sel_model = db.get_model(conn, sel) if sel else None
        cfg = {}
        if sel_model:
            for r in conn.execute("SELECT * FROM console_model_items WHERE model_id=?", (sel,)):
                cfg[r["item_id"]] = dict(r)
        return render_template("console/admin.html", models=models, sel=sel_model,
                               check_items=db.all_check_items(conn), cfg=cfg, msg=msg)
    finally:
        conn.close()


def _admin_save(conn) -> str:
    who = _s("operator")
    mfr, name = _s("manufacturer"), _s("model")
    if not mfr or not name:
        return "Manufacturer and model are required"
    kind = _s("storage_kind")
    if kind not in ("removable", "fixed", "none"):
        kind = "none"
    has_data = 1 if request.form.get("has_data") else 0
    active = 1 if request.form.get("active") else 0
    mid = request.form.get("model_id", type=int)
    try:
        if mid:
            conn.execute("UPDATE console_models SET manufacturer=?,model=?,storage_kind=?,"
                         "has_data=?,active=? WHERE id=?", (mfr, name, kind, has_data, active, mid))
        else:
            mid = conn.execute("INSERT INTO console_models(manufacturer,model,storage_kind,"
                               "has_data,active) VALUES (?,?,?,?,?)",
                               (mfr, name, kind, has_data, active)).lastrowid
    except Exception as e:
        conn.rollback()
        return f"Save failed: {e}"
    conn.execute("DELETE FROM console_model_items WHERE model_id=?", (mid,))
    for it in db.all_check_items(conn):
        if not request.form.get(f"use_{it['id']}"):
            continue
        typ = request.form.get(f"type_{it['id']}", it["default_type"])
        if typ not in ("key", "secondary"):
            typ = it["default_type"]
        sort = request.form.get(f"sort_{it['id']}", type=int) or 0
        lab = (request.form.get(f"label_{it['id']}") or "").strip() or None
        conn.execute("INSERT INTO console_model_items(model_id,item_id,type,label_override,sort) "
                     "VALUES (?,?,?,?,?)", (mid, it["id"], typ, lab, sort))
    db.audit(conn, who, "model_saved", None, None, {"model_id": mid, "model": f"{mfr} {name}"})
    conn.commit()
    return "Saved"
