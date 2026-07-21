# monitorcenter/modules/laptop — Laptop Test Server Module

Scope: this directory only. Root [`CLAUDE.md`](../../../CLAUDE.md) has the
whole-project overview; this file is loaded in addition to it whenever
work happens inside `modules/laptop/`.

## What this is

The Flask module that receives, stores, and displays reports from
[`laptop_client/laptop_test.sh`](../../../laptop_client/laptop_test.sh)
(see that directory's own `CLAUDE.md` for the client side / JSON field
contract).

```
modules/laptop/
├── module.py           LaptopModule class + Flask blueprint + all routes
├── schema.json          Frontend display schema (key_value/status_grid/list/camera_image sections)
└── templates/
    └── module.html      Today/Week/Month/Custom tabs — Alpine.js, uses static/js/app.js
```

The frontend logic (`static/js/app.js`) is **shared** by this module's
`module.html` — it is **not** the same file used by `cpu`, `gpu`, or
`wipe`, which each have their own dashboard template with Alpine logic
inlined directly in `templates/<module>/dashboard.html`. Don't assume a
change here propagates to those modules, and don't assume their patterns
apply here without checking first.

## `module.py` — key pieces

- **`extract_envelope(raw_payload)`** — builds the standard envelope
  (`sn` ← `system.serial_number`, `timestamp` ← `test_info.test_time`).
  Calls `_downgrade_noncritical_fails()` then `_compute_overall_result()`.
- **`CRITICAL_FAIL_FIELDS`** — `{(keyboard, keys_check), (keyboard,
  touchpad_check)}`. Only these can produce a server-side `FAIL`.
  **Note**: the client script computes its own `OVERALL` with a different
  (larger) critical set before upload — see
  [[laptop_client CLAUDE.md]] for the mismatch. Don't "fix" one to match
  the other without checking both sides and asking first.
- **`_downgrade_noncritical_fails()`** — mutates payload in place: any
  `"FAIL"` outside `CRITICAL_FAIL_FIELDS` becomes `"WARNING"`, so every
  downstream consumer (Test Results grid, status dots, fail_reasons stats)
  sees a pre-normalized payload without special-casing.
- **`compute_verdict()`** — builds the human-readable `summary` +
  `warnings[]` (battery low, camera driver init failed, etc).
- **`_compute_by_grade(records)`** — grade distribution widget backend.
  Reads `payload.manual_input.grade`, which is a full string like
  `"Grade B"` (**not** a bare letter) — takes `.split()[-1]` to get the
  letter. Records missing `manual_input` or `grade` are skipped entirely
  (not counted in numerator or denominator). Always returns fixed
  `A → B → C` order, never sorted by count.
- **Cyclelution hook in `api_upload()`** — after storing the envelope,
  best-effort calls `cyclelution.sync_state.ensure_pending()` +
  `cyclelution.scan.evaluate_one()` so the record lands in
  Ready/Exceptions immediately. Wrapped in try/except — **a Cyclelution
  failure must never block the upload response**. See
  [[cyclelution-integration]] memory for the full export pipeline.

### Routes

```
GET  /laptop/                        dashboard (module.html)
POST /laptop/api/upload              raw JSON in, envelope out (201)
GET  /laptop/api/latest              today's records
GET  /laptop/api/search?sn=XXX       cross-SN history
GET  /laptop/api/schema              schema.json passthrough
GET  /laptop/api/stats               today KPIs + by_grade
GET  /laptop/api/stats/total         all-time count (rglob over history/)
GET  /laptop/api/stats/range         week|month|from+to → KPIs, brands,
                                      by_grade, fail_reasons, daily, records
```

`api_stats_range()` is the one endpoint every tab (Week/Month/Custom)
calls with different query params — if you add a new aggregate (like
`by_grade` was added), it goes in this one function, not duplicated per
tab.

## `schema.json`

Declares how the frontend's generic `renderer.js` (in `static/js/`,
shared across laptop only — see note above) draws the detail-card
sections: System, Manual Input, Hardware, Storage (list), Camera
(camera_image, reads `payload.camera.image_base64`), Test Results
(status_grid). **This is the source of truth for exact `payload.*` field
paths** — check it before guessing a field path from a raw JSON sample,
since some paths (e.g. `payload.manual_input.grade`) aren't obvious from
casual inspection of older records that predate a field's introduction.

## `templates/module.html`

Four tabs (`activeTab`: `today` / `week` / `month` / `custom`), each with
its own state object in `app.js` (`today`, `week`, `month`, `custom`).

- **Today**: KPI strip + standalone `By Grade` widget + record cards
  (grouped All / By Operator).
- **Week / Month / Custom**: KPI strip + three-column stats row
  (`By Grade | By Brand | Fail Reasons`, class `three-col-stats`, collapses
  to one column under 1200px — see `dashboard.css`) + Daily Volume chart +
  record list.
- **Custom** additionally has date pickers + Apply button gated by
  `customLoading` (disabled + "Loading…" label while a request is
  in-flight, `try/finally` in `loadCustom()`) to prevent duplicate
  requests from double-clicks.

`By Grade` is intentionally listed **first** in that three-column row (not
alphabetical/original order) — a UI decision, not accidental; if you're
tempted to reorder, ask first since it was explicitly requested.

Grade widget color scheme is deliberately **not** reused from
pass/warn/fail semantic colors — `gradeColor()` in `app.js` uses distinct
standout colors (`A` green `#22c55e`, `B` blue `#3b82f6`, `C` red-pink
`#f43f5e`) plus a blue accent border on the widget panel, so it reads as
its own category rather than a pass/fail signal.

## Editing rules

1. Never rename a `payload.*` field without checking `schema.json`,
   `_compute_by_grade()` / other aggregate functions, and the client
   script's JSON output in the same change.
2. `python -m py_compile modules/laptop/module.py` after any Python edit.
3. Don't modify `core/storage.py` or `core/index_db.py` from here — module
   code stays in `modules/laptop/`.
4. Test rendering without the full app if `modules/wipe` fails to start
   locally (missing sqlite path is a known local-dev-only issue, unrelated
   to this module) — register just this blueprint on a bare `Flask(__name__)`
   and use `app.test_client()` / `render_template()` under
   `test_request_context()`.
