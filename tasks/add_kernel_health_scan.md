# Add: Kernel Health Scan (dmesg Hardware Error Detection)

## Problem

During tests, kernel driver crashes (e.g. `nouveau` on Surface Book 2
with Pascal dGPU) spam dmesg with Oops/BUG/recursive-fault traces.
Operator sees screen scrolling with scary kernel stack traces and
cannot easily tell:

- Is this a **hardware failure**? (bad CPU, bad NVMe, PCIe fault)
- Or just a **driver bug**? (nouveau ACR/WPR issue, well-known)

Need automated classification so technician gets clear verdict.

## Goal

Add new section **"N. Kernel Health Scan"** that:
1. Scans `dmesg` for real hardware error signals
2. Explicitly ignores known driver-only noise patterns
3. Outputs `KERNEL_HEALTH=PASS|WARN|FAIL` with list of matched signals
4. Writes `kernel_health` object to JSON report
5. Displays summary line in TEST SUMMARY

Placement: new section 13, **after** section 12 Appearance, **before**
`BUILD JSON REPORT`. So it runs last and catches any errors triggered
by earlier tests.

## Hardware Error Signals (FAIL — real hardware problem)

| Category | Regex keyword | Why |
|----------|---------------|-----|
| CPU MCE | `mce:`, `Machine Check`, `Hardware Error` | CPU hardware error |
| Memory ECC | `EDAC .* error`, `mce.*memory`, `BadRAM` | RAM error |
| Storage | `I/O error`, `Buffer I/O error`, `Medium Error`, `end_request: critical`, `ata[0-9]+: .*failed command`, `nvme.*IO timeout`, `blk_update_request: I/O error`, `critical medium error` | Disk failure |
| PCIe AER | `AER:.*Uncorrected`, `AER:.*Fatal`, `PCIe Bus Error:.*severity=Fatal` | PCIe hardware fault (Corrected AER is NOT a FAIL — too noisy) |
| Thermal critical | `thermal .*critical`, `CPU[0-9]+: Core temperature above threshold`, `CPU[0-9]+: Package temperature above threshold` | Overheat |

## Warning Signals (WARN — check but not fail)

| Category | Regex | Note |
|----------|-------|------|
| USB errors | `device descriptor read/64, error -`, `device not accepting address`, `usb.*disabled by hub` | Usually cable/port borderline |
| PCIe AER Corrected | `AER:.*Corrected` (count > 10 only) | Intermittent link issue |
| SATA link | `ata[0-9]+.*SError`, `link is slow to respond` | Cable/port issue |

## Ignore List (driver noise, NOT hardware)

Lines matching ANY of these → discarded before hardware match:

```
nouveau
g84_bar_flush
nvkm_
gp102_acr_wpr_patch
ov13858.*probe.*failed
ov[0-9]+.*probe.*failed
DMAR.*Passthrough
Bluetooth: hci.*command.*tx timeout
i915.*GPU HANG           # i915 hang is driver, not hardware
WARNING: CPU.*at drivers/
Call Trace:
 ? 
RIP:
RSP:
Code:
Modules linked in:
---\[ end trace
Tainted:
irq/.*pciehp
```

Implementation: `grep -v -iE "nouveau|nvkm_|g84_bar_flush|..."` before
applying hardware match.

## Result Logic

```
kernel_health:
  any FAIL match → KERNEL_HEALTH=FAIL, list of matched lines (up to 10)
  else any WARN match → KERNEL_HEALTH=WARN, list of matched lines (up to 10)
  else → KERNEL_HEALTH=PASS
```

Note: `KERNEL_HEALTH=WARN` does **NOT** trigger overall FAIL.
Only `FAIL` does (current logic counts `"FAIL"` strings in JSON).

## JSON addition

```json
"kernel_health": {
  "status": "PASS | WARN | FAIL",
  "fail_count": 0,
  "warn_count": 0,
  "matched_signals": ["..."]
}
```

`matched_signals` is an array of up to 10 short strings (truncated to
120 chars each) showing the actual dmesg lines that matched.

## Display Format

During section execution:
```
=== 13. Kernel Health Scan ===
  Scanning dmesg for hardware error signals...
  ✓ No hardware error signals detected.      (PASS — green)
```

On WARN:
```
  ⚠ 3 warning signal(s) detected (may indicate marginal hardware):
    usb 1-4: device descriptor read/64, error -71
    ata3: SError: { RecovComm }
    ...
```

On FAIL:
```
  ✗ 2 hardware error signal(s) detected:
    mce: [Hardware Error]: Machine check events logged
    blk_update_request: critical medium error, dev nvme0n1
  This laptop has hardware errors — DO NOT refurbish without investigation.
```

In TEST SUMMARY:
```
  Kernel Health:       PASS
```
or
```
  Kernel Health:       WARN (3 signals — see report)
  Kernel Health:       FAIL (2 hardware errors — see report)
```

## Code skeleton

```bash
banner "13. Kernel Health Scan"
echo "  Scanning dmesg for hardware error signals..."

KH_IGNORE='nouveau|nvkm_|g84_bar_flush|gp102_acr_wpr_patch|ov[0-9]+.*probe.*failed|DMAR.*Passthrough|Bluetooth: hci.*command.*tx timeout|i915.*GPU HANG|WARNING: CPU.*at drivers/|^\[.*\] Call Trace:|^\[.*\]  \?|^\[.*\] RIP:|^\[.*\] RSP:|^\[.*\] Code:|^\[.*\] Modules linked in:|end trace|Tainted:|irq/.*pciehp'

KH_FAIL_RE='mce:|Machine Check|Hardware Error|EDAC .* error|BadRAM|I/O error|Buffer I/O error|Medium Error|end_request: critical|ata[0-9]+: .*failed command|nvme.*IO timeout|blk_update_request: I/O error|critical medium error|AER:.*Uncorrected|AER:.*Fatal|PCIe Bus Error:.*severity=Fatal|thermal .*critical|Core temperature above threshold|Package temperature above threshold'

KH_WARN_RE='device descriptor read/64, error -|device not accepting address|usb.*disabled by hub|ata[0-9]+.*SError|link is slow to respond'

DMESG_FILTERED=$(dmesg 2>/dev/null | grep -vE "$KH_IGNORE")

KH_FAIL_LINES=$(echo "$DMESG_FILTERED" | grep -iE "$KH_FAIL_RE" | head -10)
KH_WARN_LINES=$(echo "$DMESG_FILTERED" | grep -iE "$KH_WARN_RE" | head -10)

KH_FAIL_COUNT=$(echo -n "$KH_FAIL_LINES" | grep -c '^' 2>/dev/null || echo 0)
KH_WARN_COUNT=$(echo -n "$KH_WARN_LINES" | grep -c '^' 2>/dev/null || echo 0)

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
```

## JSON insertion point

Add between `appearance` and `overall_result`:

```json
  "appearance": { ... },
  "kernel_health": {
    "status": "$(esc "$KERNEL_HEALTH")",
    "fail_count": ${KH_FAIL_COUNT:-0},
    "warn_count": ${KH_WARN_COUNT:-0},
    "matched_signals": ${KH_SIGNALS_JSON}
  },
  "overall_result": "PENDING"
```

## TEST SUMMARY addition

After appearance summary line:

```bash
if [[ "$KERNEL_HEALTH" == "FAIL" ]]; then
  printf "  %-20s %s\n" "Kernel Health:" "FAIL ($KH_FAIL_COUNT hardware errors — see report)"
elif [[ "$KERNEL_HEALTH" == "WARN" ]]; then
  printf "  %-20s %s\n" "Kernel Health:" "WARN ($KH_WARN_COUNT signals — see report)"
else
  printf "  %-20s %s\n" "Kernel Health:" "PASS"
fi
```

## overall_result behavior

- `KERNEL_HEALTH=FAIL` → `"status": "FAIL"` in JSON → will match
  `grep -o '"FAIL"'` counter → overall becomes FAIL ✓ (desired)
- `KERNEL_HEALTH=WARN` → `"status": "WARN"` → not FAIL, no impact ✓
- `KERNEL_HEALTH=PASS` → no impact ✓

## Constraints

- New section 13 only — do not modify other sections
- Do not change existing JSON field names
- Add `kernel_health` object to JSON
- Add one line to TEST SUMMARY
- Run `bash -n laptop_test.sh` after changes
