# Task 03: Frontend Dashboard

## Prerequisites
Tasks 01 and 02 complete. `/laptop/api/*` endpoints return JSON.

## Goal
Build a polished, schema-driven dashboard for the laptop module using
Alpine.js + HTMX. Template is generic — works for any future module.

## Deliverables

### 1. `static/css/dashboard.css`
Dark theme, clean grid layout. Full file:

```css
:root {
  --bg-primary: #1a1c2c;
  --bg-secondary: #242739;
  --bg-card: #2d324a;
  --border: #3d4465;
  --text-primary: #e0e0e0;
  --text-secondary: #888da8;
  --accent: #00d2ff;
  --pass: #4caf50;
  --fail: #e74c3c;
  --warn: #f1c40f;
  --skip: #7f8c8d;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: 'Segoe UI', Tahoma, sans-serif;
  background: var(--bg-primary);
  color: var(--text-primary);
  padding: 20px;
}

header {
  max-width: 1800px;
  margin: 0 auto 20px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 2px solid var(--border);
  padding-bottom: 12px;
}

header h1 { color: var(--accent); font-size: 1.5em; }

nav { display: flex; gap: 16px; }
nav a {
  color: var(--text-secondary);
  text-decoration: none;
  padding: 6px 12px;
  border-radius: 4px;
  transition: all 0.2s;
}
nav a:hover { color: var(--accent); background: var(--bg-card); }

main { max-width: 1800px; margin: 0 auto; }

/* Tabs */
.tabs {
  display: flex;
  gap: 4px;
  border-bottom: 2px solid var(--border);
  margin-bottom: 20px;
}
.tab-btn {
  background: transparent;
  border: none;
  color: var(--text-secondary);
  padding: 10px 18px;
  cursor: pointer;
  font-size: 0.95em;
  border-bottom: 3px solid transparent;
  margin-bottom: -2px;
}
.tab-btn.active { color: var(--accent); border-bottom-color: var(--accent); }
.tab-btn:hover { color: var(--accent); }

.tab-content { display: none; }
.tab-content.active { display: block; }

/* Stats strip */
.stats-strip {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 20px;
}
.stat-card {
  background: var(--bg-card);
  border-radius: 6px;
  padding: 14px 16px;
  border-left: 3px solid var(--accent);
}
.stat-label {
  color: var(--text-secondary);
  font-size: 0.8em;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.stat-value { color: var(--accent); font-size: 1.8em; font-weight: 600; }

/* Result cards grid */
.cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 16px;
}
.result-card {
  background: var(--bg-card);
  border-radius: 6px;
  overflow: hidden;
  cursor: pointer;
  transition: transform 0.15s;
  border-top: 4px solid var(--border);
}
.result-card:hover { transform: translateY(-2px); }
.result-card.pass { border-top-color: var(--pass); }
.result-card.fail { border-top-color: var(--fail); }

.card-header {
  padding: 12px 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.card-sn { font-family: monospace; letter-spacing: 0.05em; font-weight: 600; }
.card-model { color: var(--text-secondary); font-size: 0.85em; margin-top: 2px; }

.badge {
  padding: 2px 10px;
  border-radius: 3px;
  font-size: 0.75em;
  font-weight: 600;
  letter-spacing: 0.05em;
}
.badge.pass { background: rgba(76,175,80,0.2); color: var(--pass); }
.badge.fail { background: rgba(231,76,60,0.2); color: var(--fail); }

.card-body { padding: 10px 16px; border-top: 1px solid var(--border); }
.card-spec { color: var(--text-secondary); font-size: 0.85em; margin: 2px 0; }

.status-mini-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 4px;
  padding: 10px 16px;
  border-top: 1px solid var(--border);
}
.status-dot {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 0.75em;
  color: var(--text-secondary);
}
.status-dot::before {
  content: '';
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--skip);
}
.status-dot.pass::before { background: var(--pass); }
.status-dot.fail::before { background: var(--fail); }
.status-dot.warn::before { background: var(--warn); }

.card-footer {
  padding: 8px 16px;
  font-size: 0.75em;
  color: var(--text-secondary);
  background: var(--bg-secondary);
}

/* Detail view (expanded) */
.detail-panel {
  background: var(--bg-card);
  border-radius: 6px;
  padding: 20px;
  margin-bottom: 16px;
}
.detail-section { margin-bottom: 18px; }
.detail-section h3 {
  color: var(--accent);
  font-size: 0.95em;
  margin-bottom: 10px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.kv-grid {
  display: grid;
  grid-template-columns: 180px 1fr;
  gap: 6px 16px;
}
.kv-label { color: var(--text-secondary); }
.kv-value { color: var(--text-primary); }

.status-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 8px;
}
.status-item {
  background: var(--bg-secondary);
  padding: 8px 12px;
  border-radius: 4px;
  border-left: 3px solid var(--skip);
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.status-item.pass { border-left-color: var(--pass); }
.status-item.fail { border-left-color: var(--fail); }
.status-item.warn { border-left-color: var(--warn); }

/* Search tab */
.search-box {
  display: flex;
  gap: 8px;
  margin-bottom: 20px;
}
.search-box input {
  flex: 1;
  padding: 10px 14px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text-primary);
  font-family: monospace;
  font-size: 1em;
}
.search-box input:focus { border-color: var(--accent); outline: none; }
.search-box button {
  padding: 10px 20px;
  background: var(--accent);
  color: var(--bg-primary);
  border: none;
  border-radius: 4px;
  font-weight: 600;
  cursor: pointer;
}

/* Module tiles on index page */
.module-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 16px;
  margin-top: 20px;
}
.module-tile {
  background: var(--bg-card);
  padding: 30px 20px;
  border-radius: 8px;
  text-align: center;
  text-decoration: none;
  color: var(--text-primary);
  transition: transform 0.15s;
}
.module-tile:hover { transform: translateY(-3px); border-color: var(--accent); }
.module-tile h3 { color: var(--accent); }
```

### 2. `static/js/renderer.js`
Schema-driven renderer. Walks schema, renders into DOM.

```javascript
function getByPath(obj, path) {
  return path.split('.').reduce((acc, key) => acc?.[key], obj);
}

function statusClass(value) {
  if (value === "PASS") return "pass";
  if (value === "FAIL") return "fail";
  if (["WARNING", "HARDWARE_DETECTED", "DATA_UNAVAILABLE"].includes(value)) return "warn";
  return "skip";
}

function renderField(field, data) {
  const value = getByPath(data, field.path);
  const display = (value === null || value === undefined || value === "") ? "—" : value + (field.suffix || "");
  return `
    <div class="kv-label">${field.label}</div>
    <div class="kv-value">${display}</div>
  `;
}

function renderKeyValueSection(section, data) {
  const rows = section.fields.map(f => renderField(f, data)).join("");
  return `
    <div class="detail-section">
      <h3>${section.title}</h3>
      <div class="kv-grid">${rows}</div>
    </div>
  `;
}

function renderStatusGridSection(section, data) {
  const items = section.items.map(item => {
    const value = getByPath(data, item.path) ?? "—";
    return `
      <div class="status-item ${statusClass(value)}">
        <span>${item.label}</span>
        <span>${value}</span>
      </div>
    `;
  }).join("");
  return `
    <div class="detail-section">
      <h3>${section.title}</h3>
      <div class="status-grid">${items}</div>
    </div>
  `;
}

function renderListSection(section, data) {
  const list = getByPath(data, section.path) || [];
  const items = list.map(item => {
    let line = section.item_template;
    Object.entries(item).forEach(([k, v]) => {
      line = line.replace(`{${k}}`, v ?? "—");
    });
    return `<div class="kv-value">${line}</div>`;
  }).join("");
  return `
    <div class="detail-section">
      <h3>${section.title}</h3>
      ${items || '<div class="kv-label">No items</div>'}
    </div>
  `;
}

function renderPayload(schema, data) {
  return schema.sections.map(section => {
    switch (section.type) {
      case "key_value": return renderKeyValueSection(section, data);
      case "status_grid": return renderStatusGridSection(section, data);
      case "list": return renderListSection(section, data);
      default: return `<div>Unknown section type: ${section.type}</div>`;
    }
  }).join("");
}
```

### 3. `static/js/app.js`
Alpine component. Three tabs: Latest, Search, Stats.

```javascript
function dashboardApp(moduleName) {
  return {
    moduleName,
    activeTab: "latest",
    schema: null,
    latest: [],
    stats: {},
    searchQuery: "",
    searchResults: [],
    expandedSn: null,
    pollInterval: null,

    async init() {
      const r = await fetch(`/${this.moduleName}/api/schema`);
      this.schema = await r.json();
      await this.loadLatest();
      await this.loadStats();
      this.pollInterval = setInterval(() => {
        if (this.activeTab === "latest") this.loadLatest();
      }, 10000);
    },

    async loadLatest() {
      const r = await fetch(`/${this.moduleName}/api/latest`);
      this.latest = await r.json();
    },

    async loadStats() {
      const r = await fetch(`/${this.moduleName}/api/stats`);
      this.stats = await r.json();
    },

    async runSearch() {
      if (!this.searchQuery.trim()) { this.searchResults = []; return; }
      const r = await fetch(`/${this.moduleName}/api/search?sn=${encodeURIComponent(this.searchQuery.trim())}`);
      this.searchResults = await r.json();
    },

    toggleExpand(sn) {
      this.expandedSn = this.expandedSn === sn ? null : sn;
    },

    statusClass(value) { return statusClass(value); },

    renderDetails(record) {
      if (!this.schema) return "";
      return renderPayload(this.schema, record);
    },

    miniStatusItems(record) {
      // Pull a few key status fields for card preview
      const p = record.payload || {};
      return [
        { label: "Screen", value: p.screen?.dead_pixel_check },
        { label: "Cam", value: p.camera?.device_status },
        { label: "Audio", value: p.audio?.speaker_quality_check },
        { label: "KB", value: p.keyboard?.keys_check },
        { label: "Net", value: p.network?.internet_test },
        { label: "Batt", value: p.battery?.status },
      ];
    },

    cardSpecs(record) {
      const p = record.payload || {};
      return {
        cpu: p.cpu?.model || "—",
        memory: `${p.memory?.total_gb || "?"} GB ${p.memory?.type || ""}`,
        battery: p.battery?.health_percent ? `${p.battery.health_percent}%` : "—",
      };
    },
  };
}
```

### 4. Update `modules/laptop/templates/module.html`
Replace the placeholder with the full dashboard:

```html
{% extends "base.html" %}
{% block title %}{{ display_name }} — Monitorcenter{% endblock %}
{% block content %}
<script src="{{ url_for('static', filename='js/renderer.js') }}"></script>
<script src="{{ url_for('static', filename='js/app.js') }}"></script>

<div x-data="dashboardApp('{{ module_name }}')" x-init="init()">

  <div class="stats-strip">
    <div class="stat-card">
      <div class="stat-label">Tested Today</div>
      <div class="stat-value" x-text="stats.total_today ?? 0"></div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Passed</div>
      <div class="stat-value" x-text="stats.pass ?? 0" style="color: var(--pass)"></div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Failed</div>
      <div class="stat-value" x-text="stats.fail ?? 0" style="color: var(--fail)"></div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Pass Rate</div>
      <div class="stat-value" x-text="(stats.pass_rate ?? 0) + '%'"></div>
    </div>
  </div>

  <div class="tabs">
    <button class="tab-btn" :class="{active: activeTab==='latest'}" @click="activeTab='latest'">Latest</button>
    <button class="tab-btn" :class="{active: activeTab==='search'}" @click="activeTab='search'">SN Search</button>
  </div>

  <!-- LATEST TAB -->
  <div class="tab-content" :class="{active: activeTab==='latest'}">
    <div class="cards-grid">
      <template x-for="r in latest" :key="r.sn + r.timestamp">
        <div :class="'result-card ' + r.overall_result.toLowerCase()">
          <div class="card-header" @click="toggleExpand(r.sn)">
            <div>
              <div class="card-sn" x-text="r.sn"></div>
              <div class="card-model" x-text="r.payload?.system?.vendor + ' ' + r.payload?.system?.model"></div>
            </div>
            <span class="badge" :class="r.overall_result.toLowerCase()" x-text="r.overall_result"></span>
          </div>
          <div class="card-body">
            <div class="card-spec" x-text="cardSpecs(r).cpu"></div>
            <div class="card-spec" x-text="cardSpecs(r).memory + ' • Battery ' + cardSpecs(r).battery"></div>
          </div>
          <div class="status-mini-grid">
            <template x-for="item in miniStatusItems(r)" :key="item.label">
              <div class="status-dot" :class="statusClass(item.value)">
                <span x-text="item.label"></span>
              </div>
            </template>
          </div>
          <div class="card-footer" x-text="r.timestamp"></div>

          <!-- Expanded details -->
          <template x-if="expandedSn === r.sn">
            <div class="detail-panel" x-html="renderDetails(r)"></div>
          </template>
        </div>
      </template>
    </div>
    <div x-show="latest.length === 0" style="color: var(--text-secondary); text-align: center; padding: 40px;">
      No tests today yet.
    </div>
  </div>

  <!-- SEARCH TAB -->
  <div class="tab-content" :class="{active: activeTab==='search'}">
    <div class="search-box">
      <input type="text" x-model="searchQuery" @keydown.enter="runSearch()" placeholder="Enter SN or Service Tag...">
      <button @click="runSearch()">Search</button>
    </div>
    <div x-show="searchResults.length === 0 && searchQuery" style="color: var(--text-secondary);">
      No records found for <span x-text="searchQuery"></span>.
    </div>
    <template x-for="r in searchResults" :key="r.timestamp">
      <div class="detail-panel">
        <div style="display: flex; justify-content: space-between; margin-bottom: 12px;">
          <strong x-text="r.sn + ' — ' + r.timestamp"></strong>
          <span class="badge" :class="r.overall_result.toLowerCase()" x-text="r.overall_result"></span>
        </div>
        <div x-html="renderDetails(r)"></div>
      </div>
    </template>
  </div>

</div>
{% endblock %}
```

## Verification

1. POST a few test JSONs with different `overall_result` values
2. Open `http://localhost:8080/laptop/`
3. Latest tab should show cards with correct colors (green for PASS, red for FAIL)
4. Click card → expand details section-by-section using schema
5. Search tab: enter SN → see history
6. Wait 10s → Latest auto-refreshes

## Constraints
- All JS in `static/js/` is GENERIC — no laptop-specific logic there
- Module-specific rules live in `schema.json`
- Dark theme matches `:root` variables in dashboard.css
- No external dependencies added beyond what task 01 set up
