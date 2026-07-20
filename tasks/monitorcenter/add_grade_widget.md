# Task: Add "By Grade" Widget to All Stats Tabs (Today/Week/Month/Custom)

## Goal
Add a third widget "By Grade" alongside existing "By Brand" and
"Fail Reasons" widgets, in ALL FOUR tabs: Today, This Week, This Month,
Custom Range. Change the two-column layout to three-column.

## Grade Field Location
The operator-entered grade (A/B/C, appearance-based) already exists in
the JSON payload. Locate it — likely under a section like
`payload.appearance.grade` or `payload.grade` — inspect an actual
uploaded report to confirm the exact path before implementing.

## Design Spec

### Layout
Change existing two-column grid (`By Brand` | `Fail Reasons`) to
three-column: `By Brand` | `By Grade` | `Fail Reasons`.

```html
<div style="display:flex; flex-direction:row; gap:16px; margin-bottom:24px; align-items:stretch;">
  <!-- By Grade (NEW) -->
  <div class="detail-panel" style="flex:1; min-width:0; padding:16px 20px;">...</div>
    <!-- By Brand -->
  <div class="detail-panel" style="flex:1; min-width:0; padding:16px 20px;">...</div>
    <!-- Fail Reasons -->
  <div class="detail-panel" style="flex:1; min-width:0; padding:16px 20px;">...</div>
</div>
```

Add responsive breakpoint in `dashboard.css`:
```css
@media (max-width: 1200px) {
  .three-col-stats { flex-direction: column; }
}
```
Apply class `three-col-stats` to the wrapper div.

### By Grade Widget HTML (reusable template)

```html
<div class="detail-panel" style="flex:1; min-width:0; padding:16px 20px;">
  <div style="font-size:0.75em; font-weight:700; text-transform:uppercase;
              letter-spacing:0.06em; color:var(--text-secondary); margin-bottom:14px;">
    By Grade
  </div>

  <template x-if="!(TAB.by_grade ?? []).length">
    <div style="color:var(--text-secondary); font-size:0.88em;">No grade data</div>
  </template>

  <template x-for="item in (TAB.by_grade ?? [])" :key="item.grade">
    <div style="margin-bottom:12px;">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:5px;">
        <span style="font-size:0.9em;" x-text="'Grade ' + item.grade"></span>
        <span style="font-weight:700;" :style="'color:' + gradeColor(item.grade)" x-text="item.count"></span>
      </div>
      <div style="height:4px; background:rgba(255,255,255,0.06); border-radius:2px; overflow:hidden;">
        <div style="height:100%; border-radius:2px; transition:width 0.5s;"
             :style="'width:' + item.pct + '%; background:' + gradeColor(item.grade)">
        </div>
      </div>
    </div>
  </template>
</div>
```

Replace `TAB` with `today`, `week`, `month`, or `custom` depending on
which tab this is placed in (4 separate insertions, one per tab).

### Add `gradeColor()` helper in `static/js/app.js`

```javascript
gradeColor(grade) {
  const colors = { A: 'var(--pass)', B: 'var(--warn)', C: '#e07b3a' };
  return colors[grade] || 'var(--text-secondary)';
},
```

### Grade Order — Always A, B, C (never sorted by count)

Backend must return grades in fixed order A → B → C, not sorted by count.

---

## Backend Changes — `modules/laptop/module.py`

### 1. Today tab — `/api/latest` handling

The `/api/latest` endpoint itself doesn't need backend changes since
`by_grade` for Today is computed client-side from the same records
already returned. Add a helper function shared by both frontend
aggregation (today) and backend aggregation (week/month/custom).

Actually, to keep consistency, compute `by_grade` in Python and expose
via a small addition to `/api/stats` (today's stats) response:

```python
@blueprint.route("/api/stats")
def api_stats():
    records = storage.read_latest(_module.name)
    total  = len(records)
    passed = sum(1 for r in records if r.get("overall_result") == "PASS")
    failed = total - passed

    # By Grade (today)
    by_grade = _compute_by_grade(records)

    return jsonify({
        "total_today": total,
        "pass": passed,
        "fail": failed,
        "pass_rate": round(passed / total * 100, 1) if total else 0,
        "by_grade": by_grade,
    })
```

### 2. Shared helper function — add to `modules/laptop/module.py`

```python
def _compute_by_grade(records):
    """
    Compute grade distribution in fixed order A, B, C.
    Records without a grade field are skipped entirely (not counted
    in numerator or denominator).
    """
    counts = {"A": 0, "B": 0, "C": 0}
    for r in records:
        # CONFIRM exact path after inspecting real payload —
        # placeholder assumes payload.appearance.grade
        grade = r.get("payload", {}).get("appearance", {}).get("grade")
        if grade in counts:
            counts[grade] += 1

    total_graded = sum(counts.values())
    result = []
    for g in ["A", "B", "C"]:
        count = counts[g]
        pct = round(count / total_graded * 100) if total_graded else 0
        result.append({"grade": g, "count": count, "pct": pct})
    return result
```

### 3. `/api/stats/range` — add `by_grade` to response

In `api_stats_range()`, after computing `brands_sorted` and
`fail_reasons_sorted`, add:

```python
by_grade = _compute_by_grade(records)
```

Add `"by_grade": by_grade` to the returned JSON.

---

## Frontend Changes — `static/js/app.js`

### Update `loadToday()` — reuse `/api/stats` for by_grade

```javascript
async loadToday() {
  const r = await fetch(`/${this.moduleName}/api/latest`);
  const records = await r.json();
  const total  = records.length;
  const passed = records.filter(r => r.overall_result === 'PASS').length;
  const failed = total - passed;

  const statsR = await fetch(`/${this.moduleName}/api/stats`);
  const statsD = await statsR.json();

  this.today = {
    stats: { total, passed, failed, pass_rate: total ? Math.round(passed/total*100) : 0 },
    by_grade: statsD.by_grade ?? [],
    records,
  };
},
```

### Update `loadWeek()`, `loadMonth()`, `loadCustom()` — add by_grade

```javascript
async loadWeek() {
  const r = await fetch(`/${this.moduleName}/api/stats/range?range=week`);
  const d = await r.json();
  this.week = {
    stats:        { total: d.total, passed: d.passed, failed: d.failed, pass_rate: d.pass_rate },
    by_brand:     (d.brands ?? []).map(([name, count]) => ({ name, count })),
    by_grade:     d.by_grade ?? [],
    fail_reasons: (d.fail_reasons ?? []).map(([reason, count]) => ({ reason, count })),
    daily:        d.daily ?? [],
    start: d.date_from, end: d.date_to,
  };
},
```

Apply the same `by_grade: d.by_grade ?? []` addition to `loadMonth()`
and `loadCustom()`.

---

## Template Changes — `modules/laptop/templates/module.html`

Insert the "By Grade" widget HTML block (from Design Spec above)
between "By Brand" and "Fail Reasons" in all four locations:

1. Today tab — currently has no By Brand/Fail Reasons section; if Today
   tab doesn't have this row yet, ADD the full three-column row above
   the record list, using `today.by_grade`, `today.by_brand` (if exists),
   `today.fail_reasons` (if exists). If Today tab currently has none of
   these three widgets, only add "By Grade" for Today (skip Brand/Fail
   Reasons for Today unless they already exist).

2. This Week tab — existing two-column row becomes three-column,
   insert By Grade widget using `week.by_grade`.

3. This Month tab — same as Week, using `month.by_grade`.

4. Custom Range tab — same as Week, using `custom.by_grade`.

---

## Verification

```bash
# Backend check
curl "http://localhost:5004/laptop/api/stats" | jq .by_grade
curl "http://localhost:5004/laptop/api/stats/range?range=week" | jq .by_grade
curl "http://localhost:5004/laptop/api/stats/range?range=month" | jq .by_grade
```

Expected format:
```json
[
  {"grade": "A", "count": 12, "pct": 60},
  {"grade": "B", "count": 6,  "pct": 30},
  {"grade": "C", "count": 2,  "pct": 10}
]
```

Browser checks:
1. This Week tab → three widgets side by side: By Brand | By Grade | Fail Reasons
2. By Grade always shows A, B, C in that order (never re-sorted)
3. Grade A = green bar, Grade B = yellow bar, Grade C = orange bar
4. Switch to This Month → widget updates with month data
5. Custom Range → pick dates → Apply → widget updates
6. If no records have a grade field → shows "No grade data"
7. Narrow browser window (<1200px) → three columns stack vertically

## Constraints
- Confirm exact JSON path for grade field before implementing
  `_compute_by_grade()` — inspect a real uploaded report first
- Records without grade field: skip entirely, do not count as ungraded
- Grade order is always A → B → C, never sorted by count
- Do NOT modify `core/storage.py`
- Do NOT change existing API endpoint URLs
- Run `python -m py_compile modules/laptop/module.py` after Python changes
