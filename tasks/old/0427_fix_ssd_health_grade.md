# Task: Add NVMe SSD Health Grading to laptop_test.sh

## Goal
Add SSD health percentage and grade (A/B/C/D) to the storage section
of laptop_test.sh, based on NVMe `Percentage Used`.

## Also Fix: NVMe Disk Type Label

In the storage section, after `disk_type` is set, add NVMe detection:

```bash
disk_type="HDD"
[[ "$rotational" == "0" ]] && disk_type="SSD"
[[ "$disk" == *"nvme"* ]] && disk_type="SSD NVMe"   # ← add this line
```

---

## Grade Definition

| Grade | Condition |
|-------|-----------|
| A | ssd_health_percent >= 95% |
| B | ssd_health_percent >= 80% |
| C | ssd_health_percent >= 60% |
| D | ssd_health_percent < 60% |

`ssd_health_percent = 100 - Percentage Used`
Grade is based solely on `ssd_health_percent`.

## Where to Modify

Storage section (section 4) in `laptop_test.sh`.
Inside the `while IFS= read -r disk` loop, after SMART check,
add NVMe-specific fields before building the JSON entry.

## Code to Add

```bash
# NVMe SSD health (only for NVMe devices)
SSD_HEALTH_PCT="unknown"
SSD_GRADE="unknown"
SSD_AVAIL_SPARE="unknown"
SSD_DATA_WRITTEN="unknown"

if [[ "$disk" == *"nvme"* ]]; then
  SMART_DETAIL=$(smartctl -A "$disk" 2>/dev/null)

  PCT_USED=$(echo "$SMART_DETAIL" | grep "Percentage Used" | grep -oP '\d+(?=%)' | head -1)
  AVAIL_SPARE=$(echo "$SMART_DETAIL" | grep "Available Spare:" | grep -oP '\d+(?=%)' | head -1)
  SSD_DATA_WRITTEN=$(echo "$SMART_DETAIL" | grep "Data Units Written" | cut -d: -f2 | xargs | cut -d'[' -f2 | tr -d ']' | xargs)

  if [[ -n "$PCT_USED" ]]; then
    SSD_HEALTH_PCT=$((100 - PCT_USED))
    if   [[ $SSD_HEALTH_PCT -ge 95 ]]; then SSD_GRADE="A"
    elif [[ $SSD_HEALTH_PCT -ge 80 ]]; then SSD_GRADE="B"
    elif [[ $SSD_HEALTH_PCT -ge 60 ]]; then SSD_GRADE="C"
    else SSD_GRADE="D"
    fi
  fi

  [[ -n "$AVAIL_SPARE" ]] && SSD_AVAIL_SPARE="${AVAIL_SPARE}%"
fi
```

## Update JSON Storage Entry

Change the existing DISK_JSON line from:
```bash
DISK_JSON+="{\"device\":\"$name\",\"model\":\"${model:-unknown}\",\"size\":\"${size:-unknown}\",\"type\":\"$disk_type\",\"smart\":\"$smart\",\"power_on_hours\":\"${power_on_hours:-unknown}\"}"
```

To:
```bash
DISK_JSON+="{\"device\":\"$name\",\"model\":\"${model:-unknown}\",\"size\":\"${size:-unknown}\",\"type\":\"$disk_type\",\"smart\":\"$smart\",\"power_on_hours\":\"${power_on_hours:-unknown}\",\"ssd_health_percent\":\"${SSD_HEALTH_PCT}\",\"ssd_grade\":\"${SSD_GRADE}\",\"ssd_available_spare\":\"${SSD_AVAIL_SPARE}\",\"ssd_data_written\":\"${SSD_DATA_WRITTEN}\"}"
```

## Update Console Output

After `ok "$name | ..."` line, add:
```bash
[[ "$disk" == *"nvme"* && "$SSD_GRADE" != "unknown" ]] && \
  ok "  SSD Health: ${SSD_HEALTH_PCT}% | Grade: ${SSD_GRADE} | Available Spare: ${SSD_AVAIL_SPARE} | Written: ${SSD_DATA_WRITTEN}"
```

## Expected JSON Output

```json
"storage": [{
  "device": "nvme0n1",
  "model": "PC611 NVMe SK hynix 256GB",
  "size": "238.5G",
  "type": "SSD NVMe",
  "smart": "PASSED",
  "power_on_hours": "267",
  "ssd_health_percent": "98",
  "ssd_grade": "A",
  "ssd_available_spare": "100%",
  "ssd_data_written": "1.13 TB"
}]
```

For non-NVMe (HDD or SATA SSD), all new fields will be `"unknown"`.

## Constraints
- Only modify storage section (section 4)
- Do not change field names for existing fields
- SATA SSD and HDD: set all new fields to "unknown", do not error
- Run `bash -n laptop_test.sh` after changes to verify syntax
