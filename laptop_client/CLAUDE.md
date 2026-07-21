# laptop_client — Laptop Test Client Script

Scope: this directory only. Root [`CLAUDE.md`](../CLAUDE.md) has the
whole-project overview (CearTrack / monitorcenter / WIPE); this file is
loaded in addition to it whenever work happens inside `laptop_client/`.

## What this is

`laptop_test.sh` — single self-contained bash script, run from a Live USB
to test refurbished laptops. Current `SCRIPT_VERSION="2.3.0"` (bump the
last digit on every bug fix — see [[bump-script-version-on-fix]] memory).

- **Run as**: `sudo bash laptop_test.sh`
- **Target env**: Ubuntu/Debian Live USB
- **Upload endpoint**: `UPLOAD_URL="http://192.168.30.18:80/laptop/api/upload"`
- **Do not restructure into multiple files** — the whole point is a single
  script a technician can copy onto a USB stick and run.

Other files here: `launcher.sh` (menu wrapper), `deploy_script.sh`
(pushes the script to test rigs), `DEPLOY.md`.

## Critical rule

**The server (`monitorcenter/modules/laptop/module.py`) depends on the
exact JSON field names this script emits.** Never rename a field without
updating the server's `extract_envelope()`, `schema.json`, and
`_compute_by_grade()` in the same change. See
[[manual-input-contract]] memory for the manual_input contract
specifically.

## Script flow (sequential)

```
deps → sysinfo → cpu → memory → storage → battery →
screen → camera → audio → keyboard/touchpad → network → usb → appearance →
kernel_health → manual_input (interactive prompts) →
build JSON → compute OVERALL → upload → summary
```

Sub-tests are inline bash functions — no separate files:

| Function | Purpose |
|---|---|
| `run_screen_test()` | ANSI full-screen color patterns, dead-pixel check |
| `run_keyboard_test()` | Python raw TTY key capture via `/dev/tty` |
| `run_touchpad_test()` | evdev-based touchpad auto-detect |
| `run_audio_test()` | Speaker tone + mic record/playback via ALSA |
| `ask_manual()` | Prompt technician: `p=PASS / f=FAIL / s=SKIP` |

## `overall_result` computation — client computes it too

The client computes `OVERALL` itself (not just "PENDING" left for the
server) around line ~2089 of the script:

- **Critical (FAIL → whole device FAIL)**: `SCREEN_CHECK`, `KB_KEYS_CHECK`,
  `TOUCHPAD_RESULT`, `INTERNET_STATUS`, `ETH_STATUS` (no wired link = test
  invalid, can't even upload reliably).
- **Everything else** (storage, battery, camera, audio, ports, appearance,
  kernel_health): FAIL/WARN here only downgrades to `WARN`, never `FAIL`.

**Note the server independently recomputes overall_result** in
`LaptopModule._compute_overall_result()` using a *different* critical set
(`keyboard.keys_check`, `keyboard.touchpad_check` only — screen/internet
are NOT critical server-side). This mismatch is intentional-by-accretion,
not a bug to "fix" reflexively — if you touch either side, check the other
first and ask before unifying them.

## JSON report shape (current, 2.3.0)

```json
{
  "test_info":    { "test_time", "hostname", "script_version" },
  "system":       { "vendor", "model", "serial_number", "bios_version" },
  "cpu":          { "model", "cores", "threads", "max_mhz", "architecture" },
  "memory":       { "total_gb", "type", "speed", "slots_total", "slots_used" },
  "storage":      [ { "device", "model", "size", "type", "smart", "power_on_hours",
                       "ssd_health_percent", "ssd_grade", "ssd_available_spare", "ssd_data_written" } ],
  "battery":      { "manufacturer", "model", "health_percent", "current_percent",
                     "cycle_count", "voltage_v", "battery_condition", "status" },
  "screen":       { "resolution", "interface", "dead_pixel_check", "backlight_check" },
  "camera":       { "device_status", "device_count", "driver_type", "capture_method",
                     "capture_result", "driver_note", "image_base64" },
  "audio":        { "speaker_device_status", "mic_device_status",
                     "speaker_quality_check", "mic_record_check" },
  "keyboard":     { "device_status", "keys_check", "touchpad_check" },
  "network":      { "wifi_status", "wifi_device", "wifi_fail_reason",
                     "ethernet_status", "ethernet_device",
                     "internet_test", "internet_test_via" },
  "ports":        { "usb_device_count", "usb3_count", "physical_check" },
  "appearance":   { "hinge_check", "scratch_check" },
  "kernel_health":{ "status", "fail_count", "warn_count", "matched_signals" },
  "manual_input": {
    "weight_lbs", "grade", "condition", "color",
    "screen_size_inch", "mark", "cddvd_present"
  },
  "overall_result": "PASS | WARN | FAIL"
}
```

### `manual_input` field formats — these are display strings, not codes

Server (CearTrack) reads these **as-is**, no remapping:

- `grade` → `"Grade A"` / `"Grade B"` / `"Grade C"` (full string, not bare
  letter — server parses the trailing word to get the letter, e.g. in
  `_compute_by_grade()`)
- `condition` → `"C4 - Used Good"` (code + label concatenated)
- `mark` → `;`-separated free text, e.g. `"Bios Blocked;Minor scratches/blemishes"`
- `cddvd_present` → `"Yes"` / `"No"`, auto-detected (not prompted)
- `screen_size_inch` → `"16 inch"` or `""` if skipped

If you change how any of these are formatted, the Cyclelution export
pipeline (`monitorcenter/cyclelution/`) and the CearTrack `By Grade`
widget both read this same string — check both before changing the format.

## Known hardware compatibility notes

- **Surface Pro (IPU3/IPU6 cameras)**: `libcamera` sees the sensor but
  can't capture (missing IPA + incomplete driver on standard Live USB) —
  reported as `HARDWARE_DETECTED`, not `FAIL`.
- **ALSA on Live USB**: output is often muted by default — script runs
  `amixer sset Master unmute` before playback; iterates all cards
  (`plughw:N,0`), never assumes `default`.
- **Storage — USB boot disk filter**: excludes the Live USB itself and any
  external USB disks via `lsblk -d -o NAME,TRAN | awk '$2=="usb"'`.
- **Dell dual touchpad (I2C)**: some Dell XPS/Precision models expose the
  same touchpad on both PS/2 and I2C buses — see
  [[dell-dual-touchpad-i2c]] memory (I2C nodes have no `ID_BUS`, filter by
  `DEVPATH`'s `i2c-` prefix).

## Editing rules

1. Read the current script before editing — 2200+ lines, don't guess.
2. Targeted edits only — do not rewrite functions that aren't changing.
3. `bash -n laptop_test.sh` to syntax-check before considering done.
4. Never rename an existing JSON field or function without checking the
   server side (`monitorcenter/modules/laptop/`) in the same change.
5. Bump `SCRIPT_VERSION`'s last digit on every fix (see
   [[bump-script-version-on-fix]]).
