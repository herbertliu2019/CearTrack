# Task 04: Landing Page & Global Search

## Prerequisites
Tasks 01-03 complete. Laptop dashboard fully functional.

## Goal
Polish the landing page and add a global cross-module SN search.

## Deliverables

### 1. Update `templates/index.html`
Show tiles with live stats per module:

```html
{% extends "base.html" %}
{% block title %}Monitorcenter{% endblock %}
{% block content %}
<div x-data="landingApp()" x-init="init()">

  <div style="text-align: center; padding: 40px 0; border-bottom: 1px solid var(--border); margin-bottom: 30px;">
    <h1 style="font-size: 2em; color: var(--accent);">Monitor Center</h1>
    <p style="color: var(--text-secondary); margin-top: 8px;">
      Hardware Test Aggregation Dashboard
    </p>
  </div>

  <!-- Global search -->
  <div style="max-width: 600px; margin: 0 auto 40px;">
    <div class="search-box">
      <input type="text" x-model="globalSearch" @keydown.enter="runGlobalSearch()"
             placeholder="Search by SN / Service Tag across all modules...">
      <button @click="runGlobalSearch()">Search</button>
    </div>
    <div x-show="globalResults.length > 0" style="margin-top: 20px;">
      <h3 style="color: var(--accent); margin-bottom: 12px;">Found across modules:</h3>
      <template x-for="r in globalResults" :key="r.module + r.timestamp">
        <div class="detail-panel" style="padding: 12px 16px;">
          <div style="display: flex; justify-content: space-between;">
            <div>
              <span style="color: var(--accent); font-weight: 600;" x-text="r.module.toUpperCase()"></span>
              <span style="color: var(--text-secondary); margin-left: 12px;" x-text="r.timestamp"></span>
            </div>
            <a :href="`/${r.module}/?sn=${r.sn}`" style="color: var(--accent);">View →</a>
          </div>
          <div style="margin-top: 6px; color: var(--text-secondary);" x-text="r.summary"></div>
        </div>
      </template>
    </div>
  </div>

  <!-- Module tiles -->
  <h2 style="margin-bottom: 12px;">Test Modules</h2>
  <div class="module-grid">
    {% for m in modules %}
    <a href="/{{ m }}/" class="module-tile">
      <h3>{{ m|capitalize }}</h3>
      <div x-data="{stats:{}}" x-init="fetch('/{{ m }}/api/stats').then(r=>r.json()).then(d=>stats=d).catch(()=>{})">
        <div style="color: var(--text-secondary); font-size: 0.85em; margin-top: 10px;">
          <span x-text="stats.total_today ?? 0"></span> tested today
        </div>
        <div style="color: var(--pass); font-size: 0.85em;">
          <span x-text="stats.pass_rate ?? 0"></span>% pass
        </div>
      </div>
    </a>
    {% endfor %}

    <!-- Placeholder for future modules -->
    <div class="module-tile" style="opacity: 0.4; cursor: not-allowed;">
      <h3>CPU</h3>
      <div style="color: var(--text-secondary); margin-top: 10px;">Coming soon</div>
    </div>
    <div class="module-tile" style="opacity: 0.4; cursor: not-allowed;">
      <h3>GPU</h3>
      <div style="color: var(--text-secondary); margin-top: 10px;">Coming soon</div>
    </div>
    <div class="module-tile" style="opacity: 0.4; cursor: not-allowed;">
      <h3>Wipe</h3>
      <div style="color: var(--text-secondary); margin-top: 10px;">Coming soon</div>
    </div>
  </div>

</div>

<script>
function landingApp() {
  return {
    globalSearch: "",
    globalResults: [],
    async runGlobalSearch() {
      if (!this.globalSearch.trim()) { this.globalResults = []; return; }
      const r = await fetch(`/api/search?sn=${encodeURIComponent(this.globalSearch.trim())}`);
      this.globalResults = await r.json();
    },
  };
}
</script>
{% endblock %}
```

### 2. Add global search endpoint to `app.py`

```python
from flask import request, jsonify
from core import storage
from core.module_registry import register_modules

# ... existing code ...

@app.route("/api/search")
def global_search():
    """Search SN across all registered modules."""
    sn = request.args.get("sn", "").strip()
    if not sn:
        return jsonify({"error": "sn parameter required"}), 400
    
    results = []
    for module_name in MODULES:
        try:
            module_results = storage.search_sn(module_name, sn)
            results.extend(module_results)
        except Exception as e:
            print(f"Search error for {module_name}: {e}")
    
    results.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return jsonify(results)
```

### 3. Support deep-linking to SN in module dashboards

Update `modules/laptop/templates/module.html` — in the Alpine `init()`
method, check URL for `?sn=` parameter and auto-populate search:

```javascript
async init() {
  // ... existing code ...
  
  // Deep link: /laptop/?sn=XXX auto-searches
  const urlParams = new URLSearchParams(window.location.search);
  const snParam = urlParams.get("sn");
  if (snParam) {
    this.searchQuery = snParam;
    this.activeTab = "search";
    await this.runSearch();
  }
}
```

### 4. Simple "today's activity" widget on landing

Above the module tiles, show aggregate numbers:

```html
<div class="stats-strip" style="max-width: 800px; margin: 0 auto 30px;">
  <div class="stat-card">
    <div class="stat-label">Total Tests Today</div>
    <div class="stat-value" x-text="totalToday"></div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Active Modules</div>
    <div class="stat-value">{{ modules|length }}</div>
  </div>
</div>
```

In `landingApp()` add:
```javascript
totalToday: 0,
async init() {
  const moduleNames = {{ modules|tojson }};
  let total = 0;
  for (const m of moduleNames) {
    try {
      const r = await fetch(`/${m}/api/stats`);
      const d = await r.json();
      total += d.total_today ?? 0;
    } catch {}
  }
  this.totalToday = total;
},
```

## Verification

1. `http://localhost:8080/` — landing page shows laptop tile with live stats
2. Enter an SN in global search — returns cross-module results
3. Click "View →" on a result — jumps to that module's dashboard with SN pre-filled
4. Future modules (CPU/GPU/Wipe) show as "Coming soon"

## Constraints
- Global search MUST work even if individual modules fail (catch errors)
- URL deep-linking uses standard `?sn=` query param
- Do not cache results — always fetch fresh for today's data
