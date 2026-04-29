# Task: SSD Health Grading — Use smartctl -x for All Disk Types

## Problem

Previous implementation used `smartctl -A` which misses:
- SATA SSD `Percentage Used` — located in `Device Statistics` section,
  only available via `smartctl -x`
- Result: ssd_health_percent, ssd_grade, ssd_available_spare,
  ssd_data_written all return "N/A" or "unknown" for SATA SSD

## Solution

Replace `smartctl -A` with `smartctl -x` for all SSD health reads.
Both NVMe and SATA SSD use the same `Percentage Used` field,
just in different sections — `smartctl -x` outputs both.

## Field Locations in smartctl -x output

### NVMe SSD (from SMART/Health Information section):
```
Available Spare:                    100%
Percentage Used:                    2%
Data Units Written:                 21,698,391 [11.1 TB]
Power On Hours:                     2,039
```

### SATA SSD (from Device Statistics section):
```
0x07  0x008  1               0  ---  Percentage Used Endurance Indicator
```
Value is the last number on the line (column $NF).

### SATA SSD Power On Hours (from SMART Attributes):
```
  9 Power_On_Hours  -O--CK   100   100   000    -    60
```

## Replace Fix 2 in storage section with this code:

```bash
SSD_HEALTH_PCT="unknown"
SSD_GRADE="unknown"
SSD_AVAIL_SPARE="unknown"
SSD_DATA_WRITTEN="unknown"

if [[ "$disk_type" == "SSD NVMe" || "$disk_type" == "SSD" ]]; then
  SMART_X=$(smartctl -x "$disk" 2>/dev/null)

  if [[ "$disk_type" == "SSD NVMe" ]]; then
    # NVMe: Percentage Used is in SMART/Health Information section
    # Format: "Percentage Used:                    2%"
    PCT_USED=$(echo "$SMART_X" | grep "^Percentage Used:" \
      | grep -oP '\d+(?=%)' | head -1)

    # Available Spare
    AVAIL_SPARE=$(echo "$SMART_X" | grep "^Available Spare:" \
      | grep -oP '\d+(?=%)' | head -1)
    [[ -n "$AVAIL_SPARE" ]] && SSD_AVAIL_SPARE="${AVAIL_SPARE}%"

    # Data Units Written — extract the [X.X TB/GB] part
    SSD_DATA_WRITTEN=$(echo "$SMART_X" | grep "^Data Units Written:" \
      | grep -oP '\[.*?\]' | tr -d '[]' | head -1)

  elif [[ "$disk_type" == "SSD" ]]; then
    # SATA SSD: Percentage Used is in Device Statistics section
    # Format: "0x07  0x008  1               0  ---  Percentage Used Endurance Indicator"
    # Value is field $4 (the number before the flags)
    PCT_USED=$(echo "$SMART_X" \
      | grep "Percentage Used Endurance Indicator" \
      | awk '{print $4}' | head -1)

    # SATA SSD: no Available Spare or Data Written equivalent
    SSD_AVAIL_SPARE="N/A"
    SSD_DATA_WRITTEN="N/A"
  fi

  # Calculate health percent (same formula for both)
  if [[ -n "$PCT_USED" ]] && [[ "$PCT_USED" =~ ^[0-9]+$ ]]; then
    SSD_HEALTH_PCT=$((100 - PCT_USED))
  fi
fi

# Apply grade for all SSD types
if [[ "$SSD_HEALTH_PCT" != "unknown" ]]; then
  if   [[ $SSD_HEALTH_PCT -ge 95 ]]; then SSD_GRADE="A"
  elif [[ $SSD_HEALTH_PCT -ge 80 ]]; then SSD_GRADE="B"
  elif [[ $SSD_HEALTH_PCT -ge 70 ]]; then SSD_GRADE="C"
  else SSD_GRADE="D"
  fi
fi
```

## Also Replace power_on_hours read to use smartctl -x

Currently `power_on_hours` uses `smartctl -a`. Replace with reuse of
`$SMART_X` already fetched above (avoid double call):

For NVMe:
```bash
# NVMe power on hours from SMART/Health Information
power_hours=$(echo "$SMART_X" | grep "^Power On Hours:" \
  | awk '{print $NF}' | tr -d ',' | head -1)
```

For SATA SSD/HDD — keep existing `smartctl -a` call OR reuse SMART_X:
```bash
# SATA: Power_On_Hours from SMART Attributes (field $10 = RAW_VALUE)
power_hours=$(echo "$SMART_X" \
  | awk '/Power_On_Hours/{print $10}' | head -1)
```

## Expected JSON Output

NVMe (Samsung MZVLB256, Percentage Used=2%):
```json
{
  "type": "SSD NVMe",
  "smart": "PASSED",
  "power_on_hours": "2039",
  "ssd_health_percent": "98",
  "ssd_grade": "A",
  "ssd_available_spare": "100%",
  "ssd_data_written": "11.1 TB"
}
```

SATA SSD (LITEON CV1-8B256, Percentage Used Endurance=0):
```json
{
  "type": "SSD",
  "smart": "PASSED",
  "power_on_hours": "60",
  "ssd_health_percent": "100",
  "ssd_grade": "A",
  "ssd_available_spare": "N/A",
  "ssd_data_written": "N/A"
}
```

HDD:
```json
{
  "type": "HDD",
  "ssd_health_percent": "unknown",
  "ssd_grade": "unknown",
  "ssd_available_spare": "unknown",
  "ssd_data_written": "unknown"
}
```

## Debug Check

After implementing, test with these commands to verify parsing:

```bash
# NVMe
smartctl -x /dev/nvme0n1 | grep "^Percentage Used:"
smartctl -x /dev/nvme0n1 | grep "^Available Spare:"
smartctl -x /dev/nvme0n1 | grep "^Data Units Written:"

# SATA SSD
smartctl -x /dev/sda | grep "Percentage Used Endurance Indicator"
# Expected output line: "0x07  0x008  1               0  ---  Percentage Used Endurance Indicator"
# $4 = 0 → health = 100%
```

## Constraints
- Replace `smartctl -A` and `smartctl -H` calls with single `smartctl -x`
- Reuse `$SMART_X` variable — do NOT call smartctl twice per disk
- Only modify storage section (section 4)
- Do not change JSON field names
- Run `bash -n laptop_test.sh` after changes to verify syntax
