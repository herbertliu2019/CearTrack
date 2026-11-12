#!/bin/bash
# ============================================================
# monitor_test.sh — External Monitor Test & Report Generator
# Runs on a fixed test station; the monitor under test (DUT) is a passive device
# identified by its EDID and the barcode on its label.
# Usage: sudo bash monitor_test.sh   (from an Xorg desktop session)
# ============================================================

UPLOAD_URL="http://192.168.30.18:80/monitor/api/upload"
SERVER_VERSION_URL="http://192.168.30.18:80/monitor/version.txt"
# Single source of truth for the script version. Bump this on every release and
# keep server-side version.txt in sync (deploy_script.sh extracts it from here).
SCRIPT_VERSION="1.0.0"
MAX_DEAD_PIXELS=2   # dead+bright pixels allowed; keep in sync with MONITOR_MAX_DEAD_PIXELS in config.py

REPORT_DIR="${MONITOR_REPORT_DIR:-/root/monitor_reports}"
DRM_ROOT="${MONITOR_DRM_ROOT:-/sys/class/drm}"
NET_ROOT="${MONITOR_NET_ROOT:-/sys/class/net}"
DETECT_TIMEOUT=60
PORT_TIMEOUT=30

# TODO Cyclelution list: replace these three placeholders with the monitor dropdowns
SIZE_OPTIONS=(17 19 20 21.5 22 23 23.8 24 25 27 28 32 34 38 43)
COLOR_OPTIONS=(Black Blue Gold Gray Green Purple Red Silver White Yellow)
MARK_OPTIONS=(
  "Minor scratches/blemishes"
  "Screen blemish"
  "Bezel scratches"
  "Stand scratches"
)
DEFECT_OPTIONS=(crack burn-in severe_scratch backlight_bleed stand_damaged bezel_damaged other)
PORT_TYPES_ALLOWED=(DP mDP HDMI DVI VGA USB-C)

# ── Colors ───────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

banner() { echo -e "\n${CYAN}${BOLD}=== $1 ===${NC}"; }
ok()     { echo -e "  ${GREEN}✓ $1${NC}"; }
warn()   { echo -e "  ${YELLOW}⚠ $1${NC}"; }
err()    { echo -e "  ${RED}✗ $1${NC}"; }

# ── Require root ─────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
  echo -e "${RED}Please run with sudo: sudo bash monitor_test.sh${NC}"; exit 1
fi

# All operator input comes through fd 3: stdin may be a pipe, and a scanner acts as a keyboard.
exec 3<"${MONITOR_TTY:-/dev/tty}" || { echo "Cannot open terminal for input."; exit 1; }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

ask() {  # ask VAR "prompt"
  local __line
  printf '%b' "$2" >&2
  IFS= read -r __line <&3 || { echo; err "Terminal input closed — exiting."; exit 1; }
  printf -v "$1" '%s' "$(printf '%s' "$__line" | tr -d '\r' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
}

ask_manual() {  # ask_manual VAR "item" "hint" [allow_skip]
  local __ans __prompt="p=pass / f=fail"
  [[ "$4" == "allow_skip" ]] && __prompt+=" / s=skip"
  echo -e "  ${BOLD}► $2${NC}" >&2
  [[ -n "$3" ]] && echo -e "    ${CYAN}Hint: $3${NC}" >&2
  while :; do
    ask __ans "    Result [$__prompt]: "
    case "${__ans,,}" in
      p) printf -v "$1" 'PASS'; return ;;
      f) printf -v "$1" 'FAIL'; return ;;
      s) [[ "$4" == "allow_skip" ]] && { printf -v "$1" 'SKIPPED'; return; } ;;
    esac
    warn "  Invalid choice."
  done
}

# ============================================================
# EMBEDDED PYTHON
# ============================================================
# Parse one EDID file; prints shell assignments (values are shlex-quoted because
# they come from the monitor, and the output is eval'd).
PY_EDID=$(cat <<'PY'
import math, shlex, sys

VENDORS = {"DEL": "Dell", "GSM": "LG", "ACI": "ASUS", "AUS": "ASUS", "HWP": "HP", "LEN": "Lenovo",
           "SAM": "Samsung", "ACR": "Acer", "BNQ": "BenQ", "VSC": "ViewSonic", "PHL": "Philips", "AOC": "AOC"}

d = open(sys.argv[1], "rb").read()
if len(d) < 128:
    sys.exit(1)
pnp_raw = (d[8] << 8) | d[9]
pnp = "".join(chr(((pnp_raw >> s) & 0x1F) + 64) for s in (10, 5, 0))
product = "%04X" % (d[10] | (d[11] << 8))
serial_num = int.from_bytes(d[12:16], "little")
w_cm, h_cm = d[21], d[22]
size = round(math.hypot(w_cm, h_cm) / 2.54, 1) if w_cm and h_cm else ""

model = serial_str = ""
native = ""
refresh = ""
for off in (54, 72, 90, 108):
    b = d[off:off + 18]
    if b[0] or b[1]:
        if not native:
            clock = (b[0] | (b[1] << 8)) * 10000
            hact = b[2] | ((b[4] & 0xF0) << 4)
            hbl = b[3] | ((b[4] & 0x0F) << 8)
            vact = b[5] | ((b[7] & 0xF0) << 4)
            vbl = b[6] | ((b[7] & 0x0F) << 8)
            native = f"{hact}x{vact}"
            if (hact + hbl) and (vact + vbl):
                refresh = round(clock / ((hact + hbl) * (vact + vbl)), 2)
        continue
    text = bytes(c for c in b[5:18].split(b"\n")[0] if 32 <= c < 127).decode("ascii").strip()
    if b[3] == 0xFC:
        model = text
    elif b[3] == 0xFF:
        serial_str = text

fingerprint = f"{pnp}+{product}+{serial_num}+{serial_str}"
out = {
    "EDID_PNP": pnp, "EDID_VENDOR": VENDORS.get(pnp, pnp), "EDID_PRODUCT": product,
    "EDID_SERIAL_NUM": serial_num, "EDID_SERIAL_STR": serial_str, "EDID_MODEL": model,
    "EDID_WEEK": d[16], "EDID_YEAR": d[17] + 1990, "EDID_SIZE": size,
    "EDID_NATIVE": native, "EDID_REFRESH": refresh,
    "EDID_CHECKSUM_OK": "true" if sum(d[:128]) % 256 == 0 else "false",
    "EDID_FP": fingerprint, "EDID_HEX": d.hex(),
}
for k, v in out.items():
    print(f"{k}={shlex.quote(str(v))}")
PY
)

# Map a DRM connector to its xrandr output by EDID (names differ between drivers,
# e.g. HDMI-A-1 vs HDMI-1 vs HDMI-A-0). Falls back to the only external output.
PY_XR_NAME=$(cat <<'PY'
import re, sys

prop = open(sys.argv[1]).read()
edid = open(sys.argv[2], "rb").read().hex()
outputs, cur = {}, None
in_edid = False
for line in prop.splitlines():
    m = re.match(r"(\S+) (connected|disconnected)", line)
    if m:
        cur = m.group(1)
        outputs[cur] = {"status": m.group(2), "edid": ""}
        in_edid = False
    elif cur and re.match(r"\s+EDID:", line):
        in_edid = True
    elif in_edid and re.fullmatch(r"\s+[0-9a-fA-F]+", line):
        outputs[cur]["edid"] += line.strip().lower()
    else:
        in_edid = False

for name, o in outputs.items():
    if o["status"] == "connected" and o["edid"] and o["edid"][:256] == edid[:256]:
        print(name)
        sys.exit(0)
ext = [n for n, o in outputs.items() if o["status"] == "connected" and not re.match(r"(eDP|LVDS|DSI)", n)]
if len(ext) == 1:
    print(ext[0])
PY
)

# Read one output from `xrandr --query`; prints shell assignments.
PY_XR_INFO=$(cat <<'PY'
import re, shlex, sys

lines = open(sys.argv[1]).read().splitlines()
output, native = sys.argv[2], sys.argv[3]
geom = cur_mode = cur_rate = pref_mode = pref_rate = native_rate = ""
best = (0, 0, "", "")
active = False
for line in lines:
    if not line[:1].isspace():
        active = line.startswith(output + " ")
        if active:
            m = re.search(r"(\d+x\d+\+\d+\+\d+)", line)
            geom = m.group(1) if m else ""
        continue
    if not active:
        continue
    m = re.match(r"\s+(\d+)x(\d+)(i?)\s+(.*)$", line)
    if not m or m.group(3):
        continue  # interlaced modes are never the target
    mode = f"{m.group(1)}x{m.group(2)}"
    for rate, star, plus in re.findall(r"(\d+\.\d+)(\*?)\s?(\+?)", m.group(4)):
        r = float(rate)
        if star:
            cur_mode, cur_rate = mode, rate
        if plus and not pref_mode:
            pref_mode, pref_rate = mode, rate
        if mode == native and (not native_rate or r > float(native_rate)):
            native_rate = rate
        area = int(m.group(1)) * int(m.group(2))
        if (area, r) > best[:2]:
            best = (area, r, mode, rate)
if not pref_mode:
    pref_mode, pref_rate = best[2], best[3]
out = {"XR_GEOM": geom, "XR_CUR_MODE": cur_mode, "XR_CUR_RATE": cur_rate, "XR_PREF_MODE": pref_mode,
       "XR_PREF_RATE": pref_rate, "XR_NATIVE_RATE": native_rate}
for k, v in out.items():
    print(f"{k}={shlex.quote(str(v))}")
PY
)

# Full-screen test patterns on the DUT only. argv: width height x y shown_file
PY_PATTERNS=$(cat <<'PY'
import json, sys
import tkinter

W, H, X, Y = (int(v) for v in sys.argv[1:5])
SHOWN_FILE = sys.argv[5]
NAMES = ["red", "green", "blue", "white", "black", "gray50", "grid", "gradient", "checker"]
SOLID = {"red": "#ff0000", "green": "#00ff00", "blue": "#0000ff", "white": "#ffffff",
         "black": "#000000", "gray50": "#808080"}
GRID_STEP = 16
CHECKER = 32

root = tkinter.Tk()
root.overrideredirect(True)
root.geometry(f"{W}x{H}+{X}+{Y}")
root.configure(bg="black", cursor="none")
canvas = tkinter.Canvas(root, width=W, height=H, highlightthickness=0, bg="black")
canvas.pack()

index = 0
shown = []
label_timer = None


def draw(name):
    canvas.delete("all")
    if name in SOLID:
        canvas.configure(bg=SOLID[name])
    elif name == "grid":
        canvas.configure(bg="black")
        for x in range(0, W, GRID_STEP):
            canvas.create_line(x, 0, x, H, fill="white", width=1)
        for y in range(0, H, GRID_STEP):
            canvas.create_line(0, y, W, y, fill="white", width=1)
    elif name == "gradient":
        for level in range(256):
            x0, x1 = W * level // 256, W * (level + 1) // 256
            canvas.create_rectangle(x0, 0, x1, H, width=0, fill=f"#{level:02x}{level:02x}{level:02x}")
    elif name == "checker":
        canvas.configure(bg="black")
        for row in range(H // CHECKER + 1):
            for col in range(W // CHECKER + 1):
                if (row + col) % 2 == 0:
                    canvas.create_rectangle(col * CHECKER, row * CHECKER, (col + 1) * CHECKER,
                                            (row + 1) * CHECKER, width=0, fill="white")


def show():
    global label_timer
    name = NAMES[index]
    draw(name)
    if name not in shown:
        shown.append(name)
    if label_timer:
        root.after_cancel(label_timer)
    # Small corner label, gone after 3s so it can't hide a dead pixel.
    color = "black" if name in ("white", "green") else "white"
    text = f"{index + 1}/{len(NAMES)} {name}   Right/Space next, Left back, Esc end"
    canvas.create_text(W - 10, H - 10, anchor="se", text=text, fill=color, font=("TkDefaultFont", 9), tags="label")
    label_timer = root.after(3000, lambda: canvas.delete("label"))


def step(delta):
    global index
    index = max(0, min(len(NAMES) - 1, index + delta))
    show()


def finish(_event=None):
    with open(SHOWN_FILE, "w") as f:
        json.dump(shown, f)
    root.destroy()


def take_keyboard():
    root.lift()
    root.focus_force()
    try:
        root.grab_set_global()  # override-redirect windows may get no focus from the WM
    except tkinter.TclError:
        pass


root.bind("<Right>", lambda _e: step(1))
root.bind("<space>", lambda _e: step(1))
root.bind("<Left>", lambda _e: step(-1))
root.bind("<Escape>", finish)
root.after(300, take_keyboard)
show()
root.mainloop()
PY
)

# Colour bars shown while the operator confirms there is a picture. argv: width height x y
PY_PICTURE=$(cat <<'PY'
import sys
import tkinter

W, H, X, Y = (int(v) for v in sys.argv[1:5])
root = tkinter.Tk()
root.overrideredirect(True)
root.geometry(f"{W}x{H}+{X}+{Y}")
root.configure(cursor="none")
canvas = tkinter.Canvas(root, width=W, height=H, highlightthickness=0, bg="black")
canvas.pack()
bars = ["#ffffff", "#ffff00", "#00ffff", "#00ff00", "#ff00ff", "#ff0000", "#0000ff", "#000000"]
for i, c in enumerate(bars):
    canvas.create_rectangle(W * i // 8, 0, W * (i + 1) // 8, H, width=0, fill=c)
canvas.create_text(W // 2, H // 2, text="PICTURE OK - answer in the terminal", fill="#808080",
                   font=("TkDefaultFont", max(18, H // 40)))
root.after(300, root.lift)
root.mainloop()
PY
)

# Build the JSON report from R_* environment variables and helper files.
PY_REPORT=$(cat <<'PY'
import json, os, sys

e = os.environ
out_path, work = sys.argv[1], sys.argv[2]


def read_lines(name):
    path = os.path.join(work, name)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", errors="replace") as f:
        return [ln.rstrip("\r\n") for ln in f if ln.strip()]


def to_int(v):
    return int(v) if str(v).strip().lstrip("-").isdigit() else None


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def to_bool(v):
    return v == "true"


ports = []
for line in read_lines("ports.tsv"):
    ptype, index, result, conn = (line.split("\t") + [""] * 4)[:4]
    ports.append({"type": ptype, "index": int(index), "result": result, "station_connector": conn})

shown_path = os.path.join(work, "shown.json")
shown = json.load(open(shown_path)) if os.path.exists(shown_path) else []
decode_path = os.path.join(work, "edid_decode.txt")
decode = open(decode_path, encoding="utf-8", errors="replace").read() if os.path.exists(decode_path) else ""

report = {
    "report_type": "monitor",
    "test_info": {
        "test_time": e["R_TEST_TIME"], "operator_id": e["R_OPERATOR"], "duration_seconds": to_int(e["R_DURATION"]),
        "script_version": e["R_VERSION"], "station_hostname": e["R_HOST"], "station_gpu": e["R_GPU"],
    },
    "identity": {
        "label_sn": e["R_LABEL_SN"], "edid_serial_str": e["R_SERIAL_STR"],
        "edid_serial_num": to_int(e["R_SERIAL_NUM"]) or 0, "sn_match": e["R_SN_MATCH"],
        "vendor": e["R_VENDOR"], "vendor_pnp": e["R_PNP"], "model": e["R_MODEL"], "product_code": e["R_PRODUCT"],
        "mfg_week": to_int(e["R_WEEK"]) or 0, "mfg_year": to_int(e["R_YEAR"]) or 0,
        "edid_checksum_ok": to_bool(e["R_CHECKSUM"]) if e["R_CHECKSUM"] else None,
        "edid_fingerprint": e["R_FP"], "edid_raw_hex": e["R_HEX"], "edid_decode_text": decode,
    },
    "display": {
        "native_resolution": e["R_NATIVE"], "native_refresh": to_float(e["R_NATIVE_RATE"]),
        "achieved_resolution": e["R_ACHIEVED"], "achieved_refresh": to_float(e["R_ACHIEVED_RATE"]) or 0,
        "resolution_check": e["R_RES_CHECK"], "station_limited": to_bool(e["R_STATION_LIMITED"]),
        "no_signal": to_bool(e["R_NO_SIGNAL"]), "size_inch_edid": to_float(e["R_SIZE"]),
        "dead_pixel_count": to_int(e["R_DEAD"]), "max_dead_pixels_allowed": to_int(e["R_MAX_DEAD"]),
        "dead_pixel_check": e["R_DEAD_CHECK"], "backlight_check": e["R_BACKLIGHT"], "patterns_shown": shown,
    },
    "ports": ports,
    "appearance": {
        "cosmetic_check": e["R_COSMETIC"], "defects": read_lines("defects.txt"), "defect_note": e["R_DEFECT_NOTE"],
        "osd_buttons_check": e["R_OSD"], "stand_included": e["R_STAND"],
    },
    "manual_input": {
        "weight_lbs": e["R_WEIGHT"], "grade": e["R_GRADE"], "condition": e["R_CONDITION"],
        "color": e["R_COLOR"], "screen_size_inch": e["R_SIZE_FULL"], "mark": e["R_MARK"],
    },
    "network": {"ethernet_status": e["R_ETH_STATUS"], "ethernet_device": e["R_ETH_DEV"]},
    "result_reasons": read_lines("reasons.txt"),
    "overall_result": e["R_OVERALL"],
}
with open(out_path, "w", encoding="utf-8", newline="\n") as f:
    json.dump(report, f, ensure_ascii=False)
PY
)

# ============================================================
# GRAPHICAL SESSION
# ============================================================
# sudo drops XDG_SESSION_TYPE / WAYLAND_DISPLAY, so also ask logind about the invoking user.
session_type() {
  local _s _t
  [[ -n "${WAYLAND_DISPLAY:-}" ]] && { echo wayland; return; }
  case "${XDG_SESSION_TYPE:-}" in wayland|x11) echo "$XDG_SESSION_TYPE"; return ;; esac
  if [[ -n "${SUDO_USER:-}" ]] && command -v loginctl &>/dev/null; then
    for _s in $(loginctl list-sessions --no-legend 2>/dev/null | awk -v u="$SUDO_USER" '$3==u {print $1}'); do
      _t=$(loginctl show-session "$_s" -p Type --value 2>/dev/null)
      case "$_t" in wayland|x11) echo "$_t"; return ;; esac
    done
  fi
  echo unknown
}

wayland_exit() {
  err "This is a Wayland session — xrandr is unreliable there, so this test cannot run."
  echo -e "  Log out, click the ${BOLD}gear icon${NC} on the login screen, choose ${BOLD}Ubuntu on Xorg${NC},"
  echo -e "  log in again, then re-run: ${BOLD}sudo bash monitor_test.sh${NC}"
  exit 1
}

no_session_exit() {
  err "No graphical session found (DISPLAY is not set)."
  echo -e "  This test needs an Xorg desktop session. Boot the ${BOLD}monitor-test image / boot entry${NC} (auto-login to Xorg),"
  echo -e "  then run it over SSH, or from a terminal on the machine's desktop."
  exit 1
}

check_session_type() {
  [[ "$(session_type)" == "wayland" ]] && wayland_exit
  if [[ -z "${DISPLAY:-}" ]]; then
    local _sock
    for _sock in /tmp/.X11-unix/X*; do
      [[ -S "$_sock" ]] && { export DISPLAY=":${_sock##*/X}"; break; }
    done
    [[ -n "${DISPLAY:-}" ]] || no_session_exit
    warn "DISPLAY was not set — using $DISPLAY"
  fi
}

# Root needs the desktop user's X cookie; sudo normally passes XAUTHORITY along.
check_x_access() {
  xrandr --query &>/dev/null && return 0
  local _uid _f
  _uid="${SUDO_UID:-1000}"
  for _f in "/run/user/$_uid/gdm/Xauthority" "/home/${SUDO_USER:-ubuntu}/.Xauthority" \
            "/run/lightdm/${SUDO_USER:-ubuntu}/xauthority" "/home/ubuntu/.Xauthority"; do
    [[ -r "$_f" ]] || continue
    export XAUTHORITY="$_f"
    xrandr --query &>/dev/null && return 0
  done
  err "Cannot talk to the X server on DISPLAY=$DISPLAY."
  echo -e "  Run this from a terminal in the Xorg desktop, or first run ${BOLD}xhost +SI:localuser:root${NC} as the desktop user."
  exit 1
}

# ============================================================
# DEPENDENCIES
# ============================================================
install_dependencies() {
  banner "Checking and Installing Dependencies"
  local PKGS=(python3 python3-tk x11-xserver-utils edid-decode curl jq ethtool pciutils)
  local MISSING=() FAILED=() pkg
  for pkg in "${PKGS[@]}"; do
    dpkg -s "$pkg" &>/dev/null 2>&1 || MISSING+=("$pkg")
  done

  if [[ ${#MISSING[@]} -eq 0 ]]; then
    ok "All dependencies already installed."
  else
    warn "${#MISSING[@]} package(s) missing: ${MISSING[*]}"
    echo "  Running apt-get update..."
    apt-get update -qq 2>/dev/null || warn "apt-get update failed — network may be unavailable."
    for pkg in "${MISSING[@]}"; do
      echo -n "  Installing $pkg ... "
      if apt-get install -y -q "$pkg" &>/dev/null 2>&1; then
        echo -e "${GREEN}OK${NC}"
      else
        echo -e "${RED}FAILED${NC}"
        FAILED+=("$pkg")
      fi
    done
    [[ ${#FAILED[@]} -eq 0 ]] && ok "All dependencies installed successfully." || warn "Could not install: ${FAILED[*]}"
  fi

  # edid-decode only adds raw text to the report; these are required to run at all.
  local fatal=0
  command -v xrandr &>/dev/null || { err "xrandr is missing (x11-xserver-utils)."; fatal=1; }
  command -v curl &>/dev/null || { err "curl is missing."; fatal=1; }
  python3 -c 'import tkinter' &>/dev/null || { err "python3 tkinter is missing (python3-tk)."; fatal=1; }
  if (( fatal )); then
    err "Connect the wired network and re-run so the packages can be installed."
    exit 1
  fi
}

check_script_version() {
  local _server
  _server=$(curl -sf --max-time 3 "$SERVER_VERSION_URL" 2>/dev/null | tr -d '[:space:]')
  if [[ -n "$_server" && "$_server" != "$SCRIPT_VERSION" ]]; then
    warn "Server has monitor_test.sh v$_server; you are running v$SCRIPT_VERSION."
    warn "Update: curl -o monitor_test.sh ${SERVER_VERSION_URL%version.txt}script"
  fi
}

# ============================================================
# ETHERNET (same rule as laptop_test.sh: no link, no valid test)
# ============================================================
detect_eth_dev() {
  local ifc name best=""
  for ifc in "$NET_ROOT"/*; do
    name=$(basename "$ifc")
    [[ "$name" == "lo" ]] && continue
    [[ -e "$ifc/wireless" || -e "$ifc/phy80211" ]] && continue   # skip WiFi
    [[ -e "$ifc/device" ]] || continue                            # real HW (covers USB-RJ45)
    case "$name" in docker*|veth*|virbr*|br-*|tun*|tap*|bond*|dummy*) continue ;; esac
    if [[ "$(cat "$ifc/carrier" 2>/dev/null)" == "1" ]]; then echo "$name"; return 0; fi
    [[ -z "$best" ]] && best="$name"
  done
  [[ -n "$best" ]] && { echo "$best"; return 0; }
  return 1
}

# carrier == 1 means cable connected + link up (port LED on). Bring the iface up
# first — an admin-down interface reports no carrier even with the cable plugged.
eth_has_link() {
  local dev="$1"
  [[ -n "$dev" ]] || return 1
  ip link set "$dev" up 2>/dev/null || true
  [[ "$(cat "$NET_ROOT/$dev/carrier" 2>/dev/null)" == "1" ]]
}

# A missing link is the station's fault, not the monitor's, so there is no
# "mark bad" here: fix the link or quit. Returns 1 when the operator quits.
require_ethernet() {
  local _ans _e
  ETH_DEV=$(detect_eth_dev)
  [[ -n "$ETH_DEV" ]] && ip link set "$ETH_DEV" up 2>/dev/null || true
  for ((_e=0; _e<5; _e++)); do
    ETH_DEV=$(detect_eth_dev)
    eth_has_link "$ETH_DEV" && break
    sleep 1
  done
  ETH_STATUS="FAIL"
  while true; do
    ETH_DEV=$(detect_eth_dev)                 # re-detect (a USB-RJ45 may be plugged mid-wait)
    if eth_has_link "$ETH_DEV"; then
      ok "Ethernet: $ETH_DEV (link up)"
      ETH_STATUS="PASS"
      return 0
    fi
    if [[ -n "$ETH_DEV" ]]; then
      warn "Ethernet $ETH_DEV present but NO LINK — cable unplugged, port LED off, or bad port."
    else
      warn "No wired NIC detected — plug the network cable / USB-RJ45 adapter."
    fi
    echo -e "  ${RED}${BOLD}A wired link is REQUIRED — results cannot upload to CearTrack without it.${NC}"
    ask _ans "  Fix it, wait for the port LED, then press Enter to re-check (q=quit): "
    [[ "${_ans,,}" == "q" ]] && return 1
  done
}

# ============================================================
# REPORT STORE
# ============================================================
upload_file() {
  curl -s -o "$WORK/upload_response.txt" -w "%{http_code}" \
    -X POST "$UPLOAD_URL" \
    -H "Content-Type: application/json" \
    -d @"$1" \
    --connect-timeout 10 --max-time 30
}

report_store() {  # report_store FILE: upload, then move into sent/ or pending/
  local _file="$1" _code _name
  _name=$(basename "$_file")
  _code=$(upload_file "$_file")
  if [[ "$_code" == "200" || "$_code" == "201" ]]; then
    mv -f "$_file" "$REPORT_DIR/sent/$_name"
    ok "Upload successful (HTTP $_code): $_name"
    return 0
  fi
  [[ "$(dirname "$_file")" == "$REPORT_DIR/pending" ]] || mv -f "$_file" "$REPORT_DIR/pending/$_name"
  err "Upload failed (HTTP ${_code:-no response}): $_name — kept in pending/"
  return 1
}

# Reports stranded by a failed upload (or a crash between saving and uploading).
retry_pending() {
  local _f _found=()
  for _f in "$REPORT_DIR"/pending/*.json "$REPORT_DIR"/*.json; do
    [[ -f "$_f" ]] && _found+=("$_f")
  done
  [[ ${#_found[@]} -eq 0 ]] && return 0
  banner "Re-uploading ${#_found[@]} pending report(s)"
  for _f in "${_found[@]}"; do
    report_store "$_f"
  done
}

pending_count() {
  local _f _n=0
  for _f in "$REPORT_DIR"/pending/*.json; do
    [[ -f "$_f" ]] && _n=$((_n + 1))
  done
  echo "$_n"
}

# ============================================================
# DRM / EDID
# ============================================================
# Stat size is unreliable on sysfs binary files (often 0), so read the bytes.
edid_nonempty() { [[ "$(head -c 128 "$1" 2>/dev/null | wc -c)" -ge 128 ]]; }

is_external() {
  case "$1" in eDP*|LVDS*|DSI*|Writeback*) return 1 ;; esac
  return 0
}

list_external() {  # connected external connectors with a readable EDID, as cardN-NAME
  local d name
  for d in "$DRM_ROOT"/card*-*; do
    [[ -d "$d" ]] || continue
    name=${d##*/}
    is_external "${name#card*-}" || continue
    [[ "$(cat "$d/status" 2>/dev/null)" == "connected" ]] || continue
    edid_nonempty "$d/edid" && echo "$name"
  done
}

list_external_no_edid() {
  local d name
  for d in "$DRM_ROOT"/card*-*; do
    [[ -d "$d" ]] || continue
    name=${d##*/}
    is_external "${name#card*-}" || continue
    [[ "$(cat "$d/status" 2>/dev/null)" == "connected" ]] || continue
    edid_nonempty "$d/edid" || echo "$name"
  done
}

connector_type() {  # HDMI-A-1 -> HDMI
  case "$1" in
    DP-*|DisplayPort-*) echo "DP" ;;
    HDMI-*) echo "HDMI" ;;
    DVI-*) echo "DVI" ;;
    VGA-*) echo "VGA" ;;
    *) echo "${1%%-*}" ;;
  esac
}

edid_vars() {  # edid_vars FILE: prints EDID_* assignments
  python3 -c "$PY_EDID" "$1" 2>/dev/null
}

fingerprint_of() {  # fingerprint_of FILE
  local EDID_FP=""
  eval "$(edid_vars "$1")"
  echo "$EDID_FP"
}

# Step 1. Sets DUT_DRM. Returns 0=found, 1=operator marked it bad (no EDID), 2=quit.
wait_for_dut() {
  local _start _ext _noedid _n _ans _note="" _fp
  while true; do
    banner "Step 1: Detect Monitor"
    echo "  Waiting for one external monitor (up to ${DETECT_TIMEOUT}s)..."
    _start=$SECONDS
    while (( SECONDS - _start < DETECT_TIMEOUT )); do
      xrandr --query &>/dev/null   # forces a connector re-probe on drivers without hotplug
      mapfile -t _ext < <(list_external)
      mapfile -t _noedid < <(list_external_no_edid)
      _n=$(( ${#_ext[@]} + ${#_noedid[@]} ))
      if (( _n > 1 )); then
        if [[ "$_note" != "multi" ]]; then
          warn "$_n external monitors connected (${_ext[*]} ${_noedid[*]}) — keep only ONE cable plugged in."
          _note="multi"
        fi
      elif (( ${#_ext[@]} == 1 )); then
        DUT_DRM="${_ext[0]}"
        _fp=$(fingerprint_of "$DRM_ROOT/$DUT_DRM/edid")
        if [[ -n "$LAST_FP" && "$_fp" == "$LAST_FP" ]]; then
          ask _ans "  This looks like the monitor just tested. Test it again? [y=yes / Enter=wait for next]: "
          if [[ "${_ans,,}" != "y" ]]; then
            _start=$SECONDS
            sleep 2
            continue
          fi
        fi
        ok "Monitor found on ${DUT_DRM#card*-}"
        return 0
      elif (( ${#_noedid[@]} == 1 )) && [[ "$_note" != "noedid" ]]; then
        warn "${_noedid[0]#card*-} is connected but its EDID cannot be read — still trying..."
        _note="noedid"
      fi
      sleep 2
    done
    warn "No usable monitor detected in ${DETECT_TIMEOUT}s."
    while :; do
      ask _ans "  [r=retry / b=mark BAD (no EDID / no signal, records FAIL) / q=quit]: "
      case "${_ans,,}" in
        r) _note=""; break ;;
        b) return 1 ;;
        q) return 2 ;;
        *) warn "  Enter r, b, or q." ;;
      esac
    done
  done
}

# ============================================================
# STEP 3: LABEL SN
# ============================================================
clean_sn() { printf '%s' "$1" | tr -cd '[:print:]' | sed 's/^ *//; s/ *$//' | tr '[:lower:]' '[:upper:]'; }

scan_label_sn() {
  local _raw
  while :; do
    ask _raw "  $(printf '%b' "${BOLD}")Scan the monitor label SN barcode: $(printf '%b' "${NC}")"
    LABEL_SN=$(clean_sn "$_raw")
    [[ -n "$LABEL_SN" ]] && return 0
    err "SN cannot be empty."
  done
}

edid_serial_number_usable() {  # 0 and 0x01010101 are common "no serial" fillers
  [[ -n "$1" && "$1" != "0" && "$1" != "16843009" ]]
}

sn_compare() {  # sn_compare LABEL EDID_STR EDID_NUM -> MATCH|MISMATCH|EDID_EMPTY
  local _label="$1" _edid _short
  _edid=$(clean_sn "$2")
  if [[ -z "$_edid" ]]; then
    edid_serial_number_usable "$3" && _edid="$3"
  fi
  [[ -z "$_edid" ]] && { echo "EDID_EMPTY"; return; }
  [[ "$_label" == "$_edid" ]] && { echo "MATCH"; return; }
  # "One contains the other" needs enough characters to mean anything.
  _short=$(( ${#_label} < ${#_edid} ? ${#_label} : ${#_edid} ))
  if (( _short >= 4 )) && [[ "$_label" == *"$_edid"* || "$_edid" == *"$_label"* ]]; then
    echo "MATCH"
  else
    echo "MISMATCH"
  fi
}

step3_label_sn() {
  banner "Step 3: Label SN"
  scan_label_sn
  SN_MATCH=$(sn_compare "$LABEL_SN" "$EDID_SERIAL_STR" "$EDID_SERIAL_NUM")
  if [[ "$SN_MATCH" == "MISMATCH" ]]; then
    warn "Label SN $LABEL_SN does not match EDID serial ${EDID_SERIAL_STR:-$EDID_SERIAL_NUM}. Please scan again."
    scan_label_sn
    SN_MATCH=$(sn_compare "$LABEL_SN" "$EDID_SERIAL_STR" "$EDID_SERIAL_NUM")
  fi
  case "$SN_MATCH" in
    MATCH)      ok "Label SN $LABEL_SN matches EDID." ;;
    MISMATCH)   warn "Still MISMATCH (EDID: ${EDID_SERIAL_STR:-$EDID_SERIAL_NUM}) — continuing, result will be WARN." ;;
    EDID_EMPTY) warn "EDID has no serial number — continuing, result will be WARN." ;;
  esac
}

# ============================================================
# STEP 4: RESOLUTION
# ============================================================
internal_output() {
  xrandr --query 2>/dev/null | awk '/^(eDP|LVDS|DSI)[^ ]* connected/ {print $1; exit}'
}

read_xr_info() {
  xrandr --query > "$WORK/xr.txt" 2>/dev/null
  eval "$(python3 -c "$PY_XR_INFO" "$WORK/xr.txt" "$XR_OUT" "$NATIVE_RES" 2>/dev/null)"
}

step4_resolution() {
  banner "Step 4: Resolution Check"
  local _int _ans _target _rate _args
  RES_CHECK="FAIL"; STATION_LIMITED="false"; NO_SIGNAL="false"
  ACHIEVED_RES=""; ACHIEVED_RATE=""; XR_GEOM=""
  NATIVE_RES="$EDID_NATIVE"; NATIVE_RATE="$EDID_REFRESH"

  xrandr --prop > "$WORK/xr_prop.txt" 2>/dev/null
  XR_OUT=$(python3 -c "$PY_XR_NAME" "$WORK/xr_prop.txt" "$DRM_ROOT/$DUT_DRM/edid" 2>/dev/null)
  if [[ -z "$XR_OUT" ]]; then
    err "xrandr does not list this monitor."
    NO_SIGNAL="true"
    return 1
  fi

  read_xr_info
  [[ -z "$NATIVE_RES" ]] && { NATIVE_RES="$XR_PREF_MODE"; NATIVE_RATE="$XR_PREF_RATE"; read_xr_info; }

  if [[ -n "$XR_NATIVE_RATE" ]]; then
    _target="$NATIVE_RES"; _rate="$XR_NATIVE_RATE"
  else
    _target="$XR_PREF_MODE"; _rate="$XR_PREF_RATE"
  fi

  _int=$(internal_output)
  _args=(--output "$XR_OUT")
  if [[ -n "$_target" ]]; then
    _args+=(--mode "$_target")
    [[ -n "$_rate" ]] && _args+=(--rate "$_rate")
  else
    _args+=(--auto)
  fi
  if [[ -n "$_int" ]]; then
    _args+=(--right-of "$_int")
  else
    warn "No built-in screen found — patterns will take over this display."
  fi
  if ! xrandr "${_args[@]}" 2>/dev/null; then
    warn "xrandr could not set $_target@$_rate — trying automatic mode."
    if [[ -n "$_int" ]]; then
      xrandr --output "$XR_OUT" --auto --right-of "$_int" 2>/dev/null
    else
      xrandr --output "$XR_OUT" --auto 2>/dev/null
    fi
  fi
  sleep 2
  read_xr_info
  ACHIEVED_RES="$XR_CUR_MODE"; ACHIEVED_RATE="$XR_CUR_RATE"

  if [[ -z "$XR_GEOM" || -z "$ACHIEVED_RES" ]]; then
    err "Monitor did not come up on $XR_OUT."
    NO_SIGNAL="true"
    return 1
  fi

  # xrandr succeeds on a dead panel too, so only the operator can confirm a picture.
  local _w _h _x _y _pic_pid=""
  IFS='x+' read -r _w _h _x _y <<< "$XR_GEOM"
  python3 -c "$PY_PICTURE" "$_w" "$_h" "$_x" "$_y" &>/dev/null &
  _pic_pid=$!
  while :; do
    ask _ans "  Is the monitor showing colour bars? [y/n]: "
    case "${_ans,,}" in
      y) break ;;
      n) kill "$_pic_pid" 2>/dev/null; err "No picture — recording FAIL."; NO_SIGNAL="true"; return 1 ;;
      *) warn "  Enter y or n." ;;
    esac
  done
  kill "$_pic_pid" 2>/dev/null; wait "$_pic_pid" 2>/dev/null

  if [[ "$ACHIEVED_RES" == "$NATIVE_RES" ]] && awk -v r="$ACHIEVED_RATE" 'BEGIN {exit !(r >= 59)}'; then
    RES_CHECK="PASS"
    ok "Running native $ACHIEVED_RES @ ${ACHIEVED_RATE}Hz"
  else
    RES_CHECK="WARN"; STATION_LIMITED="true"
    warn "Got $ACHIEVED_RES @ ${ACHIEVED_RATE}Hz, native is $NATIVE_RES @ ${NATIVE_RATE:-?}Hz — test station limit, not a monitor fault."
  fi
  return 0
}

# ============================================================
# STEP 5: PATTERNS
# ============================================================
step5_patterns() {
  banner "Step 5: Pattern Test"
  local _w _h _x _y _ans _count
  IFS='x+' read -r _w _h _x _y <<< "$XR_GEOM"
  while true; do
    echo -e "  Patterns show on the monitor only. ${BOLD}Right/Space${NC}=next, ${BOLD}Left${NC}=back, ${BOLD}Esc${NC}=end."
    rm -f "$WORK/shown.json"
    if ! python3 -c "$PY_PATTERNS" "$_w" "$_h" "$_x" "$_y" "$WORK/shown.json"; then
      err "Pattern window failed."
      ask _ans "  [r=retry / q=abandon this monitor]: "
      [[ "${_ans,,}" == "q" ]] && return 1
      continue
    fi
    _count=$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))))' "$WORK/shown.json" 2>/dev/null)
    if [[ "${_count:-0}" -ge 9 ]]; then
      ok "All 9 patterns shown."
      break
    fi
    warn "Only ${_count:-0} of 9 patterns were shown."
    ask _ans "  [r=show again / Enter=continue anyway]: "
    [[ "${_ans,,}" == "r" ]] || break
  done

  while :; do
    ask DEAD_PIXELS "  $(printf '%b' "${BOLD}")Dead + bright pixel count [0-99]: $(printf '%b' "${NC}")"
    [[ "$DEAD_PIXELS" =~ ^[0-9]{1,2}$ ]] && { DEAD_PIXELS=$((10#$DEAD_PIXELS)); break; }
    warn "  Enter a whole number from 0 to 99."
  done
  if (( DEAD_PIXELS > MAX_DEAD_PIXELS )); then
    DEAD_CHECK="FAIL"
    err "Dead pixels $DEAD_PIXELS > $MAX_DEAD_PIXELS"
  else
    DEAD_CHECK="PASS"
  fi
  ask_manual BACKLIGHT_CHECK "Backlight" "Light leaks and uneven brightness on the black and white patterns"
  return 0
}

# ============================================================
# STEP 6: PORTS
# ============================================================
add_port() {  # add_port TYPE INDEX
  PORT_TYPE+=("$1"); PORT_INDEX+=("$2"); PORT_RESULT+=(""); PORT_CONN+=("")
}

canonical_port_type() {
  local _t
  for _t in "${PORT_TYPES_ALLOWED[@]}"; do
    [[ "${_t,,}" == "${1,,}" ]] && { echo "$_t"; return 0; }
  done
  return 1
}

declare_ports() {
  local _line _tok _type _count _i _good
  PORT_TYPE=(); PORT_INDEX=(); PORT_RESULT=(); PORT_CONN=()
  echo "  Types: ${PORT_TYPES_ALLOWED[*]}"
  while :; do
    ask _line "  $(printf '%b' "${BOLD}")Ports on this monitor (e.g. DP=1 HDMI=2): $(printf '%b' "${NC}")"
    PORT_TYPE=(); PORT_INDEX=(); PORT_RESULT=(); PORT_CONN=()
    _good=1
    for _tok in $_line; do
      if [[ "$_tok" =~ ^([A-Za-z-]+)=([0-9])$ ]] && _type=$(canonical_port_type "${BASH_REMATCH[1]}"); then
        _count="${BASH_REMATCH[2]}"
        for ((_i=1; _i<=_count; _i++)); do add_port "$_type" "$_i"; done
      else
        warn "  Not understood: $_tok"
        _good=0
      fi
    done
    (( _good && ${#PORT_TYPE[@]} > 0 )) && return 0
    warn "  Enter at least one port, as TYPE=COUNT."
  done
}

# The first port is the one already in use. A station connector type may not
# name the monitor port (adapters, DP Alt Mode), so ask when there is no exact match.
mark_first_port() {
  local _conn="$1" _type _i _ans
  _type=$(connector_type "$_conn")
  for _i in "${!PORT_TYPE[@]}"; do
    if [[ "${PORT_TYPE[$_i]}" == "$_type" ]]; then
      PORT_RESULT[$_i]="PASS"; PORT_CONN[$_i]="$_conn"
      ok "${PORT_TYPE[$_i]} #${PORT_INDEX[$_i]}: PASS (already connected via $_conn)"
      return 0
    fi
  done
  warn "Station connector $_conn ($_type) is not on the declared list. Which monitor port is the cable in?"
  for _i in "${!PORT_TYPE[@]}"; do
    printf "    %d) %s #%s\n" "$((_i + 1))" "${PORT_TYPE[$_i]}" "${PORT_INDEX[$_i]}"
  done
  while :; do
    ask _ans "  Select [1-${#PORT_TYPE[@]}]: "
    if [[ "$_ans" =~ ^[0-9]+$ ]] && (( _ans >= 1 && _ans <= ${#PORT_TYPE[@]} )); then
      _i=$((_ans - 1))
      PORT_RESULT[$_i]="PASS"; PORT_CONN[$_i]="$_conn"
      return 0
    fi
    warn "  Enter a list number."
  done
}

connected_snapshot() { list_external | tr '\n' ' '; list_external_no_edid | tr '\n' ' '; }

# Wait for Enter while watching the cable. Returns 1 if nothing was ever unplugged,
# which means the operator pressed Enter without moving the cable.
wait_enter_for_swap() {
  local _before _line _changed=0
  _before=$(connected_snapshot)
  while :; do
    if IFS= read -r -t 1 _line <&3; then
      break
    elif (( $? <= 128 )); then
      echo; err "Terminal input closed — exiting."; exit 1
    fi
    [[ "$(connected_snapshot)" != "$_before" ]] && _changed=1
  done
  [[ "$(connected_snapshot)" != "$_before" ]] && _changed=1
  (( _changed ))
}

# Returns 0 and sets MATCH_CONN when the DUT shows up on any connector.
wait_port_match() {
  local _start=$SECONDS _ext _fp _warned=""
  while (( SECONDS - _start < PORT_TIMEOUT )); do
    xrandr --query &>/dev/null
    mapfile -t _ext < <(list_external)
    if (( ${#_ext[@]} > 1 )); then
      [[ "$_warned" == "multi" ]] || warn "More than one monitor connected — keep only one cable."
      _warned="multi"
    elif (( ${#_ext[@]} == 1 )); then
      _fp=$(fingerprint_of "$DRM_ROOT/${_ext[0]}/edid")
      if [[ "$_fp" == "$EDID_FP" ]]; then
        MATCH_CONN="${_ext[0]#card*-}"
        return 0
      fi
      [[ "$_warned" == "$_fp" ]] || warn "A DIFFERENT monitor is connected ($_fp) — check the cable and the monitor."
      _warned="$_fp"
    fi
    sleep 1
  done
  return 1
}

step6_ports() {
  banner "Step 6: Port Test"
  local _i _ans _swapped
  declare_ports
  mark_first_port "${DUT_DRM#card*-}"
  xrandr --output "$XR_OUT" --off 2>/dev/null   # DDC is all that's needed; re-enabling across hotplugs is noisy

  for _i in "${!PORT_TYPE[@]}"; do
    [[ -n "${PORT_RESULT[$_i]}" ]] && continue
    while [[ -z "${PORT_RESULT[$_i]}" ]]; do
      echo -e "  ${BOLD}► Move the cable to ${PORT_TYPE[$_i]} #${PORT_INDEX[$_i]}${NC} (switch the input with the monitor buttons if needed), then press Enter."
      _swapped=1
      wait_enter_for_swap || _swapped=0
      if (( ! _swapped )); then
        ask _ans "  No cable change was detected. Did you really move it? [y=yes / Enter=let me do it]: "
        [[ "${_ans,,}" == "y" ]] || continue
      fi
      if wait_port_match; then
        PORT_RESULT[$_i]="PASS"; PORT_CONN[$_i]="$MATCH_CONN"
        ok "${PORT_TYPE[$_i]} #${PORT_INDEX[$_i]}: PASS via $MATCH_CONN"
        break
      fi
      warn "The same monitor was not detected within ${PORT_TIMEOUT}s."
      while :; do
        ask _ans "  [r=retry / f=FAIL / n=cannot test (no cable or adapter)]: "
        case "${_ans,,}" in
          r) break ;;
          f) PORT_RESULT[$_i]="FAIL"; err "${PORT_TYPE[$_i]} #${PORT_INDEX[$_i]}: FAIL"; break ;;
          n) PORT_RESULT[$_i]="NOT_TESTED"; warn "${PORT_TYPE[$_i]} #${PORT_INDEX[$_i]}: NOT_TESTED"; break ;;
          *) warn "  Enter r, f, or n." ;;
        esac
      done
    done
  done
}

# ============================================================
# STEP 7: MANUAL CHECKS
# ============================================================
step7_cosmetic() {
  local _i _input _sel _picked
  ask_manual COSMETIC_CHECK "Cosmetic" "Cracks, burn-in, severe scratches, bezel and stand damage"
  : > "$WORK/defects.txt"
  DEFECT_NOTE=""
  [[ "$COSMETIC_CHECK" == "PASS" ]] && return 0
  echo -e "  ${BOLD}Defects:${NC}"
  for _i in "${!DEFECT_OPTIONS[@]}"; do
    printf "    %d) %s\n" "$((_i + 1))" "${DEFECT_OPTIONS[$_i]}"
  done
  while :; do
    ask _input "  Select (multiple with comma, e.g. 1,3): "
    : > "$WORK/defects.txt"
    _picked=0
    IFS=',' read -ra _sel <<< "$_input"
    for _i in "${_sel[@]}"; do
      _i="${_i// /}"
      if [[ "$_i" =~ ^[0-9]+$ ]] && (( _i >= 1 && _i <= ${#DEFECT_OPTIONS[@]} )); then
        grep -qxF -- "${DEFECT_OPTIONS[$((_i - 1))]}" "$WORK/defects.txt" || echo "${DEFECT_OPTIONS[$((_i - 1))]}" >> "$WORK/defects.txt"
        _picked=1
      else
        warn "  Invalid choice: $_i (ignored)"
      fi
    done
    (( _picked )) && break
    warn "  Pick at least one defect."
  done
  if grep -qx "other" "$WORK/defects.txt"; then
    while [[ -z "$DEFECT_NOTE" ]]; do
      ask DEFECT_NOTE "  Describe 'other': "
    done
  fi
}

closest_size() {  # closest list value within 0.6 inch of the EDID diagonal
  [[ -n "$1" ]] || return 0
  printf '%s\n' "${SIZE_OPTIONS[@]}" | awk -v s="$1" '
    { d = $1 - s; if (d < 0) d = -d; if (best == "" || d < bd) { best = $1; bd = d } }
    END { if (best != "" && bd <= 0.6) print best }'
}

step7_manual_input() {
  banner "Step 7: Manual Input — Appearance & Grading"
  local _i _opt _c _sz _size_default _input _sel _custom _marks
  step7_cosmetic
  ask_manual OSD_CHECK "OSD buttons" "Open the on-screen menu and try each button" allow_skip
  while :; do
    ask _c "  Stand included? [y/n]: "
    case "${_c,,}" in
      y) STAND="Yes"; break ;;
      n) STAND="No"; break ;;
      *) warn "  Enter y or n." ;;
    esac
  done

  # Field names/format are the same contract as laptop_test.sh manual_input.
  while :; do
    ask WEIGHT_LBS "  $(printf '%b' "${BOLD}")Enter weight in lbs (e.g. 11.5): $(printf '%b' "${NC}")"
    [[ "$WEIGHT_LBS" =~ ^[0-9]+(\.[0-9]+)?$ ]] && awk -v w="$WEIGHT_LBS" 'BEGIN {exit !(w > 0)}' && break
    warn "  Weight must be a positive number (integer or decimal)."
  done

  while :; do
    ask GRADE "  $(printf '%b' "${BOLD}")Enter Grade [A/B/C/D]: $(printf '%b' "${NC}")"
    GRADE="${GRADE^^}"
    [[ "$GRADE" =~ ^[ABCD]$ ]] && break
    warn "  Grade must be one of A, B, C, D."
  done

  local CONDITION_LABELS=("Not categorized" "Damaged" "Used Poor" "Used Fair" "Used Good" \
                          "Used Very Good" "Used Excellent" "Certified Pre-Owned" "Unused" "New Open box")
  echo -e "  ${BOLD}Condition codes:${NC}"
  for _i in 0 1 2 3 4 5 6 7 8 9; do
    printf "    %d) C%d - %s\n" "$_i" "$_i" "${CONDITION_LABELS[$_i]}"
  done
  while :; do
    ask CONDITION "  $(printf '%b' "${BOLD}")Enter Condition [0-9, Enter=4 (C4-Used Good)]: $(printf '%b' "${NC}")"
    [[ -z "$CONDITION" ]] && { CONDITION="4"; break; }
    [[ "$CONDITION" =~ ^[0-9]$ ]] && break
    warn "  Condition must be a single digit 0-9 (or Enter for 4)."
  done
  CONDITION_FULL="C${CONDITION} - ${CONDITION_LABELS[$CONDITION]}"

  echo -e "  ${BOLD}Color options:${NC}"
  for _i in "${!COLOR_OPTIONS[@]}"; do
    printf "    %2d) %s\n" "$((_i + 1))" "${COLOR_OPTIONS[$_i]}"
  done
  COLOR=""
  while :; do
    ask _c "  $(printf '%b' "${BOLD}")Select color number [1-${#COLOR_OPTIONS[@]}, s=skip]: $(printf '%b' "${NC}")"
    [[ -z "$_c" || "${_c,,}" == "s" ]] && break
    if [[ "$_c" =~ ^[0-9]+$ ]] && (( _c >= 1 && _c <= ${#COLOR_OPTIONS[@]} )); then
      COLOR="${COLOR_OPTIONS[$((_c - 1))]}"; break
    fi
    warn "  Enter a list number 1-${#COLOR_OPTIONS[@]}, or s to skip."
  done

  _size_default=$(closest_size "$EDID_SIZE")
  echo -e "  ${BOLD}Screen size options (inch):${NC}"
  for _i in "${!SIZE_OPTIONS[@]}"; do
    printf "    %2d) %s inch\n" "$((_i + 1))" "${SIZE_OPTIONS[$_i]}"
  done
  [[ -n "$_size_default" ]] && ok "  EDID detected ${EDID_SIZE} inch — press Enter to accept $_size_default, or pick a number."
  SCREEN_SIZE_INCH=""
  while :; do
    ask _sz "  $(printf '%b' "${BOLD}")Select size number [1-${#SIZE_OPTIONS[@]}${_size_default:+, Enter=$_size_default}, s=skip]: $(printf '%b' "${NC}")"
    if [[ -z "$_sz" ]]; then
      [[ -n "$_size_default" ]] && { SCREEN_SIZE_INCH="$_size_default"; break; }
      warn "  Pick a number 1-${#SIZE_OPTIONS[@]}, or s to skip."
      continue
    fi
    [[ "${_sz,,}" == "s" ]] && break
    if [[ "$_sz" =~ ^[0-9]+$ ]] && (( _sz >= 1 && _sz <= ${#SIZE_OPTIONS[@]} )); then
      SCREEN_SIZE_INCH="${SIZE_OPTIONS[$((_sz - 1))]}"; break
    fi
    warn "  Enter a list number 1-${#SIZE_OPTIONS[@]}, or s to skip."
  done

  echo -e "  ${BOLD}Mark [Enter=none]:${NC}"
  for _i in "${!MARK_OPTIONS[@]}"; do
    printf "    %d) %s\n" "$((_i + 1))" "${MARK_OPTIONS[$_i]}"
  done
  echo "    0) Type custom text"
  MARK=""
  while :; do
    ask _input "  $(printf '%b' "${BOLD}")Select (multiple with comma, e.g. 1,3 or 0) [Enter=none]: $(printf '%b' "${NC}")"
    [[ -z "$_input" ]] && break
    IFS=',' read -ra _sel <<< "$_input"
    _marks=()
    for _i in "${_sel[@]}"; do
      _i="${_i// /}"
      if [[ "$_i" == "0" ]]; then
        ask _custom "  $(printf '%b' "${BOLD}")Enter custom mark text: $(printf '%b' "${NC}")"
        [[ -n "$_custom" ]] && _marks+=("$_custom")
      elif [[ "$_i" =~ ^[0-9]+$ ]] && (( _i >= 1 && _i <= ${#MARK_OPTIONS[@]} )); then
        _marks+=("${MARK_OPTIONS[$((_i - 1))]}")
      else
        warn "  Invalid choice: $_i (ignored)"
      fi
    done
    if [[ ${#_marks[@]} -gt 0 ]]; then
      MARK=$(IFS=';'; echo "${_marks[*]}")
      break
    fi
    warn "  No valid selection. Please try again or press Enter to skip."
  done

  GRADE_FULL="Grade $GRADE"
  if [[ -n "$SCREEN_SIZE_INCH" ]]; then SCREEN_SIZE_FULL="$SCREEN_SIZE_INCH inch"; else SCREEN_SIZE_FULL=""; fi
}

# ============================================================
# STEP 8: VERDICT, SAVE, UPLOAD
# ============================================================
# Keep the rules in step with monitorcenter/modules/monitor/verdict.py.
compute_verdict() {
  local _i _defects
  REASONS=()
  local _fail=0 _warn=0
  fail_reason() { REASONS+=("$1"); _fail=1; }
  warn_reason() { REASONS+=("$1"); _warn=1; }

  [[ "$NO_SIGNAL" == "true" ]] && fail_reason "no EDID / no signal"
  if [[ -n "$DEAD_PIXELS" ]] && (( DEAD_PIXELS > MAX_DEAD_PIXELS )); then
    fail_reason "dead pixels $DEAD_PIXELS > $MAX_DEAD_PIXELS"
  fi
  if [[ "$COSMETIC_CHECK" == "FAIL" ]]; then
    _defects=$(paste -sd, "$WORK/defects.txt" 2>/dev/null | sed 's/,/, /g')
    fail_reason "cosmetic FAIL${_defects:+: $_defects}"
  fi
  [[ "$BACKLIGHT_CHECK" == "FAIL" ]] && fail_reason "backlight FAIL"
  [[ "$RES_CHECK" == "FAIL" && "$NO_SIGNAL" != "true" ]] && fail_reason "resolution check FAIL"
  for _i in "${!PORT_TYPE[@]}"; do
    [[ "${PORT_RESULT[$_i]}" == "FAIL" ]] && fail_reason "port ${PORT_TYPE[$_i]} #${PORT_INDEX[$_i]} FAIL"
  done
  [[ "$ETH_STATUS" == "FAIL" ]] && fail_reason "ethernet FAIL"

  case "$SN_MATCH" in
    MATCH) ;;
    EDID_EMPTY) warn_reason "EDID has no serial number" ;;
    *) warn_reason "SN mismatch: label $LABEL_SN vs EDID ${EDID_SERIAL_STR:-$EDID_SERIAL_NUM}" ;;
  esac
  [[ "$STATION_LIMITED" == "true" ]] && \
    warn_reason "station limited: achieved $ACHIEVED_RES@$ACHIEVED_RATE, native $NATIVE_RES@$NATIVE_RATE"
  [[ "$OSD_CHECK" == "FAIL" ]] && warn_reason "OSD buttons FAIL"
  for _i in "${!PORT_TYPE[@]}"; do
    [[ "${PORT_RESULT[$_i]}" == "NOT_TESTED" ]] && warn_reason "port ${PORT_TYPE[$_i]} #${PORT_INDEX[$_i]} NOT_TESTED"
  done

  if (( _fail )); then OVERALL="FAIL"; elif (( _warn )); then OVERALL="WARN"; else OVERALL="PASS"; fi
}

build_report() {
  local _i
  : > "$WORK/ports.tsv"
  for _i in "${!PORT_TYPE[@]}"; do
    printf '%s\t%s\t%s\t%s\n' "${PORT_TYPE[$_i]}" "${PORT_INDEX[$_i]}" "${PORT_RESULT[$_i]}" "${PORT_CONN[$_i]}" >> "$WORK/ports.tsv"
  done
  : > "$WORK/reasons.txt"
  [[ ${#REASONS[@]} -gt 0 ]] && printf '%s\n' "${REASONS[@]}" > "$WORK/reasons.txt"

  local _safe_sn _stamp
  _safe_sn=$(printf '%s' "$LABEL_SN" | tr -c 'A-Za-z0-9._-' '_')
  _stamp=$(date +%Y%m%d-%H%M%S)
  REPORT_FILE="$REPORT_DIR/${_safe_sn}_${_stamp}.json"

  R_TEST_TIME="$TEST_TIME" R_OPERATOR="$OPERATOR_ID" R_DURATION="$((SECONDS - TEST_START))" \
  R_VERSION="$SCRIPT_VERSION" R_HOST="$(hostname)" R_GPU="$STATION_GPU" \
  R_LABEL_SN="$LABEL_SN" R_SERIAL_STR="$EDID_SERIAL_STR" R_SERIAL_NUM="$EDID_SERIAL_NUM" R_SN_MATCH="$SN_MATCH" \
  R_VENDOR="$EDID_VENDOR" R_PNP="$EDID_PNP" R_MODEL="$EDID_MODEL" R_PRODUCT="$EDID_PRODUCT" \
  R_WEEK="$EDID_WEEK" R_YEAR="$EDID_YEAR" R_CHECKSUM="$EDID_CHECKSUM_OK" R_FP="$EDID_FP" R_HEX="$EDID_HEX" \
  R_NATIVE="$NATIVE_RES" R_NATIVE_RATE="$NATIVE_RATE" R_ACHIEVED="$ACHIEVED_RES" R_ACHIEVED_RATE="$ACHIEVED_RATE" \
  R_RES_CHECK="$RES_CHECK" R_STATION_LIMITED="$STATION_LIMITED" R_NO_SIGNAL="$NO_SIGNAL" R_SIZE="$EDID_SIZE" \
  R_DEAD="$DEAD_PIXELS" R_MAX_DEAD="$MAX_DEAD_PIXELS" R_DEAD_CHECK="$DEAD_CHECK" R_BACKLIGHT="$BACKLIGHT_CHECK" \
  R_COSMETIC="$COSMETIC_CHECK" R_DEFECT_NOTE="$DEFECT_NOTE" R_OSD="$OSD_CHECK" R_STAND="$STAND" \
  R_WEIGHT="$WEIGHT_LBS" R_GRADE="$GRADE_FULL" R_CONDITION="$CONDITION_FULL" R_COLOR="$COLOR" \
  R_SIZE_FULL="$SCREEN_SIZE_FULL" R_MARK="$MARK" R_ETH_STATUS="$ETH_STATUS" R_ETH_DEV="$ETH_DEV" R_OVERALL="$OVERALL" \
    python3 -c "$PY_REPORT" "$REPORT_FILE" "$WORK"

  if [[ ! -s "$REPORT_FILE" ]]; then
    err "Could not write the report."
    return 1
  fi
  if command -v jq &>/dev/null; then
    if jq . "$REPORT_FILE" > "$WORK/report_pretty.json" 2>/dev/null; then
      cat "$WORK/report_pretty.json" > "$REPORT_FILE"
      ok "Report saved (validated): $REPORT_FILE"
    else
      err "JSON validation failed — saved raw version: $REPORT_FILE"
    fi
  else
    ok "Report saved: $REPORT_FILE"
  fi
}

big_result() {
  case "$1" in
    PASS) echo -e "${GREEN}${BOLD}"
      cat <<'ART'
    ██████   █████  ███████ ███████
    ██   ██ ██   ██ ██      ██
    ██████  ███████ ███████ ███████
    ██      ██   ██      ██      ██
    ██      ██   ██ ███████ ███████
ART
      ;;
    WARN) echo -e "${YELLOW}${BOLD}"
      cat <<'ART'
    ██     ██  █████  ██████  ███    ██
    ██     ██ ██   ██ ██   ██ ████   ██
    ██  █  ██ ███████ ██████  ██ ██  ██
    ██ ███ ██ ██   ██ ██   ██ ██  ██ ██
     ███ ███  ██   ██ ██   ██ ██   ████
ART
      ;;
    *) echo -e "${RED}${BOLD}"
      cat <<'ART'
    ███████  █████  ██ ██
    ██      ██   ██ ██ ██
    █████   ███████ ██ ██
    ██      ██   ██ ██ ██
    ██      ██   ██ ██ ███████
ART
      ;;
  esac
  echo -e "${NC}"
}

show_summary() {
  local _reason
  big_result "$OVERALL"
  printf "  %-14s %s\n" "Label SN:" "$LABEL_SN"
  printf "  %-14s %s\n" "Model:" "$EDID_VENDOR $EDID_MODEL"
  printf "  %-14s %s\n" "Dead pixels:" "${DEAD_PIXELS:-not tested}"
  if [[ ${#REASONS[@]} -gt 0 ]]; then
    echo -e "  ${BOLD}Reasons:${NC}"
    for _reason in "${REASONS[@]}"; do
      echo "    - $_reason"
    done
  fi
  echo ""
}

# ============================================================
# ONE MONITOR
# ============================================================
reset_unit_state() {
  LABEL_SN=""; SN_MATCH=""; DUT_DRM=""; XR_OUT=""; REPORT_FILE=""
  EDID_PNP=""; EDID_VENDOR=""; EDID_PRODUCT=""; EDID_SERIAL_NUM=""; EDID_SERIAL_STR=""; EDID_MODEL=""
  EDID_WEEK=""; EDID_YEAR=""; EDID_SIZE=""; EDID_NATIVE=""; EDID_REFRESH=""; EDID_CHECKSUM_OK=""; EDID_FP=""; EDID_HEX=""
  NATIVE_RES=""; NATIVE_RATE=""; ACHIEVED_RES=""; ACHIEVED_RATE=""; RES_CHECK="FAIL"
  STATION_LIMITED="false"; NO_SIGNAL="false"
  DEAD_PIXELS=""; DEAD_CHECK="NOT_TESTED"; BACKLIGHT_CHECK="NOT_TESTED"
  COSMETIC_CHECK=""; DEFECT_NOTE=""; OSD_CHECK=""; STAND=""
  WEIGHT_LBS=""; GRADE=""; GRADE_FULL=""; CONDITION=""; CONDITION_FULL=""; COLOR=""; SCREEN_SIZE_INCH=""; SCREEN_SIZE_FULL=""; MARK=""
  PORT_TYPE=(); PORT_INDEX=(); PORT_RESULT=(); PORT_CONN=()
  REASONS=()
  rm -f "$WORK"/shown.json "$WORK"/defects.txt "$WORK"/ports.tsv "$WORK"/reasons.txt "$WORK"/edid_decode.txt
}

# Returns 0 when a report was produced, 1 when this monitor was abandoned, 2 to quit.
test_one_monitor() {
  reset_unit_state
  local _rc
  TEST_START=$SECONDS
  TEST_TIME=$(date +%Y-%m-%dT%H:%M:%S%z)

  wait_for_dut
  _rc=$?
  (( _rc == 2 )) && return 2

  if (( _rc == 0 )); then
    banner "Step 2: Read EDID"
    local _edid="$DRM_ROOT/$DUT_DRM/edid"
    eval "$(edid_vars "$_edid")"
    command -v edid-decode &>/dev/null && edid-decode "$_edid" > "$WORK/edid_decode.txt" 2>&1
    ok "$EDID_VENDOR ${EDID_MODEL:-(no model name)} | ${EDID_NATIVE:-?} @ ${EDID_REFRESH:-?}Hz | ${EDID_SIZE:-?} inch | $EDID_YEAR"
    [[ "$EDID_CHECKSUM_OK" == "true" ]] || warn "EDID checksum is invalid."
    LAST_FP="$EDID_FP"
    step3_label_sn

    if step4_resolution; then
      step5_patterns || return 1
      step6_ports
    fi
  else
    # Nothing readable from the monitor: identity comes from the operator.
    banner "No EDID / No Signal — recording FAIL"
    NO_SIGNAL="true"
    SN_MATCH="EDID_EMPTY"
    scan_label_sn
    ask EDID_VENDOR "  Vendor (from the label): "
    ask EDID_MODEL "  Model (from the label): "
  fi
  if [[ "$NO_SIGNAL" == "true" ]]; then
    RES_CHECK="FAIL"
  fi

  step7_manual_input

  banner "Step 8: Result"
  compute_verdict
  build_report || return 1
  show_summary
  report_store "$REPORT_FILE"
  # Only blank the monitor if another screen remains; on a one-screen station this
  # would leave a black display that looks like the machine powered off.
  [[ -n "$XR_OUT" && -n "$(internal_output)" ]] && xrandr --output "$XR_OUT" --off 2>/dev/null
  return 0
}

# ============================================================
# MAIN
# ============================================================
check_session_type
install_dependencies
check_x_access
mkdir -p "$REPORT_DIR/sent" "$REPORT_DIR/pending"

banner "CearTrack Monitor Test v$SCRIPT_VERSION"
check_script_version
STATION_GPU=$(lspci 2>/dev/null | grep -iE 'vga|3d|display' | head -1 | cut -d: -f3- | sed 's/^ *//')
LAST_FP=""

OPERATOR_ID=""
while [[ -z "$OPERATOR_ID" ]]; do
  ask OPERATOR_ID "  $(printf '%b' "${BOLD}")Enter your operator ID: $(printf '%b' "${NC}")"
  [[ -z "$OPERATOR_ID" ]] && echo -e "  ${RED}Operator ID cannot be empty.${NC}"
done
ok "Operator: $OPERATOR_ID"

retry_pending

while true; do
  banner "Network"
  require_ethernet || break
  test_one_monitor
  (( $? == 2 )) && break
  retry_pending

  echo -e "\n  ${BOLD}Unplug this monitor and connect the next one.${NC}"
  ask _next "  Press Enter to continue, or q to quit: "
  [[ "${_next,,}" == "q" ]] && break
done

_left=$(pending_count)
if (( _left > 0 )); then
  warn "$_left report(s) are still in $REPORT_DIR/pending."
  warn "Connect the network and re-run this script BEFORE rebooting — a Live USB may lose them."
fi
echo -e "\n  ${GREEN}Done.${NC}"

ask _pw "  Power off this machine now? [y/N]: "
if [[ "${_pw,,}" == "y" ]]; then
  echo "  Powering off..."
  systemctl poweroff
else
  echo -e "  Staying on. Run ${BOLD}sudo poweroff${NC} when finished."
fi
