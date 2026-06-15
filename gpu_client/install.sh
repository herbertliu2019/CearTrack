#!/bin/bash
# ============================================================
# install.sh — GPU Test Station Environment Setup
# Ubuntu 22.04 LTS (Jammy)
# Supports: NVIDIA + AMD discrete GPUs
# Usage: sudo bash install.sh
# NOTE: Run inside screen to protect against SSH disconnect:
#   screen -S setup
#   sudo bash install.sh
# ============================================================

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

banner() { echo -e "\n${CYAN}${BOLD}=== $1 ===${NC}"; }
ok()     { echo -e "  ${GREEN}✓ $1${NC}"; }
warn()   { echo -e "  ${YELLOW}⚠ $1${NC}"; }
err()    { echo -e "  ${RED}✗ $1${NC}"; }

# ── Root check ────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    err "Please run with sudo: sudo bash install.sh"
    exit 1
fi

# ── Screen check ──────────────────────────────────────────────
if [[ -z "${STY:-}${TMUX:-}" ]]; then
    warn "Not running inside screen or tmux."
    warn "SSH disconnect will interrupt this installation."
    echo ""
    echo "  Recommended:"
    echo "    screen -S setup"
    echo "    sudo bash install.sh"
    echo ""
    read -t 15 -p "  Continue anyway? (y/N, auto-cancel in 15s): " CONFIRM || true
    [[ "${CONFIRM:-N}" != "y" && "${CONFIRM:-N}" != "Y" ]] && { echo "Cancelled."; exit 1; }
fi

echo -e "${BOLD}>>> GPU Test Station Install${NC}"
echo "Ubuntu: $(lsb_release -rs) | Kernel: $(uname -r)"
echo "Start:  $(date)"
echo ""

# ============================================================
# Step 1 — System Update
# ============================================================
banner "Step 1: System Update"
apt-get update -qq
ok "Package lists updated."

# ============================================================
# Step 2 — Base Tools
# ============================================================
banner "Step 2: Base Tools"
apt-get install -y -qq \
    screen \
    pciutils \
    jq \
    curl \
    wget \
    dmidecode \
    xorg \
    glmark2 \
    radeontop \
    htop \
    nano \
    2>/dev/null
ok "Base tools installed."

# ============================================================
# Step 3 — Detect GPU Vendor
# ============================================================
banner "Step 3: GPU Vendor Detection"
LSPCI_OUT=$(lspci | grep -iE 'vga|3d|display')
echo "$LSPCI_OUT"

HAS_NVIDIA=0
HAS_AMD=0
echo "$LSPCI_OUT" | grep -qi 'nvidia' && HAS_NVIDIA=1
echo "$LSPCI_OUT" | grep -qi 'amd\|ati' && HAS_AMD=1

[[ "$HAS_NVIDIA" -eq 1 ]] && ok "NVIDIA GPU detected"
[[ "$HAS_AMD" -eq 1 ]]    && ok "AMD GPU detected"
[[ "$HAS_NVIDIA" -eq 0 && "$HAS_AMD" -eq 0 ]] && \
    warn "No NVIDIA or AMD GPU detected — installing all drivers anyway"

# ============================================================
# Step 4 — NVIDIA Driver + CUDA
# ============================================================
banner "Step 4: NVIDIA Driver + CUDA"

if nvidia-smi &>/dev/null; then
    ok "NVIDIA driver already installed and working."
else
    ok "Adding NVIDIA CUDA repo..."
    CUDA_DEB="/tmp/cuda-keyring_1.1-1_all.deb"
    wget -q https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-keyring_1.1-1_all.deb \
        -O "$CUDA_DEB"
    dpkg -i "$CUDA_DEB" >/dev/null 2>&1
    rm -f "$CUDA_DEB"
    apt-get update -qq

    ok "Installing nvidia-driver-535..."
    ok "This may take 10-30 minutes, do NOT interrupt..."
    apt-get install -y nvidia-driver-535
    ok "NVIDIA driver installed."

    ok "Installing libcublas (required for gpu-burn)..."
    apt-get install -y -qq libcublas-12-5 2>/dev/null
    ok "libcublas installed."
fi

# Install gpu-burn
# Ubuntu 24.04: available via apt
# Ubuntu 22.04: not in apt, must compile from source
if command -v gpu-burn &>/dev/null; then
    ok "gpu-burn already installed."
elif apt-get install -y -qq gpu-burn 2>/dev/null && command -v gpu-burn &>/dev/null; then
    # Ubuntu 24.04 path - apt installs to /usr/sbin, create symlink
    [[ -x /usr/sbin/gpu-burn && ! -x /usr/local/bin/gpu-burn ]] && \
        ln -sf /usr/sbin/gpu-burn /usr/local/bin/gpu-burn
    ok "gpu-burn installed via apt."
else
    # Ubuntu 22.04 path - compile from source
    ok "apt install failed, compiling gpu-burn from source..."
    apt-get install -y -qq build-essential git 2>/dev/null
    cd /tmp
    rm -rf gpu-burn-src
    git clone https://github.com/wilicc/gpu-burn gpu-burn-src
    cd gpu-burn-src
    make 2>/dev/null
    if [[ -x gpu_burn ]]; then
        mkdir -p /usr/share/gpu-burn
        cp compare.ptx /usr/share/gpu-burn/
        cp gpu_burn /usr/local/bin/gpu-burn-bin
        chmod +x /usr/local/bin/gpu-burn-bin
        # Create wrapper so gpu-burn works from any directory
        tee /usr/local/bin/gpu-burn << 'WRAPPER'
#!/bin/bash
cd /usr/share/gpu-burn
exec /usr/local/bin/gpu-burn-bin "$@"
WRAPPER
        chmod +x /usr/local/bin/gpu-burn
        cd /tmp
        ok "gpu-burn compiled and installed."
    else
        err "gpu-burn compilation failed."
    fi
fi

# ============================================================
# Step 5 — AMD ROCm
# ============================================================
banner "Step 5: AMD ROCm (rocm-smi)"

if command -v rocm-smi &>/dev/null; then
    ok "rocm-smi already installed."
else
    ok "Adding AMD ROCm repo..."
    mkdir -p /etc/apt/keyrings
    wget -q https://repo.radeon.com/rocm/rocm.gpg.key -O - | \
        gpg --dearmor | tee /etc/apt/keyrings/rocm.gpg > /dev/null
    echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/rocm.gpg] \
https://repo.radeon.com/rocm/apt/latest jammy main" \
        | tee /etc/apt/sources.list.d/rocm.list > /dev/null
    apt-get update -qq

    ok "Installing rocm-smi-lib..."
    apt-get install -y -qq rocm-smi-lib 2>/dev/null
    ln -sf /opt/rocm/bin/rocm-smi /usr/local/bin/rocm-smi
    ok "rocm-smi installed."
fi

# ============================================================
# Step 6 — Blacklist nouveau
# ============================================================
banner "Step 6: Blacklist nouveau"

if [[ ! -f /etc/modprobe.d/blacklist-nouveau.conf ]]; then
    echo "blacklist nouveau"         > /etc/modprobe.d/blacklist-nouveau.conf
    echo "options nouveau modeset=0" >> /etc/modprobe.d/blacklist-nouveau.conf
    ok "nouveau blacklisted."
else
    ok "nouveau already blacklisted."
fi

# ============================================================
# Step 7 — Disable CPU powersave (performance mode for testing)
# ============================================================
banner "Step 7: CPU Governor"

apt-get install -y -qq cpufrequtils 2>/dev/null
echo 'GOVERNOR="performance"' > /etc/default/cpufrequtils
systemctl enable cpufrequtils 2>/dev/null || true
# Apply immediately
echo performance | tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor &>/dev/null || true
ok "CPU governor set to performance."

# ============================================================
# Step 8 — Xorg VSync config (disable for glmark2)
# ============================================================
banner "Step 8: Xorg Config"

mkdir -p /etc/X11/xorg.conf.d/
cat > /etc/X11/xorg.conf.d/20-nvidia-novsync.conf << 'EOF'
Section "Device"
    Identifier "NVIDIA"
    Driver "nvidia"
    Option "TripleBuffer" "False"
    Option "SwapbuffersWait" "False"
EndSection

Section "Screen"
    Identifier "Default Screen"
    Device "NVIDIA"
    Option "SyncToVBlank" "0"
EndSection
EOF
ok "Xorg VSync disabled for NVIDIA."

# ============================================================
# Step 9 — Copy gpu_test.sh
# ============================================================
banner "Step 9: gpu_test.sh"

mkdir -p /opt/gpurun
if [[ -f "$(dirname "$0")/gpu_test.sh" ]]; then
    cp "$(dirname "$0")/gpu_test.sh" /opt/gpurun/gpu_test.sh
    chmod +x /opt/gpurun/gpu_test.sh
    ok "gpu_test.sh copied to /opt/gpurun/"
else
    warn "gpu_test.sh not found in same directory as install.sh"
    warn "Please copy gpu_test.sh to /opt/gpurun/ manually"
fi

# ============================================================
# Step 10 — Verify
# ============================================================
banner "Step 10: Verification"

check_tool() {
    if command -v "$1" &>/dev/null; then
        ok "$1: $(command -v $1)"
    else
        warn "$1: NOT FOUND"
    fi
}

check_tool nvidia-smi
check_tool rocm-smi
check_tool gpu-burn
check_tool glmark2
check_tool radeontop
check_tool jq
check_tool curl
check_tool dmidecode

# ============================================================
# Done
# ============================================================
echo ""
echo "============================================================"
echo -e "${GREEN}${BOLD}  Installation complete!${NC}"
echo ""
echo "  Next steps:"
echo "  1. Reboot: sudo reboot"
echo "  2. After reboot, verify: nvidia-smi"
echo "  3. Run GPU test: sudo bash /opt/gpurun/gpu_test.sh"
echo "============================================================"
echo "End: $(date)"
