# Fix: Storage — Filter USB Disks from Report

## Problem

Live USB boot disk appears in storage report:
```json
{"device": "sda", "model": "USB DISK 3.0", "size": "14.5G", "type": "HDD", ...}
```

This is the Live USB itself, not the laptop's internal storage.
It must be excluded from the report.

## Root Cause

Current filter logic uses two conditions:
1. `TRAN == usb`
2. Device is current boot device (via `findmnt`)

Condition 2 fails when root is on LVM (`/dev/mapper/ubuntu--vg-...`).
`lsblk -no PKNAME` returns empty for LVM devices.

## Fix

**Remove condition 2. Filter all `TRAN==usb` disks.**

Reasoning: internal laptop storage is always `nvme` or `sata`.
USB transport means external/removable device — never internal storage.
No risk of false positives.

## Current Code (in Storage section)

```bash
BOOT_DEV=$(lsblk -no PKNAME "$(findmnt -n -o SOURCE /)" 2>/dev/null | head -1)
USB_DISKS=$(lsblk -d -o NAME,TRAN 2>/dev/null | awk '$2=="usb"{print $1}')

while IFS= read -r disk; do
  [[ -z "$disk" ]] && continue
  name=$(basename "$disk")

  if [[ -n "$BOOT_DEV" && "$name" == "$BOOT_DEV" ]]; then
    warn "Skipping $name — detected as boot/live USB device."
    continue
  fi
  if echo "$USB_DISKS" | grep -q "^${name}$"; then
    warn "Skipping $name — USB external disk, not internal storage."
    continue
  fi
  ...
```

## Fix — Replace with:

```bash
USB_DISKS=$(lsblk -d -o NAME,TRAN 2>/dev/null | awk '$2=="usb"{print $1}')

while IFS= read -r disk; do
  [[ -z "$disk" ]] && continue
  name=$(basename "$disk")

  if echo "$USB_DISKS" | grep -q "^${name}$"; then
    warn "Skipping $name (USB transport) — not internal storage."
    continue
  fi
  ...
```

Remove the `BOOT_DEV` variable and its associated `if` block entirely.

## Verification

After fix, report should only contain internal disks:
```json
"storage": [
  {"device": "nvme0n1", "model": "PC611 NVMe SK hynix 256GB", ...}
]
```

`sda` (USB DISK 3.0) must not appear.

## Constraints
- Only modify the Storage section (section 4)
- Do not change JSON field names
- Do not modify any other sections
- Run `bash -n laptop_test.sh` after changes
