#!/bin/bash
# ============================================================
# laptop_test.sh — Laptop Hardware Test & Report Generator
# All sub-tests (screen, keyboard, audio) are embedded inline.
# Usage: sudo bash laptop_test.sh
# ============================================================

UPLOAD_URL="http://192.168.30.18:80/laptop/api/upload"
REPORT_FILE=""  # set after SYS_SERIAL is collected
PASS="PASS"
FAIL="FAIL"

# ── Colors ───────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

banner() { echo -e "\n${CYAN}${BOLD}=== $1 ===${NC}"; }
ok()     { echo -e "  ${GREEN}✓ $1${NC}"; }
warn()   { echo -e "  ${YELLOW}⚠ $1${NC}"; }
err()    { echo -e "  ${RED}✗ $1${NC}"; }
esc()    { printf '%s' "$1" | tr '\n\r\t' '   ' | sed 's/\\/\\\\/g; s/"/\\"/g'; }

# ── Require root ─────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
  echo -e "${RED}Please run with sudo: sudo bash laptop_test.sh${NC}"; exit 1
fi

# ============================================================
# EMBEDDED: screen_test
# ============================================================
run_screen_test() {
  banner "SCREEN — Dead Pixel / Backlight Test"
  echo -e "  ${YELLOW}Displaying full-screen color patterns. Look carefully for dead/bright pixels.${NC}"
  echo -e "  ${YELLOW}Press Ctrl+C to skip to next color.${NC}"
  echo ""

  if [[ -n "$DISPLAY" ]] && command -v xterm &>/dev/null; then
    local colors=("red" "green" "blue" "white" "black")
    for color in "${colors[@]}"; do
      echo -e "  Showing: ${BOLD}$color${NC} (5 seconds)..."
      xterm -fullscreen -bg "$color" -fg "$color" -e "sleep 5" 2>/dev/null &
      local xpid=$!
      sleep 5
      kill "$xpid" 2>/dev/null
      wait "$xpid" 2>/dev/null
    done
  else
    python3 - <<'PYEOF'
import os, sys, time, signal

COLORS = [
    ("\033[41m\033[30m", "RED"),
    ("\033[42m\033[30m", "GREEN"),
    ("\033[44m\033[37m", "BLUE"),
    ("\033[47m\033[30m", "WHITE"),
    ("\033[40m\033[37m", "BLACK"),
]

interrupted = False

def handle_int(sig, frame):
    global interrupted
    interrupted = True

signal.signal(signal.SIGINT, handle_int)

try:
    rows, cols = os.get_terminal_size()
except Exception:
    rows, cols = 24, 80

for ansi, name in COLORS:
    interrupted = False
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.write(ansi)
    line = " " * cols
    for _ in range(rows):
        sys.stdout.write(line)
    mid_row = rows // 2
    label = f" [ {name} - checking for dead pixels ] "
    col_pos = max(0, (cols - len(label)) // 2)
    sys.stdout.write(f"\033[{mid_row};{col_pos}H{label}")
    sys.stdout.flush()
    for _ in range(50):
        if interrupted:
            break
        time.sleep(0.1)
    sys.stdout.write("\033[0m\033[2J\033[H")
    sys.stdout.flush()

sys.stdout.write("\033[0m")
sys.stdout.flush()
PYEOF
  fi
  echo ""
  ok "Screen color test complete."
}

# ============================================================
# EMBEDDED: keyboard_test
# ============================================================
run_keyboard_test() {
  banner "KEYBOARD — Physical Key Test"
  KB_TEST_RESULT="SKIPPED"

  # ── evdev mode ───────────────────────────────────────────────
  python3 - <<'EVDEV_EOF'
import sys, select

tty_out = open('/dev/tty', 'w', buffering=1)
def w(s): tty_out.write(s); tty_out.flush()

try:
    import evdev
    from evdev import ecodes
except ImportError:
    w("  NO_EVDEV\n")
    sys.exit(42)

KEY_MAP = {
    'KEY_ESC': 'Esc',
    'KEY_F1': 'F1',  'KEY_F2': 'F2',  'KEY_F3': 'F3',  'KEY_F4': 'F4',
    'KEY_F5': 'F5',  'KEY_F6': 'F6',  'KEY_F7': 'F7',  'KEY_F8': 'F8',
    'KEY_F9': 'F9',  'KEY_F10': 'F10','KEY_F11': 'F11','KEY_F12': 'F12',
    'KEY_BRIGHTNESSDOWN': 'Bri-', 'KEY_BRIGHTNESSUP': 'Bri+',
    'KEY_VOLUMEDOWN': 'Vol-',     'KEY_VOLUMEUP': 'Vol+',
    'KEY_MUTE': 'Mute', 'KEY_MICMUTE': 'MicMute',
    'KEY_PLAYPAUSE': 'Play', 'KEY_PREVIOUSSONG': 'Prev', 'KEY_NEXTSONG': 'Next',
    'KEY_GRAVE': '`',  'KEY_1': '1', 'KEY_2': '2', 'KEY_3': '3', 'KEY_4': '4',
    'KEY_5': '5',      'KEY_6': '6', 'KEY_7': '7', 'KEY_8': '8', 'KEY_9': '9',
    'KEY_0': '0',      'KEY_MINUS': '-', 'KEY_EQUAL': '=', 'KEY_BACKSPACE': 'BkSp',
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
    'KEY_LEFTMETA': 'Win',    'KEY_RIGHTMETA': 'Win-R',
    'KEY_LEFTALT': 'Alt-L',   'KEY_RIGHTALT': 'Alt-R',
    'KEY_SPACE': 'Space', 'KEY_FN': 'Fn', 'KEY_COMPOSE': 'Menu',
    'KEY_UP': 'Up', 'KEY_DOWN': 'Down', 'KEY_LEFT': 'Left', 'KEY_RIGHT': 'Right',
    'KEY_INSERT': 'Ins',  'KEY_DELETE': 'Del',
    'KEY_HOME': 'Home',   'KEY_END': 'End',
    'KEY_PAGEUP': 'PgUp', 'KEY_PAGEDOWN': 'PgDn',
    'KEY_SYSRQ': 'PrtSc', 'KEY_SCROLLLOCK': 'ScrLk', 'KEY_PAUSE': 'Pause',
}

# Build code ↔ display-name mappings
CODE_TO_DISP = {}
KEY_BY_CODE  = {}
for attr in dir(ecodes):
    if attr.startswith('KEY_'):
        code = getattr(ecodes, attr)
        if isinstance(code, int):
            KEY_BY_CODE[code] = attr
            if attr in KEY_MAP:
                CODE_TO_DISP[code] = KEY_MAP[attr]

# Keyboard layout rows — None = visual spacer between groups
ROWS = [
    ['Esc', None, 'F1','F2','F3','F4', None, 'F5','F6','F7','F8', None, 'F9','F10','F11','F12'],
    [],
    ['`','1','2','3','4','5','6','7','8','9','0','-','=','BkSp'],
    ['Tab','Q','W','E','R','T','Y','U','I','O','P','[',']','\\'],
    ['CapsL','A','S','D','F','G','H','J','K','L',';',"'",'Enter'],
    ['Shift-L','Z','X','C','V','B','N','M',',','.','/', 'Shift-R'],
    ['Ctrl-L','Win','Alt-L','Space','Alt-R','Fn','Menu','Ctrl-R'],
    [None, None, None, None, 'Up'],
    ['Left','Down','Right', None, 'Ins','Del','Home','End','PgUp','PgDn'],
]
TOTAL = sum(1 for row in ROWS for k in row if k is not None)

DIM = '\033[2;37m'
GRN = '\033[1;32m'
RST = '\033[0m'

def key_cell(name, pressed):
    c = GRN if name in pressed else DIM
    return c + '[' + name + ']' + RST

def draw(pressed, other):
    lines = []
    for row in ROWS:
        if not row:
            lines.append('')
            continue
        parts = []
        for k in row:
            parts.append('  ' if k is None else key_cell(k, pressed))
        lines.append(' '.join(parts))
    lines.append('')
    lines.append('  Other: ' + (DIM + ' '.join(sorted(other)) + RST if other else '-'))
    lines.append('  Pressed: ' + GRN + str(len(pressed)) + RST +
                 ' / ' + str(TOTAL) + '   (Ctrl+C to finish)')
    return lines

def find_keyboard():
    devs = [evdev.InputDevice(p) for p in evdev.list_devices()]
    for dev in devs:
        caps = dev.capabilities()
        if ecodes.EV_KEY in caps:
            keys = caps[ecodes.EV_KEY]
            if ecodes.KEY_A in keys and ecodes.KEY_SPACE in keys:
                if ecodes.KEY_LEFT not in caps.get(ecodes.EV_REL, []):
                    return dev
    return None

kbd = find_keyboard()
if kbd is None:
    w("  NO_KEYBOARD\n")
    sys.exit(42)

w("  Device: " + kbd.name + "\n")
w("  Press EVERY key — Ctrl+C when done\n\n")

pressed = set()
held    = set()
other   = set()

lines  = draw(pressed, other)
NLINES = len(lines)
for line in lines:
    w(line + '\n')

kbd.grab()
try:
    while True:
        r, _, _ = select.select([kbd.fd], [], [], 0.05)
        if not r:
            continue
        try:
            events = kbd.read()
        except BlockingIOError:
            continue
        for ev in events:
            if ev.type != ecodes.EV_KEY:
                continue
            code, val = ev.code, ev.value
            if val == 1:    # key down
                held.add(code)
                if code == ecodes.KEY_C and (
                        ecodes.KEY_LEFTCTRL in held or ecodes.KEY_RIGHTCTRL in held):
                    raise KeyboardInterrupt
                disp = CODE_TO_DISP.get(code)
                if disp:
                    pressed.add(disp)
                else:
                    raw = KEY_BY_CODE.get(code, 'KEY_' + str(code))
                    other.add(raw.replace('KEY_', ''))
            elif val == 0:  # key up
                held.discard(code)
            else:
                continue    # repeat events — skip
            new_lines = draw(pressed, other)
            w('\033[' + str(NLINES) + 'A')
            for line in new_lines:
                w('\033[2K' + line + '\n')
except KeyboardInterrupt:
    pass
finally:
    try:
        kbd.ungrab()
    except Exception:
        pass

w('\n  Done — ' + str(len(pressed)) + ' / ' + str(TOTAL) + ' keys detected.\n')
tty_out.close()
EVDEV_EOF

  # ── fallback to TTY mode if evdev unavailable ────────────────
  if [[ $? -eq 42 ]]; then
    echo -e "  ${YELLOW}⚠ evdev not available — falling back to TTY mode${NC}"
    echo -e "  ${YELLOW}Press EVERY key. For Ctrl/Shift/Alt use combos (e.g. Ctrl+A).${NC}"
    echo -e "  ${YELLOW}Press Ctrl+C when done.${NC}"
    echo ""
    python3 /dev/stdin </dev/tty <<'TTY_EOF'
import sys, tty, termios, select

try:
    tty_fd = open('/dev/tty', 'rb', buffering=0)
    out    = open('/dev/tty', 'w')
except OSError as e:
    print("  ERROR: Cannot open /dev/tty: " + str(e))
    sys.exit(1)

pressed = set()
old_settings = termios.tcgetattr(tty_fd.fileno())

def restore():
    try:
        termios.tcsetattr(tty_fd.fileno(), termios.TCSADRAIN, old_settings)
    except Exception:
        pass

SINGLE = {
    b'\x08': 'Backspace', b'\x09': 'Tab', b'\x0a': 'Enter',
    b'\x0d': 'Enter',     b'\x1b': 'Esc', b'\x7f': 'Backspace',
    b'\x00': 'Ctrl+Space',
}
for i in range(1, 27):
    k = bytes([i])
    if k not in SINGLE:
        SINGLE[k] = 'Ctrl+' + chr(i + 64)

ESCAPE_SEQS = {
    b'\x1b[A': 'Up',      b'\x1b[B': 'Down',
    b'\x1b[C': 'Right',   b'\x1b[D': 'Left',
    b'\x1b[H': 'Home',    b'\x1b[F': 'End',
    b'\x1bOH': 'Home',    b'\x1bOF': 'End',
    b'\x1b[1~': 'Home',   b'\x1b[4~': 'End',
    b'\x1b[2~': 'Insert', b'\x1b[3~': 'Delete',
    b'\x1b[5~': 'PgUp',   b'\x1b[6~': 'PgDn',
    b'\x1bOP': 'F1',  b'\x1bOQ': 'F2',  b'\x1bOR': 'F3',  b'\x1bOS': 'F4',
    b'\x1b[15~': 'F5', b'\x1b[17~': 'F6', b'\x1b[18~': 'F7', b'\x1b[19~': 'F8',
    b'\x1b[20~': 'F9', b'\x1b[21~': 'F10',b'\x1b[23~': 'F11',b'\x1b[24~': 'F12',
}

def read_key():
    tty.setraw(tty_fd.fileno())
    ch = tty_fd.read(1)
    if ch == b'\x1b':
        seq = ch
        while True:
            r, _, _ = select.select([tty_fd], [], [], 0.08)
            if not r:
                break
            seq += tty_fd.read(1)
        return seq
    return ch

out.write("  Keys: ")
out.flush()
try:
    while True:
        key = read_key()
        if key == b'\x03':
            out.write("\n\n  Ctrl+C — done.\n")
            out.flush()
            break
        name = ESCAPE_SEQS.get(key) or SINGLE.get(key)
        if name is None:
            try:
                d = key.decode('utf-8')
                name = d if (len(d) == 1 and d.isprintable()) else '<' + key.hex() + '>'
            except Exception:
                name = '<' + key.hex() + '>'
        if key not in pressed:
            pressed.add(key)
            out.write('\033[32m' + name + '\033[0m ')
            out.flush()
except Exception as e:
    out.write("\n  Error: " + str(e) + "\n")
    out.flush()
finally:
    restore()
    tty_fd.close()

out.write("\n  Total unique keys: " + str(len(pressed)) + "\n")
out.flush()
out.close()
TTY_EOF
  fi

  echo ""
  read -rp "  Did all keys respond correctly? [p=pass / f=fail / s=skip]: " ans </dev/tty
  case "$ans" in
    p|P) KB_TEST_RESULT="PASS" ;;
    f|F) KB_TEST_RESULT="FAIL" ;;
    *)   KB_TEST_RESULT="SKIPPED" ;;
  esac
}

# ============================================================
# EMBEDDED: audio_test
# ============================================================
run_audio_test() {
  banner "AUDIO — Speaker & Microphone Test"

  SPEAKER_QUALITY_RESULT="SKIPPED"
  MIC_RECORD_RESULT="SKIPPED"
  AUDIO_CARD_USED=""

  # Speaker Test
  echo -e "\n  ${BOLD}[1/2] Speaker Test${NC}"

  # --- Reset ALSA state so prior boot's mute/0% volume cannot follow us ---
  alsactl init >/dev/null 2>&1 || true

  # --- Pick the best playback card adaptively (brand-agnostic) ---
  # Score: any card with "Master" or "Speaker" mixer control beats one without.
  # Exclude: HDMI / DisplayPort / NVidia / Dock outputs (not internal speakers).
  pick_speaker_card() {
    local best="" fallback=""
    while IFS= read -r line; do
      # aplay -l line: "card N: ID [Long Name], device M: ..."
      [[ "$line" =~ ^card[[:space:]]+([0-9]+): ]] || continue
      local idx="${BASH_REMATCH[1]}"
      local lc; lc=$(echo "$line" | tr '[:upper:]' '[:lower:]')
      # Skip non-internal outputs
      echo "$lc" | grep -qE "hdmi|displayport|nvidia|dock" && continue
      # Prefer cards exposing analog speaker controls
      if amixer -c "$idx" scontrols 2>/dev/null \
           | grep -qE "'(Master|Speaker)'"; then
        best="$idx"
        break
      fi
      [[ -z "$fallback" ]] && fallback="$idx"
    done < <(aplay -l 2>/dev/null | grep "^card ")
    echo "${best:-$fallback}"
  }

  AUDIO_CARD_USED=$(pick_speaker_card)

  # --- Unmute and set sane volume on whichever controls exist ---
  if [[ -n "$AUDIO_CARD_USED" ]]; then
    for ctl in "Master" "Speaker" "Headphone" "PCM" "Front" "Front Speaker"; do
      amixer -c "$AUDIO_CARD_USED" sset "$ctl" unmute >/dev/null 2>&1 || true
      amixer -c "$AUDIO_CARD_USED" sset "$ctl" 80% >/dev/null 2>&1 || true
    done
    # Some Realtek codecs auto-mute internal speakers when a (phantom) headphone
    # is detected. Force Disabled so the speaker stays on during testing.
    amixer -c "$AUDIO_CARD_USED" sset "Auto-Mute Mode" Disabled >/dev/null 2>&1 || true
    echo "  Audio card selected: card $AUDIO_CARD_USED"
  else
    echo "  No usable audio card found — falling back to default device."
  fi

  # --- Play tone, forcing the chosen card to bypass default-device drift ---
  if command -v speaker-test &>/dev/null; then
    echo "  Playing test tone for 3 seconds..."
    if [[ -n "$AUDIO_CARD_USED" ]]; then
      speaker-test -D "plughw:${AUDIO_CARD_USED},0" -t sine -f 1000 -c 2 -l 1 &>/dev/null &
    else
      speaker-test -t sine -f 1000 -c 2 -l 1 &>/dev/null &
    fi
    SPKR_PID=$!
    sleep 3
    kill "$SPKR_PID" 2>/dev/null
    wait "$SPKR_PID" 2>/dev/null
  else
    echo "  Generating tone via Python + aplay..."
    APLAY_DEV=()
    [[ -n "$AUDIO_CARD_USED" ]] && APLAY_DEV=(-D "plughw:${AUDIO_CARD_USED},0")
    python3 -c "
import struct, math, wave, io, sys
rate=44100; dur=2; freq=440
samples=[int(32767*math.sin(2*math.pi*freq*i/rate)) for i in range(rate*dur)]
buf=io.BytesIO()
w=wave.open(buf,'wb'); w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
w.writeframes(struct.pack('<'+'h'*len(samples),*samples)); w.close()
sys.stdout.buffer.write(buf.getvalue())
" 2>/dev/null | aplay -q "${APLAY_DEV[@]}" 2>/dev/null
  fi

  read -rp "  Did you hear the speaker clearly? [p=pass / f=fail / s=skip]: " ans </dev/tty
  case "$ans" in
    p|P) SPEAKER_QUALITY_RESULT="PASS" ;;
    f|F) SPEAKER_QUALITY_RESULT="FAIL" ;;
    *)   SPEAKER_QUALITY_RESULT="SKIPPED" ;;
  esac

  # Microphone Test
  echo -e "\n  ${BOLD}[2/2] Microphone Test${NC}"

  # Discover capture devices via arecord -l and pick the best card+device pair.
  # Priority: DMIC (not DMIC16kHz) > HDA Analog > any other non-HDMI device.
  # Returns "CARD,DEVICE" string, e.g. "0,6".
  pick_mic_device() {
    local dmic_cd="" analog_cd="" fallback_cd=""
    while IFS= read -r line; do
      # arecord -l lines: "card N: ID [Long Name], device M: NAME [desc]"
      [[ "$line" =~ ^card[[:space:]]+([0-9]+).*device[[:space:]]+([0-9]+):[[:space:]]*(.*) ]] || continue
      local cidx="${BASH_REMATCH[1]}"
      local didx="${BASH_REMATCH[2]}"
      local dname_lc; dname_lc=$(echo "${BASH_REMATCH[3]}" | tr '[:upper:]' '[:lower:]')
      # Skip HDMI/DisplayPort outputs (appear in capture list on some cards)
      echo "$dname_lc" | grep -qE "hdmi|displayport" && continue
      # DMIC16kHz — lower quality, only use as last resort
      if echo "$dname_lc" | grep -q "dmic16khz"; then
        [[ -z "$fallback_cd" ]] && fallback_cd="${cidx},${didx}"
        continue
      fi
      # Prefer DMIC (broadband) — typical for SOF/Intel SST laptops
      if echo "$dname_lc" | grep -q "dmic"; then
        [[ -z "$dmic_cd" ]] && dmic_cd="${cidx},${didx}"
        continue
      fi
      # HDA Analog — Realtek/Conexant external mic jack
      if echo "$dname_lc" | grep -qE "analog|hda analog"; then
        [[ -z "$analog_cd" ]] && analog_cd="${cidx},${didx}"
        continue
      fi
      [[ -z "$fallback_cd" ]] && fallback_cd="${cidx},${didx}"
    done < <(arecord -l 2>/dev/null | grep "^card ")
    # Return best available: DMIC > Analog > fallback
    echo "${dmic_cd:-${analog_cd:-$fallback_cd}}"
  }

  MIC_DEV=$(pick_mic_device)   # e.g. "0,6"
  MIC_CARD_USED="${MIC_DEV%%,*}"

  if [[ -n "$MIC_DEV" ]]; then
    # Show operator what was found
    _mic_label=$(arecord -l 2>/dev/null \
      | awk -v c="${MIC_DEV%%,*}" -v d="${MIC_DEV##*,}" \
          '$0 ~ "^card "c".*device "d":" {sub(/.*device [0-9]+: /,""); print $0; exit}')
    ok "Mic device found: card ${MIC_DEV%%,*} device ${MIC_DEV##*,} — ${_mic_label:-unknown}"

    # Only unmute and enable capture — do not override volume levels.
    # Setting Mic Boost + Capture both to 100% causes clipping distortion.
    # System defaults after alsactl init are sufficient.
    for ctl in "Capture" "Internal Mic" "Mic" "Front Mic" "Dmic" "Mic Boost" "Internal Mic Boost"; do
      amixer -c "$MIC_CARD_USED" sset "$ctl" cap    >/dev/null 2>&1 || true
      amixer -c "$MIC_CARD_USED" sset "$ctl" unmute >/dev/null 2>&1 || true
    done
  else
    warn "No capture device found in arecord -l — will try default device."
  fi

  REC_FILE="/tmp/mic_test_$$.wav"
  echo "  Recording 3 seconds... Please speak now."
  AREC_DEV=()
  [[ -n "$MIC_DEV" ]] && AREC_DEV=(-D "plughw:${MIC_DEV}")

  if arecord "${AREC_DEV[@]}" -f cd -d 3 -q "$REC_FILE" 2>/dev/null; then
    if [[ -f "$REC_FILE" && -s "$REC_FILE" ]]; then
      echo "  Playing back the recording..."
      APLAY_DEV=()
      [[ -n "$AUDIO_CARD_USED" ]] && APLAY_DEV=(-D "plughw:${AUDIO_CARD_USED},0")
      aplay -q "${APLAY_DEV[@]}" "$REC_FILE" 2>/dev/null
      rm -f "$REC_FILE"
      read -rp "  Did you hear your voice clearly? [p=pass / f=fail / s=skip]: " ans </dev/tty
      case "$ans" in
        p|P) MIC_RECORD_RESULT="PASS" ;;
        f|F) MIC_RECORD_RESULT="FAIL" ;;
        *)   MIC_RECORD_RESULT="SKIPPED" ;;
      esac
    else
      err "Recording file empty — microphone may not be working."
      MIC_RECORD_RESULT="FAIL"
      rm -f "$REC_FILE"
    fi
  else
    err "arecord failed — no microphone device found."
    MIC_RECORD_RESULT="FAIL"
  fi
}

# ============================================================
# INSTALL DEPENDENCIES
# ============================================================
banner "Checking and Installing Dependencies"
PKGS=(python3 dmidecode smartmontools util-linux pciutils usbutils \
      curl jq alsa-utils v4l-utils iw ethtool bc \
      fswebcam ffmpeg libcamera-tools python3-evdev)

# Collect which packages are missing first
MISSING=()
for pkg in "${PKGS[@]}"; do
  dpkg -s "$pkg" &>/dev/null 2>&1 || MISSING+=("$pkg")
done

if [[ ${#MISSING[@]} -eq 0 ]]; then
  ok "All dependencies already installed."
else
  warn "${#MISSING[@]} package(s) missing: ${MISSING[*]}"
  echo "  Running apt-get update..."
  apt-get update -qq 2>/dev/null || warn "apt-get update failed — network may be unavailable."

  FAILED=()
  for pkg in "${MISSING[@]}"; do
    echo -n "  Installing $pkg ... "
    if apt-get install -y -q "$pkg" &>/dev/null 2>&1; then
      echo -e "${GREEN}OK${NC}"
    else
      echo -e "${RED}FAILED${NC}"
      FAILED+=("$pkg")
    fi
  done

  if [[ ${#FAILED[@]} -eq 0 ]]; then
    ok "All dependencies installed successfully."
  else
    warn "Could not install: ${FAILED[*]}"
    warn "Some tests may be skipped or limited."
  fi
fi

# ============================================================
# 1. SYSTEM INFO
# ============================================================
banner "1. System Info"
SYS_VENDOR=$(dmidecode -s system-manufacturer 2>/dev/null | tr -d '\n')
SYS_MODEL=$(dmidecode -s system-product-name 2>/dev/null | tr -d '\n')
SYS_SERIAL=$(dmidecode -s system-serial-number 2>/dev/null | tr -d '\n')
BIOS_VER=$(dmidecode -s bios-version 2>/dev/null | tr -d '\n')
SN_CLEAN=$(echo "$SYS_SERIAL" | tr -cd '[:alnum:]_-')
REPORT_FILE="/tmp/${SN_CLEAN:-$(date +%Y%m%d_%H%M%S)}.json"
TEST_TIME=$(date +"%Y-%m-%dT%H:%M:%SZ")
HOSTNAME=$(hostname)
ok "Vendor: $SYS_VENDOR | Model: $SYS_MODEL | Serial: $SYS_SERIAL"

# ============================================================
# 2. CPU
# ============================================================
banner "2. CPU"
CPU_MODEL=$(grep "model name" /proc/cpuinfo | head -1 | cut -d: -f2 | xargs)
CPU_CORES=$(nproc --all)
CPU_THREADS=$(grep -c "^processor" /proc/cpuinfo)
CPU_MAX_MHZ=$(lscpu | grep "CPU max MHz" | awk '{print $NF}' | cut -d. -f1)
CPU_ARCH=$(uname -m)
ok "$CPU_MODEL | ${CPU_CORES} cores / ${CPU_THREADS} threads | Max ${CPU_MAX_MHZ:-?} MHz"

# ============================================================
# 3. MEMORY
# ============================================================
banner "3. Memory"
MEM_TOTAL_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
MEM_TOTAL_GB=$(echo "scale=1; $MEM_TOTAL_KB/1024/1024" | bc)
MEM_TYPE=$(dmidecode -t memory 2>/dev/null | grep -E "^\s+Type:" | grep -v "Unknown\|Error" | head -1 | awk '{print $2}')
MEM_SPEED=$(dmidecode -t memory 2>/dev/null | grep -E "^\s+Speed:" | grep -v "Unknown" | head -1 | awk '{print $2, $3}')
MEM_SLOTS=$(dmidecode -t memory 2>/dev/null | grep -c "Memory Device$")
MEM_USED_SLOTS=$(dmidecode -t memory 2>/dev/null | grep -A5 "Memory Device$" | grep -cE "Size:.*GB|Size:.*MB")
ok "${MEM_TOTAL_GB} GB | Type: ${MEM_TYPE:-unknown} | Speed: ${MEM_SPEED:-unknown} | Slots used: ${MEM_USED_SLOTS}/${MEM_SLOTS}"

# ============================================================
# 4. STORAGE (original logic kept)
# ============================================================
banner "4. Storage"
DISK_STATUS=$PASS
DISK_JSON="["
first=1

# Pre-collect all USB transport disks — internal storage is always nvme/sata
USB_DISKS=$(lsblk -d -o NAME,TRAN 2>/dev/null | awk '$2=="usb"{print $1}')

while IFS= read -r disk; do
  [[ -z "$disk" ]] && continue
  name=$(basename "$disk")

  # Skip all USB disks (Live USB, external drives) — never internal storage
  if echo "$USB_DISKS" | grep -q "^${name}$"; then
    warn "Skipping $name (USB transport) — not internal storage."
    continue
  fi

  size=$(lsblk -dn -o SIZE "$disk" 2>/dev/null | xargs)
  model=$(lsblk -dn -o MODEL "$disk" 2>/dev/null | xargs)
  [[ -z "$model" ]] && model=$(cat /sys/block/$name/device/model 2>/dev/null | xargs)
  rotational=$(cat /sys/block/$name/queue/rotational 2>/dev/null)
  disk_type="HDD"
  [[ "$rotational" == "0" ]] && disk_type="SSD"
  [[ "$disk" == *"nvme"* ]] && disk_type="SSD NVMe"

  # Serial number — try lsblk, then sysfs, then smartctl
  serial=$(lsblk -dn -o SERIAL "$disk" 2>/dev/null | xargs)
  [[ -z "$serial" ]] && serial=$(cat /sys/block/$name/device/serial 2>/dev/null | xargs)
  [[ -z "$serial" ]] && serial=$(smartctl -i "$disk" 2>/dev/null | awk -F: '/Serial Number/{print $2; exit}' | xargs)
  [[ -z "$serial" ]] && serial="unknown"

  # One smartctl -x call covers health, power-on hours, and all SSD metrics.
  SMART_DETAIL=$(smartctl -x "$disk" 2>/dev/null)

  if echo "$SMART_DETAIL" | grep -qE "PASSED|OK"; then
    smart="PASSED"
  elif echo "$SMART_DETAIL" | grep -q "FAILED"; then
    smart="FAILED"
    DISK_STATUS=$FAIL
  else
    smart="UNKNOWN"
  fi

  power_hours=$(echo "$SMART_DETAIL" | grep -iE "power.on.hours|Power_On_Hours" \
    | awk '{print $NF}' | head -1)

  # SSD health: both NVMe and SATA SSD expose "Percentage Used" in -x output.
  # NVMe: in SMART/Health log.  SATA: in Device Statistics (Endurance Indicator).
  # HDDs stay "unknown".
  SSD_HEALTH_PCT="unknown"
  SSD_GRADE="unknown"
  SSD_AVAIL_SPARE="unknown"
  SSD_DATA_WRITTEN="unknown"

  if [[ "$disk_type" == "SSD NVMe" ]]; then
    PCT_USED=$(echo "$SMART_DETAIL" | grep "Percentage Used" \
      | grep -oP '\d+(?=%)' | head -1)
    AVAIL_SPARE=$(echo "$SMART_DETAIL" | grep "Available Spare:" \
      | grep -oP '\d+(?=%)' | head -1)
    SSD_DATA_WRITTEN=$(echo "$SMART_DETAIL" | grep "Data Units Written" \
      | cut -d: -f2 | xargs | cut -d'[' -f2 | tr -d ']' | xargs)
    [[ -z "$SSD_DATA_WRITTEN" ]] && SSD_DATA_WRITTEN="unknown"

    if [[ -n "$PCT_USED" ]]; then
      SSD_HEALTH_PCT=$((100 - PCT_USED))
    fi
    [[ -n "$AVAIL_SPARE" ]] && SSD_AVAIL_SPARE="${AVAIL_SPARE}%"

  elif [[ "$disk_type" == "SSD" ]]; then
    # SATA SSD: prefer "Percentage Used Endurance Indicator" from Device Statistics
    # (present on LITEON, Crucial, Intel, newer Samsung etc.).
    # Fallback: Wear_Leveling_Count / Media_Wearout_Indicator VALUE column.
    # Device Statistics line layout:
    #   0x07  0x008  1               0  ---  Percentage Used Endurance Indicator
    # Field $4 is the numeric value (percent used); $NF is "Indicator" (wrong).
    PCT_USED=$(echo "$SMART_DETAIL" | awk '/Percentage Used Endurance Indicator/{print $4; exit}')

    if [[ -n "$PCT_USED" ]] && [[ "$PCT_USED" =~ ^[0-9]+$ ]]; then
      SSD_HEALTH_PCT=$((100 - PCT_USED))
    else
      WLC_VALUE=$(echo "$SMART_DETAIL" | awk '/Wear_Leveling_Count/{print $4}' | head -1)
      [[ -z "$WLC_VALUE" ]] && \
        WLC_VALUE=$(echo "$SMART_DETAIL" | awk '/Media_Wearout_Indicator/{print $4}' | head -1)
      [[ -z "$WLC_VALUE" ]] && \
        WLC_VALUE=$(echo "$SMART_DETAIL" | awk '/SSD_Life_Left/{print $4}' | head -1)
      [[ -n "$WLC_VALUE" && "$WLC_VALUE" =~ ^[0-9]+$ ]] && SSD_HEALTH_PCT=$WLC_VALUE
    fi
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

  ok "$name | ${model:-unknown} | SN: $serial | $size | $disk_type | SMART: $smart | Power-on: ${power_hours:-?} hrs"
  if [[ "$disk_type" != "HDD" && "$SSD_GRADE" != "unknown" ]]; then
    ok "  SSD Health: ${SSD_HEALTH_PCT}% | Grade: ${SSD_GRADE} | Available Spare: ${SSD_AVAIL_SPARE} | Written: ${SSD_DATA_WRITTEN}"
  fi

  [[ $first -eq 0 ]] && DISK_JSON+=","
  DISK_JSON+="{\"device\":\"$(esc "$name")\",\"model\":\"$(esc "${model:-unknown}")\",\"serial\":\"$(esc "$serial")\",\"size\":\"$(esc "${size:-unknown}")\",\"type\":\"$disk_type\",\"smart\":\"$smart\",\"power_on_hours\":\"$(esc "${power_hours:-unknown}")\",\"ssd_health_percent\":\"$(esc "${SSD_HEALTH_PCT}")\",\"ssd_grade\":\"$(esc "${SSD_GRADE}")\",\"ssd_available_spare\":\"$(esc "${SSD_AVAIL_SPARE}")\",\"ssd_data_written\":\"$(esc "${SSD_DATA_WRITTEN}")\"}"
  first=0
done < <(lsblk -dpn -o PATH 2>/dev/null | grep -E "^/dev/(sd|nvme|hd)")
DISK_JSON+="]"

# ============================================================
# 5. BATTERY
# ============================================================
banner "5. Battery"
BAT_STATUS=$PASS
BAT_JSON="{}"
BAT_HEALTH="N/A"
BAT_CYCLE="N/A"
BAT_CONDITION="OK"

BAT_DIR=$(ls -d /sys/class/power_supply/BAT* 2>/dev/null | head -1)
if [[ -n "$BAT_DIR" && -d "$BAT_DIR" ]]; then
  # Read uevent for richer low-level data
  BAT_UEVENT="$BAT_DIR/uevent"
  BAT_VOLTAGE_NOW=$(grep "^POWER_SUPPLY_VOLTAGE_NOW=" "$BAT_UEVENT" 2>/dev/null | cut -d= -f2)
  BAT_ENERGY_NOW=$(grep "^POWER_SUPPLY_ENERGY_NOW=" "$BAT_UEVENT" 2>/dev/null | cut -d= -f2)

  BAT_DESIGN=$(cat "$BAT_DIR/energy_full_design" 2>/dev/null)
  [[ -z "$BAT_DESIGN" ]] && BAT_DESIGN=$(cat "$BAT_DIR/charge_full_design" 2>/dev/null)
  BAT_FULL=$(cat "$BAT_DIR/energy_full" 2>/dev/null)
  [[ -z "$BAT_FULL" ]] && BAT_FULL=$(cat "$BAT_DIR/charge_full" 2>/dev/null)
  BAT_CYCLE=$(cat "$BAT_DIR/cycle_count" 2>/dev/null)
  BAT_MANUF=$(cat "$BAT_DIR/manufacturer" 2>/dev/null | xargs)
  BAT_MODEL_NAME=$(cat "$BAT_DIR/model_name" 2>/dev/null | xargs)
  BAT_CAPACITY=$(cat "$BAT_DIR/capacity" 2>/dev/null)

  # Normalize cycle_count: -1 or empty → "unknown"
  if [[ -z "$BAT_CYCLE" || "$BAT_CYCLE" == "-1" ]]; then
    BAT_CYCLE="unknown"
  fi

  # Ensure voltage/energy values are numeric
  [[ ! "${BAT_VOLTAGE_NOW:-0}" =~ ^[0-9]+$ ]] && BAT_VOLTAGE_NOW=0
  [[ ! "${BAT_ENERGY_NOW:-0}" =~ ^[0-9]+$ ]] && BAT_ENERGY_NOW=0
  BAT_VOLTAGE_NOW="${BAT_VOLTAGE_NOW:-0}"
  BAT_ENERGY_NOW="${BAT_ENERGY_NOW:-0}"

  # Compute voltage in volts (2dp)
  if [[ "$BAT_VOLTAGE_NOW" -gt 0 ]]; then
    BAT_VOLTAGE_V=$(echo "scale=2; $BAT_VOLTAGE_NOW / 1000000" | bc)
  else
    BAT_VOLTAGE_V="0"
  fi

  # Priority order for battery verdict
  if [[ "$BAT_VOLTAGE_NOW" -gt 0 && "$BAT_VOLTAGE_NOW" -lt 3000000 && "$BAT_ENERGY_NOW" -eq 0 ]]; then
    # Case A: physically dead — voltage below 3V and no stored energy
    BAT_STATUS=$FAIL
    BAT_CONDITION="DEAD"
    err "Battery physically dead: voltage=${BAT_VOLTAGE_V}V, energy=0"
  elif [[ -z "$BAT_MANUF" && -z "$BAT_MODEL_NAME" && "$BAT_ENERGY_NOW" -eq 0 && "$BAT_VOLTAGE_NOW" -eq 0 ]]; then
    # Case B: driver cannot read battery data
    BAT_STATUS="BATTERY_DATA_UNAVAILABLE"
    BAT_CONDITION="DATA_UNAVAILABLE"
    warn "Battery data unavailable (driver not supported)"
  else
    if [[ -n "$BAT_DESIGN" && -n "$BAT_FULL" && "$BAT_DESIGN" -gt 0 ]]; then
      BAT_HEALTH=$(echo "scale=1; $BAT_FULL * 100 / $BAT_DESIGN" | bc)
    else
      BAT_HEALTH="?"
    fi
    if [[ "$BAT_HEALTH" != "?" ]] && (( $(echo "$BAT_HEALTH < 60" | bc -l) )); then
      BAT_STATUS=$FAIL
      err "Battery health critically low: ${BAT_HEALTH}%"
    else
      ok "Battery detected | Health: ${BAT_HEALTH}% | Cycles: ${BAT_CYCLE}"
    fi
    BAT_CONDITION="OK"
  fi

  BAT_JSON="{\"manufacturer\":\"${BAT_MANUF:-unknown}\",\"model\":\"${BAT_MODEL_NAME:-unknown}\",\"health_percent\":\"${BAT_HEALTH}\",\"current_percent\":\"${BAT_CAPACITY:-unknown}\",\"cycle_count\":\"${BAT_CYCLE}\",\"voltage_v\":\"${BAT_VOLTAGE_V}\",\"battery_condition\":\"$BAT_CONDITION\",\"status\":\"$BAT_STATUS\"}"
else
  warn "No battery detected."
  BAT_JSON="{\"status\":\"NOT_FOUND\"}"
fi

# ============================================================
# 6. SCREEN
# ============================================================
banner "6. Screen"
SCREEN_RES=$(xrandr 2>/dev/null | grep " connected" | grep -oP '\d+x\d+' | head -1)
SCREEN_NAME=$(xrandr 2>/dev/null | grep " connected" | awk '{print $1}' | head -1)
[[ -z "$SCREEN_RES" ]] && SCREEN_RES=$(cat /sys/class/drm/*/modes 2>/dev/null | head -1)
ok "Interface: ${SCREEN_NAME:-unknown} | Resolution: ${SCREEN_RES:-unknown}"

run_screen_test

run_touchpad_test() {
  banner "TOUCHPAD — Auto Detection Test"
  TOUCHPAD_RESULT="NOT_FOUND"

  # Use udevadm to find the best touchpad by kernel property ID_INPUT_TOUCHPAD=1.
  # Priority: I2C/HID (HP ELAN/Synaptics) > RMI > PS/2 (Dell).
  # Result exported so Python opens it directly instead of guessing.
  _tp_best="" _tp_pri=0
  for _tp_dev in /dev/input/event*; do
    [[ -e "$_tp_dev" ]] || continue
    _tp_info=$(udevadm info -q property -n "$_tp_dev" 2>/dev/null)
    echo "$_tp_info" | grep -q "ID_INPUT_TOUCHPAD=1" || continue
    if echo "$_tp_info" | grep -qE "ID_BUS=(i2c|hid)"; then
      _tp_best="$_tp_dev"; break          # highest priority — take immediately
    elif echo "$_tp_info" | grep -q "RMI"; then
      [[ $_tp_pri -lt 2 ]] && { _tp_best="$_tp_dev"; _tp_pri=2; }
    else
      [[ $_tp_pri -lt 1 ]] && { _tp_best="$_tp_dev"; _tp_pri=1; }
    fi
  done
  export _TP_PREFERRED_DEV="$_tp_best"

  python3 - <<'TPEVDEV_EOF'
import sys, select, time

tty_out = open('/dev/tty', 'w', buffering=1)
def w(s): tty_out.write(s); tty_out.flush()

try:
    import evdev
    from evdev import ecodes
except ImportError:
    w("  ⚠ python3-evdev not installed\n")
    sys.exit(42)

def find_touchpad():
    import os
    # 1. Try the udevadm-selected device (bash ranked I2C/HID > RMI > PS/2).
    preferred = os.environ.get("_TP_PREFERRED_DEV", "").strip()
    if preferred:
        try:
            dev = evdev.InputDevice(preferred)
            caps = dev.capabilities()
            abs_codes = [a[0] if isinstance(a, tuple) else a
                         for a in caps.get(ecodes.EV_ABS, [])]
            if ecodes.ABS_X in abs_codes and ecodes.ABS_Y in abs_codes:
                return dev
        except Exception:
            pass

    # 2. Generic evdev scan — capability check + phys bus preference.
    #    dev.phys contains bus path: "i2c-SYNA.../input0" vs "isa0060/serio.../input0"
    candidates = []
    for p in evdev.list_devices():
        try:
            dev = evdev.InputDevice(p)
        except Exception:
            continue
        caps = dev.capabilities()
        keys      = caps.get(ecodes.EV_KEY, [])
        abs_axes  = caps.get(ecodes.EV_ABS, [])
        abs_codes = [a[0] if isinstance(a, tuple) else a for a in abs_axes]
        if (ecodes.ABS_X     in abs_codes and
                ecodes.ABS_Y     in abs_codes and
                ecodes.BTN_TOUCH in keys and
                ecodes.KEY_A     not in keys):
            candidates.append(dev)

    if not candidates:
        return None
    # Prefer I2C (phys path starts with "i2c-")
    for dev in candidates:
        if (dev.phys or "").startswith("i2c-"):
            return dev
    return candidates[0]

tp = find_touchpad()
if tp is None:
    w("  ⚠ No touchpad device found via evdev\n")
    sys.exit(42)

w("  Device: " + tp.name + "\n\n")

GRN = '\033[1;32m'; RED = '\033[0;31m'; YEL = '\033[1;33m'; RST = '\033[0m'
TIMEOUT = 10

def wait_for(label, check_fn):
    w("  " + YEL + label + RST + "\n")
    deadline = time.time() + TIMEOUT
    tp.grab()
    try:
        prev = {}
        while time.time() < deadline:
            r, _, _ = select.select([tp.fd], [], [], min(0.1, deadline - time.time()))
            if not r:
                continue
            try:
                events = tp.read()
            except BlockingIOError:
                continue
            for ev in events:
                msg = check_fn(ev, prev)
                if msg:
                    w("      " + GRN + "✓ " + msg + RST + "\n\n")
                    return True
    finally:
        try:
            tp.ungrab()
        except Exception:
            pass
    w("      " + RED + "✗ No signal detected (timeout " + str(TIMEOUT) + "s)" + RST + "\n\n")
    return False

# ── Sub-test 1: single finger movement ──────────────────────
def check_move(ev, prev):
    if ev.type == ecodes.EV_ABS and ev.code in (ecodes.ABS_X, ecodes.ABS_Y):
        axis = ev.code
        last = prev.get(axis)
        if last is not None and abs(ev.value - last) > 50:
            return "Movement detected"
        prev[axis] = ev.value
    return None

r1 = wait_for("[1/3] Move one finger across the touchpad...", check_move)

# ── Sub-test 2: click ────────────────────────────────────────
def check_click(ev, prev):
    if ev.type == ecodes.EV_KEY and ev.code == ecodes.BTN_LEFT and ev.value == 1:
        return "Click detected"
    return None

r2 = wait_for("[2/3] Click the touchpad (physical press or tap)...", check_click)

# ── Sub-test 3: two-finger touch ─────────────────────────────
def check_two_finger(ev, prev):
    if ev.type == ecodes.EV_ABS:
        if ev.code == ecodes.ABS_MT_SLOT:
            prev['slot'] = ev.value
            if ev.value >= 1:
                return "Two-finger touch detected"
        if ev.code == ecodes.ABS_MT_TRACKING_ID and ev.value >= 0:
            if prev.get('slot', 0) >= 1:
                return "Two-finger touch detected"
    return None

r3 = wait_for("[3/3] Place TWO fingers on the touchpad...", check_two_finger)

# ── Overall result ───────────────────────────────────────────
overall = "PASS" if (r1 and r2 and r3) else "FAIL"
color   = GRN if overall == "PASS" else RED
w("  Touchpad result: " + color + overall + RST + "\n")
tty_out.close()
# Exit code 0=PASS 1=FAIL — bash maps these to TOUCHPAD_RESULT
sys.exit(0 if overall == "PASS" else 1)
TPEVDEV_EOF

  case $? in
    0)  TOUCHPAD_RESULT="PASS" ;;
    1)  TOUCHPAD_RESULT="FAIL" ;;
    42) warn "evdev not available — falling back to manual check"
        TOUCHPAD_RESULT=$(ask_manual "Touchpad click / scroll" \
          "Test single click, double click, and two-finger scroll") ;;
    *)  TOUCHPAD_RESULT="FAIL" ;;
  esac
}

ask_manual() {
  local item="$1"
  local hint="$2"
  echo -e "  ${BOLD}► $item${NC}" >&2
  [[ -n "$hint" ]] && echo -e "    ${CYAN}Hint: $hint${NC}" >&2
  read -rp "    Result [p=pass / f=fail / s=skip]: " ans </dev/tty
  case "$ans" in
    p|P) echo "PASS" ;;
    f|F) echo "FAIL" ;;
    *)   echo "SKIPPED" ;;
  esac
}

SCREEN_CHECK=$(ask_manual "Screen quality (dead pixels & backlight)" "Check for dead/bright pixels and uneven corner brightness")
SCREEN_DEADPIXEL=$SCREEN_CHECK
SCREEN_BACKLIGHT=$SCREEN_CHECK

# ============================================================
# 7. CAMERA
# ============================================================
banner "7. Camera"

CAM_STATUS=$FAIL
CAM_DRIVER_TYPE="unknown"
CAM_CAPTURE_METHOD="none"
CAM_CAPTURE_RESULT="SKIPPED"
CAM_IMAGE_RESULT="SKIPPED"
CAM_DRIVER_NOTE="ok"
CAM_COUNT=0
SNAP=""

REAL_CAMS=()
IPU_DETECTED=0

# Non-camera v4l2 drivers to skip (GPU, ACPI display, TV tuners)
_CAM_SKIP_DRIVERS="i915|acpi_video|pvrusb2|cx88|saa7134|em28xx"

for dev in /dev/video*; do
  [[ -e "$dev" ]] || continue

  dev_info=$(v4l2-ctl --device="$dev" --info 2>/dev/null)

  # Extract driver name (lowercase)
  cam_driver=$(echo "$dev_info" | grep -i "Driver name" \
    | cut -d: -f2 | xargs | tr '[:upper:]' '[:lower:]')

  # Detect IPU3/IPU6 before anything else
  card_lc=$(echo "$dev_info" | grep -i "Card type" | tr '[:upper:]' '[:lower:]')
  if echo "$cam_driver$card_lc" | grep -qE "ipu3|ipu6"; then
    IPU_DETECTED=1
    echo "$cam_driver$card_lc" | grep -q "ipu6" && CAM_DRIVER_TYPE="ipu6" || CAM_DRIVER_TYPE="ipu3"
    continue
  fi

  # Skip non-camera drivers (GPU, ACPI display, TV tuners)
  if [[ -n "$cam_driver" ]] && echo "$cam_driver" | grep -qE "$_CAM_SKIP_DRIVERS"; then
    warn "Skipping $dev (driver: $cam_driver) — not a camera device"
    continue
  fi

  # Must have at least one capture format
  fmt_count=$(v4l2-ctl --device="$dev" --list-formats 2>/dev/null | grep -c "\[")
  if [[ $fmt_count -eq 0 ]]; then
    warn "Skipping $dev — no capture formats available"
    continue
  fi

  # Real camera confirmed
  cam_name=$(echo "$dev_info" | grep "Card type" | cut -d: -f2 | xargs)
  REAL_CAMS+=("$dev")
  ok "Camera found: $dev | ${cam_name:-unknown} | driver: ${cam_driver:-unknown}"

  # Set driver type once
  if [[ "$CAM_DRIVER_TYPE" == "unknown" ]]; then
    echo "$cam_driver" | grep -qE "uvcvideo|uvc" && CAM_DRIVER_TYPE="uvc"
  fi
done

if [[ $IPU_DETECTED -eq 1 ]]; then
  warn "${CAM_DRIVER_TYPE} camera hardware detected — capture not supported without IPA binary."
  CAM_STATUS="HARDWARE_DETECTED"
  CAM_CAPTURE_RESULT="NOT_SUPPORTED"
  CAM_DRIVER_NOTE="driver_init_failed"
  CAM_COUNT=$(ls /dev/video* 2>/dev/null | wc -l)
elif [[ ${#REAL_CAMS[@]} -eq 0 ]]; then
  # All /dev/video* were filtered out or none exist — check dmesg for real camera hardware.
  # Only match real camera sensor/driver keywords; exclude GPU/ACPI display terms.
  DMESG_CAM=$(dmesg 2>/dev/null | grep -iE \
    "ipu[36]|cio2|imgu|ov[0-9]+|hi[0-9]+|imx[0-9]+|uvcvideo|OVTID" \
    | grep -viE "acpi.video|GFX0|display|shadowed ROM" \
    | head -5)

  if [[ -n "$DMESG_CAM" ]]; then
    CAM_STATUS="HARDWARE_DETECTED"
    warn "Camera hardware in kernel log but no working device node:"
    echo "$DMESG_CAM" | while read -r line; do warn "  $line"; done
    warn "Driver failed to initialize — verify camera in Windows/OEM OS."
    CAM_DRIVER_NOTE="driver_init_failed"
  else
    CAM_STATUS="NOT_FOUND"
    ok "No camera hardware detected (confirmed)."
    CAM_DRIVER_NOTE="no_hardware"
  fi
else
  CAM_COUNT=${#REAL_CAMS[@]}
  CAM_STATUS=$PASS
  FIRST_CAM="${REAL_CAMS[0]}"
  SNAP="/tmp/cam_test_$$.jpg"

  if [[ "$CAM_DRIVER_TYPE" == "uvc" ]]; then
    CAM_CAPTURE_METHOD="ffmpeg"
    echo "  Capturing via ffmpeg (UVC)..."
    if ffmpeg -f v4l2 -input_format mjpeg -video_size 640x480 -i "$FIRST_CAM" -frames:v 1 -y "$SNAP" &>/dev/null ||
       ffmpeg -f v4l2 -input_format yuyv422 -video_size 640x480 -i "$FIRST_CAM" -frames:v 1 -y "$SNAP" &>/dev/null ||
       ffmpeg -f v4l2 -i "$FIRST_CAM" -frames:v 1 -y "$SNAP" &>/dev/null; then
      CAM_CAPTURE_RESULT="SUCCESS"
    else
      CAM_CAPTURE_RESULT="FAILED"
      err "ffmpeg capture failed."
      SNAP=""
    fi
  else
    CAM_CAPTURE_METHOD="fswebcam"
    echo "  Capturing via fswebcam..."
    if fswebcam -q -r 640x480 --no-banner "$SNAP" 2>/dev/null && [[ -s "$SNAP" ]]; then
      CAM_CAPTURE_RESULT="SUCCESS"
    else
      CAM_CAPTURE_RESULT="FAILED"
      err "fswebcam capture failed."
      SNAP=""
    fi
  fi

  if [[ "$CAM_CAPTURE_RESULT" == "SUCCESS" ]]; then
    ok "Test image captured: $SNAP"
    CAM_IMAGE_RESULT="CAPTURED"
  else
    CAM_IMAGE_RESULT="CAPTURE_FAILED"
  fi

  # Encode captured image as base64 for upload to CearTrack, then clean up.
  CAM_IMAGE_B64=""
  if [[ "$CAM_IMAGE_RESULT" == "CAPTURED" && -f "$SNAP" ]]; then
    CAM_IMAGE_B64=$(base64 -w 0 "$SNAP" 2>/dev/null)
    ok "Image encoded for upload ($(wc -c < "$SNAP") bytes)"
    rm -f "$SNAP"
  fi
fi
# Always ensure CAM_IMAGE_B64 is defined (empty string when no capture).
CAM_IMAGE_B64="${CAM_IMAGE_B64:-}"

# HARDWARE_DETECTED with zero video nodes means no real camera hardware
# (e.g. GPU-only machines where dmesg matched a generic keyword).
# Reclassify to NOT_FOUND so CearTrack displays correctly.
if [[ "$CAM_STATUS" == "HARDWARE_DETECTED" && ${CAM_COUNT:-0} -eq 0 ]]; then
  CAM_STATUS="NOT_FOUND"
  CAM_DRIVER_NOTE="no_hardware"
fi

# ============================================================
# 8. AUDIO
# ============================================================
banner "8. Audio"
AUDIO_CARDS=$(aplay -l 2>/dev/null | grep "^card" | wc -l)
MIC_CARDS=$(arecord -l 2>/dev/null | grep "^card" | wc -l)

[[ $AUDIO_CARDS -gt 0 ]] && ok "Speaker devices found: ${AUDIO_CARDS} card(s)" || err "No audio output device found."
[[ $MIC_CARDS -gt 0 ]]   && ok "Microphone devices found: ${MIC_CARDS} card(s)" || err "No audio input device found."

run_audio_test
SPEAKER_QUALITY_CHECK=$SPEAKER_QUALITY_RESULT
MIC_RECORD_CHECK=$MIC_RECORD_RESULT

# ============================================================
# 9. KEYBOARD
# ============================================================
banner "9. Keyboard"
KB_DEVICES=$(ls /dev/input/by-path/ 2>/dev/null | grep -ci kbd)
[[ $KB_DEVICES -gt 0 ]] && ok "Keyboard device(s) found: $KB_DEVICES" || err "No keyboard device found."

run_keyboard_test
KB_KEYS_CHECK=$KB_TEST_RESULT

run_touchpad_test
TOUCHPAD=$TOUCHPAD_RESULT

# ============================================================
# 10. NETWORK
# ============================================================
banner "10. Network"
WIFI_DEV=$(iw dev 2>/dev/null | awk '/Interface/{print $2}' | head -1)
ETH_DEV=$(ip -o addr show 2>/dev/null | awk '$3=="inet" && $2!~/^lo$|^wl/{print $2; exit}')

[[ -n "$WIFI_DEV" ]] && ok "WiFi: $WIFI_DEV" || err "No WiFi device found."
[[ -n "$ETH_DEV" ]] && ok "Ethernet: $ETH_DEV" || warn "No Ethernet device found."

# ============================================================
# 10b. INTERNET CONNECTIVITY
# ============================================================
banner "10b. Internet Connectivity"
INTERNET_STATUS="NO_ETH_DEVICE"
INTERNET_VIA="${ETH_DEV:-none}"

_inet_check() {
  local dev="$1"
  HTTP_CODE_INET=$(curl -s -o /dev/null -w "%{http_code}" \
    --max-time 5 \
    http://connectivitycheck.gstatic.com/generate_204 2>/dev/null)
  if [[ "$HTTP_CODE_INET" =~ ^2[0-9][0-9]$ ]]; then
    return 0
  elif ping -c 3 -W 3 8.8.8.8 &>/dev/null; then
    return 0
  fi
  return 1
}

if [[ -n "$ETH_DEV" ]]; then
  if _inet_check "$ETH_DEV"; then
    INTERNET_STATUS="PASS"
    ok "Internet reachable via $ETH_DEV"
  else
    INTERNET_STATUS="FAIL"
    _retry=1
    while true; do
      warn "Internet unreachable (attempt ${_retry}) — via $ETH_DEV  [curl HTTP code: ${HTTP_CODE_INET:-none}]"
      echo ""
      echo -e "  ${YELLOW}${BOLD}Please check the ethernet cable and network connection.${NC}"
      echo -e "  Press ${BOLD}Enter${NC} to retry, or type ${BOLD}s${NC} + Enter to skip and mark as FAIL:"
      read -r _ans < /dev/tty
      if [[ "${_ans,,}" == "s" ]]; then
        err "Operator skipped — internet marked as FAIL"
        break
      fi
      (( _retry++ ))
      echo -e "  Retrying..."
      if _inet_check "$ETH_DEV"; then
        INTERNET_STATUS="PASS"
        ok "Internet reachable via $ETH_DEV (passed on attempt ${_retry})"
        break
      fi
    done
  fi
else
  warn "No ethernet device — skipping internet connectivity test"
fi

# ============================================================
# 11. USB PORTS
# ============================================================
banner "11. USB Ports"
USB_DEVICE_COUNT=$(lsusb 2>/dev/null | wc -l)
USB3_COUNT=$(lsusb 2>/dev/null | grep -ciE "3\.0|3\.1|3\.2")
ok "USB devices detected: ${USB_DEVICE_COUNT} | USB 3.x controllers: ${USB3_COUNT}"

PORTS_PHYSICAL=$(ask_manual "Physical port condition (USB/HDMI/audio)" "Check for bent pins or physical damage")

# ============================================================
# 12. APPEARANCE
# ============================================================
banner "12. Appearance"
APPEARANCE_CHECK=$(ask_manual "Appearance (hinge & exterior)" "Open/close lid for hinge check, inspect all sides for scratches/damage")
HINGE=$APPEARANCE_CHECK
APPEARANCE=$APPEARANCE_CHECK

# ============================================================
# 13. KERNEL HEALTH SCAN
# ============================================================
banner "13. Kernel Health Scan"
echo "  Scanning dmesg for hardware error signals..."

# Driver noise to ignore — these are driver bugs, not hardware failures
KH_IGNORE='nouveau|nvkm_|g84_bar_flush|gp102_acr_wpr_patch|ov[0-9]+.*probe.*failed|DMAR.*Passthrough|Bluetooth: hci.*command.*tx timeout|i915.*GPU HANG|WARNING: CPU.*at drivers/|Call Trace:| \? |RIP:|RSP:| Code:|Modules linked in:|end trace|Tainted:|irq/.*pciehp|rewind_stack_and_make_dead'

# Real hardware error signals — only uncorrectable / fatal conditions
# EDAC CE (correctable) is intentionally excluded here; it goes to WARN below.
KH_FAIL_RE='mce:|Machine Check|Hardware Error|EDAC.*(UE|[Uu]ncorrectable)|BadRAM|I/O error|Buffer I/O error|Medium Error|end_request: critical|ata[0-9]+: .*failed command|nvme.*IO timeout|blk_update_request: I/O error|critical medium error|AER:.*Uncorrected|AER:.*Fatal|PCIe Bus Error:.*severity=Fatal|thermal .*critical|Core temperature above threshold|Package temperature above threshold'

# Warning signals — marginal or correctable hardware events, not conclusive failures.
# EDAC HANDLING / CE = ECC correctable error (hardware already fixed the bit flip).
KH_WARN_RE='EDAC.*(HANDLING|CE\b|[Cc]orrected)|device descriptor read/64, error -|device not accepting address|usb.*disabled by hub|ata[0-9]+.*SError|link is slow to respond'

DMESG_FILTERED=$(dmesg 2>/dev/null | grep -vE "$KH_IGNORE")

KH_FAIL_LINES=$(echo "$DMESG_FILTERED" | grep -iE "$KH_FAIL_RE" | head -10)
KH_WARN_LINES=$(echo "$DMESG_FILTERED" | grep -iE "$KH_WARN_RE" | head -10)

if [[ -n "$KH_FAIL_LINES" ]]; then
  KH_FAIL_COUNT=$(echo "$KH_FAIL_LINES" | wc -l)
else
  KH_FAIL_COUNT=0
fi
if [[ -n "$KH_WARN_LINES" ]]; then
  KH_WARN_COUNT=$(echo "$KH_WARN_LINES" | wc -l)
else
  KH_WARN_COUNT=0
fi

if [[ $KH_FAIL_COUNT -gt 0 ]]; then
  KERNEL_HEALTH="FAIL"
  err "$KH_FAIL_COUNT hardware error signal(s) detected:"
  echo "$KH_FAIL_LINES" | while read -r l; do err "  $l"; done
  warn "This laptop has hardware errors — DO NOT refurbish without investigation."
elif [[ $KH_WARN_COUNT -gt 0 ]]; then
  KERNEL_HEALTH="WARN"
  warn "$KH_WARN_COUNT warning signal(s) detected (may indicate marginal hardware):"
  echo "$KH_WARN_LINES" | while read -r l; do warn "  $l"; done
else
  KERNEL_HEALTH="PASS"
  ok "No hardware error signals detected."
fi

# Build JSON array of matched signals (truncate each line to 120 chars)
KH_SIGNALS_JSON="["
kh_first=1
while IFS= read -r l; do
  [[ -z "$l" ]] && continue
  trunc="${l:0:120}"
  [[ $kh_first -eq 0 ]] && KH_SIGNALS_JSON+=","
  KH_SIGNALS_JSON+="\"$(esc "$trunc")\""
  kh_first=0
done < <(printf "%s\n%s\n" "$KH_FAIL_LINES" "$KH_WARN_LINES" | grep -v '^$')
KH_SIGNALS_JSON+="]"

# ============================================================
# BUILD JSON REPORT
# ============================================================
banner "Generating Report"

WIFI_STATUS=$([[ -n "$WIFI_DEV" ]] && echo "PASS" || echo "FAIL")
ETH_STATUS=$([[ -n "$ETH_DEV" ]] && echo "PASS" || echo "FAIL")


JSON=$(cat <<EOF
{
  "test_info": {
    "test_time": "$(esc "$TEST_TIME")",
    "hostname": "$(esc "$HOSTNAME")",
    "script_version": "2.0.0"
  },
  "system": {
    "vendor": "$(esc "$SYS_VENDOR")",
    "model": "$(esc "$SYS_MODEL")",
    "serial_number": "$(esc "$SYS_SERIAL")",
    "bios_version": "$(esc "$BIOS_VER")"
  },
  "cpu": {
    "model": "$(esc "$CPU_MODEL")",
    "cores": ${CPU_CORES:-0},
    "threads": ${CPU_THREADS:-0},
    "max_mhz": "${CPU_MAX_MHZ:-0}",
    "architecture": "$(esc "$CPU_ARCH")"
  },
  "memory": {
    "total_gb": "$(esc "$MEM_TOTAL_GB")",
    "type": "$(esc "${MEM_TYPE:-unknown}")",
    "speed": "$(esc "${MEM_SPEED:-unknown}")",
    "slots_total": ${MEM_SLOTS:-0},
    "slots_used": ${MEM_USED_SLOTS:-0}
  },
  "storage": ${DISK_JSON},
  "battery": ${BAT_JSON},
  "screen": {
    "resolution": "$(esc "${SCREEN_RES:-unknown}")",
    "interface": "$(esc "${SCREEN_NAME:-unknown}")",
    "dead_pixel_check": "$(esc "$SCREEN_DEADPIXEL")",
    "backlight_check": "$(esc "$SCREEN_BACKLIGHT")"
  },
  "camera": {
    "device_status": "$(esc "$CAM_STATUS")",
    "device_count": ${CAM_COUNT:-0},
    "driver_type": "$(esc "$CAM_DRIVER_TYPE")",
    "capture_method": "$(esc "$CAM_CAPTURE_METHOD")",
    "capture_result": "$(esc "$CAM_IMAGE_RESULT")",
    "driver_note": "$(esc "$CAM_DRIVER_NOTE")",
    "image_base64": "$(esc "$CAM_IMAGE_B64")"
  },
  "audio": {
    "speaker_device_status": "$(esc "${AUDIO_CARDS:-0}")",
    "mic_device_status": "$(esc "${MIC_CARDS:-0}")",
    "speaker_quality_check": "$(esc "$SPEAKER_QUALITY_CHECK")",
    "mic_record_check": "$(esc "$MIC_RECORD_CHECK")",
    "speaker_card_used": "$(esc "${AUDIO_CARD_USED:-}")",
    "mic_card_used": "$(esc "${MIC_CARD_USED:-}")"
  },
  "keyboard": {
    "device_status": "$(esc "${KB_DEVICES:-0}")",
    "keys_check": "$(esc "$KB_KEYS_CHECK")",
    "touchpad_check": "$(esc "$TOUCHPAD")"
  },
  "network": {
    "wifi_status": "$(esc "$WIFI_STATUS")",
    "wifi_device": "$(esc "${WIFI_DEV:-none}")",
    "ethernet_status": "$(esc "$ETH_STATUS")",
    "ethernet_device": "$(esc "${ETH_DEV:-none}")",
    "internet_test": "__INTERNET_TEST__",
    "internet_test_via": "__INTERNET_VIA__"
  },
  "ports": {
    "usb_device_count": ${USB_DEVICE_COUNT:-0},
    "usb3_count": ${USB3_COUNT:-0},
    "physical_check": "$(esc "$PORTS_PHYSICAL")"
  },
  "appearance": {
    "hinge_check": "$(esc "$HINGE")",
    "scratch_check": "$(esc "$APPEARANCE")"
  },
  "kernel_health": {
    "status": "$(esc "$KERNEL_HEALTH")",
    "fail_count": ${KH_FAIL_COUNT:-0},
    "warn_count": ${KH_WARN_COUNT:-0},
    "matched_signals": ${KH_SIGNALS_JSON}
  },
  "overall_result": "PENDING"
}
EOF
)

# Determine overall result directly from status variables — more reliable
# than grepping the JSON string (avoids encoding / quoting edge cases).
OVERALL="PASS"
for _s in "$DISK_STATUS" "$BAT_STATUS" "$SCREEN_CHECK" "$CAM_STATUS" \
          "$SPEAKER_QUALITY_RESULT" "$MIC_RECORD_RESULT" \
          "$KB_KEYS_CHECK" "$TOUCHPAD_RESULT" \
          "$INTERNET_STATUS" "$PORTS_PHYSICAL" \
          "$HINGE" "$APPEARANCE" "$KERNEL_HEALTH"; do
  if [[ "$_s" == "FAIL" ]]; then
    OVERALL="FAIL"
    break
  fi
  [[ "$_s" == "WARN" ]] && OVERALL="WARN"
done
JSON=$(echo "$JSON" | sed 's/"PENDING"/"'"$OVERALL"'"/')
# Replace internet placeholders after OVERALL is computed so internet FAIL doesn't affect overall_result
JSON=$(echo "$JSON" | sed "s/__INTERNET_TEST__/$INTERNET_STATUS/; s/__INTERNET_VIA__/$INTERNET_VIA/")

if command -v jq &>/dev/null; then
  if echo "$JSON" | jq . &>/dev/null; then
    echo "$JSON" | jq . > "$REPORT_FILE"
    ok "Report saved (validated): $REPORT_FILE"
  else
    echo "$JSON" > "$REPORT_FILE"
    err "JSON validation failed — saved raw version."
  fi
else
  echo "$JSON" > "$REPORT_FILE"
  ok "Report saved: $REPORT_FILE"
fi

# ============================================================
# UPLOAD REPORT
# ============================================================
banner "Uploading Report"
HTTP_CODE=$(curl -s -o /tmp/upload_response.txt -w "%{http_code}" \
  -X POST "$UPLOAD_URL" \
  -H "Content-Type: application/json" \
  -d @"$REPORT_FILE" \
  --connect-timeout 10 --max-time 30)

if [[ "$HTTP_CODE" == "200" || "$HTTP_CODE" == "201" ]]; then
  ok "Upload successful (HTTP $HTTP_CODE)"
else
  err "Upload failed (HTTP ${HTTP_CODE:-no response})"
  warn "Report kept locally: $REPORT_FILE"
fi

# ============================================================
# TEST SUMMARY
# ============================================================
banner "TEST SUMMARY"
echo ""
printf "  %-20s %s\n" "Vendor/Model:"     "$SYS_VENDOR $SYS_MODEL"
printf "  %-20s %s\n" "Serial:"           "$SYS_SERIAL"
printf "  %-20s %s\n" "CPU:"              "$CPU_MODEL"
printf "  %-20s %s\n" "Memory:"           "${MEM_TOTAL_GB} GB"
printf "  %-20s %s\n" "Battery Health:"   "${BAT_HEALTH}%"
printf "  %-20s %s\n" "Screen:"           "Dead pixel: $SCREEN_DEADPIXEL | Backlight: $SCREEN_BACKLIGHT"
if [[ "$CAM_STATUS" == "HARDWARE_DETECTED" ]]; then
  printf "  %-20s %s\n" "Camera:"         "HARDWARE DETECTED — verify in CearTrack"
elif [[ "$CAM_IMAGE_RESULT" == "CAPTURED" ]]; then
  printf "  %-20s %s\n" "Camera:"         "PASS — image uploaded to CearTrack"
else
  printf "  %-20s %s\n" "Camera:"         "$CAM_STATUS | $CAM_IMAGE_RESULT"
fi
printf "  %-20s %s\n" "Speaker:"          "Quality: $SPEAKER_QUALITY_CHECK"
printf "  %-20s %s\n" "Microphone:"       "Record: $MIC_RECORD_CHECK"
printf "  %-20s %s\n" "Keyboard:"         "Keys: $KB_KEYS_CHECK | Touchpad: $TOUCHPAD"
printf "  %-20s %s\n" "WiFi:"             "${WIFI_DEV:+PASS}"
printf "  %-20s %s\n" "Internet:"         "$INTERNET_STATUS (via $INTERNET_VIA)"
printf "  %-20s %s\n" "Ports:"            "$PORTS_PHYSICAL"
printf "  %-20s %s\n" "Appearance:"       "Hinge: $HINGE | Scratches: $APPEARANCE"
if [[ "$KERNEL_HEALTH" == "FAIL" ]]; then
  printf "  %-20s %s\n" "Kernel Health:"  "FAIL ($KH_FAIL_COUNT hardware errors — see report)"
elif [[ "$KERNEL_HEALTH" == "WARN" ]]; then
  printf "  %-20s %s\n" "Kernel Health:"  "WARN ($KH_WARN_COUNT signals — see report)"
else
  printf "  %-20s %s\n" "Kernel Health:"  "PASS"
fi
echo ""

if [[ "$OVERALL" == "PASS" ]]; then
  echo -e "  ${GREEN}${BOLD}RESULT: ✓ PASS — Ready for resale${NC}"
elif [[ "$OVERALL" == "WARN" ]]; then
  echo -e "  ${YELLOW}${BOLD}RESULT: ⚠ WARNING — See report for details${NC}"
else
  echo -e "  ${RED}${BOLD}RESULT: ✗ FAIL — Needs repair${NC}"
fi

echo -e "\n  Report file: $REPORT_FILE"
echo ""
