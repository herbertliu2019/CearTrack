# CPU Module — Phase 4: Frontend Dashboard

## Prerequisites
- Phase 1–3 complete and API endpoints responding correctly
- `GET /cpu/api/today` → `{records: [...], count: N}`
- `GET /cpu/api/stats?period=week` → `{summary, by_family, by_generation, by_model, daily}`
- `GET /cpu/api/image/<id>` → image stream

## Reference
Look at `monitorcenter/modules/wipe/templates/wipe/dashboard.html` for structure/style patterns.
Look at `monitorcenter/static/css/dashboard.css` for existing CSS variables and card styles.
Look at `monitorcenter/static/js/app.js` for Alpine.js patterns used in laptop module.

No npm, no build tools. Use only vanilla CSS + Alpine.js (already vendored at
`/static/vendor/alpine.min.js`) + HTMX (optional, not required for this module).

## File to Create

### `monitorcenter/modules/cpu/templates/cpu/dashboard.html`

Extends `base.html` (`{% extends 'base.html' %}`).

---

### Layout Structure

```
┌─────────────────────────────────────────────────────────┐
│ [Today] [Week] [Month] [Custom]         [🔍 Search bar] │
├─────────────────────────────────────────────────────────┤
│ KPI Strip (4 cards)                                     │
├──────────────────────┬──────────────────────────────────┤
│ By Family (bar chart)│ By Generation (bar chart)        │
├──────────────────────┴──────────────────────────────────┤
│ By Model Top 10 (horizontal bar chart)                  │
├─────────────────────────────────────────────────────────┤
│ Daily Trend (simple bar chart, CSS-only)                │
├─────────────────────────────────────────────────────────┤
│ Records List (today / date range)                       │
│  ┌──────────────────────────────────────────────────┐   │
│  │ SN   │ CPU         │ Speed │ Cores│ Date │ Result│   │
│  │ [▼ expand]                                       │   │
│  │   Detail panel (when expanded):                  │   │
│  │     Left col: key-value specs                    │   │
│  │     Right col: test module status grid           │   │
│  │     Bottom: image thumbnail                      │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

---

### Alpine.js App — `cpuApp()`

Define inline in the template as `<script>function cpuApp() { return { ... } }</script>`.

#### State
```javascript
{
  activeTab: 'today',       // 'today' | 'week' | 'month' | 'custom'
  records: [],
  stats: null,
  searchQuery: '',
  searchResults: [],
  searching: false,
  expandedId: null,         // currently expanded record id (one at a time)
  customStart: '',
  customEnd: '',
  loading: false,
  scanStatus: null
}
```

#### Methods
```javascript
init()            // load today data on mount
loadToday()       // GET /cpu/api/today
loadStats(period, start, end)  // GET /cpu/api/stats
search()          // GET /cpu/api/search?q=
toggleExpand(id)  // expand/collapse record detail
triggerScan()     // POST /cpu/api/scan
pollScanStatus()  // GET /cpu/api/scan/status (called every 2s while running)
fmtDuration(sec)  // "3m 50s"
fmtFreqRatio(r)   // "99.97%" colored green/red based on < 0.5
```

---

### KPI Strip (4 cards)

Data source: `stats.summary`

```
┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│ Total Tested│  │ Period Count│  │ Avg Duration│  │ Freq Anomaly│
│   1,432     │  │    234      │  │   3m 55s    │  │      1      │
│  all time   │  │  this week  │  │  per test   │  │ freq < 50%  │
└─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘
```

"Freq Anomaly" = records where `freq_ratio < 0.5`. Show in amber/orange if > 0, green if 0.

---

### Charts (CSS-only bar charts, no JS charting library)

**By Family** (vertical bars):
```html
<div class="chart-bars">
  <template x-for="item in stats.by_family">
    <div class="bar-col">
      <div class="bar" :style="`height: ${pct(item.count, maxFamily)}%`"></div>
      <span class="bar-label" x-text="item.family"></span>
      <span class="bar-val" x-text="item.count"></span>
    </div>
  </template>
</div>
```

**By Generation** (same pattern, label = "8th Gen"):

**By Model Top 10** (horizontal bars):
```html
<div class="hbar-row" x-for="item in stats.by_model">
  <span class="hbar-label" x-text="item.cpu_full_name"></span>
  <div class="hbar-track">
    <div class="hbar-fill" :style="`width: ${pct(item.count, maxModel)}%`"></div>
  </div>
  <span class="hbar-val" x-text="item.count"></span>
</div>
```

**Daily trend** (small vertical bars, `stats.daily` array):
- Show last N days from the selected period
- Label every 3rd date to avoid overlap

---

### Records List

Table columns: SN | CPU | Speed | Cores | L3 Cache | Date | Duration | Result

Row click → `toggleExpand(record.id)`

**Expanded Detail Panel** (shown below the row):

```
┌──────────────────────────┬────────────────────────────┐
│ LEFT: Specs              │ RIGHT: Test Modules         │
│                          │                             │
│ SN: M8VE287600952        │ ✓ GenuineIntel   PASS      │
│ Full Name: i5-8500       │ ✓ BrandString    PASS      │
│ Processor: i5-8500       │ ✓ Cache          PASS      │
│   @ 3.00GHz              │ ✓ MMXSSE         PASS      │
│ Generation: 8th Gen      │ ✓ IMC            PASS      │
│ Cores: 6P / 6L           │ ✓ PrimeNum       PASS      │
│ L3 Cache: 9 MB           │ ✓ FloatingPoint  PASS      │
│ Memory: 32 GB            │ ✓ Math           PASS      │
│ Expected: 3.00 GHz       │ ✓ GPUStressW     PASS      │
│ Measured: 2.999 GHz      │ ✓ CPULoad        PASS      │
│ Freq Ratio: 99.97%       │ ✓ CPUFreq        PASS      │
│ Duration: 3m 50s         │                             │
│ Test Date: 2026-01-02    │                             │
│ OS: Win10 Home 64-bit    │                             │
└──────────────────────────┴────────────────────────────┘
┌────────────────────────────────────────────────────────┐
│ TEST SCREENSHOT                                        │
│ [img src=/cpu/api/image/42  max-height:280px]          │
│ (only shown if has_image == true)                      │
└────────────────────────────────────────────────────────┘
```

Image HTML:
```html
<template x-if="record.has_image">
  <div class="cpu-screenshot">
    <img :src="`/cpu/api/image/${record.id}`"
         style="max-height:280px; max-width:100%; object-fit:contain; border-radius:6px;"
         loading="lazy"
         alt="Test screenshot">
  </div>
</template>
```

Note: `record.has_image` is a boolean sent by the API (Phase 3), not the raw path.

---

### Search Mode

When `searchQuery.length >= 2` and user hits Enter or clicks search button:
- Call `GET /cpu/api/search?q=<query>`
- Replace records list with search results
- Show "X results for 'query'" header
- Clear button to return to tab view

---

### Scan Controls

Small button in top-right corner: `[↻ Scan for New Logs]`
- Click → `triggerScan()`
- While running: show progress bar using `scanStatus.done / scanStatus.total`
- On done: show "Inserted N new records"

---

### CSS Notes

Add a `<style>` block in the template for CPU-specific styles only.
Reuse existing CSS classes from `dashboard.css` where possible:
- `.kpi-card`, `.kpi-value`, `.kpi-label` — for KPI strip
- `.status-pass` (green), `.status-fail` (red) — for result badges
- `.card`, `.section-title` — for panels

New classes needed:
```css
.chart-bars { display: flex; align-items: flex-end; gap: 8px; height: 120px; }
.bar-col { display: flex; flex-direction: column; align-items: center; flex: 1; }
.bar { background: var(--accent, #3b82f6); border-radius: 3px 3px 0 0; min-height: 4px; width: 100%; }
.bar-label { font-size: 11px; margin-top: 4px; }
.bar-val { font-size: 11px; color: #888; }

.hbar-row { display: flex; align-items: center; gap: 8px; margin: 4px 0; }
.hbar-label { width: 80px; font-size: 12px; text-align: right; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.hbar-track { flex: 1; height: 14px; background: #eee; border-radius: 3px; }
.hbar-fill { height: 100%; background: var(--accent, #3b82f6); border-radius: 3px; transition: width 0.3s; }
.hbar-val { width: 35px; font-size: 12px; color: #888; }

.cpu-screenshot { margin-top: 12px; padding-top: 12px; border-top: 1px solid #eee; text-align: center; }

.freq-normal { color: #16a34a; }
.freq-anomaly { color: #d97706; font-weight: 600; }
```

---

## Validation
1. `python -m py_compile` is N/A for HTML, but check Jinja2 renders:
   ```bash
   # With app running:
   curl -s http://localhost:5004/cpu/ | grep -c "cpuApp"
   # Should return 1
   ```
2. Open browser → `http://localhost:5004/cpu/`
3. Verify: KPI cards load, bar charts render, records list shows, expand works, image loads
4. Test search: type a known SN prefix, verify results appear
5. Test scan button: click, verify progress shows

## Notes
- Keep all Alpine.js state in `cpuApp()` — no global variables
- All `fetch()` calls use relative URLs (`/cpu/api/...`)
- Handle loading states: show spinner or "Loading..." text while fetching
- Handle empty states: "No records today" / "No results found"
- Do NOT use any external CDN links — only vendored JS already in `/static/vendor/`
