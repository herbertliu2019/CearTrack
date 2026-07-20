# Fix: Camera — Remove Quality Check, Add Base64 Image to JSON

## Goal
Remove the manual `image_quality_check` prompt from camera section.
Capture image and embed it as base64 in the JSON for CearTrack to display.
Camera PASS/FAIL is determined automatically — no human judgment during test.

## Camera Result Logic

| Status | Condition |
|--------|-----------|
| `PASS` | Device found + image captured successfully |
| `HARDWARE_DETECTED` | Device found but driver failed (e.g. Surface IPU3) |
| `FAIL` | Device found but capture failed |
| `NOT_FOUND` | No device found + no dmesg evidence |

## Changes in `laptop_test.sh` — Camera Section (Section 7)

### 1. Remove `ask_manual` for image quality

Remove this line entirely:
```bash
CAM_IMAGE_RESULT=$(ask_manual "Camera image quality" "...")
```

Replace with automatic result based on capture success:
```bash
if [[ $CAPTURED -eq 1 ]]; then
  CAM_IMAGE_RESULT="CAPTURED"
else
  CAM_IMAGE_RESULT="CAPTURE_FAILED"
fi
```

### 2. Add base64 encoding after successful capture

After the capture success block, add:
```bash
CAM_IMAGE_B64=""
if [[ $CAPTURED -eq 1 && -f "$SNAP" ]]; then
  CAM_IMAGE_B64=$(base64 -w 0 "$SNAP" 2>/dev/null)
  ok "Image encoded for upload ($(wc -c < "$SNAP") bytes)"
  rm -f "$SNAP"
fi
```

### 3. Update JSON camera section

Change the camera JSON block to include `image_base64` and remove
`image_quality_check`:

```bash
"camera": {
  "device_status": "$(esc "$CAM_STATUS")",
  "device_count": ${CAM_COUNT:-0},
  "driver_type": "$(esc "$CAM_DRIVER_TYPE")",
  "capture_method": "$(esc "$CAM_CAPTURE_METHOD")",
  "capture_result": "$(esc "$CAM_IMAGE_RESULT")",
  "driver_note": "$(esc "$CAM_DRIVER_NOTE")",
  "image_base64": "$(esc "$CAM_IMAGE_B64")"
}
```

Remove `"image_quality_check"` field entirely.

### 4. Update overall_result logic

Camera `HARDWARE_DETECTED` and `CAPTURE_FAILED` must NOT trigger
overall FAIL. Only `FAIL` (device found, driver loaded, but capture
explicitly failed) triggers overall FAIL.

Verify the FAIL count logic only counts `"FAIL"` string — not
`"CAPTURE_FAILED"` or `"HARDWARE_DETECTED"`. Current logic uses:
```bash
FAIL_COUNT=$(echo "$JSON" | grep -o '"FAIL"' | wc -l)
```
This is correct — `"CAPTURE_FAILED"` won't match `"FAIL"`. No change needed.

### 5. Update TEST SUMMARY output

Replace camera summary line:
```bash
# Old
printf "  %-20s %s\n" "Camera:" "$CAM_STATUS | image: $CAM_IMAGE_RESULT"

# New
if [[ "$CAM_STATUS" == "HARDWARE_DETECTED" ]]; then
  printf "  %-20s %s\n" "Camera:" "HARDWARE DETECTED — verify in CearTrack"
elif [[ "$CAM_IMAGE_RESULT" == "CAPTURED" ]]; then
  printf "  %-20s %s\n" "Camera:" "PASS — image uploaded to CearTrack"
else
  printf "  %-20s %s\n" "Camera:" "$CAM_STATUS | $CAM_IMAGE_RESULT"
fi
```

## Expected JSON Output

```json
"camera": {
  "device_status": "PASS",
  "device_count": 1,
  "driver_type": "uvc",
  "capture_method": "ffmpeg",
  "capture_result": "CAPTURED",
  "driver_note": "ok",
  "image_base64": "/9j/4AAQSkZJRgABAQAA..."
}
```

When no image captured:
```json
"camera": {
  "device_status": "HARDWARE_DETECTED",
  "capture_result": "CAPTURE_FAILED",
  "image_base64": ""
}
```

## Constraints
- Only modify camera section (section 7) and summary section
- Do not change any other sections
- `image_base64` is empty string `""` when no image — never null
- Run `bash -n laptop_test.sh` after changes to verify syntax
