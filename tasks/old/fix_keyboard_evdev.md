# Fix: Keyboard Test — evdev Physical Key Response Detection

## Goal
Verify every physical key on the keyboard produces a signal when pressed.
Technician needs to see: "did this key respond or not?"
Not about key names — about physical key health (no dead/stuck keys).

## Dependency
Add to PKGS install list:
```bash
python3-evdev
```

## Display Design

Show a **standard keyboard layout** with two states:
- Key not yet pressed: dim/gray
- Key pressed: bright green

```
=== KEYBOARD TEST — Press every key, Ctrl+C when done ===

[ Esc ]  [ F1 ][ F2 ][ F3 ][ F4 ]  [ F5 ][ F6 ][ F7 ][ F8 ]  [ F9 ][F10][F11][F12]

[ ` ][ 1 ][ 2 ][ 3 ][ 4 ][ 5 ][ 6 ][ 7 ][ 8 ][ 9 ][ 0 ][ - ][ = ][ BkSp ]
[ Tab ][ Q ][ W ][ E ][ R ][ T ][ Y ][ U ][ I ][ O ][ P ][ [ ][ ] ][ \ ]
[CapsL][ A ][ S ][ D ][ F ][ G ][ H ][ J ][ K ][ L ][ ; ][ ' ][  Enter  ]
[Shift ][ Z ][ X ][ C ][ V ][ B ][ N ][ M ][ , ][ . ][ / ][ Shift ]
[Ctrl][Win][Alt][          Space          ][Alt][Fn][Menu][Ctrl]
             [ Up ]
        [Left][Down][Right]    [Ins][Del][Home][End][PgUp][PgDn]

Pressed: 12 / 78 keys
```

Use ANSI color codes:
- Not pressed: `\033[2;37m` (dim gray)
- Pressed: `\033[1;32m` (bright green)
- Redraw entire layout on each keypress using `\033[{N}A` to move cursor up

## Key Mapping Table

```python
KEY_MAP = {
    'KEY_ESC': 'Esc',
    'KEY_F1': 'F1', 'KEY_F2': 'F2', 'KEY_F3': 'F3', 'KEY_F4': 'F4',
    'KEY_F5': 'F5', 'KEY_F6': 'F6', 'KEY_F7': 'F7', 'KEY_F8': 'F8',
    'KEY_F9': 'F9', 'KEY_F10': 'F10', 'KEY_F11': 'F11', 'KEY_F12': 'F12',
    'KEY_BRIGHTNESSDOWN': 'Bri-', 'KEY_BRIGHTNESSUP': 'Bri+',
    'KEY_VOLUMEDOWN': 'Vol-', 'KEY_VOLUMEUP': 'Vol+',
    'KEY_MUTE': 'Mute', 'KEY_MICMUTE': 'MicMute',
    'KEY_PLAYPAUSE': 'Play', 'KEY_PREVIOUSSONG': 'Prev', 'KEY_NEXTSONG': 'Next',
    'KEY_GRAVE': '`', 'KEY_1': '1', 'KEY_2': '2', 'KEY_3': '3',
    'KEY_4': '4', 'KEY_5': '5', 'KEY_6': '6', 'KEY_7': '7',
    'KEY_8': '8', 'KEY_9': '9', 'KEY_0': '0',
    'KEY_MINUS': '-', 'KEY_EQUAL': '=', 'KEY_BACKSPACE': 'BkSp',
    'KEY_TAB': 'Tab',
    'KEY_Q': 'Q', 'KEY_W': 'W', 'KEY_E': 'E', 'KEY_R': 'R', 'KEY_T': 'T',
    'KEY_Y': 'Y', 'KEY_U': 'U', 'KEY_I': 'I', 'KEY_O': 'O', 'KEY_P': 'P',
    'KEY_LEFTBRACE': '[', 'KEY_RIGHTBRACE': ']', 'KEY_BACKSLASH': '\\',
    'KEY_CAPSLOCK': 'CapsL',
    'KEY_A': 'A', 'KEY_S': 'S', 'KEY_D': 'D', 'KEY_F': 'F', 'KEY_G': 'G',
    'KEY_H': 'H', 'KEY_J': 'J', 'KEY_K': 'K', 'KEY_L': 'L',
    'KEY_SEMICOLON': ';', 'KEY_APOSTROPHE': "'", 'KEY_ENTER': 'Enter',
    'KEY_LEFTSHIFT': 'Shift-L', 'KEY_RIGHTSHIFT': 'Shift-R',
    'KEY_Z': 'Z', 'KEY_X': 'X', 'KEY_C': 'C', 'KEY_V': 'V', 'KEY_B': 'B',
    'KEY_N': 'N', 'KEY_M': 'M',
    'KEY_COMMA': ',', 'KEY_DOT': '.', 'KEY_SLASH': '/',
    'KEY_LEFTCTRL': 'Ctrl-L', 'KEY_RIGHTCTRL': 'Ctrl-R',
    'KEY_LEFTMETA': 'Win', 'KEY_RIGHTMETA': 'Win-R',
    'KEY_LEFTALT': 'Alt-L', 'KEY_RIGHTALT': 'Alt-R',
    'KEY_SPACE': 'Space', 'KEY_FN': 'Fn', 'KEY_COMPOSE': 'Menu',
    'KEY_UP': 'Up', 'KEY_DOWN': 'Down', 'KEY_LEFT': 'Left', 'KEY_RIGHT': 'Right',
    'KEY_INSERT': 'Ins', 'KEY_DELETE': 'Del',
    'KEY_HOME': 'Home', 'KEY_END': 'End',
    'KEY_PAGEUP': 'PgUp', 'KEY_PAGEDOWN': 'PgDn',
    'KEY_SYSRQ': 'PrtSc', 'KEY_SCROLLLOCK': 'ScrLk', 'KEY_PAUSE': 'Pause',
}
```

Any evdev key NOT in the map: display in a separate line as raw name
stripped of `KEY_` prefix e.g. `Other: Fn-Media`.

## Finding Keyboard Device

```python
import evdev
from evdev import ecodes

def find_keyboard():
    devices = [evdev.InputDevice(p) for p in evdev.list_devices()]
    for dev in devices:
        caps = dev.capabilities()
        if ecodes.EV_KEY in caps:
            keys = caps[ecodes.EV_KEY]
            if ecodes.KEY_A in keys and ecodes.KEY_SPACE in keys:
                if ecodes.KEY_LEFT not in caps.get(ecodes.EV_REL, []):
                    return dev
    return None
```

## Exit Condition

Detect Ctrl+C via evdev:
- Track currently held keys in a `held` set
- KEY_C keydown + KEY_LEFTCTRL or KEY_RIGHTCTRL in held → exit
- Key up → remove from held set

## Redraw Logic

Use cursor movement to redraw layout in-place (no scrolling):
```python
LAYOUT_LINES = 10
sys.stdout.write(f"\033[{LAYOUT_LINES}A")  # move cursor up N lines
# redraw entire layout
```

## Fallback

If `python3-evdev` not installed or no keyboard device found:
```
⚠ evdev not available — falling back to TTY mode
```
Then use existing TTY raw mode implementation unchanged.

## Function Interface (unchanged)

```bash
run_keyboard_test()
# Sets: KB_TEST_RESULT="PASS|FAIL|SKIPPED"
# Ends with: read -rp "Did all keys respond? [p/f/s]: " </dev/tty
```

## JSON (unchanged)
```json
"keyboard": {
  "device_status": "...",
  "keys_check": "PASS|FAIL|SKIPPED",
  "touchpad_check": "..."
}
```

## Constraints
- Only replace `run_keyboard_test()` function
- Do not change any other functions or JSON fields
- Add `python3-evdev` to PKGS list
- Run `bash -n laptop_test.sh` after changes
- Script runs as root so /dev/input/ access is guaranteed
