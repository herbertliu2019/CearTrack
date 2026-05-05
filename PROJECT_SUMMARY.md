# CearTrack — Project Summary

**Company:** Cear (Electronics Recycling)
**Project:** CearTrack — Multi-module hardware test log aggregation platform
**Deployment:** `/opt/monitorcenter/`
**Server:** `192.168.30.18:5004` (direct) / `192.168.30.18:8080/laptop` (via Nginx)

---

## Architecture Overview

```
laptop_test.sh (Live USB)
    ↓ POST /laptop/api/upload (X-API-Key)
CearTrack Flask Server :5004
    ↓ wraps raw JSON → standard envelope
    ↓ writes to latest/ + history/
Nginx :8080
    ↓ proxy_pass (keep /laptop prefix, no trailing slash)
Browser → CearTrack Dashboard
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12, Flask 3.x |
| Frontend | Alpine.js v3 + HTMX v1, Vanilla CSS |
| Storage | Local filesystem JSON (no database) |
| Auth | Flask session + werkzeug password hash |
| Proxy | Nginx reverse proxy |

**No build tools. No npm. No database. Vendor JS bundled locally.**

---

## Directory Structure

```
/opt/monitorcenter/
├── app.py                          Flask entrypoint
├── config.py                       Global config (BASE_DIR, API key, secret)
├── requirements.txt                Flask only
├── auth/
│   ├── routes.py                   /login /logout /admin/users
│   ├── decorators.py               @login_required @module_required @admin_required
│   └── user_store.py               users.json read/write, password hashing
├── core/
│   ├── storage.py                  write_envelope(), read_latest(), search_sn()
│   ├── module_registry.py          auto-discover modules/
│   ├── envelope.py                 build_envelope() — wrap raw JSON
│   └── search.py                   cross-module SN search
├── modules/
│   ├── base.py                     TestModule abstract class
│   └── laptop/
│       ├── module.py               LaptopModule + Flask blueprint
│       └── schema.json             field display schema for frontend renderer
├── static/
│   ├── css/dashboard.css           dark theme CSS variables
│   ├── js/
│   │   ├── app.js                  Alpine dashboardApp() component
│   │   └── renderer.js             schema-driven field renderer
│   └── vendor/
│       ├── alpine.min.js           v3.x
│       └── htmx.min.js             v1.x
├── templates/
│   ├── base.html                   shared layout, nav, session user info
│   ├── index.html                  landing page, module tiles
│   ├── login.html                  login form
│   ├── admin_users.html            user management (admin only)
│   └── module.html                 generic module dashboard (Today/Stats/Search tabs)
└── data/
    ├── users.json                  user accounts + module permissions
    └── laptop/
        ├── latest/
        │   └── <SN>.json           most recent test per SN (today only, 24h TTL)
        └── history/
            └── YYYY/
                └── MM-DD/
                    └── <SN>_YYYYMMDD_HHMMSS.json
```

---

## Standard JSON Envelope

All modules store data in this wrapper format:

```json
{
  "module": "laptop",
  "sn": "034912262653",
  "timestamp": "2026-04-22T20:17:08-0700",
  "overall_result": "PASS",
  "summary": "All tests passed",
  "hostname": "test-rig-01",
  "warnings": [],
  "payload": { "...original module JSON..." }
}
```

**SN is the primary key across all modules.**

---

## API Endpoints

### Auth
| Method | URL | Auth | Description |
|--------|-----|------|-------------|
| GET/POST | `/login` | none | Login page |
| GET | `/logout` | session | Logout |
| GET | `/admin/users` | admin | User management UI |
| POST | `/admin/users/add` | admin | Add user |
| POST | `/admin/users/<u>/delete` | admin | Delete user |
| POST | `/admin/users/<u>/modules` | admin | Update user module permissions |

### Laptop Module
| Method | URL | Auth | Description |
|--------|-----|------|-------------|
| POST | `/laptop/api/upload` | API key | Receive test JSON from laptop_test.sh |
| GET | `/laptop/api/latest` | session | Today's tested machines |
| GET | `/laptop/api/search?sn=XXX` | session | Search by SN in history |
| GET | `/laptop/api/stats` | session | Today's pass/fail count |
| GET | `/laptop/api/stats/range?range=week\|month` | session | Calendar-based stats |
| GET | `/laptop/api/stats/range?from=YYYY-MM-DD&to=YYYY-MM-DD` | session | Custom date range |
| GET | `/laptop/api/schema` | session | Display schema for frontend renderer |

### Global
| Method | URL | Auth | Description |
|--------|-----|------|-------------|
| GET | `/api/search?sn=XXX` | session | Cross-module SN search |

---

## Authentication & Authorization

### Roles
| Role | Permissions |
|------|------------|
| `admin` | All modules, user management, cannot be deleted |
| `user` | Only modules explicitly granted by admin |

### Module Permission Flow
```
User logs in → session stores username + role
    ↓
@module_required('laptop') checks users.json
    ↓
modules: ["*"]     → admin, allow
modules: ["laptop"] → has access, allow
modules: ["ram"]    → no access, 403
```

### API Key for Script Upload
`laptop_test.sh` uses `X-API-Key` header (no browser session):
```
X-API-Key: ceartrack-upload-2026
```
Defined in `config.py` as `UPLOAD_API_KEY`.

### Session Policy
- `session.permanent = False` — expires on browser close
- No remember-me functionality

### Default Admin
Created automatically on first startup:
- Username: `admin`
- Password: `admin123`
- **Change immediately after first login**

---

## Storage Logic

### Latest Directory (`latest/<SN>.json`)
- One file per SN — always the most recent test result
- **Re-uploading same SN overwrites latest AND deletes old history records**
- One SN = one laptop = one final test result (no duplicates)
- Files older than 24 hours purged on access

### History Directory (`history/YYYY/MM-DD/<SN>_timestamp.json`)
- On new upload: all existing `<SN>_*.json` deleted recursively across all dates
- New file written with current timestamp
- Empty date directories cleaned up after deletion
- **History is permanent — no delete API for test records**

### Future Index (`_index/` — NOT YET IMPLEMENTED)
```python
# TODO in storage.py write_envelope():
# _update_index(module_name, envelope)
# Appends one line to data/<module>/_index/YYYY-MM.jsonl:
# {"sn":"...","module":"...","result":"...","ts":"...","file":"..."}
# For fast bulk queries by future analysis project
```

---

## Frontend Architecture

### Schema-Driven Rendering
Each module defines `schema.json` — frontend `renderer.js` walks it generically.
Adding a new module = write `schema.json`, no JS changes.

### Section Types in schema.json
| type | Renders as |
|------|-----------|
| `key_value` | Two-column label/value grid |
| `status_grid` | Colored dot grid (PASS=green, FAIL=red, WARN=yellow) |
| `list` | Repeated items from array using item_template |
| `camera_image` | Key-value + base64 image with click-to-enlarge |

### Tab Structure
```
[ Today ]  [ Stats ]  [ Search ]
```
- **Today** — Live latest results, 10s HTMX polling, expandable cards
- **Stats** — This Week / This Month / Custom Range with bar charts
- **Search** — SN lookup across history

### Card Expand Behavior
- Each card uses `sn + timestamp` as unique key
- Multiple cards can be open simultaneously
- Click anywhere on card to toggle (not just header)
- State stored in `expandedKeys` Set (Alpine)

---

## Nginx Configuration

```nginx
server {
    listen 8080;
    server_name 192.168.30.18;

    location /laptop {
        proxy_pass http://127.0.0.1:5004;   # NO trailing slash — preserves /laptop prefix
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
    # /mem/ and /cpu/ point to other services on :5000 and :5002
}
```

**Critical:** `proxy_pass` without trailing slash preserves the `/laptop` prefix.
Flask must use `static_url_path='/laptop/static'` to match.

---

## Module System

### Auto-Discovery
`core/module_registry.py` scans `modules/` at startup, imports each
subpackage, registers `blueprint` attribute under `/<module_name>/`.

### Adding a New Module
1. Create `modules/<name>/` directory
2. Implement `module.py` with class extending `TestModule` and `blueprint`
3. Define `schema.json` for frontend rendering
4. Register module name in `@module_required('<name>')` on all routes
5. Restart server — auto-discovered and registered

### Planned Future Modules
| Module | Status | Notes |
|--------|--------|-------|
| `laptop` | ✅ Active | Full implementation |
| `ram` | 🔲 Planned | Existing RAM test may be replaced |
| `cpu` | 🔲 Planned | Future |
| `gpu` | 🔲 Planned | Future |
| `wipe` | 🔲 Planned | XERASwin log parser + collector |

---

## Laptop Module — Key Fields

### Camera
- `device_status`: `PASS` / `FAIL` / `HARDWARE_DETECTED` / `NOT_FOUND`
- `driver_type`: `uvc` / `ipu3` / `ipu6` / `unknown`
- `capture_result`: `CAPTURED` / `CAPTURE_FAILED` / `NOT_ATTEMPTED`
- `image_base64`: base64 JPEG, empty string if no image
- `HARDWARE_DETECTED` does NOT trigger overall FAIL

### Storage (NVMe)
- `type`: `SSD NVMe` / `SSD` / `HDD`
- `ssd_health_percent`: `100 - Percentage_Used` (from `smartctl -x`)
- `ssd_grade`: `A` (≥95%) / `B` (≥80%) / `C` (≥70%) / `D` (<70%)
- `ssd_available_spare`: from `smartctl -x`
- `ssd_data_written`: total data written

### Battery
- `health_percent`: `energy_full / energy_full_design * 100`
- `battery_condition`: `OK` / `DEAD` / `DATA_UNAVAILABLE`
- `DEAD`: voltage < 3V AND energy_now = 0
- `DATA_UNAVAILABLE`: driver cannot read (some Lenovo models)
- Health < 60% → `status: FAIL`

### Network
- `internet_test`: wired ethernet only (`--interface $ETH_DEV`)
- `internet_test` FAIL does NOT trigger overall FAIL

---

## laptop_test.sh Integration

**Upload command:**
```bash
UPLOAD_URL="http://192.168.30.18:8080/laptop/api/upload"

curl -s -o /tmp/upload_response.txt -w "%{http_code}" \
  -X POST "$UPLOAD_URL" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ceartrack-upload-2026" \
  -d @"$REPORT_FILE" \
  --connect-timeout 10 \
  --max-time 30
```

**Server-side envelope wrapping:**
Server extracts from raw payload:
- `sn` ← `system.serial_number`
- `timestamp` ← `test_info.test_time`
- `overall_result` ← `overall_result`
- `hostname` ← `test_info.hostname`

Client does NOT need to format envelope.

---

## Known Issues & Workarounds

### Nginx Static Files
Flask must use `static_url_path='/laptop/static'`:
```python
app = Flask(__name__, static_url_path='/laptop/static', ...)
```

### Surface IPU3/IPU6 Camera
- Cannot capture image on standard Live USB
- Requires kernel ≥ 6.6 + Intel IPA binary
- Script marks as `HARDWARE_DETECTED`, not `FAIL`
- dmesg fallback: filters out `acpi_video`/`GFX0` false positives

### HP ProBook Touchpad (I2C HID)
- Two drivers compete: `hid-multitouch` (I2C, correct) vs `psmouse` (PS/2)
- Fix: `sudo modprobe -r psmouse` before testing
- Script evdev detection: prefer `i2c` path devices over `serio` path

### SATA SSD Health
- `Percentage Used Endurance Indicator` only in `smartctl -x` Device Statistics
- `smartctl -A` misses this field → all N/A
- Solution: use `smartctl -x` for all disk health reads

### False Camera Detection (no-camera laptops)
- Intel GPU registers as `/dev/video*` via ACPI
- Filter by driver name: skip `i915`, `acpi_video`
- Only process `uvcvideo`, `ov*`, `hi*`, `imx*` drivers

---

## Future Analysis Project (Not Yet Built)

Planned separate service that reads `history/` directories:

```
Analysis Dashboard (future)
├── Cross-module SN timeline (laptop test → wipe → resale)
├── Weekly/monthly/custom date statistics
├── Fail pattern analysis
├── Wipe log integration (XERASwin .log parser)
└── Compliance reports (NIST 800-88 wipe certificates)
```

**Wipe Log Notes:**
- XERASwin generates `.log` files per disk erasure
- Key SN: disk serial number (not host machine SN)
- `Percentage Used Endurance Indicator` maps to `ssd_health_percent`
- Envelope `sn` = disk SN, `related_sn` = host machine SN (if needed)
- Raw `.log` files preserved permanently for compliance audit

**`_index/` jsonl hook** already stubbed in `storage.py`:
```python
# TODO: _update_index(module_name, envelope)
# Appends {sn, module, result, ts, file} to YYYY-MM.jsonl
# Enables O(1) bulk queries without recursive glob
```

---

## Pending Tasks (in `tasks/monitorcenter/`)

| File | Description | Status |
|------|-------------|--------|
| `fix_card_expand.md` | Card expand uses SN+timestamp key, multi-open | Done |
| `fix_latest_overwrite.md` | Re-upload SN deletes old history, overwrites latest | Done |
| `fix_brand_fail_sidebyside.md` | By Brand + Fail Reasons side-by-side equal height | Done |
| `ceartrack_and_statistics.md` | Rename + Stats tab + bar charts | Done |
| `fix_statistics_ui.md` | Calendar week/month, thin bars, storage in detail | Done |
| `add_auth_system.md` | Login, roles, module permissions, user management | Pending |
| `fix_camera_image_display.md` | Show base64 camera image in detail view | Pending |

## Pending Tasks (in `tasks/`)

| File | Description | Status |
|------|-------------|--------|
| `fix_ask_manual.md` | Redirect prompt text to stderr, clean JSON values | Done |
| `fix_ssd_health_grade.md` | NVMe/SATA grade A-D using smartctl -x | Pending |
| `fix_camera_image_upload.md` | Base64 encode camera image into JSON | Pending |
| `fix_camera_false_positive.md` | Filter GPU/ACPI fake /dev/video* devices | Pending |
| `fix_camera_dmesg_fallback.md` | HARDWARE_DETECTED for IPU3/IPU6 | Done |
| `fix_storage_usb_filter.md` | Filter Live USB from storage list (TRAN==usb) | Done |
| `fix_keyboard_evdev.md` | evdev keyboard test with layout display | Pending |
| `fix_touchpad_evdev.md` | evdev touchpad auto-detection | Pending |

---

## Change Admin Password

```bash
# Via admin UI: /admin/users → click admin → change password
# Or directly edit users.json:
python3 -c "
from werkzeug.security import generate_password_hash
print(generate_password_hash('your-new-password'))
"
# Paste output into users.json admin.password_hash field
```

---

## Start / Stop Service

```bash
# Manual
cd /opt/monitorcenter
source venv/bin/activate
python app.py

# As systemd service (recommended)
sudo systemctl start ceartrack
sudo systemctl stop ceartrack
sudo systemctl status ceartrack
sudo journalctl -u ceartrack -f
```

---

*Last updated: 2026-05*
*Maintained by: Cear IT*
