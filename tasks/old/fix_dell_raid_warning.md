# Fix: Detect No Internal Storage + Dell RAID Warning

## Problem

Dell laptops default to RAID On BIOS setting. Linux AHCI driver cannot
see the disk in RAID mode. Result: storage section is empty `[]` with
no explanation — technician doesn't know why.

## Fix in `laptop_test.sh` — Storage Section (Section 4)

After the disk detection loop completes, add a check for empty results:

```bash
# After the while loop that builds DISK_JSON
if [[ $first -eq 1 ]]; then
  # No internal storage detected at all
  DISK_STATUS=$FAIL
  err "No internal storage detected."

  if echo "$SYS_VENDOR" | grep -qi "dell"; then
    warn "Dell detected — BIOS storage mode may be set to RAID."
    warn "Fix: Reboot → F2 → System Configuration → SATA Operation → set to AHCI"
    warn "Then re-run this test."
    DISK_FAIL_REASON="DELL_RAID_MODE"
  else
    warn "Check BIOS storage mode — may need to be set to AHCI."
    DISK_FAIL_REASON="NO_STORAGE_DETECTED"
  fi

  # Add a placeholder entry to JSON so server knows what happened
  DISK_JSON+='{"device":"none","model":"NOT DETECTED","size":"","type":"","smart":"FAIL","power_on_hours":"","ssd_health_percent":"unknown","ssd_grade":"unknown","ssd_available_spare":"unknown","ssd_data_written":"unknown","fail_reason":"'"$DISK_FAIL_REASON"'"}'
fi
```

## Expected Console Output (Dell with RAID On)

```
=== 4. Storage ===
  ✗ No internal storage detected.
  ⚠ Dell detected — BIOS storage mode may be set to RAID.
  ⚠ Fix: Reboot → F2 → System Configuration → SATA Operation → set to AHCI
  ⚠ Then re-run this test.
```

## Expected JSON Output

```json
"storage": [
  {
    "device": "none",
    "model": "NOT DETECTED",
    "size": "",
    "type": "",
    "smart": "FAIL",
    "power_on_hours": "",
    "ssd_health_percent": "unknown",
    "ssd_grade": "unknown",
    "ssd_available_spare": "unknown",
    "ssd_data_written": "unknown",
    "fail_reason": "DELL_RAID_MODE"
  }
]
```

`fail_reason` values:
- `DELL_RAID_MODE` — Dell vendor + no disk detected
- `NO_STORAGE_DETECTED` — non-Dell + no disk detected

## Effect on overall_result

`DISK_STATUS=$FAIL` is already set, so `overall_result` will be `FAIL`.
This is correct — a laptop with no detectable storage cannot be sold.

## Constraints
- Only modify storage section (section 4)
- Check must run AFTER the USB disk filter loop
- `SYS_VENDOR` variable is already set in section 1 — use it directly
- Run `bash -n laptop_test.sh` after changes to verify syntax
