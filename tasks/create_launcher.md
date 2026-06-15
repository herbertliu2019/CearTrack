# Task: Create launcher.sh — Auto-Update Script from CearTrack Server

## Purpose

`launcher.sh` is the ONLY file placed on the Live USB.
It checks the server for a newer version of `laptop_test.sh`,
downloads it if available, then runs it.

The USB never needs to be updated again after this file is placed on it.

## Server Setup (do this once manually)

```bash
mkdir -p /opt/monitorcenter/static/scripts
cp /path/to/laptop_test.sh /opt/monitorcenter/static/scripts/laptop_test.sh
echo "2.0.0" > /opt/monitorcenter/static/scripts/version.txt
```

URLs available via Nginx:
```
http://192.168.30.18:8080/laptop/static/scripts/version.txt
http://192.168.30.18:8080/laptop/static/scripts/laptop_test.sh
```

## Create file: `launcher.sh`

```bash
#!/bin/bash
# ============================================================
# launcher.sh — CearTrack Auto-Update Launcher
# Place this file on Live USB. Never needs to be updated.
# ============================================================

SERVER="http://192.168.30.18:8080"
VERSION_URL="$SERVER/laptop/static/scripts/version.txt"
SCRIPT_URL="$SERVER/laptop/static/scripts/laptop_test.sh"

CACHE_DIR="/tmp/ceartrack"
CACHED_SCRIPT="$CACHE_DIR/laptop_test.sh"
CACHED_VERSION="$CACHE_DIR/version.txt"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

mkdir -p "$CACHE_DIR"

echo ""
echo -e "${GREEN}CearTrack Laptop Test Launcher${NC}"
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

echo ""

# Run the script
if [[ -f "$CACHED_SCRIPT" ]]; then
  exec bash "$CACHED_SCRIPT"
else
  echo -e "${RED}✗ No script available to run.${NC}"
  exit 1
fi
```

## How to Use

### Place on Live USB (one time only):
```bash
cp launcher.sh /media/usb/launcher.sh
chmod +x /media/usb/launcher.sh
```

### Run on test laptop:
```bash
sudo bash /media/usb/launcher.sh
```

### Update script (server side only, no USB change needed):
```bash
# 1. Copy new script to server
cp laptop_test.sh /opt/monitorcenter/static/scripts/laptop_test.sh

# 2. Update version number (must match script_version inside the script)
echo "2.1.0" > /opt/monitorcenter/static/scripts/version.txt
```

Next time any laptop runs `launcher.sh`, it auto-downloads the new version.

## Flow Diagram

```
launcher.sh starts
    ↓
Can reach server?
    ├─ NO  → use cached script (if exists) → run
    │         no cache → exit with error
    └─ YES → get server version
                ↓
             server_ver == local_ver?
                ├─ YES → run cached script
                └─ NO  → download new script
                           ↓
                        syntax check (bash -n)
                           ├─ PASS → save + run
                           └─ FAIL → keep old + run old
```

## Verification

```bash
# 1. First run (no cache)
sudo bash launcher.sh
# Expected: downloads script, runs it

# 2. Second run (same version)
sudo bash launcher.sh
# Expected: "Already up to date", runs cached

# 3. Update server version
echo "2.1.0" > /opt/monitorcenter/static/scripts/version.txt
sudo bash launcher.sh
# Expected: "Downloading update: 2.0.0 → 2.1.0", downloads, runs

# 4. Kill network, run again
sudo bash launcher.sh
# Expected: "Cannot reach server", uses cached version
```

## Constraints
- `launcher.sh` must never need updating — all logic uses URLs from variables
- Always verify downloaded script with `bash -n` before replacing cache
- Never delete cached script on download failure
- `exec bash` replaces launcher process with script process (clean exit)
- No dependencies beyond `curl` and `bash` (both available on Ubuntu Live USB)
