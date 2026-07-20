# Task: Statistics Tab UI Redesign + Storage Detail Fix

## Tech Stack Reminder
- Frontend: Alpine.js + vanilla HTML/CSS (NO Vue/React/Tailwind)
- Dark theme via CSS variables in `static/css/dashboard.css`
- All logic in `static/js/app.js` and `modules/laptop/templates/module.html`

---

## Part 1: Calendar-Based Statistics Logic

### Update `modules/laptop/module.py` — `/api/stats/range` endpoint

Replace rolling-day logic with calendar-based week/month:

```python
from datetime import datetime, timedelta
import calendar

today = datetime.now().date()

if range_param == "week":
    # Calendar week: Monday 00:00 to Sunday 23:59
    weekday = today.weekday()           # Monday=0, Sunday=6
    date_from = today - timedelta(days=weekday)
    date_to   = date_from + timedelta(days=6)

elif range_param == "month":
    # Calendar month: 1st to last day of current month
    date_from = today.replace(day=1)
    last_day  = calendar.monthrange(today.year, today.month)[1]
    date_to   = today.replace(day=last_day)
```

Also return the date range in the response so frontend can display it:
```python
return jsonify({
    "date_from":  str(date_from),    # "2026-04-21"
    "date_to":    str(date_to),      # "2026-04-27"
    ...
})
```

---

## Part 2: Date Range Display on Tab Buttons

### In `modules/laptop/templates/module.html`

Update the range selector buttons to show date range beside label.
Use Alpine to compute and display the date range:

```html
<!-- Range selector -->
<div style="display:flex; gap:10px; margin-bottom:20px; align-items:center; flex-wrap:wrap;">

  <button class="tab-btn" :class="{active: statsRange==='week'}"
          @click="statsRange='week'; loadStatsRange()">
    This Week
    <span x-show="statsData && statsRange==='week'"
          style="font-size:0.75em; opacity:0.5; margin-left:6px; font-weight:normal;"
          x-text="formatDateRange(statsData?.date_from, statsData?.date_to)">
    </span>
  </button>

  <button class="tab-btn" :class="{active: statsRange==='month'}"
          @click="statsRange='month'; loadStatsRange()">
    This Month
    <span x-show="statsData && statsRange==='month'"
          style="font-size:0.75em; opacity:0.5; margin-left:6px; font-weight:normal;"
          x-text="formatDateRange(statsData?.date_from, statsData?.date_to)">
    </span>
  </button>

  <button class="tab-btn" :class="{active: statsRange==='custom'}"
          @click="statsRange='custom'">
    Custom Range
  </button>

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
```

### Add `formatDateRange()` in `static/js/app.js`:

```javascript
formatDateRange(from, to) {
    if (!from || !to) return '';
    // Format: "04.21 - 04.27"
    const fmt = (d) => {
        const parts = d.split('-');
        return `${parts[1]}.${parts[2]}`;
    };
    return `(${fmt(from)} - ${fmt(to)})`;
},
```

---

## Part 3: By Brand and Common Fail Reasons — Layout Redesign

### Replace existing two-column grid section in `module.html`

Remove the current `grid-template-columns:1fr 1fr` layout.
Replace with two **independent cards** stacked or side-by-side,
each with dynamic height (no forced equal height):

```html
<div style="display:flex; gap:16px; margin-bottom:20px; align-items:flex-start;"
     x-show="statsData">

  <!-- By Brand Card -->
  <div class="detail-panel" style="flex:1; min-width:0;">
    <h3 style="color:var(--accent); margin-bottom:16px; font-size:0.9em;
               text-transform:uppercase; letter-spacing:0.06em;">
      By Brand
    </h3>

    <template x-for="[brand, count] in (statsData?.brands ?? [])" :key="brand">
      <div style="margin-bottom:14px;">
        <!-- Row 1: name (left) | big count (right) -->
        <div style="display:flex; justify-content:space-between; align-items:center;
                    margin-bottom:5px;">
          <span style="font-size:0.9em; color:var(--text-primary);"
                x-text="brand"></span>
          <span style="font-size:1.4em; font-weight:700; color:var(--accent);"
                x-text="count"></span>
        </div>
        <!-- Row 2: thin progress bar -->
        <div style="height:3px; max-width:300px; border-radius:2px;
                    background:rgba(255,255,255,0.05); overflow:hidden;">
          <div style="height:100%; border-radius:2px; background:var(--accent); transition:width 0.4s ease;"
               :style="`width:${Math.round(count / (statsData?.total || 1) * 100)}%`">
          </div>
        </div>
      </div>
    </template>

    <div x-show="(statsData?.brands ?? []).length === 0"
         style="color:var(--text-secondary); font-size:0.85em;">No data</div>
  </div>

  <!-- Common Fail Reasons Card -->
  <div class="detail-panel" style="flex:1; min-width:0;">
    <h3 style="color:#e07b3a; margin-bottom:16px; font-size:0.9em;
               text-transform:uppercase; letter-spacing:0.06em;">
      Common Fail Reasons
    </h3>

    <template x-if="(statsData?.fail_reasons ?? []).length === 0">
      <div style="color:var(--pass); font-size:0.85em;">No failures in this period 🎉</div>
    </template>

    <template x-for="[reason, count] in (statsData?.fail_reasons ?? [])" :key="reason">
      <div style="margin-bottom:14px;">
        <!-- Row 1: warning icon + name (left) | big count (right) -->
        <div style="display:flex; justify-content:space-between; align-items:center;
                    margin-bottom:5px;">
          <span style="display:flex; align-items:center; gap:8px;">
            <span style="color:#e07b3a; font-size:1em;">⚠</span>
            <span style="font-size:0.9em; color:var(--text-primary);"
                  x-text="reason"></span>
          </span>
          <span style="font-size:1.4em; font-weight:700; color:#e07b3a;"
                x-text="count"></span>
        </div>
        <!-- Row 2: thin progress bar -->
        <div style="height:3px; max-width:300px; border-radius:2px;
                    background:rgba(255,255,255,0.05); overflow:hidden;">
          <div style="height:100%; border-radius:2px; background:#e07b3a; transition:width 0.4s ease;"
               :style="`width:${Math.round(count / (statsData?.failed || 1) * 100)}%`">
          </div>
        </div>
      </div>
    </template>
  </div>

</div>
```



---

## Part 4: Storage Info in Detail View

### Update `modules/laptop/schema.json`

In the `Hardware` section fields array, update the storage list
`item_template` to include type, power_on_hours, ssd_data_written:

```json
{
  "title": "Storage",
  "type": "list",
  "path": "payload.storage",
  "item_template": "{model} ({size}, {type}) — SMART: {smart} | Power-on: {power_on_hours}h | Written: {ssd_data_written} | Health: {ssd_health_percent}% Grade {ssd_grade}"
}
```

This will render in the expanded detail view automatically via the
existing `renderListSection()` in `renderer.js`.

---

## Part 5: CSS Updates in `static/css/dashboard.css`

Remove the old `.bar-row`, `.bar-track`, `.bar-fill`, `.bar-count` classes
(replaced by inline styles above). They are no longer needed.

No other CSS changes required — all new styles are inline.

---

## Verification

1. Open Statistics tab → This Week
   - Button shows `This Week (04.21 - 04.27)` in small faded text
   - By Brand and Fail Reasons are two independent cards, different heights OK
   - Each item: name on left + big bold count on right, thin 3px bar below
   - Brand bar: cyan, Fail bar: orange-red `#e07b3a`

2. Switch to This Month
   - Date range updates to `(04.01 - 04.30)`

3. Custom Range → pick dates → Apply
   - No date range shown beside button (only shown for week/month)

4. Click any record row to expand
   - Storage section shows: type, power_on_hours, ssd_data_written, health%, grade

5. Verify calendar logic:
   - "This Week" = Monday to Sunday of current week
   - "This Month" = 1st to last day of current month

## Constraints
- Alpine.js + vanilla HTML/CSS only — NO Vue, React, Tailwind, or npm

- Orange-red color for fail reasons: `#e07b3a`
- Do NOT change API endpoint URLs
- Do NOT modify `core/storage.py`
- Run `python -m py_compile modules/laptop/module.py` after Python changes
