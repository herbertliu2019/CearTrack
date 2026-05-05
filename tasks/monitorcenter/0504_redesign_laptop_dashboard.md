# Task: Redesign Laptop Dashboard to Match Wipe Dashboard Layout

## Reference
Wipe dashboard (`dashboard.html`) is the design reference.
Laptop dashboard (`modules/laptop/templates/module.html`) must be restructured
to match wipe's layout and UX patterns.

---

## Layout Diff Analysis

| Element | Wipe (reference) | Laptop (current) | Action |
|---------|-----------------|------------------|--------|
| Search | Top bar, always visible, above tabs | Inside Search tab | **Move to top** |
| Tabs | Today / This Week / This Month / Custom Range | Today / Stats / Search | **Restructure** |
| Stats per tab | Each time tab has its own KPI strip | Single Stats tab | **Split into tabs** |
| By Brand | Inside week/month/custom tabs | Separate Stats tab | **Move into each tab** |
| Fail Reasons | Inside week/month/custom tabs | Separate Stats tab | **Move into each tab** |
| Daily Breakdown | Inside week/month/custom tabs | Not present | **Add** |
| Record list | Inside Today tab as cards | Inside Stats tab as table | **Move to Today tab** |
| Card expand | Single expand (one at a time) | Multi-expand (Set) | **Change to single** |

---

## New Tab Structure (match wipe exactly)

```
[ Today ]  [ This Week ]  [ This Month ]  [ Custom Range ]
```

Remove the current `Stats` and `Search` tabs.
Search moves above tabs (always visible).

---

## Part 1: New Alpine State in `static/js/app.js`

Replace `dashboardApp()` state with wipe-equivalent structure:

```javascript
function laptopApp(moduleName) {
  return {
    moduleName,
    activeTab: 'today',

    // Search (top bar, always visible)
    searchQ: '',
    searchResults: [],
    searched: false,

    // Per-tab data
    today:  { stats: {}, records: [] },
    week:   { stats: null, by_brand: [], fail_reasons: [], daily: [], start: null, end: null },
    month:  { stats: null, by_brand: [], fail_reasons: [], daily: [] },
    custom: { stats: null, by_brand: [], fail_reasons: [], daily: [] },

    customFrom: '',
    customTo:   '',
    detailOpen: null,   // single expand key (not a Set)
    schema: null,

    async init() {
      const r = await fetch(`/${this.moduleName}/api/schema`);
      this.schema = await r.json();
      await Promise.all([
        this.loadToday(),
        this.loadWeek(),
        this.loadMonth(),
      ]);
      // Poll today tab every 10s
      setInterval(() => {
        if (this.activeTab === 'today') this.loadToday();
      }, 10000);
    },

    async loadToday() {
      const r = await fetch(`/${this.moduleName}/api/latest`);
      const records = await r.json();
      const total  = records.length;
      const passed = records.filter(r => r.overall_result === 'PASS').length;
      const failed = total - passed;
      this.today = {
        stats: {
          total,
          passed,
          failed,
          pass_rate: total ? Math.round(passed / total * 100) : 0,
        },
        records,
      };
    },

    async loadWeek() {
      const r = await fetch(`/${this.moduleName}/api/stats/range?range=week`);
      const d = await r.json();
      this.week = {
        stats:       { total: d.total, passed: d.passed, failed: d.failed, pass_rate: d.pass_rate },
        by_brand:    (d.brands    ?? []).map(([name, count]) => ({ name, count })),
        fail_reasons:(d.fail_reasons ?? []).map(([reason, count]) => ({ reason, count })),
        daily:       d.daily ?? [],
        start:       d.date_from,
        end:         d.date_to,
      };
    },

    async loadMonth() {
      const r = await fetch(`/${this.moduleName}/api/stats/range?range=month`);
      const d = await r.json();
      this.month = {
        stats:       { total: d.total, passed: d.passed, failed: d.failed, pass_rate: d.pass_rate },
        by_brand:    (d.brands    ?? []).map(([name, count]) => ({ name, count })),
        fail_reasons:(d.fail_reasons ?? []).map(([reason, count]) => ({ reason, count })),
        daily:       d.daily ?? [],
      };
    },

    async loadCustom() {
      if (!this.customFrom || !this.customTo) return;
      const url = `/${this.moduleName}/api/stats/range?from=${this.customFrom}&to=${this.customTo}`;
      const d = await (await fetch(url)).json();
      this.custom = {
        stats:       { total: d.total, passed: d.passed, failed: d.failed, pass_rate: d.pass_rate },
        by_brand:    (d.brands    ?? []).map(([name, count]) => ({ name, count })),
        fail_reasons:(d.fail_reasons ?? []).map(([reason, count]) => ({ reason, count })),
        daily:       d.daily ?? [],
      };
    },

    async runSearch() {
      if (!this.searchQ.trim()) return;
      const r = await fetch(`/${this.moduleName}/api/search?sn=${encodeURIComponent(this.searchQ.trim())}`);
      this.searchResults = await r.json();
      this.searched = true;
    },

    clearSearch() {
      this.searchQ = '';
      this.searchResults = [];
      this.searched = false;
    },

    toggleDetail(key) {
      this.detailOpen = this.detailOpen === key ? null : key;
    },

    resultClass(result) {
      if (!result) return '';
      if (result === 'PASS') return 'pass';
      if (result === 'FAIL') return 'fail';
      return 'warn';
    },

    fmtRange(start, end) {
      if (!start || !end) return '';
      const fmt = d => { const p = d.split('-'); return p[1] + '/' + p[2]; };
      return fmt(start) + ' – ' + fmt(end);
    },

    renderDetails(record) {
      if (!this.schema) return '';
      return renderPayload(this.schema, record);
    },
  };
}
```

---

## Part 2: New `modules/laptop/templates/module.html`

Replace entire file with this structure:

```html
{% extends "base.html" %}
{% block title %}Laptop — CearTrack{% endblock %}
{% block content %}
<script src="{{ url_for('static', filename='js/renderer.js') }}"></script>
<script src="{{ url_for('static', filename='js/app.js') }}"></script>

<div x-data="laptopApp('{{ module_name }}')" x-init="init()">

  <!-- ── Top Bar: Search ──────────────────────────────────────────── -->
  <div style="display:flex;gap:12px;align-items:center;margin-bottom:20px;">
    <div class="search-box" style="width:60%;flex-shrink:0;margin-bottom:0;">
      <input type="text" x-model="searchQ" @keydown.enter="runSearch()"
             placeholder="Search by SN / Service Tag...">
      <button @click="runSearch()">Search</button>
      <button x-show="searched" @click="clearSearch()"
              style="background:transparent;color:var(--text-secondary);
                     border:1px solid var(--border);padding:6px 12px;
                     border-radius:4px;cursor:pointer;font-size:0.85em;">
        ✕ Clear
      </button>
    </div>
  </div>

  <!-- ── Search Results ────────────────────────────────────────────── -->
  <div x-show="searched" style="margin-bottom:24px;">
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px;">
      <span style="font-size:0.85em;font-weight:700;text-transform:uppercase;
                   letter-spacing:0.08em;color:var(--accent);">Search Results</span>
      <span style="color:var(--text-secondary);font-size:0.85em;"
            x-text="searchResults.length
              ? searchResults.length + ' record(s) found for \'' + searchQ + '\''
              : 'No records found for \'' + searchQ + '\''"></span>
    </div>
    <template x-for="r in searchResults" :key="r.sn + r.timestamp">
      <div class="detail-panel" style="margin-bottom:10px;">
        <div style="display:flex;justify-content:space-between;align-items:center;
                    margin-bottom:12px;cursor:pointer;"
             @click="toggleDetail('s_' + r.sn + r.timestamp)">
          <div>
            <div style="font-family:monospace;font-weight:700;font-size:1.05em;"
                 x-text="r.sn"></div>
            <div style="color:var(--text-secondary);font-size:0.85em;margin-top:2px;"
                 x-text="(r.payload?.system?.vendor ?? '') + ' ' + (r.payload?.system?.model ?? '') + '  •  ' + (r.timestamp ?? '').slice(0,10)">
            </div>
          </div>
          <div style="display:flex;align-items:center;gap:10px;">
            <span class="badge" :class="resultClass(r.overall_result)"
                  x-text="r.overall_result"></span>
            <span style="color:var(--text-secondary);font-size:0.8em;"
                  x-text="detailOpen === 's_' + r.sn + r.timestamp ? '▲' : '▼'"></span>
          </div>
        </div>
        <template x-if="detailOpen === 's_' + r.sn + r.timestamp">
          <div x-html="renderDetails(r)"></div>
        </template>
      </div>
    </template>
  </div>

  <!-- ── Tabs ─────────────────────────────────────────────────────── -->
  <div class="tabs">
    <button class="tab-btn" :class="{active: activeTab==='today'}"
            @click="activeTab='today'"><strong>Today</strong></button>
    <button class="tab-btn" :class="{active: activeTab==='week'}"
            @click="activeTab='week'"><strong>This Week</strong></button>
    <button class="tab-btn" :class="{active: activeTab==='month'}"
            @click="activeTab='month'"><strong>This Month</strong></button>
    <button class="tab-btn" :class="{active: activeTab==='custom'}"
            @click="activeTab='custom'"><strong>Custom Range</strong></button>
  </div>

  <!-- ══════════════════════════════════════════════════════════════
       TAB: TODAY
  ══════════════════════════════════════════════════════════════ -->
  <div x-show="activeTab==='today'">
    <div style="font-size:1em;font-weight:700;text-transform:uppercase;
                letter-spacing:0.08em;color:var(--text-primary);margin-bottom:16px;">
      Total Today
    </div>

    <!-- KPI strip -->
    <div class="stats-strip" style="grid-template-columns:repeat(4,1fr);margin-bottom:24px;">
      <div class="stat-card">
        <div class="stat-label">Total</div>
        <div class="stat-value" x-text="today.stats.total ?? 0"></div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Passed</div>
        <div class="stat-value" style="color:var(--pass);" x-text="today.stats.passed ?? 0"></div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Failed</div>
        <div class="stat-value" style="color:var(--fail);" x-text="today.stats.failed ?? 0"></div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Pass Rate</div>
        <div class="stat-value" x-text="(today.stats.pass_rate ?? 0) + '%'"></div>
      </div>
    </div>

    <!-- Today's records as cards -->
    <div style="display:flex;flex-direction:column;gap:8px;">
      <template x-for="r in today.records" :key="r.sn + r.timestamp">
        <div :class="'result-card ' + resultClass(r.overall_result)" style="margin:0;">
          <div class="card-summary" @click="toggleDetail(r.sn + r.timestamp)"
               style="cursor:pointer;">
            <div class="card-header">
              <div>
                <div class="card-sn" x-text="r.sn"></div>
                <div class="card-model"
                     x-text="(r.payload?.system?.vendor ?? '') + ' ' + (r.payload?.system?.model ?? '')">
                </div>
              </div>
              <span class="badge" :class="resultClass(r.overall_result)"
                    x-text="r.overall_result"></span>
            </div>
            <div class="card-body">
              <div class="card-spec"
                   x-text="(r.payload?.cpu?.model ?? '')"></div>
              <div class="card-spec"
                   x-text="(r.payload?.memory?.total_gb ?? '') + ' GB ' + (r.payload?.memory?.type ?? '') + '  •  Battery ' + (r.payload?.battery?.health_percent ?? '?') + '%'">
              </div>
            </div>
            <!-- Mini status dots -->
            <div style="display:flex;gap:10px;padding:6px 16px;
                        border-top:1px solid var(--border);flex-wrap:wrap;">
              <template x-for="item in [
                {label:'Screen', val: r.payload?.screen?.dead_pixel_check},
                {label:'Cam',    val: r.payload?.camera?.device_status},
                {label:'Audio',  val: r.payload?.audio?.speaker_quality_check},
                {label:'KB',     val: r.payload?.keyboard?.keys_check},
                {label:'Net',    val: r.payload?.network?.internet_test},
                {label:'Batt',   val: r.payload?.battery?.status}
              ]" :key="item.label">
                <span class="status-dot" :class="resultClass(item.val)">
                  <span x-text="item.label"></span>
                </span>
              </template>
            </div>
            <div class="card-footer"
                 x-text="(r.timestamp ?? '').replace('T',' ').slice(0,16)"></div>
          </div>
          <!-- Expanded detail -->
          <template x-if="detailOpen === r.sn + r.timestamp">
            <div class="detail-panel"
                 style="margin:0;border-radius:0;border-top:1px solid var(--border);">
              <div x-html="renderDetails(r)"></div>
            </div>
          </template>
        </div>
      </template>
      <div x-show="(today.records ?? []).length === 0"
           style="color:var(--text-secondary);text-align:center;padding:48px;
                  background:var(--bg-card);border-radius:8px;border:1px solid var(--border);">
        No laptops tested today.
      </div>
    </div>
  </div>

  <!-- ══════════════════════════════════════════════════════════════
       TAB: THIS WEEK
  ══════════════════════════════════════════════════════════════ -->
  <div x-show="activeTab==='week'">
    <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:16px;">
      <div style="font-size:1em;font-weight:700;text-transform:uppercase;
                  letter-spacing:0.08em;color:var(--text-primary);">This Week</div>
      <div style="color:var(--text-secondary);font-size:0.85em;"
           x-text="fmtRange(week.start, week.end)"></div>
    </div>

    <!-- KPI strip -->
    <div class="stats-strip" style="grid-template-columns:repeat(4,1fr);margin-bottom:24px;">
      <div class="stat-card"><div class="stat-label">Total</div>
        <div class="stat-value" x-text="week.stats?.total ?? 0"></div></div>
      <div class="stat-card"><div class="stat-label">Passed</div>
        <div class="stat-value" style="color:var(--pass);" x-text="week.stats?.passed ?? 0"></div></div>
      <div class="stat-card"><div class="stat-label">Failed</div>
        <div class="stat-value" style="color:var(--fail);" x-text="week.stats?.failed ?? 0"></div></div>
      <div class="stat-card"><div class="stat-label">Pass Rate</div>
        <div class="stat-value" x-text="(week.stats?.pass_rate ?? 0) + '%'"></div></div>
    </div>

    <!-- By Brand + Fail Reasons side by side -->
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:24px;">
      <div class="detail-panel" style="padding:16px 20px;">
        <div style="font-size:0.75em;font-weight:700;text-transform:uppercase;
                    letter-spacing:0.06em;color:var(--accent);margin-bottom:14px;">By Brand</div>
        <template x-if="!(week.by_brand ?? []).length">
          <div style="color:var(--text-secondary);font-size:0.88em;">No data</div>
        </template>
        <template x-for="item in (week.by_brand ?? [])" :key="item.name">
          <div style="margin-bottom:12px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:5px;">
              <span style="font-size:0.9em;" x-text="item.name"></span>
              <span style="font-weight:700;color:var(--accent);" x-text="item.count"></span>
            </div>
            <div style="height:4px;background:rgba(255,255,255,0.06);border-radius:2px;overflow:hidden;">
              <div style="height:100%;background:var(--accent);border-radius:2px;transition:width 0.5s;"
                   :style="'width:' + Math.round(item.count/(week.stats?.total||1)*100) + '%'"></div>
            </div>
          </div>
        </template>
      </div>
      <div class="detail-panel" style="padding:16px 20px;">
        <div style="font-size:0.75em;font-weight:700;text-transform:uppercase;
                    letter-spacing:0.06em;color:#e07b3a;margin-bottom:14px;">Fail Reasons</div>
        <template x-if="!(week.fail_reasons ?? []).length">
          <div style="color:var(--pass);font-size:0.88em;">No failures this week 🎉</div>
        </template>
        <template x-for="item in (week.fail_reasons ?? [])" :key="item.reason">
          <div style="margin-bottom:12px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:5px;">
              <span style="font-size:0.9em;" x-text="item.reason"></span>
              <span style="font-weight:700;color:#e07b3a;" x-text="item.count"></span>
            </div>
            <div style="height:4px;background:rgba(255,255,255,0.06);border-radius:2px;overflow:hidden;">
              <div style="height:100%;background:#e07b3a;border-radius:2px;transition:width 0.5s;"
                   :style="'width:' + Math.round(item.count/(week.stats?.failed||1)*100) + '%'"></div>
            </div>
          </div>
        </template>
      </div>
    </div>

    <!-- Daily Breakdown -->
    <div class="detail-panel" style="padding:16px 20px;">
      <div style="font-size:0.75em;font-weight:700;text-transform:uppercase;
                  letter-spacing:0.06em;color:var(--text-secondary);margin-bottom:12px;">
        Daily Breakdown
      </div>
      <div style="display:grid;grid-template-columns:140px 70px 80px 70px 1fr;gap:8px;
                  padding-bottom:8px;border-bottom:1px solid var(--border);
                  color:var(--text-secondary);font-size:0.75em;text-transform:uppercase;font-weight:600;">
        <span>Date</span><span>Total</span>
        <span style="color:var(--pass);">Passed</span>
        <span style="color:var(--fail);">Failed</span><span></span>
      </div>
      <template x-for="d in (week.daily ?? [])" :key="d.date">
        <div style="display:grid;grid-template-columns:140px 70px 80px 70px 1fr;
                    gap:8px;padding:8px 0;border-bottom:1px solid rgba(255,255,255,0.04);
                    align-items:center;font-size:0.88em;">
          <span style="color:var(--text-secondary);" x-text="d.date"></span>
          <span style="font-weight:600;" x-text="d.total"></span>
          <span style="color:var(--pass);font-weight:600;" x-text="d.passed"></span>
          <span style="color:var(--fail);font-weight:600;" x-text="d.failed"></span>
          <div style="height:5px;background:rgba(255,255,255,0.05);border-radius:3px;overflow:hidden;">
            <div style="height:100%;background:var(--pass);border-radius:3px;"
                 :style="'width:' + Math.round(d.passed/(d.total||1)*100) + '%'"></div>
          </div>
        </div>
      </template>
      <div x-show="!(week.daily ?? []).length"
           style="color:var(--text-secondary);font-size:0.85em;padding:12px 0;">
        No data this week.
      </div>
    </div>
  </div>

  <!-- ══════════════════════════════════════════════════════════════
       TAB: THIS MONTH
  ══════════════════════════════════════════════════════════════ -->
  <div x-show="activeTab==='month'">
    <div style="font-size:1em;font-weight:700;text-transform:uppercase;
                letter-spacing:0.08em;color:var(--text-primary);margin-bottom:16px;">
      This Month
    </div>

    <div class="stats-strip" style="grid-template-columns:repeat(4,1fr);margin-bottom:24px;">
      <div class="stat-card"><div class="stat-label">Total</div>
        <div class="stat-value" x-text="month.stats?.total ?? 0"></div></div>
      <div class="stat-card"><div class="stat-label">Passed</div>
        <div class="stat-value" style="color:var(--pass);" x-text="month.stats?.passed ?? 0"></div></div>
      <div class="stat-card"><div class="stat-label">Failed</div>
        <div class="stat-value" style="color:var(--fail);" x-text="month.stats?.failed ?? 0"></div></div>
      <div class="stat-card"><div class="stat-label">Pass Rate</div>
        <div class="stat-value" x-text="(month.stats?.pass_rate ?? 0) + '%'"></div></div>
    </div>

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:24px;">
      <div class="detail-panel" style="padding:16px 20px;">
        <div style="font-size:0.75em;font-weight:700;text-transform:uppercase;
                    letter-spacing:0.06em;color:var(--accent);margin-bottom:14px;">By Brand</div>
        <template x-if="!(month.by_brand ?? []).length">
          <div style="color:var(--text-secondary);font-size:0.88em;">No data</div>
        </template>
        <template x-for="item in (month.by_brand ?? [])" :key="item.name">
          <div style="margin-bottom:12px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:5px;">
              <span style="font-size:0.9em;" x-text="item.name"></span>
              <span style="font-weight:700;color:var(--accent);" x-text="item.count"></span>
            </div>
            <div style="height:4px;background:rgba(255,255,255,0.06);border-radius:2px;overflow:hidden;">
              <div style="height:100%;background:var(--accent);border-radius:2px;transition:width 0.5s;"
                   :style="'width:' + Math.round(item.count/(month.stats?.total||1)*100) + '%'"></div>
            </div>
          </div>
        </template>
      </div>
      <div class="detail-panel" style="padding:16px 20px;">
        <div style="font-size:0.75em;font-weight:700;text-transform:uppercase;
                    letter-spacing:0.06em;color:#e07b3a;margin-bottom:14px;">Fail Reasons</div>
        <template x-if="!(month.fail_reasons ?? []).length">
          <div style="color:var(--pass);font-size:0.88em;">No failures this month 🎉</div>
        </template>
        <template x-for="item in (month.fail_reasons ?? [])" :key="item.reason">
          <div style="margin-bottom:12px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:5px;">
              <span style="font-size:0.9em;" x-text="item.reason"></span>
              <span style="font-weight:700;color:#e07b3a;" x-text="item.count"></span>
            </div>
            <div style="height:4px;background:rgba(255,255,255,0.06);border-radius:2px;overflow:hidden;">
              <div style="height:100%;background:#e07b3a;border-radius:2px;transition:width 0.5s;"
                   :style="'width:' + Math.round(item.count/(month.stats?.failed||1)*100) + '%'"></div>
            </div>
          </div>
        </template>
      </div>
    </div>

    <div class="detail-panel" style="padding:16px 20px;">
      <div style="font-size:0.75em;font-weight:700;text-transform:uppercase;
                  letter-spacing:0.06em;color:var(--text-secondary);margin-bottom:12px;">
        Daily Breakdown
      </div>
      <div style="display:grid;grid-template-columns:140px 70px 80px 70px 1fr;gap:8px;
                  padding-bottom:8px;border-bottom:1px solid var(--border);
                  color:var(--text-secondary);font-size:0.75em;text-transform:uppercase;font-weight:600;">
        <span>Date</span><span>Total</span>
        <span style="color:var(--pass);">Passed</span>
        <span style="color:var(--fail);">Failed</span><span></span>
      </div>
      <template x-for="d in (month.daily ?? [])" :key="d.date">
        <div style="display:grid;grid-template-columns:140px 70px 80px 70px 1fr;
                    gap:8px;padding:8px 0;border-bottom:1px solid rgba(255,255,255,0.04);
                    align-items:center;font-size:0.88em;">
          <span style="color:var(--text-secondary);" x-text="d.date"></span>
          <span style="font-weight:600;" x-text="d.total"></span>
          <span style="color:var(--pass);font-weight:600;" x-text="d.passed"></span>
          <span style="color:var(--fail);font-weight:600;" x-text="d.failed"></span>
          <div style="height:5px;background:rgba(255,255,255,0.05);border-radius:3px;overflow:hidden;">
            <div style="height:100%;background:var(--pass);border-radius:3px;"
                 :style="'width:' + Math.round(d.passed/(d.total||1)*100) + '%'"></div>
          </div>
        </div>
      </template>
      <div x-show="!(month.daily ?? []).length"
           style="color:var(--text-secondary);font-size:0.85em;padding:12px 0;">
        No data this month.
      </div>
    </div>
  </div>

  <!-- ══════════════════════════════════════════════════════════════
       TAB: CUSTOM RANGE
  ══════════════════════════════════════════════════════════════ -->
  <div x-show="activeTab==='custom'">
    <div style="font-size:1em;font-weight:700;text-transform:uppercase;
                letter-spacing:0.08em;color:var(--text-primary);margin-bottom:16px;">
      Custom Range
    </div>

    <div style="display:flex;gap:10px;align-items:center;margin-bottom:20px;flex-wrap:wrap;">
      <input type="date" x-model="customFrom"
             style="background:var(--bg-card);border:1px solid var(--border);
                    color:var(--text-primary);padding:8px 14px;border-radius:4px;font-size:0.9em;">
      <span style="color:var(--text-secondary);">to</span>
      <input type="date" x-model="customTo"
             style="background:var(--bg-card);border:1px solid var(--border);
                    color:var(--text-primary);padding:8px 14px;border-radius:4px;font-size:0.9em;">
      <button @click="loadCustom()"
              style="padding:8px 22px;background:var(--accent);color:var(--bg-primary);
                     border:none;border-radius:4px;cursor:pointer;font-weight:700;font-size:0.9em;">
        Apply
      </button>
    </div>

    <template x-if="custom.stats">
      <div>
        <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:16px;">
          <span style="color:var(--text-secondary);font-size:0.88em;"
                x-text="fmtRange(customFrom, customTo) + '  (' + (custom.stats?.total ?? 0) + ' records)'">
          </span>
        </div>

        <div class="stats-strip" style="grid-template-columns:repeat(4,1fr);margin-bottom:24px;">
          <div class="stat-card"><div class="stat-label">Total</div>
            <div class="stat-value" x-text="custom.stats?.total ?? 0"></div></div>
          <div class="stat-card"><div class="stat-label">Passed</div>
            <div class="stat-value" style="color:var(--pass);" x-text="custom.stats?.passed ?? 0"></div></div>
          <div class="stat-card"><div class="stat-label">Failed</div>
            <div class="stat-value" style="color:var(--fail);" x-text="custom.stats?.failed ?? 0"></div></div>
          <div class="stat-card"><div class="stat-label">Pass Rate</div>
            <div class="stat-value" x-text="(custom.stats?.pass_rate ?? 0) + '%'"></div></div>
        </div>

        <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:24px;">
          <div class="detail-panel" style="padding:16px 20px;">
            <div style="font-size:0.75em;font-weight:700;text-transform:uppercase;
                        letter-spacing:0.06em;color:var(--accent);margin-bottom:14px;">By Brand</div>
            <template x-if="!(custom.by_brand ?? []).length">
              <div style="color:var(--text-secondary);font-size:0.88em;">No data</div>
            </template>
            <template x-for="item in (custom.by_brand ?? [])" :key="item.name">
              <div style="margin-bottom:12px;">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:5px;">
                  <span style="font-size:0.9em;" x-text="item.name"></span>
                  <span style="font-weight:700;color:var(--accent);" x-text="item.count"></span>
                </div>
                <div style="height:4px;background:rgba(255,255,255,0.06);border-radius:2px;overflow:hidden;">
                  <div style="height:100%;background:var(--accent);border-radius:2px;transition:width 0.5s;"
                       :style="'width:' + Math.round(item.count/(custom.stats?.total||1)*100) + '%'"></div>
                </div>
              </div>
            </template>
          </div>
          <div class="detail-panel" style="padding:16px 20px;">
            <div style="font-size:0.75em;font-weight:700;text-transform:uppercase;
                        letter-spacing:0.06em;color:#e07b3a;margin-bottom:14px;">Fail Reasons</div>
            <template x-if="!(custom.fail_reasons ?? []).length">
              <div style="color:var(--pass);font-size:0.88em;">No failures in this period 🎉</div>
            </template>
            <template x-for="item in (custom.fail_reasons ?? [])" :key="item.reason">
              <div style="margin-bottom:12px;">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:5px;">
                  <span style="font-size:0.9em;" x-text="item.reason"></span>
                  <span style="font-weight:700;color:#e07b3a;" x-text="item.count"></span>
                </div>
                <div style="height:4px;background:rgba(255,255,255,0.06);border-radius:2px;overflow:hidden;">
                  <div style="height:100%;background:#e07b3a;border-radius:2px;transition:width 0.5s;"
                       :style="'width:' + Math.round(item.count/(custom.stats?.failed||1)*100) + '%'"></div>
                </div>
              </div>
            </template>
          </div>
        </div>

        <div class="detail-panel" style="padding:16px 20px;">
          <div style="font-size:0.75em;font-weight:700;text-transform:uppercase;
                      letter-spacing:0.06em;color:var(--text-secondary);margin-bottom:12px;">
            Daily Breakdown
          </div>
          <div style="display:grid;grid-template-columns:140px 70px 80px 70px 1fr;gap:8px;
                      padding-bottom:8px;border-bottom:1px solid var(--border);
                      color:var(--text-secondary);font-size:0.75em;text-transform:uppercase;font-weight:600;">
            <span>Date</span><span>Total</span>
            <span style="color:var(--pass);">Passed</span>
            <span style="color:var(--fail);">Failed</span><span></span>
          </div>
          <template x-for="d in (custom.daily ?? [])" :key="d.date">
            <div style="display:grid;grid-template-columns:140px 70px 80px 70px 1fr;
                        gap:8px;padding:8px 0;border-bottom:1px solid rgba(255,255,255,0.04);
                        align-items:center;font-size:0.88em;">
              <span style="color:var(--text-secondary);" x-text="d.date"></span>
              <span style="font-weight:600;" x-text="d.total"></span>
              <span style="color:var(--pass);font-weight:600;" x-text="d.passed"></span>
              <span style="color:var(--fail);font-weight:600;" x-text="d.failed"></span>
              <div style="height:5px;background:rgba(255,255,255,0.05);border-radius:3px;overflow:hidden;">
                <div style="height:100%;background:var(--pass);border-radius:3px;"
                     :style="'width:' + Math.round(d.passed/(d.total||1)*100) + '%'"></div>
              </div>
            </div>
          </template>
          <div x-show="!(custom.daily ?? []).length"
               style="color:var(--text-secondary);font-size:0.85em;padding:12px 0;">
            No data for this period.
          </div>
        </div>
      </div>
    </template>

    <div x-show="!custom.stats"
         style="color:var(--text-secondary);text-align:center;padding:48px;
                background:var(--bg-card);border-radius:8px;border:1px solid var(--border);
                font-size:0.9em;">
      Select a date range and click <strong style="color:var(--accent);">Apply</strong> to view data.
    </div>
  </div>

</div><!-- /x-data -->

<script>
// Override Alpine component name to laptopApp
// (renderer.js is loaded above and provides renderPayload())
</script>
{% endblock %}
```

---

## Part 3: Update Backend — Add `daily` to `/api/stats/range` response

In `modules/laptop/module.py`, update `api_stats_range()` to include
daily breakdown in the response:

```python
# Add daily breakdown
from collections import defaultdict
daily_map = defaultdict(lambda: {'total': 0, 'passed': 0, 'failed': 0})
for r in records:
    day = r.get('timestamp', '')[:10]   # YYYY-MM-DD
    daily_map[day]['total'] += 1
    if r.get('overall_result') == 'PASS':
        daily_map[day]['passed'] += 1
    else:
        daily_map[day]['failed'] += 1

daily = [
    {'date': d, 'total': v['total'], 'passed': v['passed'], 'failed': v['failed']}
    for d, v in sorted(daily_map.items())
]

return jsonify({
    ...existing fields...,
    "daily": daily,
})
```

---

## Part 4: Remove Old Code

- Remove `loadStatsRange()`, `statsData`, `statsRange`, `statsFrom`, `statsTo`,
  `statsExpandedKeys`, `toggleStatsExpand()`, `isStatsExpanded()` from `app.js`
- Remove the old Stats tab panel HTML from `module.html`
- Remove `formatDateRange()` from `app.js` (replaced by `fmtRange()`)

---

## Verification

1. Open `/laptop/` → search bar at top
2. Type a SN → results appear below search bar (above tabs)
3. Click ✕ Clear → results disappear
4. Tabs: `Today | This Week | This Month | Custom Range`
5. Today tab: KPI strip + card list, click card → single expand
6. This Week tab: KPI + By Brand + Fail Reasons side-by-side + Daily Breakdown
7. This Month tab: same structure as This Week
8. Custom Range: date picker → Apply → shows same structure
9. By Brand bar proportional to weekly total
10. Fail Reasons bar proportional to weekly failed count
11. Daily Breakdown table shows per-day totals with pass bar

## Constraints
- Alpine.js + vanilla HTML/CSS only
- `laptopApp()` replaces `dashboardApp()` as the component name
- `detailOpen` is a single string key (not a Set) — only one record open at a time
- `renderDetails()` / `renderPayload()` from renderer.js still used for expand
- Do NOT change any API endpoint URLs
- Do NOT modify `core/storage.py`
- Run `python -m py_compile modules/laptop/module.py` after Python changes
