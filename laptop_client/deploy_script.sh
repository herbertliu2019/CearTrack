#!/bin/bash
# ============================================================
# deploy_script.sh — Publish a client test script to the CearTrack server
# Run this ON THE SERVER (192.168.30.18) after updating a *_test.sh script.
#
# Works for BOTH modules:
#   sudo bash deploy_script.sh laptop_test.sh   → deploys laptop module
#   sudo bash deploy_script.sh gpu_test.sh      → deploys gpu module
#   sudo bash deploy_script.sh                  → prompts which to deploy
#
# It auto-detects the module from the script's UPLOAD_URL (/laptop/ vs /gpu/),
# copies the script into scripts/<module>/, and generates version.txt from the
# SCRIPT_VERSION line inside the script so the two can never drift apart.
# ============================================================

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

# Flask serves STATIC_DIR at /laptop/static, so everything lives under it.
DEST_ROOT="/opt/monitorcenter/static/scripts"

# ── Resolve which script to deploy ───────────────────────────────────────────
SRC="$1"

if [[ -z "$SRC" ]]; then
  echo -e "${YELLOW}No script specified.${NC}"
  echo "  Which script do you want to deploy?"
  echo "    1) laptop_test.sh"
  echo "    2) gpu_test.sh"
  read -rp "  Choice [1/2]: " _choice
  case "$_choice" in
    1) SRC="laptop_test.sh" ;;
    2) SRC="gpu_test.sh" ;;
    *) echo -e "${RED}✗ Invalid choice — aborting.${NC}"; exit 1 ;;
  esac
fi

if [[ ! -f "$SRC" ]]; then
  echo -e "${RED}✗ Source script not found: $SRC${NC}"
  exit 1
fi

# ── Validate syntax before publishing — never serve a broken script ──────────
if ! bash -n "$SRC" 2>/dev/null; then
  echo -e "${RED}✗ $SRC has syntax errors — aborting deploy.${NC}"
  exit 1
fi

# ── Auto-detect module from the script's UPLOAD_URL ──────────────────────────
# Expected:  UPLOAD_URL="http://.../<module>/api/upload"
MODULE=$(sed -n 's#.*UPLOAD_URL="[^"]*/\([a-z]*\)/api/upload".*#\1#p' "$SRC" | head -1)
if [[ -z "$MODULE" ]]; then
  echo -e "${RED}✗ Could not detect module from UPLOAD_URL in $SRC${NC}"
  echo "  Expected a line like: UPLOAD_URL=\"http://.../laptop/api/upload\""
  exit 1
fi

# ── Extract the single-source-of-truth version from the script ───────────────
# Uses sed (portable) rather than grep -P, which fails on non-UTF-8 locales.
VERSION=$(sed -n 's/^SCRIPT_VERSION="\([^"]*\)".*/\1/p' "$SRC" | head -1)
if [[ -z "$VERSION" ]]; then
  echo -e "${RED}✗ Could not find SCRIPT_VERSION=\"...\" in $SRC${NC}"
  exit 1
fi

# ── Publish ──────────────────────────────────────────────────────────────────
DEST_DIR="$DEST_ROOT/$MODULE"
SCRIPT_BASENAME=$(basename "$SRC")
mkdir -p "$DEST_DIR"
cp "$SRC" "$DEST_DIR/$SCRIPT_BASENAME"
echo "$VERSION" > "$DEST_DIR/version.txt"

# Also publish any companion data files (e.g. gpu's nvidia_legacy_db.conf) that
# sit beside the source script — the client launcher downloads them next to the
# script so it can resolve them via its own SCRIPT_DIR.
SRC_DIR=$(dirname "$SRC")
CONF_COUNT=0
for _conf in "$SRC_DIR"/*.conf; do
  [[ -e "$_conf" ]] || continue
  cp "$_conf" "$DEST_DIR/$(basename "$_conf")"
  CONF_COUNT=$((CONF_COUNT + 1))
done

echo -e "${GREEN}✓ Deployed $SCRIPT_BASENAME${NC}"
echo "  Module  : $MODULE"
echo "  Version : $VERSION"
echo "  Script  : $DEST_DIR/$SCRIPT_BASENAME"
echo "  Version : $DEST_DIR/version.txt"
[[ $CONF_COUNT -gt 0 ]] && echo "  Conf    : $CONF_COUNT companion .conf file(s) published"
echo ""
echo "  Served at:"
echo "    http://192.168.30.18:80/laptop/static/scripts/$MODULE/version.txt"
echo "    http://192.168.30.18:80/laptop/static/scripts/$MODULE/$SCRIPT_BASENAME"
