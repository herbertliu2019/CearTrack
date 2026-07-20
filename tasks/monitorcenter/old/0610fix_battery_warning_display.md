# Fix: CearTrack — Battery WARNING Display

## Rule

`battery.status = "WARNING"` is not a FAIL.
- Display: yellow color
- overall_result: not affected (stays PASS if everything else passes)
- Fail Reasons stats: battery WARNING must NOT appear in fail_reasons

## Part 1: `modules/laptop/module.py` — compute_verdict()

### Fix 1: Add battery WARNING to warnings list

In `compute_verdict()`, add:
```python
bat_status = payload.get("battery", {}).get("status", "")
bat_health = payload.get("battery", {}).get("health_percent", "")
if bat_status == "WARNING":
    health_str = f" ({bat_health}%)" if bat_health and bat_health != "unknown" else ""
    warnings.append(f"Battery low{health_str} — mark note in Cyclelution")
```

### Fix 2: summary when battery WARNING but overall PASS

Update summary logic:
```python
if overall == "FAIL":
    # existing fail logic unchanged
    ...
elif warnings:
    summary = f"PASS — {len(warnings)} warning(s): {'; '.join(warnings[:2])}"
else:
    summary = "All tests passed"
```

### Fix 3: fail_reasons must exclude battery WARNING

In `api_stats_range()`, the fail_reasons loop only processes records
where `overall_result == "FAIL"`. Since battery WARNING does not cause
overall FAIL, battery issues won't appear in fail_reasons automatically.

Verify the fail_reasons check uses `overall_result != "FAIL"` to skip:
```python
for r in records:
    if r.get("overall_result") != "FAIL":
        continue   # battery WARNING records skipped here correctly
```

No change needed if this logic is already in place.

## Part 2: `static/css/dashboard.css`

Ensure WARNING color is defined and used:
```css
:root {
  --warn: #f1c40f;   /* already exists — verify */
}
```

Add status-dot warn class if not already present:
```css
.status-dot.warn::before { background: var(--warn); }
```

## Part 3: `modules/laptop/schema.json`

Battery status field already maps to `payload.battery.status`.
The `statusClass()` function in `renderer.js` maps `WARNING` to `warn`
(yellow). Verify this mapping exists:

```javascript
function statusClass(value) {
  if (value === 'PASS') return 'pass';
  if (value === 'FAIL') return 'fail';
  if (['WARNING', 'HARDWARE_DETECTED', 'DATA_UNAVAILABLE'].includes(value)) return 'warn';
  return 'skip';
}
```

If `WARNING` is not in the warn list, add it.

## Part 4: Today tab card — battery WARNING display

In `module.html` Today tab, the mini status dots section includes battery:
```html
{label:'Batt', val: r.payload?.battery?.status}
```

`WARNING` maps to `warn` class → yellow dot. No change needed if
`statusClass()` handles it correctly.

## Part 5: Card summary — show Cyclelution reminder

In the Today tab card body, add battery warning message when status is WARNING:

```html
<div class="card-body">
  <div class="card-spec" x-text="r.payload?.cpu?.model ?? ''"></div>
  <div class="card-spec"
       x-text="(r.payload?.memory?.total_gb ?? '') + ' GB  •  Battery ' + (r.payload?.battery?.health_percent ?? '?') + '%'">
  </div>
  <!-- Cyclelution reminder when battery WARNING -->
  <div x-show="r.payload?.battery?.status === 'WARNING'"
       style="font-size:0.78em;color:var(--warn);padding:4px 16px 0;">
    ⚠ Battery warning — mark note in Cyclelution
  </div>
</div>
```

## Verification

1. Upload a laptop JSON with `battery.status: "WARNING"`
2. Today tab → card shows yellow battery dot + Cyclelution reminder text
3. Card overall badge shows `PASS` (not FAIL)
4. Expand detail → Battery section shows yellow WARNING
5. This Week stats → fail_reasons does NOT include battery
6. PASS count includes this machine (not in FAIL count)

## Constraints
- Do NOT change overall_result logic
- WARNING must appear yellow in all views
- fail_reasons stats must NOT count battery WARNING
- Do NOT modify storage.py or core/
