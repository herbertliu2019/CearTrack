# Fix: Camera — Filter Out False /dev/video* Devices (GPU/ACPI)

## Problem

On laptops without a physical camera, Linux registers GPU/ACPI video
devices as `/dev/video*`. These are NOT real cameras:

- `ACPI: video: Video Device [GFX0]` — Intel GPU ACPI display control
- Intel i915 media driver — registers video decode interfaces
- These devices may have v4l2 formats but cannot capture images

Current script detects these as cameras, then fails to capture,
creating confusion (reports camera found but no image).

## Root Cause

`v4l2-ctl --list-formats` may return entries for GPU video devices.
Need to filter by driver name — only real camera drivers produce images.

## Real Camera Drivers vs Fake

| Driver | Type | Keep? |
|--------|------|-------|
| `uvcvideo` | USB webcam (most laptops) | ✅ |
| `ov2740`, `ov8856`, `ov13858` | MIPI camera sensors | ✅ |
| `hi556`, `imx208`, `imx319` | MIPI camera sensors | ✅ |
| `gspca_*` | Older USB webcams | ✅ |
| `i915` | Intel GPU | ❌ |
| `acpi_video` | ACPI display control | ❌ |
| `pvrusb2`, `cx88`, `saa7134` | TV tuner cards | ❌ |

## Fix in `laptop_test.sh` — Camera Section (Section 7)

In the device detection loop, add driver name check BEFORE adding
device to `CAM_DEVICES`:

```bash
for dev in /dev/video*; do
  [[ -e "$dev" ]] || continue

  # Get driver name for this device
  cam_driver=$(v4l2-ctl --device="$dev" --info 2>/dev/null \
    | grep -i "Driver name" | cut -d: -f2 | xargs | tr '[:upper:]' '[:lower:]')

  # Skip known non-camera drivers
  case "$cam_driver" in
    i915|acpi_video|pvrusb2|cx88*|saa7134*|em28xx*|"")
      warn "Skipping $dev (driver: ${cam_driver:-unknown}) — not a camera device"
      continue
      ;;
  esac

  # Check capture formats exist
  fmt_count=$(v4l2-ctl --device="$dev" --list-formats 2>/dev/null | grep -c "\[")
  if [[ $fmt_count -eq 0 ]]; then
    warn "Skipping $dev — no capture formats available"
    continue
  fi

  # Real camera confirmed
  cam_name=$(v4l2-ctl --device="$dev" --info 2>/dev/null \
    | grep "Card type" | cut -d: -f2 | xargs)
  CAM_DEVICES+=("${dev}:${cam_name:-unknown}")
  CAM_STATUS=$PASS
  ok "Camera found: $dev | $cam_name | driver: $cam_driver"

  [[ -z "$CAM_CAPTURE_DEV" ]] && CAM_CAPTURE_DEV="$dev"
done
```

## Also Fix: dmesg Fallback for No-Camera Machines

When `/dev/video*` devices exist but are all filtered out (all GPU/ACPI),
AND dmesg shows no real camera hardware either:
- Set `CAM_STATUS="NOT_FOUND"`
- Do NOT set `CAM_STATUS="HARDWARE_DETECTED"`

Only set `HARDWARE_DETECTED` when dmesg shows actual camera sensor
keywords: `ipu3`, `ipu6`, `cio2`, `ov[0-9]+`, `hi[0-9]+`, `imx[0-9]+`

```bash
if [[ ${#CAM_DEVICES[@]} -eq 0 ]]; then
  DMESG_CAM=$(dmesg 2>/dev/null | grep -iE \
    "ipu[36]|cio2|imgu|ov[0-9]+|hi[0-9]+|imx[0-9]+|uvcvideo|OVTID" \
    | grep -viE "acpi.video|GFX0|display|shadowed ROM" \
    | head -5)

  if [[ -n "$DMESG_CAM" ]]; then
    CAM_STATUS="HARDWARE_DETECTED"
    warn "Camera hardware in kernel log but no working device node."
  else
    CAM_STATUS="NOT_FOUND"
    ok "No camera hardware detected (confirmed)."
  fi
fi
```

## Expected Results

Machine with no physical camera (GPU video only):
```
⚠ Skipping /dev/video0 (driver: i915) — not a camera device
✓ No camera hardware detected (confirmed).
```
```json
"camera": {
  "device_status": "NOT_FOUND",
  "device_count": 0,
  "capture_result": "NOT_ATTEMPTED",
  "image_base64": ""
}
```

Machine with real UVC webcam:
```
✓ Camera found: /dev/video0 | Integrated Camera | driver: uvcvideo
```

Machine with Surface IPU3 (driver failed):
```
✓ Camera hardware in kernel log but no working device node.
```
```json
"camera": {
  "device_status": "HARDWARE_DETECTED"
}
```

## Constraints
- Only modify camera section (section 7)
- Do not change any other sections
- Driver name check must be case-insensitive
- Run `bash -n laptop_test.sh` after changes to verify syntax
