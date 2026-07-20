# Fix: Touchpad Test — evdev Auto-Detection

## Goal
Replace manual `ask_manual("Touchpad click / scroll")` with automated
evdev-based detection. Verify touchpad hardware is functional by detecting
actual input signals — no human judgment needed for basic functionality.

## What Can Be Auto-Detected via evdev

| Test | evdev Event | Auto-detectable |
|------|-------------|-----------------|
| Touchpad exists | device in /dev/input/ with ABS_X + BTN_TOUCH | ✅ |
| Single finger move | ABS_X/ABS_Y change | ✅ |
| Physical/tap click | BTN_LEFT event | ✅ |
| Two-finger touch | ABS_MT_SLOT value > 0 | ✅ |
| Two-finger scroll direction | libinput gesture | ❌ needs X11 |

Two-finger scroll gesture itself cannot be detected in TTY — but
detecting two-finger touch signal confirms the hardware supports it.

## Dependency
`python3-evdev` — already added by keyboard test task.

## Finding Touchpad Device

```python
import evdev
from evdev import ecodes

def find_touchpad():
    devices = [evdev.InputDevice(p) for p in evdev.list_devices()]
    for dev in devices:
        caps = dev.capabilities()
        keys = caps.get(ecodes.EV_KEY, [])
        abs_axes = caps.get(ecodes.EV_ABS, [])
        abs_codes = [a[0] if isinstance(a, tuple) else a for a in abs_axes]
        # Touchpad: has ABS_X/ABS_Y + BTN_TOUCH, no keyboard letter keys
        if (ecodes.ABS_X in abs_codes and
            ecodes.ABS_Y in abs_codes and
            ecodes.BTN_TOUCH in keys and
            ecodes.KEY_A not in keys):  # exclude keyboard
            return dev
    return None
```

## Test Logic

Run three sub-tests sequentially, each with a 10-second timeout:

### Sub-test 1: Single finger move
```
► Move one finger across the touchpad...
```
- Listen for `EV_ABS` + `ABS_X` or `ABS_Y` value change > 50 units
- Pass condition: movement detected within timeout
- Result: `SINGLE_MOVE=PASS|FAIL`

### Sub-test 2: Click (physical or tap)
```
► Click the touchpad (physical click or tap)...
```
- Listen for `EV_KEY` + `BTN_LEFT` with value=1 (keydown)
- Pass condition: click detected within timeout
- Result: `CLICK=PASS|FAIL`

### Sub-test 3: Two-finger touch
```
► Place TWO fingers on the touchpad...
```
- Listen for `EV_ABS` + `ABS_MT_SLOT` with value >= 1
  OR `ABS_MT_TRACKING_ID` events on slot 1
- Pass condition: second finger slot detected within timeout
- Result: `TWO_FINGER=PASS|FAIL`

## Display Format

```
=== TOUCHPAD TEST ===

[1/3] Move one finger across the touchpad...
      ✓ Movement detected                          (green)

[2/3] Click the touchpad (physical press or tap)...
      ✓ Click detected                             (green)

[3/3] Place TWO fingers on the touchpad...
      ✓ Two-finger touch detected                  (green)

Touchpad result: PASS
```

On timeout (10s no signal):
```
[1/3] Move one finger across the touchpad...
      ✗ No movement detected (timeout)             (red)
```

## Overall Touchpad Result

- All 3 PASS → `TOUCHPAD=PASS`
- Any FAIL → `TOUCHPAD=FAIL`
- Device not found → `TOUCHPAD=NOT_FOUND`

## Fallback

If `python3-evdev` not available or no touchpad device found:
```
⚠ evdev not available — manual confirmation required
```
Fall back to existing `ask_manual("Touchpad click / scroll" ...)`.

## Integration in Main Script

Replace this line:
```bash
TOUCHPAD=$(ask_manual "Touchpad click / scroll" "Test single click, double click, and two-finger scroll")
```

With:
```bash
run_touchpad_test
TOUCHPAD=$TOUCHPAD_RESULT
```

Add new function `run_touchpad_test()` that sets `TOUCHPAD_RESULT`.

## JSON (unchanged)
```json
"keyboard": {
  "device_status": "...",
  "keys_check": "...",
  "touchpad_check": "PASS|FAIL|NOT_FOUND|SKIPPED"
}
```

## Constraints
- Add `run_touchpad_test()` as a new function — do not modify other functions
- Replace only the `TOUCHPAD=$(ask_manual ...)` call line
- Do not change JSON field names
- Run `bash -n laptop_test.sh` after changes
- Timeout per sub-test: 10 seconds
- Script runs as root so /dev/input/ access guaranteed
