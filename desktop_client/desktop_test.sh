#!/bin/bash
# ============================================================
# desktop_test.sh — Desktop PC Hardware Test (non-interactive)
# Usage: sudo bash desktop_test.sh
# ============================================================

UPLOAD_URL="http://192.168.30.18:8080/desktop/api/upload"
API_KEY="ceartrack-upload-2026"
REPORT_FILE="/tmp/desktop_report_$(date +%Y%m%d_%H%M%S).json"
PASS="PASS"
FAIL="FAIL"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

banner() { echo -e "\n${CYAN}${BOLD}=== $1 ===${NC}"; }
ok()     { echo -e "  ${GREEN}\xe2\x9c\x93 $1${NC}"; }
warn()   { echo -e "  ${YELLOW}\xe2\x9a\xa0 $1${NC}"; }
err()    { echo -e "  ${RED}\xe2\x9c\x97 $1${NC}"; }

# JSON string escaper — defined early so it is available in all sections
esc() { echo "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }

if [[ $EUID -ne 0 ]]; then
  echo -e "${RED}Please run with sudo: sudo bash desktop_test.sh${NC}"; exit 1
fi

# ============================================================
# INSTALL DEPENDENCIES
# ============================================================
banner "Checking dependencies"
PKGS=(dmidecode smartmontools util-linux pciutils usbutils curl jq bc iw ethtool)
for pkg in "${PKGS[@]}"; do
  if ! dpkg -s "$pkg" &>/dev/null 2>&1; then
    warn "Installing $pkg ..."
    apt-get install -y -q "$pkg" 2>/dev/null
  fi
done
ok "Dependencies ready."

# ============================================================
# OPERATOR ID
# ============================================================
banner "Operator Information"
read -rp "  Enter Operator ID: " OPERATOR_ID </dev/tty
OPERATOR_ID="${OPERATOR_ID:-unknown}"
ok "Operator: $OPERATOR_ID"

# ============================================================
# 1. SYSTEM INFO
# ============================================================
banner "1. System Info"
SYS_VENDOR=$(dmidecode -s system-manufacturer 2>/dev/null | tr -d '\n')
SYS_MODEL=$(dmidecode -s system-product-name 2>/dev/null | tr -d '\n')
SYS_SERIAL=$(dmidecode -s system-serial-number 2>/dev/null | tr -d '\n')
BIOS_VER=$(dmidecode -s bios-version 2>/dev/null | tr -d '\n')
TEST_TIME=$(date +"%Y-%m-%dT%H:%M:%S%z")
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
ok "${MEM_TOTAL_GB} GB | Type: ${MEM_TYPE:-unknown} | Speed: ${MEM_SPEED:-unknown} | Slots: ${MEM_USED_SLOTS}/${MEM_SLOTS}"

# ============================================================
# 4. STORAGE (reuse laptop_test.sh SSD grading logic)
# ============================================================
banner "4. Storage"
DISK_STATUS=$PASS
DISK_JSON="["
first=1
NEEDS_DISK_REPLACEMENT=0

USB_DISKS=$(lsblk -d -o NAME,TRAN 2>/dev/null | awk '$2=="usb"{print $1}')

while IFS= read -r disk; do
  [[ -z "$disk" ]] && continue
  name=$(basename "$disk")

  if echo "$USB_DISKS" | grep -q "^${name}$"; then
    warn "Skipping $name (USB transport) — not internal storage."
    continue
  fi

  size=$(lsblk -dn -o SIZE "$disk" 2>/dev/null | xargs)
  model=$(cat /sys/block/$name/device/model 2>/dev/null | xargs)
  rotational=$(cat /sys/block/$name/queue/rotational 2>/dev/null)
  disk_type="HDD"
  [[ "$rotational" == "0" ]] && disk_type="SSD"
  [[ "$disk" == *"nvme"* ]] && disk_type="SSD NVMe"

  SMART_X=$(smartctl -x "$disk" 2>/dev/null)

  if echo "$SMART_X" | grep -qE "PASSED|OK"; then
    smart="PASSED"
  elif echo "$SMART_X" | grep -q "FAILED"; then
    smart="FAILED"
    DISK_STATUS=$FAIL
    NEEDS_DISK_REPLACEMENT=1
    err "Disk $name SMART FAILED — replace before resale!"
  else
    smart="UNKNOWN"
  fi

  SSD_HEALTH_PCT="unknown"; SSD_GRADE="unknown"
  SSD_AVAIL_SPARE="unknown"; SSD_DATA_WRITTEN="unknown"
  power_hours="unknown"

  if [[ "$disk_type" == "SSD NVMe" ]]; then
    PCT_USED=$(echo "$SMART_X" | grep "^Percentage Used:" | grep -oP '\d+(?=%)' | head -1)
    AVAIL_SPARE=$(echo "$SMART_X" | grep "^Available Spare:" | grep -oP '\d+(?=%)' | head -1)
    SSD_DATA_WRITTEN=$(echo "$SMART_X" | grep "^Data Units Written:" | grep -oP '\[.*?\]' | tr -d '[]' | head -1)
    power_hours=$(echo "$SMART_X" | grep "^Power On Hours:" | awk '{print $NF}' | tr -d ',' | head -1)
    [[ -n "$AVAIL_SPARE" ]] && SSD_AVAIL_SPARE="${AVAIL_SPARE}%"
    [[ -n "$PCT_USED" ]] && SSD_HEALTH_PCT=$((100 - PCT_USED))
  elif [[ "$disk_type" == "SSD" ]]; then
    PCT_USED=$(echo "$SMART_X" | grep "Percentage Used Endurance Indicator" | awk '{print $4}' | head -1)
    SSD_AVAIL_SPARE="N/A"; SSD_DATA_WRITTEN="N/A"
    [[ -n "$PCT_USED" && "$PCT_USED" =~ ^[0-9]+$ ]] && SSD_HEALTH_PCT=$((100 - PCT_USED))
    power_hours=$(echo "$SMART_X" | awk '/Power_On_Hours/{print $10}' | head -1)
  else
    power_hours=$(echo "$SMART_X" | awk '/Power_On_Hours/{print $10}' | head -1)
  fi

  if [[ "$SSD_HEALTH_PCT" != "unknown" ]]; then
    if   [[ $SSD_HEALTH_PCT -ge 95 ]]; then SSD_GRADE="A"
    elif [[ $SSD_HEALTH_PCT -ge 80 ]]; then SSD_GRADE="B"
    elif [[ $SSD_HEALTH_PCT -ge 70 ]]; then SSD_GRADE="C"
    else SSD_GRADE="D"
    fi
  fi

  ok "$name | ${model:-unknown} | $size | $disk_type | SMART: $smart | Grade: $SSD_GRADE"

  [[ $first -eq 0 ]] && DISK_JSON+=","
  DISK_JSON+="{\"device\":\"$(esc "$name")\",\"model\":\"$(esc "${model:-unknown}")\",\"size\":\"$(esc "${size:-unknown}")\",\"type\":\"$(esc "$disk_type")\",\"smart\":\"$(esc "$smart")\",\"power_on_hours\":\"$(esc "${power_hours:-unknown}")\",\"ssd_health_percent\":\"${SSD_HEALTH_PCT}\",\"ssd_grade\":\"${SSD_GRADE}\",\"ssd_available_spare\":\"$(esc "${SSD_AVAIL_SPARE}")\",\"ssd_data_written\":\"$(esc "${SSD_DATA_WRITTEN}")\"}"
  first=0
done < <(lsblk -dpn -o PATH 2>/dev/null | grep -E "^/dev/(sd|nvme|hd)")
DISK_JSON+="]"

if [[ $first -eq 1 ]]; then
  DISK_STATUS=$FAIL
  err "No internal storage detected."
  if echo "$SYS_VENDOR" | grep -qi "dell"; then
    warn "Dell detected — check BIOS: SATA Operation may be set to RAID, change to AHCI."
  fi
  DISK_JSON='[{"device":"none","model":"NOT DETECTED","size":"","type":"","smart":"FAIL","power_on_hours":"","ssd_health_percent":"unknown","ssd_grade":"unknown","ssd_available_spare":"unknown","ssd_data_written":"unknown"}]'
fi

# ============================================================
# 5. GPU (info collection only — GPU stress test is a separate module)
# ============================================================
banner "5. Graphics Card"

GPU_JSON="["
gfirst=1

# Enumerate all VGA/3D controllers via lspci
while IFS= read -r line; do
  [[ -z "$line" ]] && continue
  pci_addr=$(echo "$line" | awk '{print $1}')
  gpu_name=$(echo "$line" | cut -d: -f3 | xargs)

  # Determine integrated vs discrete (best-effort classification)
  gpu_class="discrete"
  if echo "$gpu_name" | grep -qiE "intel.*(uhd|iris|hd graphics)|integrated"; then
    gpu_class="integrated"
  fi

  # Try to get VRAM size via lspci -v (memory region size)
  vram=$(lspci -v -s "$pci_addr" 2>/dev/null | grep -oP 'Memory at.*\[size=\K[0-9]+[MG]' | sort -rh | head -1)
  [[ -z "$vram" ]] && vram="unknown"

  # Fallback: try nvidia-smi if available (requires driver, often not present on Live USB)
  if [[ "$vram" == "unknown" ]] && command -v nvidia-smi &>/dev/null; then
    vram_mb=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1)
    [[ -n "$vram_mb" ]] && vram="${vram_mb}MiB"
  fi

  ok "GPU: $gpu_name | Class: $gpu_class | VRAM: $vram"

  [[ $gfirst -eq 0 ]] && GPU_JSON+=","
  GPU_JSON+="{\"name\":\"$(esc "$gpu_name")\",\"class\":\"$gpu_class\",\"vram\":\"$(esc "$vram")\",\"pci_address\":\"$(esc "$pci_addr")\"}"
  gfirst=0
done < <(lspci 2>/dev/null | grep -iE "VGA compatible controller|3D controller")

GPU_JSON+="]"

if [[ $gfirst -eq 1 ]]; then
  warn "No GPU detected via lspci"
  GPU_JSON="[]"
fi

# ── Placeholder hook: discrete GPU stress test (future module) ──
# GPU stress testing is a separate independent module (own JSON schema,
# own upload endpoint /gpu/api/upload). Not implemented yet — no prompt,
# no execution. This is purely a placeholder for future integration.
#
# Future implementation will check for a discrete GPU and call:
#   GPU_TEST_SCRIPT="/opt/ceartrack-scripts/gpu_test.sh"
#   [[ -f "$GPU_TEST_SCRIPT" ]] && bash "$GPU_TEST_SCRIPT"
#
# Not active in this version — desktop_test.sh only collects GPU info.

# ============================================================
# 6. NETWORK (wired only)
# ============================================================
banner "6. Network"
ETH_DEV=$(ip -o link show 2>/dev/null | awk -F': ' '{print $2}' | grep -vE "^lo$|^wl" | head -1)
ETH_STATUS=$FAIL
INTERNET_TEST="NO_ETH_DEVICE"

if [[ -n "$ETH_DEV" ]]; then
  ETH_STATUS=$PASS
  ok "Ethernet: $ETH_DEV"
  if curl -s --max-time 5 --interface "$ETH_DEV" \
     http://connectivitycheck.gstatic.com/generate_204 -o /dev/null -w "%{http_code}" 2>/dev/null \
     | grep -q "204"; then
    INTERNET_TEST=$PASS
    ok "Internet: connected via $ETH_DEV"
  else
    INTERNET_TEST=$FAIL
    warn "Internet: no connectivity via $ETH_DEV"
  fi
else
  err "No ethernet device found."
fi

# ============================================================
# 7. PSU (best-effort, often not readable)
# ============================================================
banner "7. Power Supply"
PSU_INFO=$(dmidecode -t 39 2>/dev/null | grep -E "Max Power Capacity|Manufacturer" | head -2)
if [[ -n "$PSU_INFO" ]]; then
  ok "PSU info available"
else
  warn "PSU info not readable via DMI (common — not all desktops expose this)"
fi
PSU_MAXPOWER=$(echo "$PSU_INFO" | grep "Max Power" | cut -d: -f2 | xargs)
PSU_MANUFACTURER=$(echo "$PSU_INFO" | grep "Manufacturer" | cut -d: -f2 | xargs)

# ============================================================
# BUILD JSON REPORT
# ============================================================
banner "Generating Report"

OVERALL=$PASS
[[ "$DISK_STATUS" == "$FAIL" ]] && OVERALL=$FAIL

JSON=$(cat <<EOF
{
  "test_info": {
    "test_time": "$(esc "$TEST_TIME")",
    "hostname": "$(esc "$HOSTNAME")",
    "script_version": "1.0.0",
    "operator_id": "$(esc "$OPERATOR_ID")"
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
  "gpu": ${GPU_JSON},
  "network": {
    "ethernet_status": "$(esc "$ETH_STATUS")",
    "ethernet_device": "$(esc "${ETH_DEV:-none}")",
    "internet_test": "$(esc "$INTERNET_TEST")"
  },
  "psu": {
    "manufacturer": "$(esc "${PSU_MANUFACTURER:-unknown}")",
    "max_power": "$(esc "${PSU_MAXPOWER:-unknown}")"
  },
  "overall_result": "$OVERALL"
}
EOF
)

if command -v jq &>/dev/null && echo "$JSON" | jq . &>/dev/null; then
  echo "$JSON" | jq . > "$REPORT_FILE"
  ok "Report saved: $REPORT_FILE"
else
  echo "$JSON" > "$REPORT_FILE"
fi

# ============================================================
# UPLOAD
# ============================================================
banner "Uploading Report"
HTTP_CODE=$(curl -s -o /tmp/upload_response.txt -w "%{http_code}" \
  -X POST "$UPLOAD_URL" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d @"$REPORT_FILE" \
  --connect-timeout 10 --max-time 30)

if [[ "$HTTP_CODE" == "200" || "$HTTP_CODE" == "201" ]]; then
  ok "Upload successful (HTTP $HTTP_CODE)"
else
  err "Upload failed (HTTP ${HTTP_CODE:-no response})"
  warn "Report kept locally: $REPORT_FILE"
fi

# ============================================================
# SUMMARY
# ============================================================
banner "TEST SUMMARY"
echo ""
printf "  %-20s %s\n" "Operator:" "$OPERATOR_ID"
printf "  %-20s %s\n" "Vendor/Model:" "$SYS_VENDOR $SYS_MODEL"
printf "  %-20s %s\n" "Serial:" "$SYS_SERIAL"
printf "  %-20s %s\n" "CPU:" "$CPU_MODEL"
printf "  %-20s %s\n" "Memory:" "${MEM_TOTAL_GB} GB ${MEM_TYPE}"
printf "  %-20s %s\n" "Storage:" "$DISK_STATUS"
printf "  %-20s %s\n" "Ethernet:" "$ETH_STATUS | Internet: $INTERNET_TEST"
echo ""
if [[ "$OVERALL" == "PASS" ]]; then
  echo -e "  ${GREEN}${BOLD}RESULT: \xe2\x9c\x93 PASS — Ready for resale${NC}"
else
  echo -e "  ${RED}${BOLD}RESULT: \xe2\x9c\x97 FAIL — Replace storage before resale${NC}"
fi
echo ""
echo -e "  Report: $REPORT_FILE"
echo ""
