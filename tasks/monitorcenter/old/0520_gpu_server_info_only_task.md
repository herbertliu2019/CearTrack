# MonitorCenter GPU Module — INFO_ONLY Tier Server Task ✅ COMPLETED 2026-05-20
**Project:** CearTrack / MonitorCenter
**Module:** `gpu`
**Deploy path:** `/opt/monitorcenter/`
**Depends on:** `gpu_test_tier_task.md` (client-side changes must be deployed first)

---

## Background

Client script `gpu_test.sh` now supports two test tiers:
- `FULL` — complete test (gpu-burn + glmark2), result = PASS/WARN/FAIL
- `INFO_ONLY` — L1 info only (low VRAM < 4096MB or legacy card), result = INFO_ONLY

Server must handle `INFO_ONLY` as a new valid `overall_result` value.

JSON from INFO_ONLY card example:
```json
{
  "module": "gpu",
  "sn": "Quadro_P400_20260520_091535",
  "overall_result": "INFO_ONLY",
  "summary": "GPU:Quadro P400 VRAM:2048MB MODE:INFO_ONLY",
  "payload": {
    "test_info": {
      "test_tier": "INFO_ONLY",
      ...
    },
    "vram_test": { "status": "SKIPPED" },
    "vulkan_benchmark": { "status": "SKIPPED", "score": 0 }
  }
}
```

---

## Task T1 — module.py: Accept INFO_ONLY as valid result

**File:** `modules/gpu/module.py`

**Find** the validation section that checks `overall_result` values and add `INFO_ONLY`:

```python
VALID_RESULTS = {"PASS", "WARN", "FAIL", "INFO_ONLY"}

# In validate() method, ensure overall_result check uses this set
if data.get("overall_result") not in VALID_RESULTS:
    return False, f"Invalid overall_result: {data.get('overall_result')}"
```

**Also update** stats calculation — INFO_ONLY should NOT count as pass or fail:

```python
def _count_results(self, records):
    counts = {"PASS": 0, "WARN": 0, "FAIL": 0, "INFO_ONLY": 0, "total": 0}
    for r in records:
        result = r.get("overall_result", "")
        if result in counts:
            counts[result] += 1
        counts["total"] += 1
    # pass_rate based on FULL tier only
    full_tier = counts["PASS"] + counts["WARN"] + counts["FAIL"]
    counts["pass_rate"] = round(counts["PASS"] / full_tier * 100) if full_tier > 0 else 0
    return counts
```

---

## Task T2 — module.py: API endpoints return INFO_ONLY stats

**File:** `modules/gpu/module.py`

Update `/gpu/api/today` and `/gpu/api/stats` responses to include `info_only` count:

```python
# Response structure
{
    "stats": {
        "total": 10,
        "passed": 6,
        "warned": 1,
        "failed": 1,
        "info_only": 2,        # NEW
        "pass_rate": 75        # based on FULL tier only (6/8)
    },
    "records": [...]
}
```

---

## Task T3 — dashboard.html: INFO_ONLY badge color

**File:** `templates/gpu/dashboard.html`

Add light blue color for INFO_ONLY in CSS and result badge logic.

**CSS addition** (add alongside existing PASS/WARN/FAIL vars):
```css
--info-only: #64748b;        /* light blue */
--info-only-bg: #f1f5f9;     /* very light blue background */
--info-only-text: #334155;   /* dark blue text */
```

**Result badge function** — add INFO_ONLY case:
```javascript
resultClass(result) {
    const map = {
        'PASS':      'pass',
        'WARN':      'warn',
        'FAIL':      'fail',
        'INFO_ONLY': 'info-only'   // NEW
    };
    return map[result] || 'unknown';
},

resultLabel(result) {
    const map = {
        'PASS':      '✅ PASS',
        'WARN':      '⚠️ WARN',
        'FAIL':      '❌ FAIL',
        'INFO_ONLY': 'ℹ️ INFO'    // NEW
    };
    return map[result] || result;
}
```

**Badge CSS** (add alongside .badge-pass, .badge-fail etc):
```css
.badge-info-only {
    background: var(--info-only-bg);
    color: var(--info-only-text);
    border: 1px solid var(--info-only);
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 0.85em;
    font-weight: 600;
}
```

---

## Task T4 — dashboard.html: KPI strip add INFO_ONLY count

**File:** `templates/gpu/dashboard.html`

Add 5th KPI card for INFO_ONLY (light blue):

```html
<!-- Existing 4 cards: Total / Passed / Failed / Pass Rate -->
<!-- Add 5th card: -->
<div class="kpi-card info-only">
    <div class="kpi-value" x-text="stats.info_only || 0"></div>
    <div class="kpi-label">Info Only</div>
</div>
```

**KPI card CSS:**
```css
.kpi-card.info-only .kpi-value {
    color: var(--info-only);
}
```

---

## Task T5 — dashboard.html: INFO_ONLY detail panel

**File:** `templates/gpu/dashboard.html`

When expanding an INFO_ONLY card, show different detail content:

```javascript
// In renderGpuDetail(r) or detail panel template
// Check test_tier from payload
const tier = r.payload?.test_info?.test_tier || 'FULL';

if (tier === 'INFO_ONLY') {
    // Show simplified view — no test results section
    // Show info banner
    infoSection = `
        <div class="info-only-banner">
            ℹ️ <strong>Info Only Mode</strong> —
            VRAM ${r.payload?.gpu?.vram_mb || 0}MB is below 4096MB threshold.
            Stress tests were skipped. Card suitable for office / display use.
        </div>
    `;
    // Hide VRAM test, glmark2 score sections
    // Show only GPU spec section
} else {
    // existing full detail panel
}
```

**Info banner CSS:**
```css
.info-only-banner {
    background: var(--info-only-bg);
    border-left: 4px solid var(--info-only);
    color: var(--info-only-text);
    padding: 10px 14px;
    border-radius: 4px;
    margin-bottom: 12px;
    font-size: 0.9em;
}
```

---

## Task T6 — dashboard.html: Filter INFO_ONLY from pass rate calculation

**File:** `templates/gpu/dashboard.html`

Pass rate display should show:
```
Pass Rate: 75% (of fully-tested cards)
```

Not count INFO_ONLY cards in denominator:

```javascript
// In stats display
passRateLabel() {
    const fullTier = (this.stats.passed || 0) + 
                     (this.stats.warned || 0) + 
                     (this.stats.failed || 0);
    if (fullTier === 0) return 'N/A';
    return Math.round((this.stats.passed / fullTier) * 100) + '%';
}
```

---

## Task T7 — PDF report: INFO_ONLY template

**File:** `modules/gpu/templates/gpu/gpu_report.html`

Add INFO_ONLY section that replaces test results:

```html
{% if overall == 'INFO_ONLY' %}
<div class="info-only-section">
    <div class="info-header">ℹ️ INFO ONLY — Stress Tests Skipped</div>
    <table class="info-table">
        <tr>
            <td class="label">Reason</td>
            <td class="value">VRAM {{ data.gpu.vram_mb }}MB &lt; 4096MB threshold</td>
        </tr>
        <tr>
            <td class="label">Suitable for</td>
            <td class="value">Office use / display output / light workloads</td>
        </tr>
        <tr>
            <td class="label">Tests run</td>
            <td class="value">L1 Hardware Identification only</td>
        </tr>
    </table>
</div>
{% else %}
<!-- existing test results section -->
{% endif %}
```

**CSS for PDF:**
```css
.info-only-section {
    background: #f1f5f9;
    border-left: 4px solid #64748b;
    padding: 12px;
    margin: 10px 0;
    border-radius: 4px;
}
.info-header {
    color: #334155;
    font-weight: bold;
    margin-bottom: 8px;
}
```

**Verdict stamp** — light blue instead of green/red:
```html
<div class="verdict {{ overall|lower|replace('_','-') }}">
    {% if overall == 'INFO_ONLY' %}
        ℹ️ INFO ONLY
    {% elif overall == 'PASS' %}
        ✅ PASS
    ...
    {% endif %}
</div>
```

---

## Task T8 — schema.json: Add test_tier field

**File:** `modules/gpu/schema.json`

Add `test_tier` to the Test Results section:

```json
{
    "key": "payload.test_info.test_tier",
    "label": "Test Tier",
    "type": "badge"
}
```

---

## Implementation Notes for Claude Code

1. **Read existing files first** before any edits:
   - `modules/gpu/module.py`
   - `templates/gpu/dashboard.html`
   - `modules/gpu/templates/gpu/gpu_report.html`
   - `modules/gpu/schema.json`

2. **Do NOT modify** `core/` files

3. **Run syntax check** after Python changes:
   ```bash
   python -m py_compile modules/gpu/module.py
   ```

4. **Test with curl** after T1-T2:
   ```bash
   # Upload a test INFO_ONLY JSON
   curl -X POST http://localhost:5004/gpu/api/upload \
     -H "Content-Type: application/json" \
     -H "X-API-Key: ceartrack-upload-2026" \
     -d '{"module":"gpu","sn":"test-info","overall_result":"INFO_ONLY",
          "timestamp":"2026-05-20T10:00:00","summary":"test",
          "payload":{"test_info":{"test_tier":"INFO_ONLY","test_time":"2026-05-20T10:00:00",
          "test_station":"test","script_version":"1.1.0","burn_duration_seconds":0,
          "glmark2_duration_seconds":0,"total_duration_seconds":30},
          "gpu":{"vendor":"NVIDIA","name":"Quadro P400","chip":"GP107GL",
          "vram_mb":2048,"vram_type":"GDDR5","vram_bus_width":64,
          "vram_bandwidth_gbps":14.4,"driver_version":"535.288.01",
          "bios_version":"86.07.8F.00.0A","pcie_gen":3,"pcie_gen_current":3,
          "pcie_width_current":4,"pcie_width_max":16,"clock_gpu_mhz":1228,
          "clock_mem_mhz":1752,"power_limit_w":"30","subvendor":"Dell",
          "device_id":"10DE:1CB3","gpu_sn":""},
          "thermal":{"temp_max_c":0,"temp_avg_c":0,"util_avg_pct":0,"power_max_w":0.0,
          "thermal_log_path":""},
          "vram_test":{"tool":"skipped","duration_seconds":0,"errors":0,"status":"SKIPPED"},
          "vulkan_benchmark":{"tool":"glmark2","resolution":"1920x1080","score":0,"status":"SKIPPED"},
          "dmesg_gpu_errors":[],"overall_result":"INFO_ONLY"}}'
   ```

5. **Color values** (slate gray-blue theme — neutral, "no conclusion"):
   - Primary: `#64748b`
   - Background: `#f1f5f9`
   - Text: `#334155`

6. **Pass rate** must exclude INFO_ONLY from denominator — this affects both server-side API response and client-side display calculation.

---

## Files to Modify

| File | Tasks |
|------|-------|
| `modules/gpu/module.py` | T1, T2 |
| `templates/gpu/dashboard.html` | T3, T4, T5, T6 |
| `modules/gpu/templates/gpu/gpu_report.html` | T7 |
| `modules/gpu/schema.json` | T8 |

## Files NOT to Modify

- `core/storage.py`
- `core/envelope.py`
- `core/module_registry.py`
- Any other module's files
