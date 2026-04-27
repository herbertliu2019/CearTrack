# Task: Rename to CearTrack + Add Statistics Tab

## Part 1: Rename monitorcenter to CearTrack

### Files to modify:

**`templates/base.html`:**
```html
<!-- Change -->
<title>{% block title %}Monitorcenter{% endblock %}</title>
<h1>Monitor Center</h1>

<!-- To -->
<title>{% block title %}CearTrack{% endblock %}</title>
<h1>CearTrack</h1>
```

**`templates/index.html`:**
```html
<!-- Change -->
<h1 style="...">Monitor Center</h1>
<p>Hardware Test Aggregation Dashboard</p>

<!-- To -->
<h1 style="...">CearTrack</h1>
<p>Cear Hardware Test &amp; Traceability Platform</p>
```

---

## Part 2: Add Statistics Tab

### 2a. New API endpoint in `modules/laptop/module.py`

Add `GET /laptop/api/stats/range` endpoint.

IMPORTANT: record_list must include full `payload` so frontend can expand details.

```python
@blueprint.route("/api/stats/range")
def api_stats_range():
    """
    Query params:
      range=week   → last 7 days
      range=month  → last 30 days
      from=YYYY-MM-DD&to=YYYY-MM-DD → custom range
    """
    from datetime import datetime, timedelta
    import json

    range_param = request.args.get("range")
    from_param  = request.args.get("from")
    to_param    = request.args.get("to")

    today = datetime.now().date()

    if range_param == "week":
        date_from = today - timedelta(days=6)
        date_to   = today
    elif range_param == "month":
        date_from = today - timedelta(days=29)
        date_to   = today
    elif from_param and to_param:
        try:
            date_from = datetime.strptime(from_param, "%Y-%m-%d").date()
            date_to   = datetime.strptime(to_param,   "%Y-%m-%d").date()
        except ValueError:
            return jsonify({"error": "Invalid date format, use YYYY-MM-DD"}), 400
    else:
        return jsonify({"error": "Provide range=week|month or from+to params"}), 400

    base = config.BASE_DIR / "laptop" / "history"
    records = []
    current = date_from
    while current <= date_to:
        year   = current.strftime("%Y")
        mmdd   = current.strftime("%m-%d")
        day_dir = base / year / mmdd
        if day_dir.exists():
            for f in day_dir.glob("*.json"):
                try:
                    with open(f) as fh:
                        records.append(json.load(fh))
                except Exception:
                    pass
        current += timedelta(days=1)

    total  = len(records)
    passed = sum(1 for r in records if r.get("overall_result") == "PASS")
    failed = total - passed

    # Brand distribution
    brands = {}
    for r in records:
        vendor = r.get("payload", {}).get("system", {}).get("vendor", "Unknown")
        if "Dell"    in vendor: vendor = "Dell"
        elif "HP"    in vendor or "Hewlett" in vendor: vendor = "HP"
        elif "Lenovo" in vendor: vendor = "Lenovo"
        elif "Microsoft" in vendor: vendor = "Microsoft"
        elif "Apple" in vendor: vendor = "Apple"
        brands[vendor] = brands.get(vendor, 0) + 1

    # Common fail reasons
    fail_reasons = {}
    for r in records:
        if r.get("overall_result") != "FAIL":
            continue
        payload = r.get("payload", {})
        checks = [
            ("Screen",     payload.get("screen",    {}).get("dead_pixel_check")),
            ("Camera",     payload.get("camera",    {}).get("device_status")),
            ("Speaker",    payload.get("audio",     {}).get("speaker_quality_check")),
            ("Microphone", payload.get("audio",     {}).get("mic_record_check")),
            ("Keyboard",   payload.get("keyboard",  {}).get("keys_check")),
            ("Touchpad",   payload.get("keyboard",  {}).get("touchpad_check")),
            ("Battery",    payload.get("battery",   {}).get("status")),
            ("Network",    payload.get("network",   {}).get("internet_test")),
            ("Ports",      payload.get("ports",     {}).get("physical_check")),
            ("Appearance", payload.get("appearance",{}).get("scratch_check")),
        ]
        for label, val in checks:
            if val == "FAIL":
                fail_reasons[label] = fail_reasons.get(label, 0) + 1

    brands_sorted       = sorted(brands.items(),       key=lambda x: x[1], reverse=True)
    fail_reasons_sorted = sorted(fail_reasons.items(), key=lambda x: x[1], reverse=True)

    # Record list — include full payload so frontend can expand
    record_list = [
        {
            "sn":             r.get("sn"),
            "timestamp":      r.get("timestamp"),
            "overall_result": r.get("overall_result"),
            "model":          r.get("payload", {}).get("system", {}).get("model", ""),
            "vendor":         r.get("payload", {}).get("system", {}).get("vendor", ""),
            "summary":        r.get("summary", ""),
            "payload":        r.get("payload", {}),
        }
        for r in sorted(records, key=lambda x: x.get("timestamp",""), reverse=True)
    ]

    return jsonify({
        "date_from":    str(date_from),
        "date_to":      str(date_to),
        "total":        total,
        "passed":       passed,
        "failed":       failed,
        "pass_rate":    round(passed / total * 100, 1) if total else 0,
        "brands":       brands_sorted,
        "fail_reasons": fail_reasons_sorted,
        "records":      record_list,
    })
```

### 2b. Add CSS bar chart styles to `static/css/dashboard.css`

Add these styles:

```css
/* Bar chart rows */
.bar-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 0;
  border-bottom: 1px solid var(--border);
}
.bar-label { width: 120px; flex-shrink: 0; font-size: 0.9em; }
.bar-track {
  flex: 1;
  height: 14px;
  background: var(--bg-secondary);
  border-radius: 3px;
  overflow: hidden;
}
.bar-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.4s ease;
}
.bar-fill.brand { background: var(--accent); }
.bar-fill.fail  { background: var(--fail); }
.bar-count {
  width: 30px;
  text-align: right;
  font-weight: 600;
  font-size: 0.9em;
  flex-shrink: 0;
}

/* Stats record list */
.stats-record-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 0;
  border-bottom: 1px solid var(--border);
  cursor: pointer;
}
.stats-record-row:hover { background: var(--bg-secondary); padding-left: 8px; }
.stats-record-expand {
  background: var(--bg-secondary);
  border-radius: 6px;
  padding: 16px;
  margin: 4px 0 8px;
}
```

### 2c. Statistics tab HTML in `modules/laptop/templates/module.html`

Add tab button alongside Latest and SN Search:
```html
<button class="tab-btn" :class="{active: activeTab==='stats'}"
        @click="activeTab='stats'; loadStatsRange()">Statistics</button>
```

Add tab content panel after SN Search panel:

```html
<!-- STATISTICS TAB -->
<div class="tab-content" :class="{active: activeTab==='stats'}">

  <!-- Range selector -->
  <div style="display:flex; gap:10px; margin-bottom:20px; align-items:center; flex-wrap:wrap;">
    <button class="tab-btn" :class="{active: statsRange==='week'}"
            @click="statsRange='week'; loadStatsRange()">This Week</button>
    <button class="tab-btn" :class="{active: statsRange==='month'}"
            @click="statsRange='month'; loadStatsRange()">This Month</button>
    <button class="tab-btn" :class="{active: statsRange==='custom'}"
            @click="statsRange='custom'">Custom Range</button>
    <template x-if="statsRange==='custom'">
      <span style="display:flex; gap:8px; align-items:center;">
        <input type="date" x-model="statsFrom"
               style="background:var(--bg-card);border:1px solid var(--border);
                      color:var(--text-primary);padding:6px 10px;border-radius:4px;">
        <span style="color:var(--text-secondary)">to</span>
        <input type="date" x-model="statsTo"
               style="background:var(--bg-card);border:1px solid var(--border);
                      color:var(--text-primary);padding:6px 10px;border-radius:4px;">
        <button @click="loadStatsRange()"
                style="padding:6px 16px;background:var(--accent);color:var(--bg-primary);
                       border:none;border-radius:4px;cursor:pointer;font-weight:600;">
          Apply
        </button>
      </span>
    </template>
  </div>

  <!-- Summary stat cards -->
  <div class="stats-strip" x-show="statsData">
    <div class="stat-card">
      <div class="stat-label">Total Tested</div>
      <div class="stat-value" x-text="statsData?.total ?? 0"></div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Passed</div>
      <div class="stat-value" style="color:var(--pass)" x-text="statsData?.passed ?? 0"></div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Failed</div>
      <div class="stat-value" style="color:var(--fail)" x-text="statsData?.failed ?? 0"></div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Pass Rate</div>
      <div class="stat-value" x-text="(statsData?.pass_rate ?? 0) + '%'"></div>
    </div>
  </div>

  <!-- Brand distribution + Fail reasons with CSS bar charts -->
  <div style="display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:20px;"
       x-show="statsData">

    <!-- By Brand -->
    <div class="detail-panel">
      <h3 style="color:var(--accent);margin-bottom:14px;">By Brand</h3>
      <template x-for="[brand, count] in (statsData?.brands ?? [])" :key="brand">
        <div class="bar-row">
          <span class="bar-label" x-text="brand"></span>
          <div class="bar-track">
            <div class="bar-fill brand"
                 :style="`width:${Math.round(count / (statsData?.total || 1) * 100)}%`">
            </div>
          </div>
          <span class="bar-count" style="color:var(--accent)" x-text="count"></span>
        </div>
      </template>
      <div x-show="(statsData?.brands ?? []).length === 0"
           style="color:var(--text-secondary);">No data</div>
    </div>

    <!-- Common Fail Reasons -->
    <div class="detail-panel">
      <h3 style="color:var(--fail);margin-bottom:14px;">Common Fail Reasons</h3>
      <template x-if="(statsData?.fail_reasons ?? []).length === 0">
        <div style="color:var(--pass);">No failures in this period 🎉</div>
      </template>
      <template x-for="[reason, count] in (statsData?.fail_reasons ?? [])" :key="reason">
        <div class="bar-row">
          <span class="bar-label" x-text="reason"></span>
          <div class="bar-track">
            <div class="bar-fill fail"
                 :style="`width:${Math.round(count / (statsData?.failed || 1) * 100)}%`">
            </div>
          </div>
          <span class="bar-count" style="color:var(--fail)" x-text="count"></span>
        </div>
      </template>
    </div>
  </div>

  <!-- All Records table with expandable rows -->
  <div class="detail-panel" x-show="statsData">
    <h3 style="color:var(--accent);margin-bottom:12px;">
      All Records
      <span style="color:var(--text-secondary);font-size:0.85em;font-weight:normal;"
            x-text="' (' + (statsData?.date_from ?? '') + ' → ' + (statsData?.date_to ?? '') + ')'">
      </span>
    </h3>

    <!-- Table header -->
    <div style="display:grid;grid-template-columns:160px 1fr 1fr 100px;
                gap:8px;padding:6px 0;border-bottom:2px solid var(--border);
                color:var(--text-secondary);font-size:0.8em;text-transform:uppercase;
                letter-spacing:0.05em;">
      <span>Date</span>
      <span>SN</span>
      <span>Model</span>
      <span>Result</span>
    </div>

    <template x-for="r in (statsData?.records ?? [])" :key="r.sn + r.timestamp">
      <div>
        <!-- Row -->
        <div class="stats-record-row"
             @click="toggleStatsExpand(r.sn + '_' + r.timestamp)">
          <div style="display:grid;grid-template-columns:160px 1fr 1fr 100px;
                      gap:8px;width:100%;align-items:center;">
            <span style="color:var(--text-secondary);font-size:0.85em;"
                  x-text="r.timestamp?.slice(0,10)"></span>
            <span style="font-family:monospace;font-weight:600;" x-text="r.sn"></span>
            <span style="color:var(--text-secondary);font-size:0.85em;"
                  x-text="r.vendor + ' ' + r.model"></span>
            <span class="badge" :class="r.overall_result?.toLowerCase()"
                  x-text="r.overall_result"></span>
          </div>
          <span style="color:var(--text-secondary);margin-left:12px;"
                x-text="isStatsExpanded(r.sn + '_' + r.timestamp) ? '▲' : '▼'"></span>
        </div>

        <!-- Expandable detail -->
        <template x-if="isStatsExpanded(r.sn + '_' + r.timestamp)">
          <div class="stats-record-expand" x-html="renderDetails(r)"></div>
        </template>
      </div>
    </template>

    <div x-show="(statsData?.records ?? []).length === 0"
         style="color:var(--text-secondary);text-align:center;padding:20px;">
      No records in this period.
    </div>
  </div>

</div>
```

### 2d. Update `static/js/app.js`

Add to the `dashboardApp()` return object:

```javascript
// Statistics state
statsRange: 'week',
statsFrom: '',
statsTo: '',
statsData: null,
statsExpandedKeys: new Set(),

async loadStatsRange() {
    let url = `/${this.moduleName}/api/stats/range?`;
    if (this.statsRange === 'week') {
        url += 'range=week';
    } else if (this.statsRange === 'month') {
        url += 'range=month';
    } else {
        if (!this.statsFrom || !this.statsTo) return;
        url += `from=${this.statsFrom}&to=${this.statsTo}`;
    }
    const r = await fetch(url);
    this.statsData = await r.json();
    this.statsExpandedKeys = new Set(); // reset expand state on new load
},

toggleStatsExpand(key) {
    if (this.statsExpandedKeys.has(key)) {
        this.statsExpandedKeys.delete(key);
    } else {
        this.statsExpandedKeys.add(key);
    }
    this.statsExpandedKeys = new Set(this.statsExpandedKeys);
},

isStatsExpanded(key) {
    return this.statsExpandedKeys.has(key);
},
```

Note: `renderDetails(r)` already exists from task 03 — reuse it here.
The stats record objects include `payload` so `renderDetails()` works unchanged.

---

## Verification

```bash
curl "http://localhost:5004/laptop/api/stats/range?range=week"
# Should return brands array, fail_reasons array, records with payload
```

Browser checks:
1. Statistics tab → This Week → shows 4 stat cards + bar charts + record table
2. Brand bars proportional to count
3. Fail Reasons bars proportional to fail count
4. Click any record row → expands full detail (same as Latest tab)
5. Click again → collapses
6. Multiple rows can be expanded simultaneously
7. Switch to This Month → expand state resets
8. Custom Range → pick dates → Apply → data updates

## Constraints
- Do NOT modify storage.py or core/ files
- Do NOT change existing API endpoints (/api/latest, /api/search, /api/stats)
- reuse existing `renderDetails()` function — do not duplicate it
- reuse existing `isExpanded()`/`toggleExpand()` pattern for stats expand
- Run `python -m py_compile modules/laptop/module.py` after changes
