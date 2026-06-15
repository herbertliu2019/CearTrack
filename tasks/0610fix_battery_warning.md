# Fix: Battery — Change FAIL to WARNING

## Rule Change

Battery issues must NOT cause overall_result to FAIL.
Battery bad condition = WARNING only, overall_result unaffected.

| Condition | Old status | New status |
|-----------|-----------|------------|
| health_percent < 60% | FAIL | WARNING |
| battery_condition = DEAD | FAIL | WARNING |
| battery_condition = DATA_UNAVAILABLE | BATTERY_DATA_UNAVAILABLE | WARNING |
| No battery found | NOT_FOUND | NOT_FOUND (unchanged) |

## Fix in `laptop_test.sh` — Battery Section (Section 5)

### Change 1: health threshold

Find:
```bash
if [[ "$BAT_HEALTH" != "?" ]] && (( $(echo "$BAT_HEALTH < 60" | bc -l) )); then
  BAT_STATUS=$FAIL
  err "Battery health critically low: ${BAT_HEALTH}% (threshold: 60%)"
```

Replace with:
```bash
if [[ "$BAT_HEALTH" != "?" ]] && (( $(echo "$BAT_HEALTH < 60" | bc -l) )); then
  BAT_STATUS="WARNING"
  warn "Battery health low: ${BAT_HEALTH}% — mark note in Cyclelution"
```

### Change 2: DEAD battery condition

Find:
```bash
BAT_STATUS=$FAIL
err "Battery physically dead"
```

Replace with:
```bash
BAT_STATUS="WARNING"
warn "Battery condition: DEAD — mark note in Cyclelution"
```

### Change 3: DATA_UNAVAILABLE condition

Find any line setting:
```bash
BAT_STATUS="BATTERY_DATA_UNAVAILABLE"
```

Replace with:
```bash
BAT_STATUS="WARNING"
```

### Change 4: overall_result must NOT count battery WARNING as FAIL

The current overall FAIL detection uses:
```bash
FAIL_COUNT=$(echo "$JSON" | grep -o '"FAIL"' | wc -l)
```

`"WARNING"` does not match `"FAIL"` so overall_result is automatically
unaffected. No change needed here.

### Change 5: Add Cyclelution reminder in SUMMARY section

In the TEST SUMMARY printf block, update battery line:

```bash
if [[ "$BAT_STATUS" == "WARNING" ]]; then
  printf "  %-20s %s\n" "Battery:" "WARNING ${BAT_HEALTH}% — ⚠ Mark note in Cyclelution"
else
  printf "  %-20s %s\n" "Battery:" "${BAT_STATUS} | Health: ${BAT_HEALTH}% | Cycles: ${BAT_CYCLE:-?}"
fi
```

## Expected Console Output

```
  ⚠ Battery health low: 55.0% — mark note in Cyclelution
  ...
  Battery:             WARNING 55.0% — ⚠ Mark note in Cyclelution
  RESULT: ✓ PASS — Ready for resale
```

## Expected JSON

```json
"battery": {
  "health_percent": "55.0",
  "status": "WARNING",
  "battery_condition": "OK"
}
```

`overall_result` remains `"PASS"` if all other checks pass.

## Constraints
- Only modify battery section (section 5) and summary section
- Do NOT change overall_result logic
- Run `bash -n laptop_test.sh` after changes
