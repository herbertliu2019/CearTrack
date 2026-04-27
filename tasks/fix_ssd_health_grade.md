# Task: Add SSD Health Grading to laptop_test.sh

## Goal
Add SSD health percentage and grade (A/B/C/D) to the storage section.
Support three disk types: NVMe SSD, SATA SSD, HDD.

## Disk Type + Grade Logic

| Disk | type field | Grade |
|------|-----------|-------|
| NVMe SSD | `SSD NVMe` | A/B/C/D by ssd_health_percent |
| SATA SSD | `SSD` | A/B/C/D by ssd_health_percent |
| HDD | `HDD` | `unknown` |

Grade definition (applies to both NVMe and SATA SSD):

| Grade | ssd_health_percent |
|-------|-------------------|
| A | >= 95% |
| B | >= 80% |
| C | >= 70% |
| D | < 70% |

## Fix 1: NVMe Disk Type Label

In the storage section, after `disk_type` is set:

```bash
disk_type="HDD"
[[ "$rotational" == "0" ]] && disk_type="SSD"
[[ "$disk" == *"nvme"* ]] && disk_type="SSD NVMe"
```

## Fix 2: Health Detection per Disk Type

Replace the existing SSD health block with this logic:

```bash
SSD_HEALTH_PCT="unknown"
SSD_GRADE="unknown"
SSD_AVAIL_SPARE="unknown"
SSD_DATA_WRITTEN="unknown"

if [[ "$disk_type" == "SSD NVMe" ]]; then
  # NVMe: use Percentage Used
  SMART_DETAIL=$(smartctl -A "$disk" 2>/dev/null)
  PCT_USED=$(echo "$SMART_DETAIL" | grep "Percentage Used" | grep -oP '\d+(?=%)' | head -1)
  AVAIL_SPARE=$(echo "$SMART_DETAIL" | grep "Available Spare:" | grep -oP '\d+(?=%)' | head -1)
  SSD_DATA_WRITTEN=$(echo "$SMART_DETAIL" | grep "Data Units Written" \
    | cut -d: -f2 | xargs | cut -d'[' -f2 | tr -d ']' | xargs)

  if [[ -n "$PCT_USED" ]]; then
    SSD_HEALTH_PCT=$((100 - PCT_USED))
  fi
  [[ -n "$AVAIL_SPARE" ]] && SSD_AVAIL_SPARE="${AVAIL_SPARE}%"

elif [[ "$disk_type" == "SSD" ]]; then
  # SATA SSD: use Wear_Leveling_Count VALUE field
  # VALUE column is the normalized health score (100=new, decreases with wear)
  SMART_DETAIL=$(smartctl -A "$disk" 2>/dev/null)

  # Try Wear_Leveling_Count first (Samsung, most common)
  WLC_VALUE=$(echo "$SMART_DETAIL" | awk '/Wear_Leveling_Count/{print $4}' | head -1)

  # Fallback: Media_Wearout_Indicator (Intel, some others)
  if [[ -z "$WLC_VALUE" ]]; then
    WLC_VALUE=$(echo "$SMART_DETAIL" | awk '/Media_Wearout_Indicator/{print $4}' | head -1)
  fi

  # Fallback: SSD_Life_Left
  if [[ -z "$WLC_VALUE" ]]; then
    WLC_VALUE=$(echo "$SMART_DETAIL" | awk '/SSD_Life_Left/{print $4}' | head -1)
  fi

  if [[ -n "$WLC_VALUE" ]] && [[ "$WLC_VALUE" =~ ^[0-9]+$ ]]; then
    SSD_HEALTH_PCT=$WLC_VALUE
  fi
  # SATA SSD has no Available Spare or Data Written equivalent
  SSD_AVAIL_SPARE="N/A"
  SSD_DATA_WRITTEN="N/A"
fi

# Apply grade for SSD types (NVMe and SATA)
if [[ "$SSD_HEALTH_PCT" != "unknown" ]] && [[ "$disk_type" != "HDD" ]]; then
  if   [[ $SSD_HEALTH_PCT -ge 95 ]]; then SSD_GRADE="A"
  elif [[ $SSD_HEALTH_PCT -ge 80 ]]; then SSD_GRADE="B"
  elif [[ $SSD_HEALTH_PCT -ge 70 ]]; then SSD_GRADE="C"
  else SSD_GRADE="D"
  fi
fi
```

## Fix 3: Update JSON Storage Entry

Change the DISK_JSON line to include new fields:

```bash
DISK_JSON+="{\"device\":\"$name\",\"model\":\"${model:-unknown}\",\"size\":\"${size:-unknown}\",\"type\":\"$disk_type\",\"smart\":\"$smart\",\"power_on_hours\":\"${power_on_hours:-unknown}\",\"ssd_health_percent\":\"${SSD_HEALTH_PCT}\",\"ssd_grade\":\"${SSD_GRADE}\",\"ssd_available_spare\":\"${SSD_AVAIL_SPARE}\",\"ssd_data_written\":\"${SSD_DATA_WRITTEN}\"}"
```

## Fix 4: Update Console Output

After the existing `ok "$name | ..."` line, add:

```bash
if [[ "$disk_type" != "HDD" && "$SSD_GRADE" != "unknown" ]]; then
  ok "  SSD Health: ${SSD_HEALTH_PCT}% | Grade: ${SSD_GRADE} | Available Spare: ${SSD_AVAIL_SPARE} | Written: ${SSD_DATA_WRITTEN}"
fi
```

## Expected JSON Output

NVMe SSD:
```json
{
  "device": "nvme0n1",
  "model": "SK Hynix 256GB",
  "type": "SSD NVMe",
  "smart": "PASSED",
  "power_on_hours": "267",
  "ssd_health_percent": "98",
  "ssd_grade": "A",
  "ssd_available_spare": "100%",
  "ssd_data_written": "1.13 TB"
}
```

SATA SSD:
```json
{
  "device": "sda",
  "model": "Samsung 860 EVO 500GB",
  "type": "SSD",
  "smart": "PASSED",
  "power_on_hours": "1240",
  "ssd_health_percent": "100",
  "ssd_grade": "A",
  "ssd_available_spare": "N/A",
  "ssd_data_written": "N/A"
}
```

HDD:
```json
{
  "device": "sda",
  "model": "WD Blue 1TB",
  "type": "HDD",
  "smart": "PASSED",
  "power_on_hours": "8900",
  "ssd_health_percent": "unknown",
  "ssd_grade": "unknown",
  "ssd_available_spare": "unknown",
  "ssd_data_written": "unknown"
}
```

## Constraints
- Only modify storage section (section 4)
- Do not change existing field names
- Run `bash -n laptop_test.sh` after changes to verify syntax
