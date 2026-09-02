#!/bin/bash
# ============================================================
# gpu_test.sh — GPU Hardware Test & Report Generator v1.1
# Supports NVIDIA (gpu-burn + glmark2) and AMD (radeontop + glmark2)
# Includes auto-setup: installs drivers and tools on first run
# Usage: sudo bash gpu_test.sh
# ============================================================

# ── 1. Configuration ─────────────────────────────────────────
# Script directory — used to locate nvidia_legacy_db.conf alongside this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

UPLOAD_URL="http://192.168.30.18:80/gpu/api/upload"
# Single source of truth for the script version. Bump on every release;
# deploy_script.sh extracts it from here to generate server-side version.txt.
SCRIPT_VERSION="1.5.1"
LOG_DIR="/tmp/gpu_logs"
BURN_DURATION=120           # gpu-burn stress test duration (seconds)
AUTO_MODE=1                 # 1=unattended, 0=interactive
AUTO_POWEROFF=1             # PASS=60s auto poweroff; WARN/FAIL=no poweroff
SMI_INTERVAL=1              # thermal monitoring sample interval (seconds)
VKMARK_BASELINE_SCORE=0     # 0=disabled; >0=enable WARN if score < baseline*0.8

# ── 2. Colors & Output Functions ─────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

banner() { echo -e "\n${CYAN}${BOLD}=== $1 ===${NC}"; }
ok()     { echo -e "  ${GREEN}✓ $1${NC}"; }
warn()   { echo -e "  ${YELLOW}⚠ $1${NC}"; }
err()    { echo -e "  ${RED}✗ $1${NC}"; }
esc()    { printf '%s' "$1" | tr '\n\r\t' '   ' | sed 's/\\/\\\\/g; s/"/\\"/g'; }

# ── 3. Big Verdict Screen ─────────────────────────────────────
show_verdict_screen() {
    local result="$1"
    local COLS ROWS
    COLS=$(tput cols  2>/dev/null || echo 80)
    ROWS=$(tput lines 2>/dev/null || echo 24)

    # ── INFO_ONLY: no big ASCII, just a clean info screen ───────
    if [[ "$result" == "INFO_ONLY" ]]; then
        clear
        echo ""
        echo ""
        echo -e "  ${CYAN}${BOLD}============================================================${NC}"
        echo -e "  ${CYAN}${BOLD}     ℹ️   INFO ONLY — Low VRAM / Legacy Card${NC}"
        echo -e "  ${CYAN}${BOLD}============================================================${NC}"
        echo ""
        printf "  %-22s %s\n"   "GPU:"        "$GPU_NAME"
        printf "  %-22s %s MB (%s)\n" "VRAM:" "$GPU_VRAM_MB" "${GPU_VRAM_TYPE:-Unknown}"
        printf "  %-22s %s\n"   "Driver:"     "$GPU_DRIVER"
        printf "  %-22s %dm %02ds\n" "Test Duration:" \
            "$(( TOTAL_DURATION / 60 ))" "$(( TOTAL_DURATION % 60 ))"
        echo ""
        echo -e "  ${CYAN}Note:  Stress tests skipped — VRAM < 4096 MB${NC}"
        echo -e "  Card suitable for: office / display / light workloads"
        echo ""
        echo -e "  ${BOLD}L1 hardware info collected successfully.${NC}"
        echo -e "  Log: $JSON_FILE"
        echo ""
        if [[ "${UPLOAD_OK:-0}" -eq 1 ]]; then
            echo -e "  ${GREEN}✓ Upload: OK → MonitorCenter${NC}"
        else
            echo -e "  ${RED}✗ Upload: FAILED — report retained locally${NC}"
            echo -e "  ${YELLOW}  Manual: curl -X POST $UPLOAD_URL -H 'Content-Type: application/json' -d @\"$JSON_FILE\"${NC}"
        fi
        echo ""
        echo -e "  ${BOLD}Press  ENTER  →  shutdown now${NC}"
        echo -e "  ${BOLD}Press  Ctrl+C and ENTER →  cancel shutdown${NC}"
        echo ""
        echo -e "  ${CYAN}${BOLD}============================================================${NC}"
        echo ""
        return 0
    fi

    local COLOR
    case "$result" in
        PASS) COLOR="$GREEN"  ;;
        WARN) COLOR="$YELLOW" ;;
        FAIL) COLOR="$RED"    ;;
    esac

    # ── ASCII art (fallback when figlet not installed) ──────────
    local BIG_TEXT
    if command -v figlet &>/dev/null; then
        BIG_TEXT=$(figlet -f big -w "$COLS" "$result" 2>/dev/null)
    else
        case "$result" in
            PASS) BIG_TEXT=\
'██████╗  █████╗ ███████╗███████╗
██╔══██╗██╔══██╗██╔════╝██╔════╝
██████╔╝███████║███████╗███████╗
██╔═══╝ ██╔══██║╚════██║╚════██║
██║     ██║  ██║███████║███████║
╚═╝     ╚═╝  ╚═╝╚══════╝╚══════╝' ;;
            WARN) BIG_TEXT=\
'██╗    ██╗ █████╗ ██████╗ ███╗  ██╗
██║    ██║██╔══██╗██╔══██╗████╗ ██║
██║ █╗ ██║███████║██████╔╝██╔██╗██║
██║███╗██║██╔══██║██╔══██╗██║╚████║
╚███╔███╔╝██║  ██║██║  ██║██║ ╚███║
 ╚══╝╚══╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚══╝' ;;
            FAIL) BIG_TEXT=\
'███████╗ █████╗ ██╗██╗
██╔════╝██╔══██╗██║██║
█████╗  ███████║██║██║
██╔══╝  ██╔══██║██║██║
██║     ██║  ██║██║███████╗
╚═╝     ╚═╝  ╚═╝╚═╝╚══════╝' ;;
        esac
    fi

    local ART_LINES
    ART_LINES=$(printf '%s\n' "$BIG_TEXT" | wc -l)
    local HALF=$(( ROWS / 2 ))

    # Vertical: center the art block within the top half of the screen
    local TOP_PAD=$(( (HALF - ART_LINES) / 2 ))
    [[ "$TOP_PAD" -lt 1 ]] && TOP_PAD=1

    clear

    # Top padding
    local i
    for (( i=0; i<TOP_PAD; i++ )); do echo ""; done

    # Big colored text — each line left-padded to horizontal center
    while IFS= read -r line; do
        # Strip ANSI for length calc; unicode box chars are ~3 bytes but 1 col each
        local vis_len
        vis_len=$(echo "$line" | sed 's/\x1b\[[0-9;]*m//g' | wc -m)
        local lpad=$(( (COLS - vis_len) / 2 ))
        [[ "$lpad" -lt 0 ]] && lpad=0
        printf "%*s" "$lpad" ""
        echo -e "${COLOR}${BOLD}${line}${NC}"
    done <<< "$BIG_TEXT"

    # Fill remaining upper-half space
    local used=$(( TOP_PAD + ART_LINES ))
    local fill=$(( HALF - used - 1 ))
    [[ "$fill" -lt 1 ]] && fill=1
    for (( i=0; i<fill; i++ )); do echo ""; done

    # ── Divider ─────────────────────────────────────────────────
    printf '%*s\n' "$COLS" '' | tr ' ' '─'

    # ── Summary line ────────────────────────────────────────────
    echo ""
    case "$result" in
        PASS)
            printf "  GPU: %-30s  VRAM: %s MB   Temp: %s°C   glmark2: %s\n" \
                "$GPU_NAME" "$GPU_VRAM_MB" "$TEMP_MAX" "$VKMARK_SCORE"
            ;;
        WARN)
            echo -e "  ${YELLOW}⚠  Please review results before proceeding.${NC}"
            printf "  GPU: %-30s  VRAM: %s MB   Temp: %s°C   glmark2: %s\n" \
                "$GPU_NAME" "$GPU_VRAM_MB" "$TEMP_MAX" "$VKMARK_SCORE"
            ;;
        FAIL)
            echo -e "  ${RED}✗  This card should NOT be sold.  VRAM Errors: ${VRAM_ERRORS}   Temp: ${TEMP_MAX}°C${NC}"
            printf "  GPU: %-30s  Log: %s\n" "$GPU_NAME" "$JSON_FILE"
            ;;
    esac
    printf "  Duration: %dm %02ds\n" \
        "$(( TOTAL_DURATION / 60 ))" "$(( TOTAL_DURATION % 60 ))"

    echo ""
    echo -e "  ${BOLD}Press  ENTER  →  shutdown now${NC}"
    echo -e "  ${BOLD}Press  Ctrl+C →  cancel shutdown${NC}"
    echo ""
}

# ── 3b. GPU Fault Warning Screen ──────────────────────────────
# Big, prominent RED screen telling the operator the card is faulty and
# should be replaced. Display-only: the caller decides whether to continue
# or abort. $1 = matched kernel error lines (already truncated) to show.
show_gpu_fault_screen() {
    local err_lines="$1"
    local COLS
    COLS=$(tput cols 2>/dev/null || echo 80)

    clear
    echo ""
    echo ""
    local BIG_TEXT='\
 ██████╗ ██████╗ ██╗   ██╗    ███████╗ █████╗ ██╗   ██╗██╗  ████████╗
██╔════╝ ██╔══██╗██║   ██║    ██╔════╝██╔══██╗██║   ██║██║  ╚══██╔══╝
██║  ███╗██████╔╝██║   ██║    █████╗  ███████║██║   ██║██║     ██║
██║   ██║██╔═══╝ ██║   ██║    ██╔══╝  ██╔══██║██║   ██║██║     ██║
╚██████╔╝██║     ╚██████╔╝    ██║     ██║  ██║╚██████╔╝███████╗██║
 ╚═════╝ ╚═╝      ╚═════╝     ╚═╝     ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝'

    # Center each line horizontally
    while IFS= read -r line; do
        local vis_len lpad
        vis_len=$(echo "$line" | sed 's/\x1b\[[0-9;]*m//g' | wc -m)
        lpad=$(( (COLS - vis_len) / 2 ))
        [[ "$lpad" -lt 0 ]] && lpad=0
        printf "%*s" "$lpad" ""
        echo -e "${RED}${BOLD}${line}${NC}"
    done <<< "$BIG_TEXT"

    echo ""
    printf '%*s\n' "$COLS" '' | tr ' ' '─'
    echo ""
    echo -e "  ${RED}${BOLD}⚠  GPU HARDWARE ERROR DETECTED AT BOOT — REPLACE THIS CARD${NC}"
    echo ""
    echo -e "  ${YELLOW}The graphics card reported fatal errors in the kernel log.${NC}"
    echo -e "  ${YELLOW}This usually means the card is defective. Recommend replacing it.${NC}"
    echo ""
    if [[ -n "$err_lines" ]]; then
        echo -e "  ${BOLD}Kernel error signals:${NC}"
        echo "$err_lines" | while IFS= read -r _l; do
            [[ -n "$_l" ]] && echo -e "    ${RED}${_l}${NC}"
        done
        echo ""
    fi
    printf '%*s\n' "$COLS" '' | tr ' ' '─'
}

# ── 3c. Fatal GPU Kernel-Error Detection ──────────────────────
# Narrow, high-confidence scan of dmesg for signals that indicate a
# defective GPU (distinct from the broad Step 6 report scan). Prints the
# matched lines (truncated to 8) to stdout; returns 0 if any found, else 1.
detect_gpu_fatal_dmesg() {
    # SAFETY GUARD — never flag a card as defective when the real issue is a
    # DRIVER mismatch (too-new card, legacy card, or "not supported by ...
    # driver release"). Those are software/version problems, NOT bad hardware.
    # This prevents false "REPLACE GPU" prompts on perfectly good cards.
    if dmesg 2>/dev/null | grep -qi \
        'not supported by the\|supported through the NVIDIA\|NVRM.*legacy\|NVRM.*will ignore'; then
        return 1
    fi

    # High-confidence hardware-death signals only (kept deliberately narrow).
    local fatal_re
    fatal_re='GPU has fallen off the bus|fell off the bus|RmInitAdapter failed|rm_init_adapter failed|'\
'GPU board failed to initialize|amdgpu.*GPU reset|ring gfx.*timeout|amdgpu.*[Ff]atal error|'\
'PCIe Bus Error:[[:space:]]*severity=Fatal'

    local lines
    lines=$(dmesg 2>/dev/null | grep -iE "$fatal_re" \
        | grep -v 'nvidia-gpu.*i2c timeout' \
        | grep -v 'nvidia-gpu.*e0000000' \
        | head -8 || true)

    if [[ -n "$lines" ]]; then
        printf '%s\n' "$lines"
        return 0
    fi
    return 1
}

# ── 3d. NVIDIA Driver Selection (supports new cards) ──────────
# dmesg shows this when the GPU is NEWER than the installed driver:
#   "is not supported by the NVIDIA <ver> driver release"
# This is NOT a hardware fault — the card just needs a newer driver.
nvidia_driver_too_old() {
    dmesg 2>/dev/null | grep -qi 'not supported by the NVIDIA.*driver\|is not supported by the'
}

# Echo the recommended NVIDIA driver branch number for the installed card
# (e.g. "570"), or nothing if ubuntu-drivers can't determine one.
# Used to tell modern cards (>=535) apart from old cards (Kepler/Fermi
# needing 470/390), which we only collect info on — never stress-test.
nvidia_recommended_version() {
    apt-get install -y -qq ubuntu-drivers-common 2>/dev/null
    ubuntu-drivers devices 2>/dev/null \
        | awk '/recommended/{for(i=1;i<=NF;i++) if($i ~ /^nvidia-driver-[0-9]+/) print $i}' \
        | grep -oE '[0-9]+' | head -1
}

# Install the driver that MATCHES this card instead of a hardcoded version.
# ubuntu-drivers picks the correct version AND variant (e.g. -open for
# Blackwell/RTX-50). Falls back to autoinstall, then to nvidia-driver-535.
install_best_nvidia_driver() {
    apt-get install -y -qq ubuntu-drivers-common 2>/dev/null

    local rec
    rec=$(ubuntu-drivers devices 2>/dev/null \
        | awk '/recommended/{for(i=1;i<=NF;i++) if($i ~ /^nvidia-driver-/) print $i}' \
        | head -1)

    if [[ -n "$rec" ]]; then
        ok "Recommended driver for this GPU: $rec"
        if apt-get install -y -qq "$rec" 2>/dev/null; then
            return 0
        fi
        warn "Install of $rec failed — trying ubuntu-drivers autoinstall."
    fi

    if command -v ubuntu-drivers &>/dev/null; then
        ok "Installing best-match driver via ubuntu-drivers autoinstall..."
        ubuntu-drivers autoinstall 2>/dev/null && return 0
    fi

    warn "ubuntu-drivers unavailable — falling back to nvidia-driver-535."
    apt-get install -y -qq nvidia-driver-535 2>/dev/null
}

# ── 3. Safe Exit ──────────────────────────────────────────────
safe_exit() {
    local code=${1:-0}
    echo -e "${BOLD}Exiting with code $code${NC}"
    exit "$code"
}

# ── 3e. Reboot-and-Resume (operator-friendly driver-install reboot) ──
# After a fresh driver install the kernel module often can't load live and a
# reboot is required. Instead of a cryptic message, show a clear bilingual
# screen and — on ENTER — auto-reboot AND auto-resume the test afterwards via
# a one-shot systemd unit (self-removing, so it only ever runs once).
RESUME_UNIT="/etc/systemd/system/gpu-resume.service"

# Remove any leftover one-shot resume unit (called at startup so a normal run,
# or the resumed run itself, never leaves it lingering / double-firing).
clear_resume_unit() {
    if [[ -f "$RESUME_UNIT" ]]; then
        systemctl disable gpu-resume.service 2>/dev/null || true
        rm -f "$RESUME_UNIT"
        systemctl daemon-reload 2>/dev/null || true
    fi
}

# Install the one-shot unit that re-runs THIS script on tty1 after reboot.
schedule_resume_after_reboot() {
    local target="$SCRIPT_DIR/gpu_test.sh"
    [[ -f "$target" ]] || target="$0"

    cat > "$RESUME_UNIT" <<EOF
[Unit]
Description=Resume GPU test after NVIDIA driver install (one-shot)
After=multi-user.target

[Service]
Type=idle
# Self-remove first so this can never run twice, then resume the test on tty1.
ExecStart=/bin/bash -c 'systemctl disable gpu-resume.service; rm -f $RESUME_UNIT; systemctl daemon-reload; chvt 1; exec bash "$target"'
StandardInput=tty
StandardOutput=tty
StandardError=tty
TTYPath=/dev/tty1
TTYReset=yes
TTYVHangup=yes

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload 2>/dev/null || true
    systemctl enable gpu-resume.service 2>/dev/null || true
}

# Friendly, NON-alarming (cyan/green) full-screen "restart needed" notice.
show_reboot_screen() {
    local COLS
    COLS=$(tput cols 2>/dev/null || echo 80)
    clear
    echo ""
    echo ""
    local BIG='\
██████╗ ███████╗███████╗████████╗ █████╗ ██████╗ ████████╗
██╔══██╗██╔════╝██╔════╝╚══██╔══╝██╔══██╗██╔══██╗╚══██╔══╝
██████╔╝█████╗  ███████╗   ██║   ███████║██████╔╝   ██║
██╔══██╗██╔══╝  ╚════██║   ██║   ██╔══██║██╔══██╗   ██║
██║  ██║███████╗███████║   ██║   ██║  ██║██║  ██║   ██║
╚═╝  ╚═╝╚══════╝╚══════╝   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝'
    while IFS= read -r line; do
        local vis_len lpad
        vis_len=$(echo "$line" | sed 's/\x1b\[[0-9;]*m//g' | wc -m)
        lpad=$(( (COLS - vis_len) / 2 )); [[ "$lpad" -lt 0 ]] && lpad=0
        printf "%*s" "$lpad" ""
        echo -e "${CYAN}${BOLD}${line}${NC}"
    done <<< "$BIG"
    echo ""
    printf '%*s\n' "$COLS" '' | tr ' ' '─'
    echo ""
    echo -e "  ${GREEN}${BOLD}✓ GPU driver installed successfully.${NC}"
    echo ""
    echo -e "  ${BOLD}A reboot is required to activate the driver.${NC}"
    echo -e "  ${BOLD}The test will resume AUTOMATICALLY after restart — no action needed.${NC}"
    echo ""
    echo -e "  ${GREEN}${BOLD}>>> Press ENTER to reboot and continue${NC}"
    echo -e "  ${YELLOW}    (Press Ctrl+C to cancel)${NC}"
    echo ""
    printf '%*s\n' "$COLS" '' | tr ' ' '─'
}

# Show the screen, wait for ENTER → schedule resume + reboot; Ctrl+C cancels.
reboot_and_resume() {
    show_reboot_screen
    trap '
        echo ""
        echo -e "  ${YELLOW}Reboot cancelled. Reboot manually, then re-run the test.${NC}"
        trap - INT
        safe_exit 2
    ' INT
    read -r -s
    trap - INT
    schedule_resume_after_reboot
    echo ""
    echo -e "  ${BOLD}Rebooting...${NC}"
    sleep 2
    reboot
    safe_exit 2   # in case reboot is deferred
}

# ── 4. Root Check ─────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    err "Please run with sudo: sudo bash gpu_test.sh"
    exit 1
fi

# Clean up any one-shot resume unit from a previous driver-install reboot.
# (If we got here, the resume already fired or this is a fresh manual run.)
clear_resume_unit

# ── 5. Log Dir + Timestamp + File Paths ──────────────────────
mkdir -p "$LOG_DIR"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
TEST_HOSTNAME=$(hostname -s 2>/dev/null || hostname 2>/dev/null || echo "unknown")
THERMAL_LOG="$LOG_DIR/thermal_${TIMESTAMP}.log"
GPUBURN_LOG="$LOG_DIR/gpuburn_${TIMESTAMP}.log"
RADEONTOP_LOG="$LOG_DIR/radeontop_${TIMESTAMP}.log"
VKMARK_LOG="$LOG_DIR/vkmark_${TIMESTAMP}.log"
JSON_FILE=""
SMI_PID=""

# ── 6. Trap: kill background processes on exit ───────────────
cleanup() {
    if [[ -n "$SMI_PID" ]] && kill -0 "$SMI_PID" 2>/dev/null; then
        kill "$SMI_PID" 2>/dev/null
        wait "$SMI_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

clear
echo -e "${BOLD}>>> GPU Test Pipeline v1.1 Starting...${NC}"
echo "Kernel: $(uname -r) | Timestamp: $TIMESTAMP"
echo ""

# ============================================================
# Manual Input — Operator ID + Appearance & Grading (Cyclelution export)
# ============================================================
# Collected UP FRONT (before the SN scan / any test) so the operator enters all
# data in one pass, then the long automated test + driver install can run
# unattended. Field names/format are a fixed contract shared with laptop_test.sh
# — the same CearTrack normalization engine consumes both, so grade/condition
# are stored here as full Cyclelution labels (not raw codes), and multi-select
# marks are joined with ';' to match laptop exactly.
# NOTE: this only collects data; it does NOT touch the existing test pipeline.
banner "Operator & Manual Input"

# (0) Operator ID — required, non-empty. Preserve leading zeros (store string).
#     Barcode badge scanner = keyboard input + Enter, no special handling needed.
#OPERATOR_ID=""
#while [[ -z "$OPERATOR_ID" ]]; do
#    read -rp "$(echo -e "  ${BOLD}Enter Operator ID (e.g. 0216): ${NC}")" OPERATOR_ID </dev/tty
#    OPERATOR_ID=$(echo "$OPERATOR_ID" | xargs)
#    [[ -z "$OPERATOR_ID" ]] && err "Operator ID cannot be empty."
#done
#ok "Operator: $OPERATOR_ID"
#echo ""

# (1) Weight — required positive number (lbs). Use awk for >0 test because bc is
#     not installed at this early stage (Phase 0 installs tools later).
WEIGHT_LBS=""
while :; do
    read -rp "$(echo -e "  ${BOLD}Enter weight in lbs (e.g. 1.0): ${NC}")" WEIGHT_LBS </dev/tty
    WEIGHT_LBS=$(echo "$WEIGHT_LBS" | xargs)
    if [[ "$WEIGHT_LBS" =~ ^[0-9]+(\.[0-9]+)?$ ]] && awk "BEGIN{exit !(${WEIGHT_LBS}>0)}"; then
        break
    fi
    warn "Weight must be a positive number (integer or decimal)."
done

# (2) Grade — required A/B/C/D → stored as full "Grade X"
GRADE=""
while :; do
    read -rp "$(echo -e "  ${BOLD}Enter Grade [A/B/C/D]: ${NC}")" GRADE </dev/tty
    GRADE=$(echo "$GRADE" | xargs | tr '[:lower:]' '[:upper:]')
    [[ "$GRADE" =~ ^[ABCD]$ ]] && break
    warn "Grade must be one of A, B, C, D."
done

# (3) Condition — 0-9 (maps to Cyclelution C0-C9), default 4 → stored as full label
CONDITION_LABELS=("Not categorized" "Damaged" "Used Poor" "Used Fair" "Used Good" \
                  "Used Very Good" "Used Excellent" "Certified Pre-Owned" "Unused" "New Open box")
echo -e "  ${BOLD}Condition codes:${NC}"
for _i in 0 1 2 3 4 5 6 7 8 9; do
    printf "    %d) C%d - %s\n" "$_i" "$_i" "${CONDITION_LABELS[$_i]}"
done
CONDITION=""
while :; do
    read -rp "$(echo -e "  ${BOLD}Enter Condition [0-9, Enter=4 (C4-Used Good)]: ${NC}")" CONDITION </dev/tty
    CONDITION=$(echo "$CONDITION" | xargs)
    [[ -z "$CONDITION" ]] && { CONDITION="4"; break; }
    [[ "$CONDITION" =~ ^[0-9]$ ]] && break
    warn "Condition must be a single digit 0-9 (or Enter for 4)."
done

# (4) Color — numbered menu (matches Cyclelution color dropdown), optional (Enter to skip)
COLOR_OPTIONS=("Black" "Blue" "Gold" "Gray" "Green" "Purple" "Red" "Silver" "White" "Yellow")
echo -e "  ${BOLD}Color [Enter=none]:${NC}"
_i=1
for _opt in "${COLOR_OPTIONS[@]}"; do
    printf "    %d) %s\n" "$_i" "$_opt"
    _i=$((_i + 1))
done
COLOR=""
while :; do
    read -rp "$(echo -e "  ${BOLD}Select Color [1-${#COLOR_OPTIONS[@]}, Enter=none]: ${NC}")" _cl_input </dev/tty
    _cl_input=$(echo "$_cl_input" | xargs)
    [[ -z "$_cl_input" ]] && { COLOR=""; break; }
    if [[ "$_cl_input" =~ ^[0-9]+$ ]] && (( _cl_input >= 1 && _cl_input <= ${#COLOR_OPTIONS[@]} )); then
        COLOR="${COLOR_OPTIONS[$((_cl_input - 1))]}"
        break
    fi
    warn "Invalid choice: $_cl_input (must be 1-${#COLOR_OPTIONS[@]}, or Enter to skip)."
done
echo -e "  Selected Color: ${COLOR:-<none>}"

# (5) Mark — numbered menu + custom text + multi-select + skip. GPU-specific items
#     (NOT laptop's keyboard/screen items). Multi-select joined with ';' to match
#     laptop_test.sh so the shared normalization engine handles one format.
MARK_OPTIONS=(
    "Minor scratches/blemishes"
    "Bent bracket"
    "Missing screws"
    "Fan noise"
    "Dusty"
    "Bent PCIe connector"
)
echo -e "  ${BOLD}Mark [Enter=none]:${NC}"
_i=1
for _opt in "${MARK_OPTIONS[@]}"; do
    printf "    %d) %s\n" "$_i" "$_opt"
    _i=$((_i + 1))
done
echo "    0) Type custom text"
MARK=""
while :; do
    read -rp "$(echo -e "  ${BOLD}Select (multiple with comma, e.g. 1,3 or 0) [Enter=none]: ${NC}")" _mk_input </dev/tty
    _mk_input=$(echo "$_mk_input" | xargs)
    if [[ -z "$_mk_input" ]]; then MARK=""; break; fi
    IFS=',' read -ra _mk_sel <<< "$_mk_input"
    _mk_marks=()
    for _sel in "${_mk_sel[@]}"; do
        _sel=$(echo "$_sel" | xargs)
        if [[ "$_sel" == "0" ]]; then
            read -rp "$(echo -e "  ${BOLD}Enter custom mark text: ${NC}")" _custom </dev/tty
            _custom=$(echo "$_custom" | xargs)
            [[ -n "$_custom" ]] && _mk_marks+=("$_custom")
        elif [[ "$_sel" =~ ^[0-9]+$ ]] && (( _sel >= 1 && _sel <= ${#MARK_OPTIONS[@]} )); then
            _mk_marks+=("${MARK_OPTIONS[$((_sel - 1))]}")
        else
            warn "Invalid choice: $_sel (ignored)"
        fi
    done
    if [[ ${#_mk_marks[@]} -gt 0 ]]; then
        MARK=$(IFS=';'; echo "${_mk_marks[*]}")
        break
    else
        warn "No valid selection. Try again or press Enter to skip."
    fi
done
echo -e "  Selected Mark: ${MARK:-<none>}"

# Derived full-label strings for the JSON (match Cyclelution dropdowns):
#   grade "B"      -> "Grade B"
#   condition "4"  -> "C4 - Used Good"
GRADE_FULL="Grade $GRADE"
CONDITION_FULL="C${CONDITION} - ${CONDITION_LABELS[$CONDITION]}"
echo ""

# ── Card Label SN (barcode scanner input) ─────────────────────
# Scan the label on the back of the GPU card before tests begin.
# Barcode scanner acts as keyboard — scan auto-fills and presses Enter.
# Press Enter to skip (file will use GPU Name + Timestamp instead).
CARD_LABEL=""
echo -e "${CYAN}${BOLD}Scan card label SN then press Enter (or press Enter to skip):${NC}"
read -t 300 -r CARD_LABEL || true
CARD_LABEL=$(echo "$CARD_LABEL" | tr -cd 'A-Za-z0-9_.-' | cut -c1-50)
if [[ -n "$CARD_LABEL" ]]; then
    echo -e "  ${GREEN}✓ Card label: $CARD_LABEL${NC}"
else
    echo -e "  ${YELLOW}⚠ No label scanned — will use Name + Timestamp${NC}"
fi
echo ""

# ============================================================
# Phase 0 — Auto Setup (install drivers + tools)
# ============================================================
banner "Step 0: Environment Setup"

# Detect vendor first (needed to decide what to install)
LSPCI_GPU=$(lspci | grep -iE 'vga|3d|display')
if echo "$LSPCI_GPU" | grep -qi 'nvidia'; then
    VENDOR="NVIDIA"
elif echo "$LSPCI_GPU" | grep -qi 'amd\|ati'; then
    VENDOR="AMD"
else
    err "No supported GPU detected (NVIDIA/AMD)."
    echo "$LSPCI_GPU"
    safe_exit 2
fi
ok "Detected vendor: $VENDOR"

KVER=$(uname -r)

# ── Install base tools (always, before vendor-specific setup) ─
ok "Installing base tools (jq, curl, dmidecode, pciutils, glmark2)..."
apt-get update -qq 2>/dev/null
apt-get install -y -qq \
    jq curl wget dmidecode pciutils \
    glmark2 x11-utils 2>/dev/null
ok "Base tools ready."

# ── NVIDIA Setup ──────────────────────────────────────────────
if [[ "$VENDOR" == "NVIDIA" ]]; then

    # Detect Ubuntu version
    UBUNTU_VER=$(lsb_release -rs 2>/dev/null | tr -d '.')
    case "$UBUNTU_VER" in
        2004) CUDA_DISTRO="ubuntu2004" ;;
        2204) CUDA_DISTRO="ubuntu2204" ;;
        2404) CUDA_DISTRO="ubuntu2404" ;;
        *)    CUDA_DISTRO="ubuntu2204" ;;
    esac

    # ── Step A: Install driver from Ubuntu repo ONLY ──────────
    # Remove any CUDA repo first — it introduces packages requiring libc6>=2.38
    # which is Ubuntu 24.04 only and breaks driver install on 22.04.
    if ! nvidia-smi &>/dev/null; then
        ok "Removing CUDA repo to avoid libc6 conflicts..."
        rm -f /etc/apt/sources.list.d/cuda-*.list \
              /etc/apt/sources.list.d/nvidia-*.list \
              /usr/share/keyrings/cuda-archive-keyring.gpg 2>/dev/null || true
        apt-get update -qq 2>/dev/null

        ok "Installing NVIDIA driver for kernel $KVER (Ubuntu repo)..."

        # Blacklist nouveau first
        echo "blacklist nouveau"         > /etc/modprobe.d/blacklist-nouveau.conf
        echo "options nouveau modeset=0" >> /etc/modprobe.d/blacklist-nouveau.conf

        # Unload nouveau if running
        if lsmod | grep -q nouveau; then
            systemctl stop display-manager gdm3 lightdm 2>/dev/null || true
            modprobe -r nouveau 2>/dev/null || true
            sleep 1
        fi

        # Old-card policy: if the only driver that supports this GPU is a
        # legacy branch (< 535, i.e. Kepler→470 / Fermi→390), we do NOT install
        # it. Per policy, old cards are INFO_ONLY — collect info, never test.
        _rec_ver=$(nvidia_recommended_version)
        if [[ -n "$_rec_ver" && "$_rec_ver" -lt 535 ]] 2>/dev/null; then
            warn "Older GPU (only legacy driver ${_rec_ver}.x supports it) — INFO_ONLY mode."
            warn "Collecting L1 hardware info via lspci only; no stress test."
            LEGACY_CARD=1
        else
            # Install the driver MATCHED to this card (not hardcoded — supports new cards)
            install_best_nvidia_driver
        fi

        # Try loading without reboot (skip when we deliberately stayed legacy)
        if [[ "${LEGACY_CARD:-0}" -eq 1 ]]; then
            : # old card — handled above, fall through to legacy/INFO_ONLY
        elif modprobe nvidia 2>/dev/null && nvidia-smi &>/dev/null; then
            ok "NVIDIA driver loaded."
        elif nvidia_driver_too_old; then
            # GPU is NEWER than the driver in the distro repo. Add the
            # graphics-drivers PPA (newer releases) and retry once.
            warn "This GPU is newer than the distro driver — adding graphics-drivers PPA..."
            apt-get install -y -qq software-properties-common 2>/dev/null
            add-apt-repository -y ppa:graphics-drivers/ppa 2>/dev/null
            apt-get update -qq 2>/dev/null
            install_best_nvidia_driver
            modprobe nvidia 2>/dev/null
            if nvidia-smi &>/dev/null; then
                ok "NVIDIA driver loaded (from graphics-drivers PPA)."
            elif nvidia_driver_too_old; then
                err "This GPU is too new for any available NVIDIA driver."
                err "GPU PCI ID: $(lspci -nn | grep -iE 'vga|3d' | grep -i nvidia | head -1)"
                err "This is NOT a bad card — it needs a newer driver / newer Ubuntu."
                err "On a networked machine run: sudo ubuntu-drivers autoinstall"
                safe_exit 2
            else
                # Driver installed OK, just needs a reboot — friendly auto-resume.
                reboot_and_resume
            fi
        elif dmesg 2>/dev/null | grep -qi 'NVRM.*legacy\|NVRM.*will ignore\|supported through the NVIDIA'; then
            # Driver probed but explicitly rejected this GPU (legacy card — e.g. K2000 needs 470.xx)
            warn "Driver does not support this GPU (legacy card detected via dmesg)."
            warn "Continuing in INFO_ONLY mode — L1 hardware info via lspci only."
            LEGACY_CARD=1
        else
            # nvidia-smi still failing. Distinguish a defective card (fatal
            # kernel errors at boot) from a genuine reboot-needed situation.
            _fatal_lines=$(detect_gpu_fatal_dmesg) && _fatal_hit=1 || _fatal_hit=0
            if [[ "$_fatal_hit" -eq 1 ]]; then
                show_gpu_fault_screen "$_fatal_lines"
                echo ""
                echo -e "  ${BOLD}This card cannot be tested. Power off and REPLACE it.${NC}"
                echo ""
                safe_exit 2
            else
                # Driver installed OK, just needs a reboot — friendly auto-resume.
                reboot_and_resume
            fi
        fi
    else
        ok "NVIDIA driver already loaded."
    fi

    # ── Step B: Add CUDA repo AFTER driver is confirmed working ─
    # Skip entirely for legacy cards — gpu-burn / libcublas won't work without nvidia-smi
    if [[ "${LEGACY_CARD:-0}" -eq 1 ]]; then
        warn "Legacy card — skipping CUDA repo and gpu-burn install."
    fi
    if [[ "${LEGACY_CARD:-0}" -eq 0 ]]; then  # begin non-legacy NVIDIA block
    CUDA_LIST="/etc/apt/sources.list.d/cuda-${CUDA_DISTRO}-x86_64.list"
    if [[ ! -f "$CUDA_LIST" ]]; then
        ok "Adding CUDA repo ($CUDA_DISTRO) for gpu-burn / libcublas..."
        CUDA_KEY_DEB="/tmp/cuda-keyring_1.1-1_all.deb"
        wget -q "https://developer.download.nvidia.com/compute/cuda/repos/${CUDA_DISTRO}/x86_64/cuda-keyring_1.1-1_all.deb" \
            -O "$CUDA_KEY_DEB" && dpkg -i "$CUDA_KEY_DEB" >/dev/null 2>&1
        rm -f "$CUDA_KEY_DEB"
        apt-get update -qq 2>/dev/null
    fi

    # Install libcublas if missing
    if ! ldconfig -p 2>/dev/null | grep -q libcublas; then
        ok "Installing libcublas..."
        apt-get install -y -qq libcublas-12-4 2>/dev/null || \
        apt-get install -y -qq libcublas-12-5 2>/dev/null || true
    else
        ok "libcublas already installed."
    fi

    # Install gpu-burn if missing
    if ! command -v gpu-burn &>/dev/null; then
        ok "Installing gpu-burn..."
        apt-get install -y -qq gpu-burn 2>/dev/null
    else
        ok "gpu-burn already installed."
    fi

    fi  # end non-legacy NVIDIA block

# ── AMD Setup ─────────────────────────────────────────────────
elif [[ "$VENDOR" == "AMD" ]]; then

    # Add ROCm repo if missing
    if [[ ! -f /etc/apt/sources.list.d/rocm.list ]]; then
        ok "Adding AMD ROCm repo..."
        mkdir -p /etc/apt/keyrings
        wget -q https://repo.radeon.com/rocm/rocm.gpg.key -O - | \
            gpg --dearmor | tee /etc/apt/keyrings/rocm.gpg > /dev/null
        echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/rocm.gpg] \
https://repo.radeon.com/rocm/apt/latest noble main" \
            | tee /etc/apt/sources.list.d/rocm.list > /dev/null
        apt-get update -qq
    fi

    # Install rocm-smi if missing
    if ! command -v rocm-smi &>/dev/null; then
        ok "Installing rocm-smi-lib..."
        apt-get install -y -qq rocm-smi-lib 2>/dev/null
        ln -sf /opt/rocm/bin/rocm-smi /usr/local/bin/rocm-smi
    else
        ok "rocm-smi already installed."
    fi

    # Install radeontop if missing
    if ! command -v radeontop &>/dev/null; then
        ok "Installing radeontop..."
        apt-get install -y -qq radeontop 2>/dev/null
    else
        ok "radeontop already installed."
    fi

fi

# ── Verify all tools ready ────────────────────────────────────
MISSING_TOOLS=0
check_tool() {
    if ! command -v "$1" &>/dev/null; then
        err "Missing: $1"
        MISSING_TOOLS=1
    fi
}

check_tool lspci
check_tool jq
check_tool curl
check_tool dmidecode
check_tool glmark2

if [[ "$VENDOR" == "NVIDIA" ]]; then
    if [[ "${LEGACY_CARD:-0}" -eq 0 ]]; then
        check_tool nvidia-smi
        check_tool gpu-burn
    fi
elif [[ "$VENDOR" == "AMD" ]]; then
    check_tool rocm-smi
    check_tool radeontop
fi

if [[ "$MISSING_TOOLS" -eq 1 ]]; then
    err "Setup incomplete — missing tools above. Aborting."
    safe_exit 2
fi
ok "All tools ready."

# Warn if multiple GPUs found
GPU_COUNT=$(echo "$LSPCI_GPU" | grep -vc '^$' || true)
if [[ "$GPU_COUNT" -gt 1 ]]; then
    warn "Multiple GPUs detected ($GPU_COUNT). Testing first GPU only (v1.1 limitation)."
fi

# ============================================================
# Phase 2 — L1 Hardware Identification
# ============================================================
TEST_START_EPOCH=$(date +%s)
banner "Step 1: L1 Hardware Identification"

# Get first GPU PCI address
GPU_PCI_ADDR=$(lspci | grep -iE 'vga|3d|display' | head -1 | awk '{print $1}')

# T14 — device_id from lspci -n
DEVICE_ID_RAW=$(lspci -n -s "$GPU_PCI_ADDR" 2>/dev/null | awk '{print $3}' | tr '[:lower:]' '[:upper:]')
GPU_DEVICE_ID="${DEVICE_ID_RAW:-Unknown}"

# subvendor from lspci -v
GPU_SUBVENDOR=$(lspci -v -s "$GPU_PCI_ADDR" 2>/dev/null \
    | grep -i 'subsystem' | head -1 \
    | sed 's/.*Subsystem: //' | sed 's/[[:space:]]*$//')
GPU_SUBVENDOR="${GPU_SUBVENDOR:-Unknown}"

# PCIe link info from lspci -vv (needs two v's for LnkSta/LnkCap)
LNKSTA_LINE=$(lspci -vv -s "$GPU_PCI_ADDR" 2>/dev/null | grep 'LnkSta:')
LNKCAP_LINE=$(lspci -vv -s "$GPU_PCI_ADDR" 2>/dev/null | grep 'LnkCap:')

PCIE_SPEED_LSPCI=$(echo "$LNKSTA_LINE" | grep -oP 'Speed [0-9.]+GT/s' | grep -oP '[0-9.]+' | head -1)
PCIE_WIDTH_CUR_LSPCI=$(echo "$LNKSTA_LINE" | grep -oP 'Width x[0-9]+' | grep -oP '[0-9]+' | head -1)
PCIE_WIDTH_MAX_LSPCI=$(echo "$LNKCAP_LINE" | grep -oP 'Width x[0-9]+' | grep -oP '[0-9]+' | head -1)

# Convert PCIe speed GT/s → gen number
case "$PCIE_SPEED_LSPCI" in
    2.5) PCIE_GEN_LSPCI=1 ;;
    5)   PCIE_GEN_LSPCI=2 ;;
    8)   PCIE_GEN_LSPCI=3 ;;
    16)  PCIE_GEN_LSPCI=4 ;;
    32)  PCIE_GEN_LSPCI=5 ;;
    *)   PCIE_GEN_LSPCI=0 ;;
esac

# T12 — NVIDIA L1 via nvidia-smi
if [[ "$VENDOR" == "NVIDIA" ]]; then
    # Use max clocks (boost) instead of current (idle) for spec reporting
    SMI_QUERY="name,driver_version,vbios_version,memory.total,pcie.link.gen.current,pcie.link.gen.max,pcie.link.width.current,pcie.link.width.max,clocks.max.graphics,clocks.max.memory"
    SMI_OUT=$(nvidia-smi --query-gpu="$SMI_QUERY" --format=csv,noheader,nounits 2>/dev/null | head -1)

    IFS=',' read -r _name _driver _bios _vram _pcie_gen _pcie_gen_max _pcie_wcur _pcie_wmax _clk_gpu _clk_mem <<< "$SMI_OUT"

    GPU_NAME=$(echo "$_name"           | xargs)
    GPU_DRIVER=$(echo "$_driver"       | xargs)
    GPU_BIOS=$(echo "$_bios"           | xargs)
    GPU_VRAM_MB=$(echo "$_vram"        | grep -oP '[0-9]+' | head -1)
    GPU_PCIE_GEN=$(echo "$_pcie_gen_max" | grep -oP '[0-9]+' | head -1)   # use max gen as card spec
    GPU_PCIE_GEN_CUR=$(echo "$_pcie_gen" | grep -oP '[0-9]+' | head -1)   # current (may be downclocked)
    GPU_PCIE_GEN_MAX=$(echo "$_pcie_gen_max" | grep -oP '[0-9]+' | head -1)
    GPU_PCIE_WIDTH_CUR=$(echo "$_pcie_wcur" | grep -oP '[0-9]+' | head -1)
    GPU_PCIE_WIDTH_MAX=$(echo "$_pcie_wmax" | grep -oP '[0-9]+' | head -1)
    GPU_CLOCK_GPU=$(echo "$_clk_gpu"   | grep -oP '[0-9]+' | head -1)
    GPU_CLOCK_MEM=$(echo "$_clk_mem"   | grep -oP '[0-9]+' | head -1)

    # Memory type — try nvidia-smi -q first, fallback to N/A
    GPU_VRAM_TYPE=$(nvidia-smi -q 2>/dev/null \
        | grep -i "memory type" | head -1 \
        | sed 's/.*: //' | xargs)
    [[ -z "$GPU_VRAM_TYPE" || "$GPU_VRAM_TYPE" == "[N/A]" || "$GPU_VRAM_TYPE" == "N/A" ]] \
        && GPU_VRAM_TYPE="N/A"

    # Bus width — nvidia-smi -q
    GPU_VRAM_BUS_WIDTH=$(nvidia-smi -q 2>/dev/null \
        | grep -i "bus width" | head -1 \
        | grep -oP '[0-9]+' | head -1 || echo "0")
    [[ -z "$GPU_VRAM_BUS_WIDTH" ]] && GPU_VRAM_BUS_WIDTH=0

    # Chip codename — device_id lookup table (common Quadro/GeForce/RTX)
    case "${GPU_DEVICE_ID}" in
        # Kepler
        10DE:0FC2|10DE:0FC6|10DE:0FCD|10DE:0FCE|10DE:11C0|10DE:11C6) GPU_CHIP="GK107" ;;
        10DE:1040|10DE:1042|10DE:1048|10DE:1049|10DE:104A)           GPU_CHIP="GF119" ;;
        10DE:1287|10DE:1288)                                           GPU_CHIP="GK208" ;;
        # Maxwell
        10DE:13B0|10DE:13B1|10DE:13B2|10DE:13B3|10DE:13B4)           GPU_CHIP="GM107" ;;
        10DE:13C0|10DE:13C2|10DE:13D7|10DE:13D8|10DE:13D9)           GPU_CHIP="GM204" ;;
        10DE:17C2|10DE:17C8|10DE:17F0|10DE:17F1)                     GPU_CHIP="GM200" ;;
        # Pascal
        # GP102: GTX 1080 Ti/Titan X — 352bit GDDR5X
        10DE:1B00|10DE:1B02|10DE:1B06|10DE:1B80|10DE:1B81|10DE:1B82) GPU_CHIP="GP102"; GPU_VRAM_TYPE="GDDR5X"; GPU_VRAM_BUS_WIDTH=352 ;;
        # GP104: GTX 1070/1080 — 256bit GDDR5/GDDR5X
        10DE:1B83|10DE:1B84|10DE:1BA0|10DE:1BA1|10DE:1BA2)           GPU_CHIP="GP104"; GPU_VRAM_TYPE="GDDR5X"; GPU_VRAM_BUS_WIDTH=256 ;;
        # GP106: GTX 1060 — 192bit GDDR5
        10DE:1C02|10DE:1C03|10DE:1C20|10DE:1C30|10DE:1C60|10DE:1C61) GPU_CHIP="GP106"; GPU_VRAM_TYPE="GDDR5"; GPU_VRAM_BUS_WIDTH=192 ;;
        # GP107: GTX 1050/1050Ti — 128bit GDDR5
        10DE:1C81|10DE:1C82|10DE:1C83|10DE:1C8C|10DE:1C8D|10DE:1C8F) GPU_CHIP="GP107"; GPU_VRAM_TYPE="GDDR5"; GPU_VRAM_BUS_WIDTH=128 ;;
        # GP107GL: Quadro P400/P600 — 64bit GDDR5
        10DE:1CB1|10DE:1CB2|10DE:1CB3|10DE:1CB6)                     GPU_CHIP="GP107GL"; GPU_VRAM_TYPE="GDDR5"; GPU_VRAM_BUS_WIDTH=64 ;;
        # GP108: GT 1030/GTX 1050 3GB — 64bit GDDR5
        10DE:1D01|10DE:1D10|10DE:1D12|10DE:1D13|10DE:1D16|10DE:1D33) GPU_CHIP="GP108"; GPU_VRAM_TYPE="GDDR5"; GPU_VRAM_BUS_WIDTH=64 ;;
        # Turing — GDDR6
        # TU102: RTX 2080 Ti, Quadro RTX 6000/8000 — 352bit
        10DE:1E02|10DE:1E04|10DE:1E07|10DE:1E30|10DE:1E36|10DE:1E78) GPU_CHIP="TU102"; GPU_VRAM_TYPE="GDDR6"; GPU_VRAM_BUS_WIDTH=352 ;;
        # TU104: RTX 2080/2080S/2070S, Quadro RTX 5000 — 256bit
        10DE:1E81|10DE:1E82|10DE:1E84|10DE:1E87|10DE:1E89|10DE:1E90) GPU_CHIP="TU104"; GPU_VRAM_TYPE="GDDR6"; GPU_VRAM_BUS_WIDTH=256 ;;
        # TU106: RTX 2060/2060S/2070, Quadro RTX 4000 — 192bit (2070=256bit)
        10DE:1F02|10DE:1F06|10DE:1F07|10DE:1F08)                     GPU_CHIP="TU106"; GPU_VRAM_TYPE="GDDR6"; GPU_VRAM_BUS_WIDTH=256 ;;
        10DE:1F10|10DE:1F11|10DE:1F12|10DE:1F14|10DE:1F15|10DE:1F36) GPU_CHIP="TU106"; GPU_VRAM_TYPE="GDDR6"; GPU_VRAM_BUS_WIDTH=192 ;;
        # TU116: GTX 1660/1660S/1660Ti, GTX 1650S — 192bit
        10DE:2182|10DE:2184|10DE:2187|10DE:2188|10DE:2189|10DE:21C4) GPU_CHIP="TU116"; GPU_VRAM_TYPE="GDDR6"; GPU_VRAM_BUS_WIDTH=192 ;;
        # TU117: GTX 1650/MX450/MX550 — 128bit
        10DE:1F82|10DE:1F91|10DE:1F95|10DE:1F96|10DE:1F97|10DE:1F98) GPU_CHIP="TU117"; GPU_VRAM_TYPE="GDDR5"; GPU_VRAM_BUS_WIDTH=128 ;;
        # Ampere — GDDR6X/GDDR6
        # GA102: RTX 3090/3080/3080Ti — 384bit(3090/3080Ti) or 320bit(3080)
        10DE:2204|10DE:2208|10DE:220A|10DE:2216)                     GPU_CHIP="GA102"; GPU_VRAM_TYPE="GDDR6X"; GPU_VRAM_BUS_WIDTH=384 ;;
        10DE:2206)                                                     GPU_CHIP="GA102"; GPU_VRAM_TYPE="GDDR6X"; GPU_VRAM_BUS_WIDTH=320 ;;
        # GA104: RTX 3070/3070Ti/3060Ti — 256bit
        10DE:2482|10DE:2484|10DE:2486|10DE:2488|10DE:248A)           GPU_CHIP="GA104"; GPU_VRAM_TYPE="GDDR6"; GPU_VRAM_BUS_WIDTH=256 ;;
        # GA106: RTX 3060/3050 — 192bit
        10DE:2503|10DE:2504|10DE:2507|10DE:2560|10DE:2563)           GPU_CHIP="GA106"; GPU_VRAM_TYPE="GDDR6"; GPU_VRAM_BUS_WIDTH=192 ;;
        # GA107: RTX 3050/MX570 — 128bit
        10DE:25A0|10DE:25A2|10DE:25A5|10DE:25A6|10DE:25A9|10DE:25AA) GPU_CHIP="GA107"; GPU_VRAM_TYPE="GDDR6"; GPU_VRAM_BUS_WIDTH=128 ;;
        # Ada Lovelace — GDDR6X/GDDR6
        # AD102: RTX 4090 — 384bit
        10DE:2684|10DE:2685)                                           GPU_CHIP="AD102"; GPU_VRAM_TYPE="GDDR6X"; GPU_VRAM_BUS_WIDTH=384 ;;
        # AD103: RTX 4080/4080S — 256bit
        10DE:2702|10DE:2703|10DE:2704|10DE:2705)                     GPU_CHIP="AD103"; GPU_VRAM_TYPE="GDDR6X"; GPU_VRAM_BUS_WIDTH=256 ;;
        # AD104: RTX 4070Ti/4070Ti Super/4070S — 192bit
        10DE:2782|10DE:2783|10DE:2786|10DE:27A0|10DE:27B0|10DE:27B6) GPU_CHIP="AD104"; GPU_VRAM_TYPE="GDDR6X"; GPU_VRAM_BUS_WIDTH=192 ;;
        # AD106: RTX 4070/4060Ti — 128bit
        10DE:28A0|10DE:28A1|10DE:28B0|10DE:28B8|10DE:28E0|10DE:28F8) GPU_CHIP="AD106"; GPU_VRAM_TYPE="GDDR6"; GPU_VRAM_BUS_WIDTH=128 ;;
        *)
            # Fallback: parse from GPU name
            GPU_CHIP=$(echo "$GPU_NAME" | grep -oP '\b(G[KFMPT][0-9]{2,3}[A-Z]?|[GT][AU][0-9]{3}[A-Z]?|AD[0-9]{3}[A-Z]?)\b' | head -1)
            [[ -z "$GPU_CHIP" ]] && GPU_CHIP="Unknown"
            ;;
    esac

    # Bandwidth: nvidia-smi clocks.max.memory returns effective clock (already multiplied)
    # so always use x2 regardless of memory type
    GPU_VRAM_BANDWIDTH=0
    if [[ "$GPU_VRAM_BUS_WIDTH" -gt 0 && "$GPU_CLOCK_MEM" -gt 0 ]]; then
        GPU_VRAM_BANDWIDTH=$(awk "BEGIN {printf \"%.1f\", $GPU_VRAM_BUS_WIDTH * $GPU_CLOCK_MEM * 2 / 8 / 1000}")
    fi

    # Power max — some low-TDP cards return N/A; store as string for display
    GPU_POWER_MAX_RAW=$(nvidia-smi --query-gpu=power.limit --format=csv,noheader,nounits 2>/dev/null \
        | head -1 | xargs)
    [[ "$GPU_POWER_MAX_RAW" =~ ^[0-9] ]] && GPU_POWER_LIMIT="$GPU_POWER_MAX_RAW" || GPU_POWER_LIMIT="N/A"

    # Fall back to lspci values if nvidia-smi returned N/A or 0
    [[ -z "$GPU_PCIE_GEN"       || "$GPU_PCIE_GEN"       == "0" ]] && GPU_PCIE_GEN="${PCIE_GEN_LSPCI:-0}"
    [[ -z "$GPU_PCIE_WIDTH_CUR" || "$GPU_PCIE_WIDTH_CUR" == "0" ]] && GPU_PCIE_WIDTH_CUR="${PCIE_WIDTH_CUR_LSPCI:-0}"
    [[ -z "$GPU_PCIE_WIDTH_MAX" || "$GPU_PCIE_WIDTH_MAX" == "0" ]] && GPU_PCIE_WIDTH_MAX="${PCIE_WIDTH_MAX_LSPCI:-0}"

    # Defaults for unset
    GPU_VRAM_MB="${GPU_VRAM_MB:-0}"
    GPU_PCIE_GEN="${GPU_PCIE_GEN:-0}"
    GPU_PCIE_GEN_CUR="${GPU_PCIE_GEN_CUR:-0}"
    GPU_PCIE_WIDTH_CUR="${GPU_PCIE_WIDTH_CUR:-0}"
    GPU_PCIE_WIDTH_MAX="${GPU_PCIE_WIDTH_MAX:-0}"
    GPU_CLOCK_GPU="${GPU_CLOCK_GPU:-0}"
    GPU_CLOCK_MEM="${GPU_CLOCK_MEM:-0}"

    # ── Extended fields (non-legacy NVIDIA only) ──────────────────
    GPU_COMPUTE_ARCH=""; GPU_CLOCK_BASE_GPU=0; GPU_CLOCK_BASE_MEM=0
    if [[ "${LEGACY_CARD:-0}" -eq 0 ]]; then
        # CUDA compute capability → format as "CUDA X.Y"
        _compute_cap=$(nvidia-smi --query-gpu=compute_cap \
            --format=csv,noheader,nounits 2>/dev/null | head -1 | xargs)
        if [[ -n "$_compute_cap" && "$_compute_cap" != "[N/A]" && "$_compute_cap" != "N/A" ]]; then
            GPU_COMPUTE_ARCH="CUDA ${_compute_cap}"
        fi

        # Base (application) clocks — lower steady-state vs boost
        GPU_CLOCK_BASE_GPU=$(nvidia-smi --query-gpu=clocks.applications.graphics \
            --format=csv,noheader,nounits 2>/dev/null | head -1 | grep -oP '[0-9]+' | head -1)
        GPU_CLOCK_BASE_MEM=$(nvidia-smi --query-gpu=clocks.applications.memory \
            --format=csv,noheader,nounits 2>/dev/null | head -1 | grep -oP '[0-9]+' | head -1)
        [[ -z "$GPU_CLOCK_BASE_GPU" ]] && GPU_CLOCK_BASE_GPU=0
        [[ -z "$GPU_CLOCK_BASE_MEM" ]] && GPU_CLOCK_BASE_MEM=0
    fi

    # ── Legacy card override (nvidia-smi output is error text, not data) ──
    if [[ "${LEGACY_CARD:-0}" -eq 1 ]]; then
        # GPU name from lspci bracket notation e.g. "[Quadro K2000]"
        GPU_NAME=$(lspci | grep -iE 'vga|3d|display' | head -1 \
            | grep -oP '(?<=\[)[^\]]+(?=\])' | tail -1)
        [[ -z "$GPU_NAME" ]] && GPU_NAME=$(lspci | grep -iE 'vga|3d|display' \
            | head -1 | sed 's/.*: //' | sed 's/ (rev [0-9a-f]*)$//')
        GPU_DRIVER="Unsupported by driver 535 — needs 470.xx legacy"
        GPU_BIOS="N/A"
        GPU_VRAM_MB=0
        GPU_PCIE_GEN="${PCIE_GEN_LSPCI:-0}"
        GPU_PCIE_GEN_CUR="${PCIE_GEN_LSPCI:-0}"
        GPU_PCIE_WIDTH_CUR="${PCIE_WIDTH_CUR_LSPCI:-0}"
        GPU_PCIE_WIDTH_MAX="${PCIE_WIDTH_MAX_LSPCI:-0}"
        GPU_CLOCK_GPU=0
        GPU_CLOCK_MEM=0
    fi

    # ── VRAM lookup via external legacy DB (for legacy cards where nvidia-smi fails) ──
    # Only runs when LEGACY_CARD=1 and VRAM still unknown.
    # Maxwell/Pascal cards don't reach here — nvidia-smi works for them.
    if [[ "${LEGACY_CARD:-0}" -eq 1 && "${GPU_VRAM_MB:-0}" -eq 0 ]]; then
        _dev=$(echo "${GPU_DEVICE_ID}" | tr '[:upper:]' '[:lower:]' | grep -oP '[0-9a-f]{4}$')
        LEGACY_DB="${SCRIPT_DIR}/nvidia_legacy_db.conf"
        GPU_LEGACY_DRIVER=""

        if [[ -f "$LEGACY_DB" && -n "$_dev" ]]; then
            while IFS= read -r _line || [[ -n "$_line" ]]; do
                # Strip inline comment, skip comment-only lines and blank lines
                _line="${_line%%#*}"
                _line="${_line//[[:space:]]/}"   # remove all whitespace
                [[ -z "$_line" ]] && continue

                # Format: device_id:vram_mb:chip:vram_type:bus_width:driver_needed
                IFS=: read -r _id _vram _chip _vtype _busw _drv <<< "$_line"
                if [[ "$_id" == "$_dev" ]]; then
                    GPU_VRAM_MB="$_vram"
                    GPU_CHIP="$_chip"
                    GPU_VRAM_TYPE="$_vtype"
                    GPU_VRAM_BUS_WIDTH="${_busw:-0}"
                    GPU_LEGACY_DRIVER="$_drv"
                    ok "Legacy DB match [${_dev}]: ${GPU_VRAM_MB}MB  ${GPU_CHIP}  ${GPU_VRAM_TYPE}  ${GPU_VRAM_BUS_WIDTH}-bit  needs: ${GPU_LEGACY_DRIVER}"
                    break
                fi
            done < "$LEGACY_DB"
        else
            warn "Legacy DB not found: $LEGACY_DB"
        fi

        if [[ "${GPU_VRAM_MB:-0}" -eq 0 ]]; then
            warn "Device ID [${_dev}] not in legacy DB — VRAM unknown. Add entry to: $LEGACY_DB"
        fi
    fi

# T13 — AMD L1
elif [[ "$VENDOR" == "AMD" ]]; then

    # GPU Name — subvendor is most accurate (e.g. "MSI Radeon RX 580 ARMOR 8G OC")
    # Extract "Radeon RX 580" pattern from subvendor first
    GPU_SUBVENDOR_TMP=$(lspci -v -s "$GPU_PCI_ADDR" 2>/dev/null \
        | grep -i 'subsystem' | head -1 | sed 's/.*Subsystem: //')
    GPU_NAME=$(echo "$GPU_SUBVENDOR_TMP" \
        | grep -oP 'Radeon\s+(RX\s+)?[A-Z0-9]+(\s+Series)?' | head -1 | xargs)

    # Fallback: content inside last [...] brackets from lspci
    if [[ -z "$GPU_NAME" || ${#GPU_NAME} -lt 5 ]]; then
        GPU_NAME_RAW=$(lspci | grep -iE 'vga|3d|display' | grep -i 'amd\|ati' | head -1 \
            | sed 's/.*: //')
        GPU_NAME=$(echo "$GPU_NAME_RAW" | grep -oP '(?<=\[)[^\]]+(?=\])' | tail -1)
    fi
    # Fallback: strip AMD/ATI prefix
    if [[ -z "$GPU_NAME" || "$GPU_NAME" == "AMD/ATI" || ${#GPU_NAME} -lt 5 ]]; then
        GPU_NAME=$(echo "$GPU_NAME_RAW" \
            | sed 's/Advanced Micro Devices, Inc\. \[AMD\/ATI\] //' \
            | sed 's/\[AMD\/ATI\] //' \
            | sed 's/ (rev [0-9a-f]*)$//' | xargs)
    fi
    GPU_NAME="${GPU_NAME:-Unknown AMD GPU}"

    # Driver version — Mesa version from glxinfo (most visible to user)
    GPU_DRIVER=$(glxinfo 2>/dev/null \
        | grep 'GL_VERSION' | grep -oP 'Mesa [0-9.]+' | head -1 || echo "")
    # Fallback: amdgpu kernel module version
    [[ -z "$GPU_DRIVER" ]] && \
        GPU_DRIVER=$(cat /sys/module/amdgpu/version 2>/dev/null | head -1 | xargs || echo "")

    # BIOS version — strip ATOMBIOSBK-AMD VER prefix, keep version number only
    GPU_BIOS=$(rocm-smi --showvbios 2>/dev/null \
        | grep -v '^=' | grep -v '^$' | grep -v 'ROCm\|Interface\|======' \
        | grep -v 'GPU\[' \
        | grep -oP '[0-9]{3}\.[0-9]{3}\.[0-9]{3}\.[0-9]{3}\.[0-9]{6}' | head -1)
    # Fallback: sysfs
    [[ -z "$GPU_BIOS" ]] && \
        GPU_BIOS=$(cat /sys/class/drm/card*/device/vbios_version 2>/dev/null \
            | grep -oP '[0-9]{3}\.[0-9]{3}\.[0-9]{3}\.[0-9]{3}\.[0-9]{6}' | head -1 || echo "Unknown")

    # VRAM total (bytes → MB) via sysfs — most reliable
    VRAM_BYTES=$(cat /sys/class/drm/card*/device/mem_info_vram_total 2>/dev/null | head -1)
    if [[ -n "$VRAM_BYTES" && "$VRAM_BYTES" -gt 0 ]] 2>/dev/null; then
        GPU_VRAM_MB=$(( VRAM_BYTES / 1024 / 1024 ))
    else
        # Fallback: rocm-smi --showmeminfo vram
        GPU_VRAM_MB=$(rocm-smi --showmeminfo vram 2>/dev/null \
            | grep -i 'total' | grep -oP '[0-9]+' | head -1 || echo "0")
        # rocm-smi returns bytes
        [[ "$GPU_VRAM_MB" -gt 1000000 ]] 2>/dev/null \
            && GPU_VRAM_MB=$(( GPU_VRAM_MB / 1024 / 1024 ))
    fi
    GPU_VRAM_MB="${GPU_VRAM_MB:-0}"

    # VRAM type + Bus width + Chip — device_id lookup table
    # glxinfo returns empty for root; sysfs mem_info_vram_type not available on all kernels
    case "${GPU_DEVICE_ID}" in
        # Polaris (RX 460/470/480/550/560/570/580/590)
        1002:67DF|1002:67C0|1002:67C2|1002:67C4|1002:67C7) GPU_CHIP="polaris10"; GPU_VRAM_TYPE="GDDR5"; GPU_VRAM_BUS_WIDTH=256 ;;
        1002:67E0|1002:67E3|1002:67E8|1002:67EB|1002:67EF|1002:67FF) GPU_CHIP="polaris11"; GPU_VRAM_TYPE="GDDR5"; GPU_VRAM_BUS_WIDTH=128 ;;
        1002:6980|1002:6981|1002:6985|1002:6986|1002:6987) GPU_CHIP="polaris12"; GPU_VRAM_TYPE="GDDR5"; GPU_VRAM_BUS_WIDTH=128 ;;
        # Vega
        1002:6860|1002:6861|1002:6862|1002:6863|1002:6864|1002:6867|1002:6868|1002:686C) GPU_CHIP="vega10"; GPU_VRAM_TYPE="HBM2"; GPU_VRAM_BUS_WIDTH=2048 ;;
        1002:69A0|1002:69A1|1002:69A2|1002:69A3|1002:69AF) GPU_CHIP="vega20"; GPU_VRAM_TYPE="HBM2"; GPU_VRAM_BUS_WIDTH=4096 ;;
        # Navi (RX 5000 series)
        1002:7310|1002:7312|1002:7318|1002:7319|1002:731A|1002:731B|1002:731F) GPU_CHIP="navi10"; GPU_VRAM_TYPE="GDDR6"; GPU_VRAM_BUS_WIDTH=256 ;;
        1002:7340|1002:7341|1002:7343|1002:7347|1002:734F) GPU_CHIP="navi14"; GPU_VRAM_TYPE="GDDR6"; GPU_VRAM_BUS_WIDTH=128 ;;
        # Navi2 (RX 6000 series)
        1002:73BF|1002:73A5|1002:73AB|1002:73AE|1002:73AF) GPU_CHIP="navi21"; GPU_VRAM_TYPE="GDDR6"; GPU_VRAM_BUS_WIDTH=256 ;;
        1002:73DF|1002:73E0|1002:73E1|1002:73E3|1002:73EF) GPU_CHIP="navi22"; GPU_VRAM_TYPE="GDDR6"; GPU_VRAM_BUS_WIDTH=192 ;;
        1002:73FF|1002:73E4|1002:7422|1002:7423|1002:743F) GPU_CHIP="navi23"; GPU_VRAM_TYPE="GDDR6"; GPU_VRAM_BUS_WIDTH=128 ;;
        # Navi3 (RX 7000 series)
        1002:744C|1002:7480|1002:7483|1002:7489) GPU_CHIP="navi31"; GPU_VRAM_TYPE="GDDR6"; GPU_VRAM_BUS_WIDTH=384 ;;
        1002:747E|1002:7470|1002:7471) GPU_CHIP="navi32"; GPU_VRAM_TYPE="GDDR6"; GPU_VRAM_BUS_WIDTH=256 ;;
        1002:7448|1002:745E) GPU_CHIP="navi33"; GPU_VRAM_TYPE="GDDR6"; GPU_VRAM_BUS_WIDTH=128 ;;
        # Ellesmere (older RX 400/500 — catch-all)
        1002:67C8|1002:67C9|1002:67D0) GPU_CHIP="ellesmere"; GPU_VRAM_TYPE="GDDR5"; GPU_VRAM_BUS_WIDTH=256 ;;
        *)
            GPU_CHIP="Unknown"
            GPU_VRAM_TYPE="Unknown"
            GPU_VRAM_BUS_WIDTH=0
            ;;
    esac

    # Clocks — read max from pp_dpm tables (not current idle clock)
    GPU_CLOCK_GPU=$(cat /sys/class/drm/card*/device/pp_dpm_sclk 2>/dev/null \
        | tail -1 | grep -oP '[0-9]+(?=Mhz|MHz)' | head -1 || echo "0")
    GPU_CLOCK_MEM=$(cat /sys/class/drm/card*/device/pp_dpm_mclk 2>/dev/null \
        | tail -1 | grep -oP '[0-9]+(?=Mhz|MHz)' | head -1 || echo "0")
    # Fallback: rocm-smi current clocks
    if [[ "$GPU_CLOCK_GPU" -eq 0 ]] 2>/dev/null; then
        GPU_CLOCK_GPU=$(rocm-smi --showclocks 2>/dev/null \
            | grep -iE 'sclk' | grep -oP '[0-9]+(?=Mhz|MHz)' | tail -1 || echo "0")
    fi
    if [[ "$GPU_CLOCK_MEM" -eq 0 ]] 2>/dev/null; then
        GPU_CLOCK_MEM=$(rocm-smi --showclocks 2>/dev/null \
            | grep -iE 'mclk' | grep -oP '[0-9]+(?=Mhz|MHz)' | tail -1 || echo "0")
    fi

    # Power limit — use same card/hwmon detection as thermal
    _amd_card=$(ls /sys/class/drm/ | grep '^card[0-9]*$' | head -1)
    _amd_hwmon=$(ls /sys/class/drm/${_amd_card}/device/hwmon/ 2>/dev/null | head -1)
    GPU_POWER_LIMIT=$(cat /sys/class/drm/${_amd_card}/device/hwmon/${_amd_hwmon}/power1_cap \
        2>/dev/null | head -1)
    if [[ -n "$GPU_POWER_LIMIT" && "$GPU_POWER_LIMIT" -gt 0 ]] 2>/dev/null; then
        GPU_POWER_LIMIT=$(awk "BEGIN {printf \"%.0f\", $GPU_POWER_LIMIT / 1000000}")
    else
        GPU_POWER_LIMIT="N/A"
    fi

    # PCIe — fully from lspci (rocm-smi PCIe output unreliable)
    GPU_PCIE_GEN="${PCIE_GEN_LSPCI:-0}"
    GPU_PCIE_GEN_CUR="${PCIE_GEN_LSPCI:-0}"
    GPU_PCIE_WIDTH_CUR="${PCIE_WIDTH_CUR_LSPCI:-0}"
    GPU_PCIE_WIDTH_MAX="${PCIE_WIDTH_MAX_LSPCI:-0}"

    # Bandwidth: GDDR5/GDDR6=QDR(x4), HBM/DDR3=DDR(x2)
    GPU_VRAM_BANDWIDTH=0
    if [[ "$GPU_VRAM_BUS_WIDTH" -gt 0 && "$GPU_CLOCK_MEM" -gt 0 ]]; then
        case "$GPU_VRAM_TYPE" in
            GDDR5|GDDR5X|GDDR6|GDDR6X) _bw_mult=4 ;;
            *) _bw_mult=2 ;;
        esac
        GPU_VRAM_BANDWIDTH=$(awk "BEGIN {printf \"%.1f\", $GPU_VRAM_BUS_WIDTH * $GPU_CLOCK_MEM * $_bw_mult / 8 / 1000}")
    fi

    # Ensure numeric
    GPU_VRAM_MB=$(echo "$GPU_VRAM_MB"     | grep -oP '[0-9]+' | head -1 || echo "0")
    GPU_CLOCK_GPU=$(echo "$GPU_CLOCK_GPU" | grep -oP '[0-9]+' | head -1 || echo "0")
    GPU_CLOCK_MEM=$(echo "$GPU_CLOCK_MEM" | grep -oP '[0-9]+' | head -1 || echo "0")

    # ── Extended fields for AMD ────────────────────────────────────
    # Base GPU clock — P-state 0 from power management table
    GPU_CLOCK_BASE_GPU=$(cat /sys/class/drm/card*/device/pp_dpm_sclk 2>/dev/null \
        | grep '^0:' | grep -oP '[0-9]+(?=[Mm][Hh][Zz])' | head -1)
    [[ -z "$GPU_CLOCK_BASE_GPU" ]] && GPU_CLOCK_BASE_GPU=0

    # Base memory clock — P-state 0
    GPU_CLOCK_BASE_MEM=$(cat /sys/class/drm/card*/device/pp_dpm_mclk 2>/dev/null \
        | grep '^0:' | grep -oP '[0-9]+(?=[Mm][Hh][Zz])' | head -1)
    [[ -z "$GPU_CLOCK_BASE_MEM" ]] && GPU_CLOCK_BASE_MEM=0

    # Compute architecture — ROCm gfx code mapped from chip name
    case "$GPU_CHIP" in
        polaris10|polaris11|polaris12) GPU_COMPUTE_ARCH="gfx803"  ;;
        vega10)                        GPU_COMPUTE_ARCH="gfx900"  ;;
        vega20)                        GPU_COMPUTE_ARCH="gfx906"  ;;
        navi10)                        GPU_COMPUTE_ARCH="gfx1010" ;;
        navi12)                        GPU_COMPUTE_ARCH="gfx1011" ;;
        navi14)                        GPU_COMPUTE_ARCH="gfx1012" ;;
        navi21)                        GPU_COMPUTE_ARCH="gfx1030" ;;
        navi22)                        GPU_COMPUTE_ARCH="gfx1031" ;;
        navi23)                        GPU_COMPUTE_ARCH="gfx1032" ;;
        navi24)                        GPU_COMPUTE_ARCH="gfx1034" ;;
        navi31)                        GPU_COMPUTE_ARCH="gfx1100" ;;
        navi32)                        GPU_COMPUTE_ARCH="gfx1101" ;;
        navi33)                        GPU_COMPUTE_ARCH="gfx1102" ;;
        *)                             GPU_COMPUTE_ARCH=""        ;;
    esac
fi

# Defaults / safety
GPU_VRAM_MB="${GPU_VRAM_MB:-0}"
GPU_CLOCK_GPU="${GPU_CLOCK_GPU:-0}"
GPU_CLOCK_MEM="${GPU_CLOCK_MEM:-0}"
GPU_PCIE_GEN="${GPU_PCIE_GEN:-0}"
GPU_PCIE_GEN_CUR="${GPU_PCIE_GEN_CUR:-0}"
GPU_PCIE_WIDTH_CUR="${GPU_PCIE_WIDTH_CUR:-0}"
GPU_PCIE_WIDTH_MAX="${GPU_PCIE_WIDTH_MAX:-0}"
GPU_VRAM_BUS_WIDTH="${GPU_VRAM_BUS_WIDTH:-0}"
GPU_VRAM_BANDWIDTH="${GPU_VRAM_BANDWIDTH:-0}"
GPU_POWER_LIMIT="${GPU_POWER_LIMIT:-N/A}"
# Extended fields — defaults cover AMD and legacy NVIDIA paths
GPU_COMPUTE_ARCH="${GPU_COMPUTE_ARCH:-}"
GPU_CLOCK_BASE_GPU="${GPU_CLOCK_BASE_GPU:-0}"
GPU_CLOCK_BASE_MEM="${GPU_CLOCK_BASE_MEM:-0}"

# PCIe degraded field removed


# ── File Naming: GPU Name + Timestamp ────────────────────────
# GPU hardware SN is unavailable on most consumer cards (GeForce/Radeon).
# Use sanitized GPU name + timestamp as unique file identifier.
# e.g. Radeon_RX_580_20260511_074640.json

GPU_SN=""
if [[ "$VENDOR" == "NVIDIA" ]]; then
    # Skip nvidia-smi SN query for legacy cards — driver 535 cannot read them,
    # and nvidia-smi returns an error string that would corrupt the SN field.
    if [[ "${LEGACY_CARD:-0}" -eq 0 ]]; then
        _raw=$(nvidia-smi --query-gpu=serial --format=csv,noheader 2>/dev/null | head -1 | xargs)
        [[ -n "$_raw" && "$_raw" != "[N/A]" && "$_raw" != "N/A" ]] && GPU_SN="$_raw"
    fi
elif [[ "$VENDOR" == "AMD" ]]; then
    _raw=$(rocm-smi --showserial 2>/dev/null | grep -i 'serial' | head -1 | awk '{print $NF}' | xargs)
    # Reject: empty, N/A, all-zeros, or strings containing = (separator lines)
    if [[ -n "$_raw" && "$_raw" != "N/A" && "$_raw" != "0x0000000000000000" \
        && "$_raw" != *"="* && ${#_raw} -gt 4 ]]; then
        GPU_SN="$_raw"
    fi
fi

# File ID priority:
#   1. Card label SN (scanned barcode) — most reliable for tracking
#   2. Hardware SN (enterprise/Quadro cards only)
#   3. GPU Name + Timestamp (no label scanned)
GPU_NAME_SAFE=$(echo "$GPU_NAME" | tr ' ' '_' | tr -cd 'A-Za-z0-9_-' | cut -c1-40)
[[ -z "$GPU_NAME_SAFE" ]] && GPU_NAME_SAFE="GPU"

if [[ -n "$CARD_LABEL" ]]; then
    FILE_ID="${CARD_LABEL}"
    JSON_FILE="$LOG_DIR/${FILE_ID}.json"
    ok "Tracking ID: $FILE_ID  →  report: $JSON_FILE"
elif [[ -n "$GPU_SN" ]]; then
    FILE_ID="${GPU_SN}"
    JSON_FILE="$LOG_DIR/${FILE_ID}.json"
    ok "Tracking ID: $FILE_ID  →  report: $JSON_FILE"
else
    # No SN available: Name + Timestamp
    FILE_ID="${GPU_NAME_SAFE}_${TIMESTAMP}"
    JSON_FILE="$LOG_DIR/${FILE_ID}.json"
    ok "Tracking ID: $FILE_ID  →  report: $JSON_FILE"
fi

# top-level sn field in JSON = FILE_ID (used as tracking key in MonitorCenter)
TRACKING_ID="$FILE_ID"

# T16 — Print L1 summary
echo ""
printf "  %-22s %s\n" "GPU Name:"      "$GPU_NAME"
printf "  %-22s %s\n" "Chip:"          "$GPU_CHIP"
printf "  %-22s %s\n" "Vendor:"        "$VENDOR"
printf "  %-22s %s MB (%s)\n" "VRAM:"  "$GPU_VRAM_MB" "$GPU_VRAM_TYPE"
printf "  %-22s %s bit\n" "Bus Width:"  "$GPU_VRAM_BUS_WIDTH"
printf "  %-22s %s GB/s\n" "Bandwidth:" "$GPU_VRAM_BANDWIDTH"
printf "  %-22s %s\n" "Driver:"        "$GPU_DRIVER"
printf "  %-22s %s\n" "BIOS:"          "$GPU_BIOS"
printf "  %-24s" "PCIe:"
printf "Gen%s @ x%s (max x%s)\n" "$GPU_PCIE_GEN" "$GPU_PCIE_WIDTH_CUR" "$GPU_PCIE_WIDTH_MAX" 
printf "  %-22s %s MHz (boost)\n" "GPU Clock:"  "$GPU_CLOCK_GPU"
printf "  %-22s %s MHz (boost)\n" "Mem Clock:"  "$GPU_CLOCK_MEM"
printf "  %-22s %s W\n" "TDP:"          "$GPU_POWER_LIMIT"
printf "  %-22s %s\n" "Subvendor:"     "$GPU_SUBVENDOR"
printf "  %-22s %s\n" "Device ID:"     "$GPU_DEVICE_ID"
ok "L1 identification complete."

# ── Test Tier Determination ───────────────────────────────────
TEST_TIER="FULL"
if [[ "${LEGACY_CARD:-0}" -eq 1 ]]; then
    # Kepler / Fermi: nvidia-smi is non-functional under driver 535; CUDA / gpu-burn cannot run.
    # Force INFO_ONLY regardless of VRAM reported by the legacy DB.
    TEST_TIER="INFO_ONLY"
    warn "Legacy card (unsupported by driver 535) — forced INFO_ONLY mode"
elif [[ "$GPU_VRAM_MB" -lt 4096 ]] 2>/dev/null; then
    TEST_TIER="INFO_ONLY"
    warn "Test tier: INFO_ONLY (VRAM ${GPU_VRAM_MB}MB < 4096MB — skipping stress tests)"
fi

if [[ "$TEST_TIER" == "FULL" ]]; then
    ok "Test tier: FULL (VRAM ${GPU_VRAM_MB}MB ≥ 4096MB)"
fi

# ============================================================
# Phase 2b — Pre-Test GPU Health Gate
# ============================================================
# Scan the kernel log for FATAL GPU errors before running any test. A
# defective card often spews driver-init / Xid / fell-off-the-bus errors at
# boot — errors the operator cannot interpret. Surface them in a big, clear
# warning so the operator knows to replace the card.
banner "Step 1b: Pre-Test GPU Health Check"

_fatal_lines=$(detect_gpu_fatal_dmesg) && _fatal_hit=1 || _fatal_hit=0
if [[ "$_fatal_hit" -eq 1 ]]; then
    show_gpu_fault_screen "$_fatal_lines"
    echo ""
    echo -e "  ${BOLD}Press  ENTER  →  test anyway (card may be unstable)${NC}"
    echo -e "  ${BOLD}Press  Ctrl+C →  abort and REPLACE the card${NC}"
    echo ""

    trap '
        echo ""
        echo -e "  ${YELLOW}Aborted — power off and replace the GPU.${NC}"
        echo ""
        trap - INT
        safe_exit 2
    ' INT

    read -r -s
    trap - INT
    warn "Operator chose to continue testing despite kernel errors."
else
    ok "No fatal GPU errors in kernel log."
fi

# ── Reset kernel ring buffer before stress testing ────────────
# Step 1b above already scanned the FULL boot-time log for fatal faults. Clear
# the buffer now so the post-test Step 6 scan judges ONLY errors generated
# DURING the test — stale boot-time driver chatter (e.g. "NVRM: probe routine
# failed" from before the driver was installed) must not cause a false FAIL.
if [[ "$TEST_TIER" == "FULL" ]]; then
    dmesg -C 2>/dev/null && ok "Kernel log cleared — Step 6 will only see test-time errors." \
        || warn "Could not clear kernel log (dmesg -C) — Step 6 may include stale boot messages."
fi

# ============================================================
# Phase 3 — Async Thermal Monitoring
# ============================================================
banner "Step 2: Starting Thermal Monitor"

if [[ "$TEST_TIER" != "FULL" ]]; then
    ok "Thermal monitor skipped (INFO_ONLY mode)"
    SMI_PID=""
elif [[ "$VENDOR" == "NVIDIA" ]]; then
    # T17 — nvidia-smi background sampler
    nvidia-smi \
        --query-gpu=temperature.gpu,utilization.gpu,power.draw,clocks.current.graphics,clocks.current.memory \
        --format=csv,noheader,nounits \
        -l "$SMI_INTERVAL" \
        > "$THERMAL_LOG" 2>/dev/null &
    SMI_PID=$!

elif [[ "$VENDOR" == "AMD" ]]; then
    # T18 — AMD thermal via sysfs (most reliable, no rocm-smi table format issues)
    AMD_CARD=$(ls /sys/class/drm/ | grep '^card[0-9]*$' | head -1)
    AMD_HWMON=$(ls /sys/class/drm/${AMD_CARD}/device/hwmon/ 2>/dev/null | head -1)
    AMD_TEMP_PATH="/sys/class/drm/${AMD_CARD}/device/hwmon/${AMD_HWMON}/temp1_input"
    AMD_PWR_PATH="/sys/class/drm/${AMD_CARD}/device/hwmon/${AMD_HWMON}/power1_input"
    AMD_USE_PATH="/sys/class/drm/${AMD_CARD}/device/gpu_busy_percent"
    (
        while true; do
            TEMP=$(cat "$AMD_TEMP_PATH" 2>/dev/null | awk '{printf "%.1f", $1/1000}' || echo "0")
            USE=$(cat "$AMD_USE_PATH" 2>/dev/null || echo "0")
            PWR=$(cat "$AMD_PWR_PATH" 2>/dev/null | awk '{printf "%.1f", $1/1000000}' || echo "0")
            echo "${TEMP},${USE},${PWR}"
            sleep "$SMI_INTERVAL"
        done
    ) >> "$THERMAL_LOG" 2>/dev/null &
    SMI_PID=$!
fi

# T19 — Confirm background process started (FULL only)
if [[ "$TEST_TIER" == "FULL" ]]; then
    sleep 1
    if kill -0 "$SMI_PID" 2>/dev/null; then
        ok "Thermal monitor started (PID $SMI_PID → $THERMAL_LOG)"
    else
        warn "Thermal monitor did not start; continuing without live thermal data."
        SMI_PID=""
    fi
fi

# ============================================================
# Phase 4 — VRAM Stress Test
# ============================================================
banner "Step 3: VRAM Stress Test (${BURN_DURATION}s)"

VRAM_ERRORS=0
VRAM_STATUS="PASS"
VRAM_TOOL="unknown"
ACTUAL_BURN_DURATION=0

if [[ "$TEST_TIER" != "FULL" ]]; then
    ok "VRAM stress test skipped (INFO_ONLY mode)"
    VRAM_TOOL="skipped"
    VRAM_STATUS="SKIPPED"
elif [[ "$VENDOR" == "NVIDIA" ]]; then
    # T20 — gpu-burn
    VRAM_TOOL="gpu-burn"
    ok "Running gpu-burn for ${BURN_DURATION}s..."
    BURN_START=$(date +%s)
    gpu-burn "$BURN_DURATION" 2>&1 | tee "$GPUBURN_LOG"
    ACTUAL_BURN_DURATION=$(( $(date +%s) - BURN_START ))

    # T21 — parse error count
    # gpu-burn output: "GPU 0: 100.00% | 0 errors"
    VRAM_ERRORS=$(grep -oP '[0-9]+ error' "$GPUBURN_LOG" \
        | grep -oP '^[0-9]+' \
        | awk '{s+=$1} END {print s+0}')
    VRAM_ERRORS="${VRAM_ERRORS:-0}"

    if [[ "$VRAM_ERRORS" -gt 0 ]]; then
        err "VRAM errors detected: $VRAM_ERRORS"
        VRAM_STATUS="FAIL"
    else
        ok "VRAM test passed (0 errors)"
    fi

elif [[ "$VENDOR" == "AMD" ]]; then
    # T22 — glmark2 stress + radeontop monitoring
    VRAM_TOOL="glmark2"
    ok "Running glmark2 stress for ${BURN_DURATION}s (AMD VRAM test)..."

    radeontop -d "$RADEONTOP_LOG" -l 1 2>/dev/null &
    RADEONTOP_PID=$!

    # Start X if needed
    if [[ -z "${DISPLAY:-}" ]]; then
        X :0 -nolisten tcp &>/dev/null &
        AMD_X_PID=$!
        sleep 3
        export DISPLAY=:0
        xrandr --auto &>/dev/null || true
        sleep 1
    fi

    timeout "$BURN_DURATION" glmark2 --size 1920x1080 >> "$VKMARK_LOG" 2>&1 || true

    kill "$RADEONTOP_PID" 2>/dev/null
    wait "$RADEONTOP_PID" 2>/dev/null || true

    # T23 — GPU util peak from radeontop
    RADEONTOP_UTIL_MAX=$(grep -oP 'gpu [0-9.]+%' "$RADEONTOP_LOG" 2>/dev/null \
        | grep -oP '[0-9.]+' \
        | awk '{if($1+0>max) max=$1+0} END {printf "%d", max+0}')
    [[ -n "$RADEONTOP_UTIL_MAX" ]] && ok "AMD GPU util peak during stress: ${RADEONTOP_UTIL_MAX}%"

    VRAM_ERRORS=0
    ok "AMD VRAM stress test complete."
fi   # end TEST_TIER FULL gate (VRAM stress)

# ============================================================
# Phase 5 — OpenGL Benchmark (glmark2)
# ============================================================
banner "Step 4: OpenGL Benchmark (glmark2)"

GLMARK2_LOG="$LOG_DIR/glmark2_${TIMESTAMP}.log"
VKMARK_SCORE=0
VKMARK_STATUS="WARN"
VKMARK_WARN=false
GLMARK2_DURATION=0

if [[ "$TEST_TIER" != "FULL" ]]; then
    ok "OpenGL benchmark skipped (INFO_ONLY mode)"
    VKMARK_STATUS="SKIPPED"
else

# Start X server if not already running
X_STARTED=0
X_PID=""
if [[ -z "${DISPLAY:-}" ]] || ! xdpyinfo &>/dev/null 2>&1; then
    ok "Starting X server for benchmark..."
    X :0 -nolisten tcp &>/dev/null &
    X_PID=$!
    sleep 3
    export DISPLAY=:0
    xrandr --auto &>/dev/null || true
    sleep 1
    X_STARTED=1
    _res=$(xdpyinfo 2>/dev/null | grep dimensions | awk '{print $2}' || echo "unknown")
    ok "Display initialized: ${_res}"
else
    ok "X server already running (DISPLAY=$DISPLAY)"
    xrandr --auto &>/dev/null || true
fi

ok "Running glmark2 benchmark (1920x1080)..."
# Disable VSync — prevents FPS being capped at 60Hz (score ~3800 → ~20000)
if [[ "$VENDOR" == "NVIDIA" ]]; then
    DISPLAY=:0 nvidia-settings -a SyncToVBlank=0 &>/dev/null || true
fi
GLMARK2_START=$(date +%s)
__GL_SYNC_TO_VBLANK=0 glmark2 --size 1920x1080 2>/dev/null | tee "$GLMARK2_LOG" 
GLMARK2_DURATION=$(( $(date +%s) - GLMARK2_START ))

# Parse glmark2 Score
VKMARK_SCORE=$(grep -oP 'glmark2 Score:\s*\K[0-9]+' "$GLMARK2_LOG" | tail -1)
[[ -z "$VKMARK_SCORE" ]] && VKMARK_SCORE=0

VKMARK_STATUS="PASS"
VKMARK_WARN=false

# Baseline comparison
if [[ "$VKMARK_BASELINE_SCORE" -gt 0 && "$VKMARK_SCORE" -gt 0 ]]; then
    THRESHOLD=$(( VKMARK_BASELINE_SCORE * 80 / 100 ))
    if [[ "$VKMARK_SCORE" -lt "$THRESHOLD" ]]; then
        warn "glmark2 score $VKMARK_SCORE is >20% below baseline $VKMARK_BASELINE_SCORE (threshold $THRESHOLD)"
        VKMARK_WARN=true
        VKMARK_STATUS="WARN"
    fi
fi

if [[ "$VKMARK_SCORE" -eq 0 ]]; then
    warn "Could not parse glmark2 score — check $GLMARK2_LOG"
    VKMARK_STATUS="WARN"
else
    ok "glmark2 score: $VKMARK_SCORE"
fi

# Kill X server if we started it — verdict is shown on the text console (tty1)
if [[ "$X_STARTED" -eq 1 && -n "${X_PID:-}" ]]; then
    kill "$X_PID" 2>/dev/null || true
    wait "$X_PID" 2>/dev/null || true
    X_PID=""
fi

fi   # end TEST_TIER FULL gate (glmark2)

# Kill AMD X server started in Step 3 (AMD stress test) — never killed otherwise
# amdgpu KMS holds the framebuffer; without this the tty goes blank after test
if [[ -n "${AMD_X_PID:-}" ]]; then
    kill "$AMD_X_PID" 2>/dev/null || true
    wait "$AMD_X_PID" 2>/dev/null || true
    AMD_X_PID=""
    unset DISPLAY
    sleep 1
fi
# Restore text console after any X server exits.
# chvt 1 = switch back to virtual terminal 1 (where the script + verdict run)
chvt 1 2>/dev/null || true
sleep 1
printf '\033c'  # ESC c = full terminal reset (clears screen + resets cursor)

# ============================================================
# Phase 6 — Stop Thermal Monitor & Parse Thermal Log
# ============================================================
banner "Step 5: Parsing Thermal Data"

# T27 — Kill SMI background process
if [[ -n "$SMI_PID" ]] && kill -0 "$SMI_PID" 2>/dev/null; then
    kill "$SMI_PID" 2>/dev/null
    wait "$SMI_PID" 2>/dev/null || true
    SMI_PID=""
fi

TEMP_MAX=0
TEMP_AVG=0
UTIL_AVG=0
POWER_MAX=0
THERMAL_STATUS="PASS"

if [[ "$TEST_TIER" != "FULL" ]]; then
    ok "Thermal data skipped (INFO_ONLY mode)"
    THERMAL_STATUS="SKIPPED"
elif [[ -f "$THERMAL_LOG" && -s "$THERMAL_LOG" ]]; then
    if [[ "$VENDOR" == "NVIDIA" ]]; then
        # CSV: temp_c, util_pct, power_w, clk_gpu, clk_mem
        TEMP_MAX=$(awk -F',' 'NF>=1{t=$1+0; if(t>m) m=t} END{printf "%d", m+0}' "$THERMAL_LOG")
        TEMP_AVG=$(awk -F',' 'NF>=1{t=$1+0; s+=t; n++} END{if(n>0) printf "%d", s/n; else print 0}' "$THERMAL_LOG")
        UTIL_AVG=$(awk -F',' 'NF>=2{u=$2+0; s+=u; n++} END{if(n>0) printf "%d", s/n; else print 0}' "$THERMAL_LOG")
        POWER_MAX=$(awk -F',' 'NF>=3{p=$3+0; if(p>m) m=p} END{printf "%.1f", m+0}' "$THERMAL_LOG")
    elif [[ "$VENDOR" == "AMD" ]]; then
        # CSV format: temp_c, util_pct, power_w  (same as NVIDIA now)
        TEMP_MAX=$(awk -F',' 'NF>=1{t=$1+0; if(t>m) m=t} END{printf "%d", m+0}' "$THERMAL_LOG")
        TEMP_AVG=$(awk -F',' 'NF>=1{t=$1+0; s+=t; n++} END{if(n>0) printf "%d", s/n; else print 0}' "$THERMAL_LOG")
        UTIL_AVG=$(awk -F',' 'NF>=2{u=$2+0; s+=u; n++} END{if(n>0) printf "%d", s/n; else print 0}' "$THERMAL_LOG")
        POWER_MAX=$(awk -F',' 'NF>=3{p=$3+0; if(p>m) m=p} END{printf "%.1f", m+0}' "$THERMAL_LOG")
    fi

    TEMP_MAX="${TEMP_MAX:-0}"
    TEMP_AVG="${TEMP_AVG:-0}"
    UTIL_AVG="${UTIL_AVG:-0}"
    POWER_MAX="${POWER_MAX:-0}"

    printf "  %-22s %s°C\n" "Temp Max:"  "$TEMP_MAX"
    printf "  %-22s %s°C\n" "Temp Avg:"  "$TEMP_AVG"
    printf "  %-22s %s%%\n" "Util Avg:"  "$UTIL_AVG"
    printf "  %-22s %s W\n" "Power Max:" "$POWER_MAX"

    # T29 — Temperature thresholds
    # NVIDIA: WARN >85°C, FAIL >95°C
    # AMD:    WARN >80°C, FAIL >90°C
    if [[ "$VENDOR" == "NVIDIA" ]]; then
        TEMP_FAIL=90
        TEMP_WARN=85
    else
        TEMP_FAIL=100
        TEMP_WARN=90
    fi

    if [[ "$TEMP_MAX" -gt "$TEMP_FAIL" ]]; then
        err "Temperature critical: ${TEMP_MAX}°C > ${TEMP_FAIL}°C ($VENDOR threshold)"
        THERMAL_STATUS="FAIL"
    elif [[ "$TEMP_MAX" -gt "$TEMP_WARN" ]]; then
        warn "Temperature elevated: ${TEMP_MAX}°C > ${TEMP_WARN}°C ($VENDOR threshold)"
        THERMAL_STATUS="WARN"
    else
        ok "Temperature OK: ${TEMP_MAX}°C (threshold WARN:${TEMP_WARN}°C FAIL:${TEMP_FAIL}°C)"
    fi
else
    warn "No thermal log data found at $THERMAL_LOG"
fi   # end TEST_TIER FULL gate (thermal)

# ============================================================
# Phase 7 — dmesg GPU Error Detection
# ============================================================
banner "Step 6: Checking dmesg for GPU Errors"

# Three-tier dmesg classification — not every GPU-related kernel line is a
# hardware fault. We split signals into FATAL (hardware death → FAIL) vs
# non-fatal events (recoverable/transient → WARN). Benign noise and plain
# warnings are excluded entirely so they never affect the verdict.
#
# NOTE: the kernel ring buffer was cleared right before stress testing (after
# the Step 1b health gate), so everything scanned here was produced DURING the
# test — stale boot-time chatter cannot reach this point.

# ── FATAL signals (hardware death — high confidence) ──────────
# Same narrow set used by detect_gpu_fatal_dmesg(), plus fatal NVIDIA Xid codes:
#   48/92/94/95 = double-bit / uncorrectable ECC,  63/64 = ECC page retirement,
#   79 = GPU fell off the bus. Other Xids (13/31/43/45 etc.) are app/driver
#   level and are deliberately NOT treated as failures.
DMESG_FATAL_RE='GPU has fallen off the bus|fell off the bus|RmInitAdapter failed|rm_init_adapter failed|'\
'GPU board failed to initialize|amdgpu.*GPU reset|ring gfx.*timeout|amdgpu.*[Ff]atal error|'\
'PCIe Bus Error:[[:space:]]*severity=Fatal'

DMESG_FATAL_LINES=$(dmesg 2>/dev/null | grep -iE "$DMESG_FATAL_RE" \
    | grep -v 'nvidia-gpu.*i2c timeout' \
    | grep -v 'nvidia-gpu.*e0000000' \
    || true)
# Fatal Xid codes — match the code that follows "Xid ... :" (modern 535+ format
# "NVRM: Xid (PCI:0000:01:00): 79, ...")
DMESG_FATAL_XID=$(dmesg 2>/dev/null | grep -iE 'xid' \
    | grep -E ': ?(48|63|64|79|92|94|95)([,. ]|$)' || true)
DMESG_FATAL_LINES=$(printf '%s\n%s\n' "$DMESG_FATAL_LINES" "$DMESG_FATAL_XID" \
    | grep -v '^$' | sort -u || true)

# ── Non-fatal GPU events (recoverable / transient → WARN) ─────
# Broad GPU error/reset/hang/fault/xid scan, but: no plain "warn" keyword, and
# benign noise excluded (probe-attach, firmware-load notices, Corrected PCIe).
DMESG_WARN_LINES=$(dmesg 2>/dev/null | grep -iE \
    '(nvrm|amdgpu).*(error|fail|reset|hang|xid|fault)|'\
'(error|fail|hang|reset|xid|fault).*(nvrm|amdgpu|drm)|'\
'gpu.*(error|fail|hang|reset|xid|fault)|'\
'drm[[:space:]].*:(error|fault|hang|reset)' \
    | grep -v 'nvidia-gpu.*i2c timeout' \
    | grep -v 'nvidia-gpu.*e0000000' \
    | grep -viE 'probe routine failed|Direct firmware load|severity=Corrected' \
    || true)
# Drop any line already classified as FATAL so it is not double-counted.
if [[ -n "$DMESG_FATAL_LINES" && -n "$DMESG_WARN_LINES" ]]; then
    DMESG_WARN_LINES=$(comm -23 \
        <(sort -u <<< "$DMESG_WARN_LINES") \
        <(sort -u <<< "$DMESG_FATAL_LINES") || true)
fi

DMESG_FATAL_COUNT=0
[[ -n "$DMESG_FATAL_LINES" ]] && DMESG_FATAL_COUNT=$(grep -c '.' <<< "$DMESG_FATAL_LINES" 2>/dev/null || echo 0)
DMESG_WARN_COUNT=0
[[ -n "$DMESG_WARN_LINES" ]] && DMESG_WARN_COUNT=$(grep -c '.' <<< "$DMESG_WARN_LINES" 2>/dev/null || echo 0)

# Combined list + total (used for the JSON report and the summary count).
DMESG_GPU_LINES=$(printf '%s\n%s\n' "$DMESG_FATAL_LINES" "$DMESG_WARN_LINES" | grep -v '^$' || true)
DMESG_ERROR_COUNT=$(( DMESG_FATAL_COUNT + DMESG_WARN_COUNT ))

# ── Status ────────────────────────────────────────────────────
DMESG_STATUS="PASS"
if [[ "$DMESG_FATAL_COUNT" -gt 0 ]]; then
    DMESG_STATUS="FAIL"
    err "dmesg FATAL GPU errors ($DMESG_FATAL_COUNT) — hardware-fault signals:"
    echo "$DMESG_FATAL_LINES" | head -20
elif [[ "$DMESG_WARN_COUNT" -gt 0 ]]; then
    DMESG_STATUS="WARN"
    warn "dmesg non-fatal GPU events ($DMESG_WARN_COUNT) — recoverable/transient, not failing:"
    echo "$DMESG_WARN_LINES" | head -10
else
    ok "No GPU errors in dmesg"
fi

# T32 — Build JSON array (fatal + non-fatal lines combined)
DMESG_ERRORS_JSON=$(echo "$DMESG_GPU_LINES" \
    | grep -v '^$' \
    | jq -Rn '[inputs | select(length > 0)]' 2>/dev/null \
    || echo "[]")

# ============================================================
# Phase 8 — PASS / WARN / FAIL Determination
# ============================================================
banner "Step 7: Overall Verdict"

OVERALL_RESULT="PASS"

# T33 — Apply rules from skill.md §6
if [[ "$VRAM_ERRORS" -gt 0 ]]; then
    OVERALL_RESULT="FAIL"
    err "→ FAIL: VRAM errors ($VRAM_ERRORS)"
fi
if [[ "$DMESG_STATUS" == "FAIL" ]]; then
    OVERALL_RESULT="FAIL"
    err "→ FAIL: dmesg GPU errors detected"
fi
if [[ "$THERMAL_STATUS" == "FAIL" ]]; then
    OVERALL_RESULT="FAIL"
    err "→ FAIL: Temperature threshold exceeded"
fi

if [[ "$OVERALL_RESULT" != "FAIL" ]]; then
    if [[ "$THERMAL_STATUS" == "WARN" ]]; then
        OVERALL_RESULT="WARN"
        warn "→ WARN: Temperature elevated"
    fi
    if [[ "$VKMARK_STATUS" == "WARN" ]]; then
        OVERALL_RESULT="WARN"
        warn "→ WARN: glmark2 benchmark issue (score: $VKMARK_SCORE)"
    fi
    if [[ "$DMESG_STATUS" == "WARN" ]]; then
        OVERALL_RESULT="WARN"
        warn "→ WARN: non-fatal dmesg GPU events ($DMESG_WARN_COUNT)"
    fi
fi

# INFO_ONLY tier overrides all — no stress tests were run
if [[ "$TEST_TIER" == "INFO_ONLY" ]]; then
    OVERALL_RESULT="INFO_ONLY"
fi

# PCIe info only — not a WARN (many cards e.g. Quadro P400 are designed for x4 bandwidth)

# T34 — Print verdict table
echo ""
echo "############################################################"
case "$OVERALL_RESULT" in
    PASS)      echo -e "        TEST VERDICT: ${GREEN}${BOLD}✅  PASS${NC}" ;;
    WARN)      echo -e "        TEST VERDICT: ${YELLOW}${BOLD}⚠️   WARN${NC}" ;;
    FAIL)      echo -e "        TEST VERDICT: ${RED}${BOLD}❌  FAIL${NC}" ;;
    INFO_ONLY) echo -e "        TEST RESULT:  ${CYAN}${BOLD}ℹ️   INFO ONLY (low VRAM / legacy card)${NC}" ;;
esac
echo "############################################################"
printf "  %-22s %s\n" "GPU:"             "$GPU_NAME"
printf "  %-22s %s MB (%s)\n" "VRAM:"   "$GPU_VRAM_MB" "$GPU_VRAM_TYPE"
if [[ "$TEST_TIER" == "INFO_ONLY" ]]; then
    printf "  %-22s %s\n" "Note:" "Stress tests skipped — VRAM < 4096MB"
    printf "  %-22s %s\n" "Suitable for:" "office / display / light workloads"
else
    printf "  %-22s %s\n" "VRAM Errors:"     "$VRAM_ERRORS"
    printf "  %-22s %s°C / Avg %s°C\n" "Temp Max/Avg:" "$TEMP_MAX" "$TEMP_AVG"
    printf "  %-22s %s W\n" "Power Max:"     "$POWER_MAX"
    printf "  %-22s %s\n" "glmark2 Score:"   "$VKMARK_SCORE"
    printf "  %-22s %s (fatal:%s warn:%s)\n" "dmesg Events:" "$DMESG_ERROR_COUNT" "$DMESG_FATAL_COUNT" "$DMESG_WARN_COUNT"
fi
echo "############################################################"

# ============================================================
# Phase 9 — JSON Construction & Upload
# ============================================================
banner "Step 8: Building JSON Report"

# Surface a known VRAM type (GDDR5/GDDR6/HBM2/etc.) as a mark — skip N/A / Unknown
if [[ -n "$GPU_VRAM_TYPE" && "$GPU_VRAM_TYPE" != "N/A" && "$GPU_VRAM_TYPE" != "Unknown" ]]; then
    if [[ -n "$MARK" ]]; then
        MARK="${MARK};${GPU_VRAM_TYPE}"
    else
        MARK="$GPU_VRAM_TYPE"
    fi
fi

TEST_END_TIME=$(date '+%Y-%m-%d %H:%M:%S')
TEST_END_EPOCH=$(date +%s)
TOTAL_DURATION=$(( TEST_END_EPOCH - TEST_START_EPOCH ))
if [[ "$TEST_TIER" == "INFO_ONLY" ]]; then
    SUMMARY="GPU:${GPU_NAME} VRAM:${GPU_VRAM_MB}MB MODE:INFO_ONLY"
else
    SUMMARY="GPU:${GPU_NAME} VRAM:${GPU_VRAM_MB}MB TEMP_MAX:${TEMP_MAX}C VKMARK:${VKMARK_SCORE} RESULT:${OVERALL_RESULT}"
fi

# Sanitize string values via esc()
GPU_NAME_ESC=$(esc "$GPU_NAME")
GPU_CHIP_ESC=$(esc "$GPU_CHIP")
GPU_DRIVER_ESC=$(esc "$GPU_DRIVER")
GPU_BIOS_ESC=$(esc "$GPU_BIOS")
GPU_VRAM_TYPE_ESC=$(esc "${GPU_VRAM_TYPE:-Unknown}")
GPU_SUBVENDOR_ESC=$(esc "$GPU_SUBVENDOR")
GPU_DEVICE_ID_ESC=$(esc "$GPU_DEVICE_ID")
GPU_SN_ESC=$(esc "${GPU_SN:-}")
GPU_LEGACY_DRIVER_ESC=$(esc "${GPU_LEGACY_DRIVER:-}")
GPU_COMPUTE_ARCH_ESC=$(esc "${GPU_COMPUTE_ARCH:-}")
SUMMARY_ESC=$(esc "$SUMMARY")

# T35 — Build JSON with jq -n
jq -n \
    --arg  module             "gpu" \
    --arg  sn                 "$TRACKING_ID" \
    --arg  timestamp          "$TEST_END_TIME" \
    --arg  overall_result     "$OVERALL_RESULT" \
    --arg  summary            "$SUMMARY_ESC" \
    --arg  test_hostname      "$TEST_HOSTNAME" \
    --argjson total_duration  "${TOTAL_DURATION}" \
    --argjson glmark2_duration "${GLMARK2_DURATION:-0}" \
    --arg  script_version     "$SCRIPT_VERSION" \
    --arg  test_tier          "$TEST_TIER" \
    --argjson burn_duration   "${BURN_DURATION}" \
    --arg  gpu_vendor         "$VENDOR" \
    --arg  gpu_name           "$GPU_NAME_ESC" \
    --arg  gpu_chip           "$GPU_CHIP_ESC" \
    --argjson gpu_vram_mb     "${GPU_VRAM_MB}" \
    --arg  gpu_vram_type      "$GPU_VRAM_TYPE_ESC" \
    --argjson gpu_vram_bw     "${GPU_VRAM_BANDWIDTH}" \
    --argjson gpu_vram_bus    "${GPU_VRAM_BUS_WIDTH}" \
    --arg  gpu_driver         "$GPU_DRIVER_ESC" \
    --arg  gpu_legacy_driver  "$GPU_LEGACY_DRIVER_ESC" \
    --arg  gpu_bios           "$GPU_BIOS_ESC" \
    --argjson gpu_pcie_gen    "${GPU_PCIE_GEN}" \
    --argjson pcie_gen_cur    "${GPU_PCIE_GEN_CUR:-0}" \
    --argjson pcie_width_cur  "${GPU_PCIE_WIDTH_CUR}" \
    --argjson pcie_width_max  "${GPU_PCIE_WIDTH_MAX}" \
    --argjson gpu_clk_gpu     "${GPU_CLOCK_GPU}" \
    --argjson gpu_clk_mem     "${GPU_CLOCK_MEM}" \
    --arg  gpu_power_limit    "${GPU_POWER_LIMIT:-N/A}" \
    --arg  gpu_subvendor      "$GPU_SUBVENDOR_ESC" \
    --arg  gpu_device_id      "$GPU_DEVICE_ID_ESC" \
    --arg  gpu_sn             "$GPU_SN_ESC" \
    --arg  gpu_compute_arch   "$GPU_COMPUTE_ARCH_ESC" \
    --argjson gpu_clk_base_gpu "${GPU_CLOCK_BASE_GPU}" \
    --argjson gpu_clk_base_mem "${GPU_CLOCK_BASE_MEM}" \
    --argjson temp_max        "${TEMP_MAX}" \
    --argjson temp_avg        "${TEMP_AVG}" \
    --argjson util_avg        "${UTIL_AVG}" \
    --argjson power_max       "${POWER_MAX}" \
    --arg  thermal_log        "$THERMAL_LOG" \
    --arg  vram_tool          "$VRAM_TOOL" \
    --argjson vram_errors     "${VRAM_ERRORS}" \
    --arg  vram_status        "$VRAM_STATUS" \
    --argjson vkmark_score    "${VKMARK_SCORE}" \
    --arg  vkmark_status      "$VKMARK_STATUS" \
    --argjson dmesg_errors    "$DMESG_ERRORS_JSON" \
    --arg  operator_id        "$OPERATOR_ID" \
    --arg  manual_weight      "$WEIGHT_LBS" \
    --arg  manual_grade       "$GRADE_FULL" \
    --arg  manual_condition   "$CONDITION_FULL" \
    --arg  manual_color       "$COLOR" \
    --arg  manual_mark        "$MARK" \
    '{
        "module":        $module,
        sn:             $sn,
        timestamp:      $timestamp,
        overall_result: $overall_result,
        summary:        $summary,
        payload: {
            test_info: {
                test_time:             $timestamp,
                test_station:          $test_hostname,
                operator_id:           $operator_id,
                test_tier:             $test_tier,
                script_version:        $script_version,
                burn_duration_seconds:   $burn_duration,
                glmark2_duration_seconds: $glmark2_duration,
                total_duration_seconds:  $total_duration
            },
            gpu: {
                vendor:              $gpu_vendor,
                name:                $gpu_name,
                chip:                $gpu_chip,
                vram_mb:             $gpu_vram_mb,
                vram_type:           $gpu_vram_type,
                vram_bus_width:      $gpu_vram_bus,
                vram_bandwidth_gbps: $gpu_vram_bw,
                driver_version:      $gpu_driver,
                legacy_driver_needed: $gpu_legacy_driver,
                bios_version:        $gpu_bios,
                pcie_gen:            $gpu_pcie_gen,
                pcie_gen_current:    $pcie_gen_cur,
                pcie_width_current:  $pcie_width_cur,
                pcie_width_max:      $pcie_width_max,
                clock_boost_gpu_mhz: $gpu_clk_gpu,
                clock_boost_mem_mhz: $gpu_clk_mem,
                clock_base_gpu_mhz:  $gpu_clk_base_gpu,
                clock_base_mem_mhz:  $gpu_clk_base_mem,
                compute_arch:        $gpu_compute_arch,
                power_limit_w:       $gpu_power_limit,
                subvendor:           $gpu_subvendor,
                device_id:           $gpu_device_id,
                gpu_sn:              $gpu_sn
            },
            thermal: {
                temp_max_c:        $temp_max,
                temp_avg_c:        $temp_avg,
                util_avg_pct:      $util_avg,
                power_max_w:       $power_max,
                thermal_log_path:  $thermal_log
            },
            vram_test: {
                tool:             $vram_tool,
                duration_seconds: $burn_duration,
                errors:           $vram_errors,
                status:           $vram_status
            },
            vulkan_benchmark: {
                tool:        "glmark2",
                resolution:  "1920x1080",
                score:       $vkmark_score,
                status:      $vkmark_status
            },
            manual_input: {
                weight_lbs: $manual_weight,
                grade:      $manual_grade,
                condition:  $manual_condition,
                color:      $manual_color,
                mark:       $manual_mark
            },
            dmesg_gpu_errors: $dmesg_errors,
            overall_result:   $overall_result
        }
    }' > "$JSON_FILE"

# T36 — Validate JSON
if jq '.' "$JSON_FILE" >/dev/null 2>&1; then
    ok "JSON report saved: $JSON_FILE"
else
    err "JSON validation failed — check $JSON_FILE"
    safe_exit 3
fi

# T37 — Upload helper (3 retries). Sets UPLOAD_OK; uploads current $JSON_FILE.
UPLOAD_OK=0
do_upload() {
    UPLOAD_OK=0
    local i HTTP_CODE
    for i in 1 2 3; do
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
            --connect-timeout 10 \
            --max-time 30 \
            -X POST "$UPLOAD_URL" \
            -H "Content-Type: application/json" \
            -d @"$JSON_FILE" 2>/dev/null || echo "000")

        if [[ "$HTTP_CODE" =~ ^2 ]]; then
            ok "Upload success (HTTP $HTTP_CODE) on attempt $i."
            UPLOAD_OK=1
            break
        else
            warn "Upload attempt $i/3 failed (HTTP $HTTP_CODE). Retrying in 5s..."
            sleep 5
        fi
    done
    # T38 — Retain local file on failure
    if [[ "$UPLOAD_OK" -eq 0 ]]; then
        err "All upload attempts failed. Report retained locally: $JSON_FILE"
    fi
    printf "  %-22s %s\n" "UPLOAD:" "$( [[ "$UPLOAD_OK" -eq 1 ]] && echo "OK" || echo "FAILED — $JSON_FILE" )"
}

banner "Step 9: Uploading Report"
# Upload now only if the SN is already final (scanned at start).
# If no SN was scanned, defer the upload until after the Phase 10 re-scan
# so the report is sent exactly once — with the correct SN — avoiding
# duplicate records on the server.
if [[ -n "$CARD_LABEL" ]]; then
    do_upload
else
    ok "Upload deferred — will send once after SN is confirmed."
fi
printf "  %-22s %s\n" "LOG DIR:" "$LOG_DIR"

# ============================================================
# Phase 10 — Final Verdict Display + Shutdown
# ============================================================
[[ "$OVERALL_RESULT" == "FAIL" ]] && touch /var/log/gpu_fail.flag 2>/dev/null || true

# ── SN re-scan + deferred upload (BEFORE the verdict) ─────────
# When no SN was scanned at start, the upload was deferred in Step 9.
# Finalize the SN and upload here — BEFORE show_verdict_screen — so the
# verdict reflects the real upload status (UPLOAD_OK). Doing it after the
# verdict would make the screen show a stale "Upload: FAILED".
# This also guarantees the report is sent exactly once with the final SN.
if [[ -z "$CARD_LABEL" ]]; then
    echo ""
    echo -e "  ${YELLOW}No SN was scanned at start. Scan card SN now (or Enter to skip):${NC}"
    read -t 3600 -r _rescan </dev/tty || true
    _rescan=$(echo "$_rescan" | tr -cd 'A-Za-z0-9_.-' | cut -c1-50)
    if [[ -n "$_rescan" ]]; then
        _new_json="$LOG_DIR/${_rescan}.json"
        if command -v jq &>/dev/null; then
            jq --arg sn "$_rescan" '.sn = $sn' "$JSON_FILE" > "$_new_json" && \
                rm -f "$JSON_FILE" && \
                JSON_FILE="$_new_json" && \
                TRACKING_ID="$_rescan"
            ok "SN updated: $TRACKING_ID  →  $JSON_FILE"
        fi
    else
        warn "No SN scanned — keeping auto-generated ID: $TRACKING_ID"
    fi
    # Deferred single upload with the now-final SN
    banner "Uploading Report"
    do_upload
fi

# Compute shutdown exit code after upload status is known (UPLOAD_OK is set
# either in Step 9 or in the deferred upload above).
_shutdown_exit_code=0
[[ "$OVERALL_RESULT" == "FAIL" ]] && _shutdown_exit_code=1
[[ "${UPLOAD_OK:-0}" -eq 0 && "$_shutdown_exit_code" -eq 0 ]] && _shutdown_exit_code=4

# ── Terminal verdict (shown on tty1; includes shutdown prompt) ─
# Now UPLOAD_OK is final, so the INFO_ONLY upload line is accurate.
show_verdict_screen "$OVERALL_RESULT"

trap '
    echo ""
    echo -e "  ${YELLOW}Shutdown cancelled.  Run: sudo poweroff${NC}"
    echo ""
    trap - INT
    safe_exit '"$_shutdown_exit_code"'
' INT

read -r -s
trap - INT

echo -e "  ${BOLD}Shutting down...${NC}"
sleep 1
poweroff
