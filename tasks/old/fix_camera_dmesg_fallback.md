# Fix: Camera Detection — Add dmesg Fallback for Driver-Failed Hardware

## Problem

Some laptops (e.g. Surface with ov13858 sensor) have camera hardware
recognized by ACPI/kernel but driver fails to initialize:
```
ov13858: probe of i2c-OVTID858:00 failed with error -22
pci 0000:00:05.0: DMAR: Passthrough IOMMU for integrated Intel IPU
```

Result: `/dev/video*` does not exist, current script reports `NOT_FOUND`.
This is incorrect — hardware exists but Linux driver failed.

## Three-State Camera Result

| State | Condition | Meaning |
|-------|-----------|---------|
| `PASS` | `/dev/video*` exists + image captured | Fully working |
| `HARDWARE_DETECTED` | dmesg shows IPU/camera but no `/dev/video*` | HW exists, driver failed |
| `NOT_FOUND` | No `/dev/video*` AND no dmesg evidence | No camera hardware |

## dmesg Keywords to Detect

```bash
dmesg | grep -iE "ipu|cio2|imgu|ov[0-9]+|hi[0-9]+|imx[0-9]+|camera|webcam|uvcvideo|OVTID|csi[0-9]"
```

If any match found → camera hardware detected at kernel level.

## Implementation

Add dmesg fallback check in the camera section (section 7).

### Current flow:
```
/dev/video* exists? → yes → capture image
                   → no  → CAM_STATUS=FAIL
```

### New flow:
```
/dev/video* exists? → yes → capture image → CAM_STATUS=PASS/FAIL
                   → no  → dmesg check
                              → found keywords → CAM_STATUS=HARDWARE_DETECTED
                              → no keywords   → CAM_STATUS=NOT_FOUND
```

### Code to add after existing camera device loop:

```bash
if [[ ${#CAM_DEVICES[@]} -eq 0 ]]; then
  # No /dev/video* found — check dmesg for hardware evidence
  DMESG_CAM=$(dmesg 2>/dev/null | grep -iE \
    "ipu|cio2|imgu|ov[0-9]+|hi[0-9]+|imx[0-9]+|camera|webcam|uvcvideo|OVTID|csi[0-9]" \
    | head -5)

  if [[ -n "$DMESG_CAM" ]]; then
    CAM_STATUS="HARDWARE_DETECTED"
    warn "No /dev/video* found, but camera hardware detected in kernel log:"
    echo "$DMESG_CAM" | while read -r line; do
      warn "  $line"
    done
    warn "Driver failed to initialize — verify camera in Windows/OEM OS."
    CAM_DRIVER_NOTE="driver_init_failed"
  else
    CAM_STATUS="NOT_FOUND"
    err "No camera device found and no hardware evidence in kernel log."
    CAM_DRIVER_NOTE="no_hardware"
  fi
fi
```

## JSON Changes

Add two new fields to camera object:

```json
"camera": {
  "device_status": "PASS | HARDWARE_DETECTED | NOT_FOUND",
  "device_count": 0,
  "driver_type": "uvc | ipu3 | ipu6 | unknown | none",
  "capture_method": "ffmpeg | libcamera | none",
  "capture_result": "SUCCESS | FAILED | NOT_ATTEMPTED",
  "image_quality_check": "PASS | FAIL | SKIPPED",
  "driver_note": "driver_init_failed | no_hardware | ok"
}
```

Add `CAM_DRIVER_NOTE` variable, default `"ok"` when camera works normally.

## overall_result Logic

`HARDWARE_DETECTED` must **NOT** trigger overall FAIL.
Only `FAIL` (device found but capture failed) triggers overall FAIL.

Current overall_result counts `"FAIL"` strings in JSON.
`"HARDWARE_DETECTED"` and `"NOT_FOUND"` will not match `"FAIL"` so
no change needed to overall_result logic.

## Summary Display

Add to TEST SUMMARY section:
```bash
if [[ "$CAM_STATUS" == "HARDWARE_DETECTED" ]]; then
  printf "  %-20s %s\n" "Camera:" "HARDWARE DETECTED — driver failed (verify in Windows)"
else
  printf "  %-20s %s\n" "Camera:" "$CAM_STATUS | Image: $CAM_IMAGE_RESULT"
fi
```

## Constraints
- Only modify camera section (section 7) and summary section
- Do not change other sections
- Do not change existing JSON field names — only add new fields
- `CAM_DRIVER_NOTE` defaults to `"ok"` when camera works normally
- Run `bash -n laptop_test.sh` after changes
