# gpu_test.sh — Tiered Testing Logic Task
**Script:** `gpu_test.sh` (current version in `/opt/gpurun/`)
**Goal:** Add VRAM-based test tier logic — full test for capable cards, info-only for low-end/legacy cards.

---

## Background

Current script runs full test (gpu-burn + glmark2) on every card regardless of capability.
Need to add two tiers based on VRAM size, which is the simplest reliable indicator:

| Tier | Condition | Tests Run |
|------|-----------|-----------|
| FULL | VRAM ≥ 4096 MB | L1 info + gpu-burn + glmark2 + thermal |
| INFO_ONLY | VRAM < 4096 MB OR nvidia-smi fails | L1 info only, skip stress tests |

---

## Task T1 — Determine VRAM and set TEST_TIER variable

**Location:** After L1 hardware identification (after Step 1 completes), before Step 2 (thermal monitor start).

**Logic:**
```bash
# Set test tier based on VRAM
TEST_TIER="FULL"
if [[ "$GPU_VRAM_MB" -lt 4096 ]] 2>/dev/null; then
    TEST_TIER="INFO_ONLY"
    warn "VRAM ${GPU_VRAM_MB}MB < 4096MB — skipping stress tests (INFO_ONLY mode)"
fi

# Also set INFO_ONLY if nvidia-smi failed to read VRAM (legacy/unsupported card)
if [[ "$GPU_VRAM_MB" -eq 0 && "$VENDOR" == "NVIDIA" ]]; then
    TEST_TIER="INFO_ONLY"
    warn "VRAM unreadable — legacy driver may be required. Running INFO_ONLY mode."
fi

ok "Test tier: $TEST_TIER"
```

**Print on screen:**
```
  ✓ Test tier: FULL (VRAM 8192MB ≥ 4096MB)
  or
  ⚠ Test tier: INFO_ONLY (VRAM 2048MB < 4096MB — skipping stress tests)
```

---

## Task T2 — Gate thermal monitor (Step 2)

**Location:** Step 2 startup block.

Wrap entire thermal monitor startup in:
```bash
if [[ "$TEST_TIER" == "FULL" ]]; then
    # existing thermal monitor startup code
    ...
else
    ok "Thermal monitor skipped (INFO_ONLY mode)"
    SMI_PID=""
fi
```

---

## Task T3 — Gate VRAM stress test (Step 3)

**Location:** Step 3 (gpu-burn / AMD stress).

Wrap entire stress test block in:
```bash
if [[ "$TEST_TIER" == "FULL" ]]; then
    # existing gpu-burn / AMD stress code
    ...
    VRAM_STATUS="PASS"
    VRAM_ERRORS=0
else
    ok "VRAM stress test skipped (INFO_ONLY mode)"
    VRAM_TOOL="skipped"
    VRAM_ERRORS=0
    VRAM_STATUS="SKIPPED"
fi
```

---

## Task T4 — Gate glmark2 benchmark (Step 4)

**Location:** Step 4 (glmark2 benchmark).

Wrap entire glmark2 block in:
```bash
if [[ "$TEST_TIER" == "FULL" ]]; then
    # existing X server startup + glmark2 code
    ...
else
    ok "OpenGL benchmark skipped (INFO_ONLY mode)"
    VKMARK_SCORE=0
    VKMARK_STATUS="SKIPPED"
    GLMARK2_DURATION=0
fi
```

---

## Task T5 — Gate thermal parsing (Step 5)

**Location:** Step 5 (thermal data parsing).

```bash
if [[ "$TEST_TIER" == "FULL" ]]; then
    # existing thermal log parsing code
    ...
else
    ok "Thermal data skipped (INFO_ONLY mode)"
    TEMP_MAX=0
    TEMP_AVG=0
    UTIL_AVG=0
    POWER_MAX=0
    THERMAL_STATUS="SKIPPED"
fi
```

---

## Task T6 — Update overall verdict logic (Step 7)

**Location:** Step 7 (overall verdict).

INFO_ONLY tier should never be PASS or FAIL — use a neutral result:

```bash
if [[ "$TEST_TIER" == "INFO_ONLY" ]]; then
    OVERALL_RESULT="INFO_ONLY"
fi
```

Verdict display for INFO_ONLY:
```
############################################################
     TEST RESULT: ℹ️  INFO ONLY (low VRAM / legacy card)
############################################################
  GPU:     Quadro P400
  VRAM:    2048 MB (GDDR5)
  Note:    Stress tests skipped — VRAM < 4096MB
  Card suitable for: office / display / light workloads
############################################################
```

---

## Task T7 — Update JSON output

**Location:** Step 8 (JSON build).

Add `test_tier` field to `test_info`:
```json
"test_info": {
    "test_time": "...",
    "test_station": "...",
    "test_tier": "INFO_ONLY",
    "script_version": "1.1.0",
    ...
}
```

Update `vram_test` and `vulkan_benchmark` status to reflect SKIPPED:
```json
"vram_test": {
    "tool": "skipped",
    "duration_seconds": 0,
    "errors": 0,
    "status": "SKIPPED"
},
"vulkan_benchmark": {
    "tool": "glmark2",
    "resolution": "1920x1080",
    "score": 0,
    "status": "SKIPPED"
}
```

---

## Task T8 — Update shutdown logic (Step 10)

INFO_ONLY result should not trigger auto-poweroff countdown — just exit cleanly:

```bash
INFO_ONLY)
    echo -e "${CYAN}${BOLD}  ℹ️   INFO ONLY — No stress tests run${NC}"
    echo ""
    echo "  Card has insufficient VRAM for full testing (< 4096MB)"
    echo "  L1 hardware info collected successfully."
    echo "  Log: $JSON_FILE"
    echo "============================================================"
    ;;
```

---

## Task T9 — Update summary string

**Location:** summary construction before JSON build.

```bash
if [[ "$TEST_TIER" == "INFO_ONLY" ]]; then
    SUMMARY="GPU:${GPU_NAME} VRAM:${GPU_VRAM_MB}MB MODE:INFO_ONLY"
else
    SUMMARY="GPU:${GPU_NAME} VRAM:${GPU_VRAM_MB}MB TEMP_MAX:${TEMP_MAX}C VKMARK:${VKMARK_SCORE} RESULT:${OVERALL_RESULT}"
fi
```

---

## Implementation Notes for Claude Code

1. **Read the full script first** before making any edits
2. **Use targeted str_replace** — do NOT rewrite the entire script
3. **Test after each task** — run `bash -n gpu_test.sh` after each change
4. **Preserve existing indentation and style**
5. The VRAM threshold is `4096` MB — do not hardcode as `4000` or `4GB`
6. `TEST_TIER` variable must be set AFTER L1 completes (GPU_VRAM_MB must be populated)
7. `ACTUAL_BURN_DURATION` should be set to `0` when stress test is skipped

---

## Test Scenarios

| Card | VRAM | Expected Tier | Expected Result |
|------|------|--------------|-----------------|
| RTX 2080 SUPER | 8192 MB | FULL | PASS/FAIL |
| RX 580 | 4096 MB | FULL | PASS/FAIL |
| Quadro P400 | 2048 MB | INFO_ONLY | INFO_ONLY |
| GT 730 | 2048 MB | INFO_ONLY | INFO_ONLY |
| Quadro K2000 | 2048 MB | INFO_ONLY | INFO_ONLY |

---

## Files to Modify

- `/opt/gpurun/gpu_test.sh` — main script (only file to modify)

## Files to Reference

- Current script: read `/opt/gpurun/gpu_test.sh` before any edits
- CLAUDE.md project context if available
