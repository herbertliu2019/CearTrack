# Task: Update laptop_test.sh — Battery & Network

## Background
`laptop_test.sh` is a bash script for laptop hardware testing in a
refurbishment/recycling workflow. Run as `sudo bash laptop_test.sh` on a
Live USB. See `.claude/skills/laptop-test/SKILL.md` for full context.

---

## Task 1: Battery Detection Improvements

### Problem
Current script only checks `health_percent < 60%` for FAIL.
Two new cases need handling:

**Case A — Battery physically dead (has data but values are invalid):**
Seen on Lenovo Yoga with a dead battery that drops power immediately when
unplugged. The `uevent` shows:
```
POWER_SUPPLY_VOLTAGE_NOW=2180000   # 2.18V — way below normal 3.6-4.2V
POWER_SUPPLY_ENERGY_NOW=0
POWER_SUPPLY_MANUFACTURER=         # empty
POWER_SUPPLY_MODEL_NAME=            # empty
POWER_SUPPLY_TECHNOLOGY=Unknown
POWER_SUPPLY_CYCLE_COUNT=-1
```

**Case B — Driver cannot read battery data (no Linux support):**
All fields empty/zero but battery may actually be fine — just unsupported driver.

### Required Changes

1. **Read `uevent` file** for richer data:
   ```bash
   /sys/class/power_supply/BAT*/uevent
   ```

2. **Detect dead battery (Case A):**
   - Condition: `VOLTAGE_NOW < 3000000` (< 3V) AND `ENERGY_NOW == 0`
   - Result: `BAT_STATUS=FAIL`, add field `"battery_condition": "DEAD"`

3. **Detect unavailable data (Case B):**
   - Condition: `MANUFACTURER` empty AND `MODEL_NAME` empty AND `ENERGY_NOW == 0`
     AND `VOLTAGE_NOW` is 0 or missing
   - Result: `BAT_STATUS=BATTERY_DATA_UNAVAILABLE` (not FAIL)
   - JSON field: `"battery_condition": "DATA_UNAVAILABLE"`

4. **Filter invalid cycle_count:**
   - If `cycle_count == -1` or empty → store as `"unknown"` in JSON

5. **Priority order for battery verdict:**
   ```
   1. No BAT* directory         → NOT_FOUND
   2. VOLTAGE < 3V + ENERGY = 0 → FAIL (DEAD)
   3. All data empty/zero       → BATTERY_DATA_UNAVAILABLE
   4. health_percent < 60%      → FAIL
   5. Otherwise                 → PASS
   ```

6. **Add to JSON:**
   ```json
   "battery": {
     ...existing fields...,
     "voltage_v": "3.85",          ← VOLTAGE_NOW / 1000000, formatted to 2dp
     "battery_condition": "DEAD | DATA_UNAVAILABLE | OK",
     "status": "PASS | FAIL | BATTERY_DATA_UNAVAILABLE"
   }
   ```

---

## Task 2: Wired Internet Connectivity Test

### Requirement
- Test **wired ethernet only** (not WiFi)
- Laptops are expected to have ethernet cable plugged in during testing
- Test external internet reachability

### Required Changes

1. **Add new section** after section 10 (Network), before section 11 (USB):
   ```
   === 10b. Internet Connectivity ===
   ```

2. **Logic:**
   - Get ethernet interface name (already detected as `$ETH_DEV`)
   - If no ethernet device found → `INTERNET_STATUS=NO_ETH_DEVICE`
   - Test connectivity via:
     ```bash
     # Primary test
     curl -s --max-time 5 --interface $ETH_DEV http://connectivitycheck.gstatic.com/generate_204
     # Fallback
     ping -c 3 -W 3 -I $ETH_DEV 8.8.8.8
     ```
   - Use `-I $ETH_DEV` / `--interface $ETH_DEV` to force wired interface only

3. **Results:**
   - `PASS` — curl returns HTTP 204 or ping succeeds
   - `FAIL` — both tests fail
   - `NO_ETH_DEVICE` — no ethernet interface detected

4. **Do NOT mark overall result FAIL** if internet test fails —
   record it in JSON but don't affect `overall_result`.
   Reason: cable may not be plugged in during every test session.

5. **Add to JSON:**
   ```json
   "network": {
     ...existing fields...,
     "internet_test": "PASS | FAIL | NO_ETH_DEVICE",
     "internet_test_via": "eth0"    ← interface name used
   }
   ```

6. **Add to TEST SUMMARY** output:
   ```
   Internet:            PASS (via eth0)
   ```

---

## Constraints
- Do NOT modify any RAM/CPU test related code
- Do NOT change existing JSON field names
- Run `bash -n laptop_test.sh` after changes to verify syntax
- Keep all changes within existing function structure
- Battery section is section 5 in the script — modify in place
- Do not rewrite sections that are not changing
