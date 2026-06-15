#!/bin/bash
# ============================================================
# launcher.sh — CearTrack GPU Auto-Update Launcher
# Place this file on the GPU test Live USB. Never needs to be updated.
# ============================================================

# This script uses bash-only features ([[ ]], BASH_SOURCE, echo -e). If it was
# started with `sh`/`dash` (e.g. `sudo sh launcher.sh`), re-exec under bash so it
# works regardless of how the operator launched it.
if [ -z "$BASH_VERSION" ]; then exec bash "$0" "$@"; fi

SERVER="http://192.168.30.18:80"
VERSION_URL="$SERVER/laptop/static/scripts/gpu/version.txt"
SCRIPT_URL="$SERVER/laptop/static/scripts/gpu/gpu_test.sh"
# Companion data file gpu_test.sh expects in its OWN directory (SCRIPT_DIR).
# It must be downloaded next to the cached script or legacy-NVIDIA VRAM lookup breaks.
CONF_URL="$SERVER/laptop/static/scripts/gpu/nvidia_legacy_db.conf"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

# Cache next to this launcher (on the USB) so the downloaded script SURVIVES
# reboots — /tmp is a RAM disk on Live USB and is wiped every boot, forcing a
# re-download each time. Fall back to /tmp only if the USB dir is not writable
# (e.g. read-only mount).
SCRIPT_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CACHE_DIR="$SCRIPT_HOME/.cache/gpu"
if ! mkdir -p "$CACHE_DIR" 2>/dev/null || [[ ! -w "$CACHE_DIR" ]]; then
  CACHE_DIR="/tmp/ceartrack/gpu"
  mkdir -p "$CACHE_DIR"
  echo -e "${YELLOW}⚠ USB not writable — caching in /tmp (will re-download after reboot).${NC}"
fi
CACHED_SCRIPT="$CACHE_DIR/gpu_test.sh"
CACHED_VERSION="$CACHE_DIR/version.txt"
CACHED_CONF="$CACHE_DIR/nvidia_legacy_db.conf"

echo ""
echo -e "${GREEN}CearTrack GPU Test Launcher${NC}"
echo "================================"

# Check network connectivity to server
if ! curl -sf --max-time 5 "$SERVER" > /dev/null 2>&1; then
  echo -e "${YELLOW}⚠ Cannot reach server ($SERVER)${NC}"
  if [[ -f "$CACHED_SCRIPT" ]]; then
    CACHED_VER=$(cat "$CACHED_VERSION" 2>/dev/null || echo "unknown")
    echo -e "${YELLOW}  Using cached version: $CACHED_VER${NC}"
    echo ""
    exec bash "$CACHED_SCRIPT"
  else
    echo -e "${RED}✗ No cached script found. Cannot run without server.${NC}"
    echo "  Connect to network and retry."
    exit 1
  fi
fi

# Get server version
SERVER_VER=$(curl -sf --max-time 5 "$VERSION_URL" 2>/dev/null | tr -d '[:space:]')
if [[ -z "$SERVER_VER" ]]; then
  echo -e "${YELLOW}⚠ Could not read version from server${NC}"
  SERVER_VER="unknown"
fi

# Get local cached version
LOCAL_VER=$(cat "$CACHED_VERSION" 2>/dev/null | tr -d '[:space:]' || echo "none")

echo "  Server version : $SERVER_VER"
echo "  Cached version : $LOCAL_VER"

if [[ "$SERVER_VER" != "unknown" && "$SERVER_VER" != "$LOCAL_VER" ]]; then
  echo ""
  echo -e "${GREEN}  Downloading update: $LOCAL_VER → $SERVER_VER${NC}"
  if curl -sf --max-time 30 "$SCRIPT_URL" -o "$CACHED_SCRIPT.tmp"; then
    # Verify download is a valid bash script
    if bash -n "$CACHED_SCRIPT.tmp" 2>/dev/null; then
      mv "$CACHED_SCRIPT.tmp" "$CACHED_SCRIPT"
      echo "$SERVER_VER" > "$CACHED_VERSION"
      echo -e "${GREEN}  ✓ Update complete.${NC}"
    else
      echo -e "${RED}  ✗ Downloaded script has syntax errors — keeping old version.${NC}"
      rm -f "$CACHED_SCRIPT.tmp"
    fi
  else
    echo -e "${YELLOW}  ⚠ Download failed — using cached version.${NC}"
    rm -f "$CACHED_SCRIPT.tmp"
  fi
else
  echo -e "${GREEN}  ✓ Already up to date.${NC}"
fi

# Refresh the companion legacy-DB conf next to the cached script (best-effort).
# gpu_test.sh resolves it via its own SCRIPT_DIR, which is this cache dir.
if curl -sf --max-time 15 "$CONF_URL" -o "$CACHED_CONF.tmp" 2>/dev/null; then
  mv "$CACHED_CONF.tmp" "$CACHED_CONF"
else
  rm -f "$CACHED_CONF.tmp"
  if [[ -f "$CACHED_CONF" ]]; then
    echo -e "${YELLOW}  ⚠ Could not refresh legacy DB — using cached copy.${NC}"
  else
    echo -e "${YELLOW}  ⚠ Legacy DB unavailable — legacy NVIDIA VRAM lookup may be limited.${NC}"
  fi
fi

echo ""

# Run the script
if [[ -f "$CACHED_SCRIPT" ]]; then
  exec bash "$CACHED_SCRIPT"
else
  echo -e "${RED}✗ No script available to run.${NC}"
  exit 1
fi
