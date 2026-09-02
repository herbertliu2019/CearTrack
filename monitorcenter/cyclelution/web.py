"""Flask blueprint for the Cyclelution export UI (Phase 4).

A single centre page at /cyclelution/ with three views (Ready / Exceptions /
Exported), decoupled from the test modules. It drives the Phase 2/3 engine
(scan, export) against whichever production's data source is active.

Multi-production: everything is keyed on `production`, resolved via
_PRODUCTION_INFO to a module name (its own `<module>_sync` table + own
mapping yaml/context builder/gate). T-Laptop, T-Video Card (gpu) and
T-Hard Drive (wipe) are wired up; T-Desktop is a placeholder until its test
module ships.
"""

import json
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request, send_from_directory

from . import sync_state, scan as _scan, exporter, context_gpu, gate_gpu, context_wipe, gate_wipe, wipe_sync, recency, batch_store
from . import normalizer as _normalizer

# Archive tabs (Exceptions/Exported/Excluded/NO_GRADE) never render more
# than this many rows by default — a hard latency backstop regardless of
# how many records fall inside the recency window. Full history is still
# reachable via the sn= search param, which bypasses both the window and
# this cap (it's a targeted lookup on the indexed sn column, not a scan).
_ARCHIVE_CAP = 200

blueprint = Blueprint(
    "cyclelution", __name__,
    template_folder="templates",
    url_prefix="/cyclelution",
)

# Per-production wiring. None values mean "use the normalizer/scan/exporter
# default" (T-Laptop's original behavior, unchanged). Config is reloaded
# from disk on every use (matches T-Laptop's existing load_config() pattern)
# so a yaml edit takes effect without a restart.
#
# `rescan_fn` is None for productions whose data arrives via test-script
# upload (evaluate_one already ran at upload time; Rescan just re-checks
# records still stuck pending) — api_rescan() falls back to scan.scan_pending
# for those. T-Hard Drive has no upload event at all (see wipe_sync.py), so
# its "rescan" is really "go re-derive everything from wipe_records", which
# runs in the background (~20 min against the full table — never inline).
_PRODUCTION_INFO = {
    "T-Laptop": {
        "module": "laptop",
        "config": lambda: _normalizer.load_config(),
        "context_builder": None,
        "gate_fn": None,
        "filename_prefix": "TLaptop",
        "rescan_fn": None,
    },
    "T-Video Card": {
        "module": "gpu",
        "config": lambda: _normalizer.load_config(context_gpu.CONFIG_PATH),
        "context_builder": context_gpu.build_context,
        "gate_fn": gate_gpu.evaluate,
        "filename_prefix": "TVideoCard",
        "rescan_fn": None,
    },
    "T-Hard Drive": {
        "module": "wipe",
        "config": lambda: _normalizer.load_config(context_wipe.CONFIG_PATH),
        "context_builder": context_wipe.build_context,
        "gate_fn": gate_wipe.evaluate,
        "filename_prefix": "THardDrive",
        "rescan_fn": wipe_sync.run_in_background,
    },
}

# Productions this export centre serves. Only `active` ones have a wired-up
# data source today. The others are placeholders so the operator sees the
# roadmap and the UI is ready — when their test module ships, add an entry
# to _PRODUCTION_INFO and flip active to True. No page change needed.
PRODUCTIONS = [
    {"id": "T-Laptop",     "label": "T-Laptop",     "active": True},
    #{"id": "T-Desktop",    "label": "T-Desktop",    "active": False},
    {"id": "T-Video Card", "label": "GPU",           "active": True},
    {"id": "T-Hard Drive", "label": "T-Hard Drive",  "active": True},
]


def _is_active(pid: str) -> bool:
    return any(p["id"] == pid and p["active"] for p in PRODUCTIONS)


def _info(production: str) -> dict:
    """Resolve a production id to its wiring, defaulting to T-Laptop."""
    return _PRODUCTION_INFO.get(production, _PRODUCTION_INFO["T-Laptop"])


def _row_display(row: dict, module: str) -> dict:
    """Enrich a *_sync row with the fields the queue shows, read from
    the record JSON. Missing file -> minimal row so the queue never breaks."""
    hp = row["history_path"]
    base = {
        "history_path": hp,
        "sn": row.get("sn") or "",
        "vendor": "", "model": "", "grade": "", "operator": "", "test_station": "",
        "date": "", "note": row.get("sync_note") or "",
        "synced_at": row.get("synced_at") or "",
        "capacity": "",
    }
    try:
        env = json.loads(Path(hp).read_text(encoding="utf-8"))
        pl = env.get("payload", {}) or {}
        base["sn"] = env.get("sn") or base["sn"]
        if module == "wipe":
            wipe = pl.get("wipe", {}) or {}
            base["vendor"] = wipe.get("manufacturer", "")
            base["model"] = wipe.get("drive_model", "")
            base["capacity"] = wipe.get("capacity", "")
            # No test-script operator involved — wipe_datetime is not an
            # operator action, and there's no manual_input block to read a
            # grade from (it's a wipe_records column instead).
            base["grade"] = (wipe.get("grade") or "")
            base["operator"] = "—"
            base["date"] = (env.get("timestamp", "") or "")[:10]
        elif module == "gpu":
            gpu = pl.get("gpu", {}) or {}
            base["vendor"] = gpu.get("subvendor") or gpu.get("vendor", "")
            base["model"] = gpu.get("name", "")
            # manual_input.grade is already a complete display string
            # ("Grade B") — pass through verbatim, no code->label mapping.
            base["grade"] = (pl.get("manual_input", {}) or {}).get("grade") or ""
            ti = pl.get("test_info", {}) or {}
            # TASK_export_batch0901.md's GPU field notes: top-level
            # `hostname` mirrors this same value (use test_station, not
            # hostname, for consistency), and `test_info.operator_id` must
            # NEVER be read here — it's slated for removal in the next
            # test-script version and GPU has no operator concept (use
            # test_station instead, which is what `filters` is configured
            # to offer for this production).
            base["test_station"] = ti.get("test_station", "") or "—"
            base["date"] = (ti.get("test_time", "") or "")[:10]
        else:
            base["vendor"] = (pl.get("system", {}) or {}).get("vendor", "")
            base["model"] = (pl.get("system", {}) or {}).get("model", "")
            base["grade"] = (pl.get("manual_input", {}) or {}).get("grade") or ""
            base["operator"] = (pl.get("test_info", {}) or {}).get("operator_id", "") or "—"
            base["date"] = (env.get("timestamp", "") or "")[:10]
    except Exception:
        base["operator"] = base["operator"] or "—"
    return base


def _ready_row_for_sn(sn: str, module: str):
    """The live `ready` sync_state row for an exact SN, or None. Batch
    membership only ever points at Ready-pool SNs (never a history_path
    directly — see TASK_export_batch.md's data model, `record_sn` not an
    id), so every batch route that needs a record's detail or its
    history_path goes through this."""
    rows = sync_state.list_by_sn(sn, module=module)
    return next((r for r in rows if r["sync_status"] == "ready"), None)


def _batch_item_display(item: dict, module: str) -> dict:
    """Enrich a batch item (record_sn/slot_no/...) with the same vendor/
    model/grade/capacity fields the Ready list shows, by reusing
    _row_display() on its live ready sync_state row — keeps the batch panel
    and the plain Ready list rendering the same data through one path."""
    out = {
        "record_sn": item["record_sn"], "slot_no": item.get("slot_no"),
        "added_at": item.get("added_at"), "input_mode": item.get("input_mode"),
        "vendor": "", "model": "", "grade": "", "capacity": "", "date": "",
        "operator": "", "test_station": "",
    }
    ready_row = _ready_row_for_sn(item["record_sn"], module)
    if ready_row:
        disp = _row_display(ready_row, module)
        out.update({k: disp[k] for k in
                    ("vendor", "model", "grade", "capacity", "date", "operator", "test_station")})
    return out


def _diagnose_batch_miss(sn: str, production: str, module: str) -> str:
    """Why a scanned/typed SN isn't an exact hit in the Ready pool — batch
    /lookup's 0-candidate case and /add's rejection reason (task section
    'POST /lookup': Exceptions / NO_GRADE / already exported / already in
    another batch / doesn't exist)."""
    open_batch = batch_store.sn_open_batch(sn, production)
    if open_batch:
        return f"already_in_batch:{open_batch}"
    rows = sync_state.list_by_sn(sn, module=module)
    if not rows:
        return "not_found"
    latest = rows[-1]  # list_by_sn is oldest-first (rowid order)
    status = latest.get("sync_status")
    note = latest.get("sync_note") or ""
    if status == "synced":
        return "already_exported"
    if status == "excluded" and note == "NO_GRADE":
        return "no_grade"
    if status == "excluded":
        return "excluded"
    if status == "pending":
        return "exception"
    return "not_found"


@blueprint.route("/")
def dashboard():
    return render_template("cyclelution.html", productions=PRODUCTIONS)


@blueprint.route("/api/productions")
def api_productions():
    # Each active production's `batch` config rides along here so the page
    # can pick checkbox-list vs scan-panel mode client-side without a
    # separate round trip (see cyclelution.html's batchEnabled()).
    out = []
    for p in PRODUCTIONS:
        item = dict(p)
        if p["active"]:
            info = _info(p["id"])
            cfg = info["config"]() or {}
            batch = dict(cfg.get("batch") or {})
            batch["ready_window_days"] = cfg.get("ready_window_days", 30)
            item["batch"] = batch
        else:
            item["batch"] = None
        out.append(item)
    return jsonify({"productions": out})


def _archive_slice(raw_rows: list, window_cutoff: str, sn_query: str, cap: int) -> tuple[list, int]:
    """Apply the archive-tab display rule to a status's raw sync_state rows:
    a SN search bypasses the window/cap entirely and searches full history
    (the point of keeping an indexed sn column even for a 27,000-row
    archive); otherwise show only rows inside the recency window, newest
    first, capped. Returns (sliced_rows, full_count) — full_count is the
    true cumulative size of `raw_rows` regardless of the slice, so the UI
    can show "N shown of M total" without api_counts() needing to change
    (its cumulative counts are correct as-is)."""
    full_count = len(raw_rows)
    if sn_query:
        q = sn_query.strip().lower()
        matched = [r for r in raw_rows if q in (r.get("sn") or "").lower()]
        matched.sort(key=lambda r: r.get("record_ts") or "", reverse=True)
        return matched, full_count
    windowed = [r for r in raw_rows if (r.get("record_ts") or "") >= window_cutoff]
    windowed.sort(key=lambda r: r.get("record_ts") or "", reverse=True)
    return windowed[:cap], full_count


@blueprint.route("/api/queue")
def api_queue():
    """status=ready/exceptions/exported/excluded/no_grade -> flat-or-grouped
    list, cumulative count (via api_counts(), unchanged) but a
    window-limited + capped default list; pass sn= to search that status's
    full history instead, bypassing the window and cap (see
    _archive_slice()). Inactive productions have no data source yet ->
    empty result."""
    status = request.args.get("status", "ready")
    production = request.args.get("production", "T-Laptop")
    sn_query = request.args.get("sn", "").strip()

    if not _is_active(production):
        return jsonify({"groups": [], "records": [], "total": 0})
    info = _info(production)
    module = info["module"]
    window_cutoff = recency.cutoff_date(info["config"]().get("ready_window_days", 30))

    if status == "ready":
        # Newest tested/wiped first within each operator's group (by the
        # full record_ts, not the truncated display date, so same-day
        # records still order correctly by time).
        raw_rows = sync_state.list_by_status("ready", module=module)
        sliced, full_count = _archive_slice(raw_rows, window_cutoff, sn_query, _ARCHIVE_CAP)
        rows = [_row_display(r, module) for r in sliced]
        groups: dict[str, list] = {}
        for r in rows:
            r["flags"] = [f for f in (r["note"].split(" | ") if r["note"] else []) if f]
            groups.setdefault(r["operator"], []).append(r)
        out = [
            {"operator": op, "count": len(recs), "records": recs}
            for op, recs in sorted(groups.items())
        ]
        return jsonify({"groups": out, "total": len(rows), "cumulative_total": full_count, "searched": bool(sn_query)})

    if status == "exceptions":
        raw_rows = [r for r in sync_state.list_by_status("pending", module=module) if r.get("sync_note")]
        sliced, full_count = _archive_slice(raw_rows, window_cutoff, sn_query, _ARCHIVE_CAP)
        rows = [_row_display(r, module) for r in sliced]
        return jsonify({"records": rows, "total": len(rows), "cumulative_total": full_count, "searched": bool(sn_query)})

    if status == "exported":
        raw_rows = sync_state.list_by_status("synced", module=module)
        sliced, full_count = _archive_slice(raw_rows, window_cutoff, sn_query, _ARCHIVE_CAP)
        rows = [_row_display(r, module) for r in sliced]
        for r in rows:
            r["file"] = r["note"].replace("exported: ", "") if r["note"].startswith("exported: ") else ""
        return jsonify({"records": rows, "total": len(rows), "cumulative_total": full_count, "searched": bool(sn_query)})

    if status == "excluded":
        raw_rows = [r for r in sync_state.list_by_status("excluded", module=module) if (r.get("sync_note") or "") != "NO_GRADE"]
        sliced, full_count = _archive_slice(raw_rows, window_cutoff, sn_query, _ARCHIVE_CAP)
        rows = [_row_display(r, module) for r in sliced]
        for r in rows:
            # note is "excluded: <reason>" or "superseded by a newer test upload"
            r["reason"] = r["note"].replace("excluded: ", "") if r["note"].startswith("excluded: ") else r["note"]
        return jsonify({"records": rows, "total": len(rows), "cumulative_total": full_count, "searched": bool(sn_query)})

    if status == "no_grade":
        # T-Hard Drive only (see TASK_wipe_export.md section 2): grade is
        # auto-measured by the erasure software, not operator-fixable, so a
        # missing grade is neither ready nor an exception — gate_wipe.py
        # routes it to sync_status='excluded', note='NO_GRADE' exactly so it
        # lands here instead of the generic Excluded/Exceptions tabs.
        raw_rows = [r for r in sync_state.list_by_status("excluded", module=module) if (r.get("sync_note") or "") == "NO_GRADE"]
        sliced, full_count = _archive_slice(raw_rows, window_cutoff, sn_query, _ARCHIVE_CAP)
        rows = [_row_display(r, module) for r in sliced]
        return jsonify({"records": rows, "total": len(rows), "cumulative_total": full_count, "searched": bool(sn_query)})

    return jsonify({"error": "unknown status"}), 400


@blueprint.route("/api/counts")
def api_counts():
    production = request.args.get("production", "T-Laptop")
    if not _is_active(production):
        return jsonify({"ready": 0, "exceptions": 0, "exported": 0, "excluded": 0, "no_grade": 0})
    info = _info(production)
    module = info["module"]
    c = sync_state.counts(module=module)
    # 'excluded' bucket holds three distinct meanings (manual exclude /
    # superseded-by-newer-upload / NO_GRADE); split NO_GRADE out of the
    # generic excluded count the same way api_queue's "excluded" branch does.
    no_grade = 0
    excluded_total = c.get("excluded", 0)
    if excluded_total:
        no_grade = sum(
            1 for r in sync_state.list_by_status("excluded", module=module)
            if (r.get("sync_note") or "") == "NO_GRADE"
        )
    # Ready's badge is cumulative, same as the other four — the recency
    # window only shrinks the default *list* views (api_queue /
    # api_batch_lookup), never a badge count.
    return jsonify({
        "ready": c.get("ready", 0),
        "exceptions": c.get("pending", 0),
        "exported": c.get("synced", 0),
        "excluded": excluded_total - no_grade,
        "no_grade": no_grade,
    })


@blueprint.route("/api/rescan", methods=["POST"])
def api_rescan():
    data = request.get_json(silent=True) or {}
    production = data.get("production", "T-Laptop")
    if not _is_active(production):
        return jsonify({"scanned": 0, "ready": 0, "pending": 0,
                        "missing_file": 0, "errors": 0})
    info = _info(production)

    if info["rescan_fn"] is not None:
        # Background-only productions (T-Hard Drive): a full run can take
        # ~20 minutes against the real wipe table, so it must never run
        # inline on this request — kick it off and return immediately. The
        # queues fill in as the background thread progresses; the operator
        # can hit Rescan again later to see if it's done (a run already in
        # flight is a safe no-op, see wipe_sync.sync_all()'s busy guard).
        info["rescan_fn"]()
        return jsonify({
            "started": True, "scanned": 0, "ready": 0, "pending": 0, "errors": 0,
            "note": "Running in the background — this can take a while for the full database.",
        })

    summary = _scan.scan_pending(
        config=info["config"](), module=info["module"],
        context_builder=info["context_builder"], gate_fn=info["gate_fn"],
    )
    return jsonify(summary)


@blueprint.route("/api/export", methods=["POST"])
def api_export():
    data = request.get_json(silent=True) or {}
    paths = data.get("history_paths") or []
    production = data.get("production", "T-Laptop")
    info = _info(production)
    try:
        result = exporter.export_ready(
            paths, config_map=info["config"](), module=info["module"],
            context_builder=info["context_builder"], filename_prefix=info["filename_prefix"],
            gate_fn=info["gate_fn"],
        )
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
    production = data.get("production", "T-Laptop")
    if not hp:
        return jsonify({"error": "history_path required"}), 400
    if not reason:
        return jsonify({"error": "a reason is required to exclude"}), 400
    sync_state.set_status(hp, "excluded", note=f"excluded: {reason}", module=_info(production)["module"])
    return jsonify({"status": "ok", "history_path": hp, "reason": reason})


# --- scan-to-batch export workflow (TASK_export_batch.md) -----------------
# All routes below share one blueprint/prefix with everything above
# (/cyclelution/api/batch/...) rather than a separate per-module blueprint:
# the batch panel lives INSIDE this same export page's Ready tab (see the
# task's "page" section), so it belongs with the rest of this page's API,
# addressed by `production` like every other route here — not a new
# `/{module}/api/batch` surface under modules/laptop|gpu|wipe, which serve
# unrelated pages (module dashboards, wipe log-scan status).


def _batch_config(production: str) -> dict:
    return (_info(production)["config"]() or {}).get("batch") or {}


# Filter kinds that map to a date value (row.record_ts, no envelope read
# needed) vs. kinds that need a field only present inside the envelope
# payload (operator/test_station -> _row_display()). Keeping this
# distinction is what lets wipe's date-only filtering stay cheap even
# though the mechanism below is fully generic (task: "adding grade/model
# etc. later only needs extending this enum, not the plumbing").
_DATE_FILTER_KINDS = {"wipe_date", "test_date"}


def _filter_field(disp: dict, kind: str) -> str:
    if kind in _DATE_FILTER_KINDS:
        return disp.get("date") or ""
    if kind == "operator":
        return disp.get("operator") or ""
    if kind == "test_station":
        return disp.get("test_station") or ""
    return ""


@blueprint.route("/api/batch/facets")
def api_batch_facets():
    """Right-column stats + filter-dropdown OPTIONS for the scan panel:
    Ready pool total + distinct values per this production's configured
    `filters` kinds, WITHOUT preloading the record list itself (task
    section 'layout when batch mode is enabled': "Ready pool total, don't
    preload the list"). Same window as the Ready tab (recency.cutoff_date).

    Options are deduped from the CURRENT Ready pool, not full history (task:
    "options are deduped from the current Ready pool, not the whole DB, to
    avoid a choice that turns out to have zero results"), and each filter
    kind's option list is computed independently of any
    OTHER filter's current selection — picking a date never narrows what
    shows up in the operator dropdown, or vice versa."""
    production = request.args.get("production", "T-Laptop")
    if not _is_active(production):
        return jsonify({"total": 0, "options": {}})
    info = _info(production)
    module = info["module"]
    batch_cfg = _batch_config(production)
    filter_kinds = batch_cfg.get("filters") or []
    window_cutoff = recency.cutoff_date(info["config"]().get("ready_window_days", 30))
    rows = [r for r in sync_state.list_by_status("ready", module=module) if (r.get("record_ts") or "") >= window_cutoff]

    options = {}
    for kind in filter_kinds:
        if kind in _DATE_FILTER_KINDS:
            # Cheap path: record_ts already lives on the sync_state row,
            # no envelope file read needed.
            vals = {(r.get("record_ts") or "")[:10] for r in rows if r.get("record_ts")}
            options[kind] = sorted(vals, reverse=True)
        else:
            # operator/test_station only exist inside the envelope payload.
            vals = set()
            for r in rows:
                v = _filter_field(_row_display(r, module), kind)
                if v and v != "—":
                    vals.add(v)
            options[kind] = sorted(vals)
    return jsonify({"total": len(rows), "options": options})


@blueprint.route("/api/batch/current")
def api_batch_current():
    production = request.args.get("production", "T-Laptop")
    if not _is_active(production):
        return jsonify(None)
    module = _info(production)["module"]
    batch = batch_store.get_current(production)
    if not batch:
        return jsonify(None)
    items = batch_store.list_items(batch["batch_id"])
    return jsonify({
        "batch_id": batch["batch_id"],
        "slot_numbers": bool(batch["slot_numbers"]),
        "count": len(items),
        "items": [_batch_item_display(i, module) for i in items],
    })


@blueprint.route("/api/batch/create", methods=["POST"])
def api_batch_create():
    """Not called by the normal UI flow (see api_batch_add's auto-create) —
    kept for manual reopen after an export and for debug/curl use (task
    section 'POST /create')."""
    data = request.get_json(silent=True) or {}
    production = data.get("production", "T-Laptop")
    operator_id = data.get("operator_id")
    if not _is_active(production):
        return jsonify({"error": "inactive production"}), 400
    info = _info(production)
    batch_cfg = _batch_config(production)
    if not batch_cfg.get("enabled"):
        return jsonify({"error": "batch mode not enabled for this production"}), 400
    try:
        batch = batch_store.create_batch(
            production, info["module"], batch_cfg.get("slot_numbers", False),
            operator_id=operator_id,
        )
    except batch_store.BatchConflictError as e:
        return jsonify({"error": "batch_open", "batch_id": e.batch_id}), 409
    return jsonify(batch), 201


@blueprint.route("/api/batch/lookup", methods=["POST"])
def api_batch_lookup():
    """Dual-purpose (task 'scan box is also the filter box'): with the scan
    panel's live typing this drives the left-pool's real-time filtered/
    paginated listing; on Enter the frontend uses this same response's
    `total` to decide add-directly (1) / show-the-list (2+) / error (0).
    Also serves the plain paginated browse view when `query` is empty.

    `filters` is a {kind: value} dict, keys drawn from this production's
    configured `batch.filters` list (task section 'filters possible
    values'): wipe_date/test_date (date), operator, test_station. All
    active filters AND together with each other and the SN query (task:
    "filters AND together, and with the scan box's SN filter, all at
    once"). Date-kind filters stay on the cheap sync_state.record_ts path;
    any other kind only pays for a per-row envelope read (_row_display)
    when it's actually selected.

    Excludes any SN already claimed by the current production's open batch
    — an added record must disappear from the pool (task: "an added record
    disappears from the left column").

    The default (query-less) browse is windowed to `ready_window_days`
    (same cutoff as api_batch_facets' dropdown options), so the pool
    doesn't grow unbounded as history accumulates. A typed SN query bypasses
    the window entirely — same precedent as _archive_slice — so an operator
    scanning/typing a specific old-but-still-ready SN never gets a false
    "not found"."""
    data = request.get_json(silent=True) or {}
    production = data.get("production", "T-Laptop")
    query = (data.get("query") or "").strip()
    filters_in = {k: (v or "").strip() for k, v in (data.get("filters") or {}).items()}
    try:
        page = max(1, int(data.get("page") or 1))
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = max(1, min(200, int(data.get("page_size") or 40)))
    except (TypeError, ValueError):
        page_size = 40

    if not _is_active(production):
        return jsonify({"candidates": [], "total": 0, "reason": "inactive_production"})

    info = _info(production)
    module = info["module"]
    batch_cfg = _batch_config(production)
    filter_kinds = batch_cfg.get("filters") or []
    q = query.lower()
    window_cutoff = recency.cutoff_date(info["config"]().get("ready_window_days", 30))

    current = batch_store.get_current(production)
    claimed = {i["record_sn"] for i in batch_store.list_items(current["batch_id"])} if current else set()

    active_date_kind = next(
        (k for k in filter_kinds if k in _DATE_FILTER_KINDS and filters_in.get(k)), None,
    )
    active_rich_kinds = [k for k in filter_kinds if k not in _DATE_FILTER_KINDS and filters_in.get(k)]

    matches = []
    for r in sync_state.list_by_status("ready", module=module):
        sn = r.get("sn") or ""
        if sn in claimed:
            continue
        if q and q not in sn.lower():
            continue
        if not q and (r.get("record_ts") or "") < window_cutoff:
            continue
        if active_date_kind and (r.get("record_ts") or "")[:10] != filters_in[active_date_kind]:
            continue
        if active_rich_kinds:
            disp = _row_display(r, module)
            if any(_filter_field(disp, k) != filters_in[k] for k in active_rich_kinds):
                continue
        matches.append(r)
    matches.sort(key=lambda r: r.get("record_ts") or "", reverse=True)

    total = len(matches)
    reason = _diagnose_batch_miss(query, production, module) if (total == 0 and query) else None
    start = (page - 1) * page_size
    page_rows = matches[start:start + page_size]
    return jsonify({
        "candidates": [_row_display(r, module) for r in page_rows],
        "total": total, "reason": reason,
    })


@blueprint.route("/api/batch/add", methods=["POST"])
def api_batch_add():
    data = request.get_json(silent=True) or {}
    production = data.get("production", "T-Laptop")
    record_sn = (data.get("record_sn") or "").strip()
    input_mode = data.get("input_mode") or "manual"
    if not _is_active(production):
        return jsonify({"error": "inactive production"}), 400
    if not record_sn:
        return jsonify({"error": "record_sn required"}), 400
    if input_mode not in ("scan", "manual"):
        return jsonify({"error": "invalid input_mode"}), 400

    info = _info(production)
    module = info["module"]
    batch_cfg = _batch_config(production)
    if not batch_cfg.get("enabled"):
        return jsonify({"error": "batch mode not enabled for this production"}), 400

    # Validation order per TASK_export_batch_new.md's POST /add: (1) SN is
    # in the Ready pool (exact match only — hard rule #6, no fuzzy auto
    # -match), (2) SN not already claimed by another open batch, (3) auto
    # -create an open batch if none exists (hard rule #5 — no "start batch"
    # action; /add itself creates one the moment it's needed). (2) is
    # re-checked atomically inside add_item() regardless of the pre-check
    # here (hard rule #1: never trust a prior read alone).
    ready_row = _ready_row_for_sn(record_sn, module)
    if not ready_row:
        reason = _diagnose_batch_miss(record_sn, production, module)
        return jsonify({"error": "not_ready", "reason": reason}), 400

    other_batch = batch_store.sn_open_batch(record_sn, production)
    if other_batch:
        return jsonify({
            "error": "already_in_batch", "reason": f"already in batch {other_batch}", "batch_id": other_batch,
        }), 409

    batch = batch_store.get_current(production)
    if not batch:
        try:
            batch = batch_store.create_batch(production, module, batch_cfg.get("slot_numbers", False))
        except batch_store.BatchConflictError as e:
            # Lost a create race to a concurrent scan -- add into the
            # batch that won instead of failing this scan.
            batch = batch_store.get_batch(e.batch_id)

    try:
        result = batch_store.add_item(batch["batch_id"], record_sn, bool(batch["slot_numbers"]),
                                       input_mode, production)
    except batch_store.BatchConflictError as e:
        if e.batch_id == batch["batch_id"]:
            return jsonify({"error": "already_in_batch", "reason": "already scanned into this batch"}), 409
        return jsonify({"error": "claimed_by_other_batch", "reason": str(e), "batch_id": e.batch_id}), 409
    except ValueError as e:
        return jsonify({"error": "batch_not_open", "reason": str(e)}), 400

    disp = _row_display(ready_row, module)
    return jsonify({
        "batch_id": result["batch_id"], "record_sn": result["record_sn"], "slot_no": result["slot_no"],
        "vendor": disp["vendor"], "model": disp["model"], "grade": disp["grade"], "capacity": disp["capacity"],
    }), 201


@blueprint.route("/api/batch/remove", methods=["POST"])
def api_batch_remove():
    data = request.get_json(silent=True) or {}
    production = data.get("production", "T-Laptop")
    record_sn = (data.get("record_sn") or "").strip()
    if not record_sn:
        return jsonify({"error": "record_sn required"}), 400
    batch = batch_store.get_current(production)
    if not batch:
        return jsonify({"error": "no_open_batch"}), 400
    removed = batch_store.remove_item(batch["batch_id"], record_sn)
    if not removed:
        return jsonify({"error": "not in batch"}), 404
    return jsonify({"status": "ok", "record_sn": record_sn})


@blueprint.route("/api/batch/cancel", methods=["POST"])
def api_batch_cancel():
    data = request.get_json(silent=True) or {}
    production = data.get("production", "T-Laptop")
    batch = batch_store.get_current(production)
    if not batch:
        return jsonify({"error": "no_open_batch"}), 400
    batch_store.cancel_batch(batch["batch_id"])
    return jsonify({"status": "ok", "batch_id": batch["batch_id"]})


@blueprint.route("/api/batch/export", methods=["POST"])
def api_batch_export():
    data = request.get_json(silent=True) or {}
    production = data.get("production", "T-Laptop")
    info = _info(production)
    module = info["module"]

    batch = batch_store.get_current(production)
    if not batch:
        return jsonify({"error": "no_open_batch"}), 400
    items = batch_store.list_items_for_export(batch["batch_id"])
    if not items:
        return jsonify({"error": "batch is empty"}), 400

    # slot_no order -> history_path order (task /export: "row order follows slot_no ascending").
    paths, missing = [], []
    for it in items:
        ready_row = _ready_row_for_sn(it["record_sn"], module)
        (paths if ready_row else missing).append(ready_row["history_path"] if ready_row else it["record_sn"])
    if missing:
        return jsonify({"error": f"no longer ready, remove and rescan: {', '.join(missing)}"}), 400

    try:
        result = exporter.export_ready(
            paths, config_map=info["config"](), module=module,
            context_builder=info["context_builder"], filename_prefix=info["filename_prefix"],
            gate_fn=info["gate_fn"],
        )
    except exporter.ExportError as e:
        return jsonify({"error": str(e)}), 400

    batch_store.mark_exported(batch["batch_id"], result["file"])
    fname = Path(result["file"]).name
    result["download_url"] = f"/cyclelution/api/download/{fname}"
    result["batch_id"] = batch["batch_id"]
    return jsonify(result)


@blueprint.route("/api/batch/redownload", methods=["POST"])
def api_batch_redownload():
    data = request.get_json(silent=True) or {}
    batch_id = data.get("batch_id")
    production = data.get("production", "T-Laptop")
    if not batch_id:
        return jsonify({"error": "batch_id required"}), 400
    batch = batch_store.get_batch(batch_id)
    if not batch or batch["status"] != "exported":
        return jsonify({"error": "batch not exported"}), 400

    # Primary path: re-serve the already-written file — this is what
    # actually guarantees byte-for-byte identity with the first export
    # (task /export verification). No state change either way.
    fpath = Path(batch["export_file"]) if batch["export_file"] else None
    if fpath and fpath.exists():
        return jsonify({"file": str(fpath), "download_url": f"/cyclelution/api/download/{fpath.name}"})

    # Fallback: the file was deleted out from under the batch. Best-effort
    # regenerate from the now-`synced` records (see exporter.rebuild_file).
    info = _info(production)
    module = info["module"]
    paths = []
    for it in batch_store.list_items_for_export(batch_id):
        rows = sync_state.list_by_sn(it["record_sn"], module=module)
        synced_row = next((r for r in rows if r["sync_status"] == "synced"), None)
        if synced_row:
            paths.append(synced_row["history_path"])
    if not paths:
        return jsonify({"error": "original export file missing and no synced records to rebuild from"}), 400

    out_path = fpath or (exporter._default_out_dir() / f"adjust_{info['filename_prefix']}_{batch_id}_redownload.xlsx")
    try:
        result = exporter.rebuild_file(paths, out_path, config_map=info["config"](),
                                        context_builder=info["context_builder"])
    except exporter.ExportError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"file": result["file"], "download_url": f"/cyclelution/api/download/{Path(result['file']).name}"})


@blueprint.route("/api/batch/print/<batch_id>")
def api_batch_print(batch_id):
    batch = batch_store.get_batch(batch_id)
    if not batch:
        return "batch not found", 404
    production = request.args.get("production", "T-Laptop")
    module = _info(production)["module"]
    items = batch_store.list_items_for_export(batch_id)  # slot_no ascending
    rows = [_batch_item_display(i, module) for i in items]
    return render_template("batch_print.html", batch=batch, rows=rows)
