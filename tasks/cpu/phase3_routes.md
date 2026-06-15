# CPU Module — Phase 3: API Routes

## Prerequisites
- Phase 1 complete: `parser.py`, `db.py`
- Phase 2 complete: `scanner.py`, `scheduler.py`

## Context
Flask blueprint registered at `/cpu/`. Follow wipe module's `routes.py` pattern
at `monitorcenter/modules/wipe/routes.py`.

App config keys available (set by `integration.py` in Phase 5, but define routes
to read from `current_app.config`):
- `CPU_DB_PATH` — absolute path to `cpu.db`
- `CPU_ROOT_DIR` — root directory for log files

## File to Create

### `monitorcenter/modules/cpu/routes.py`

```python
from flask import Blueprint, jsonify, request, send_file, current_app, render_template
cpu_bp = Blueprint('cpu', __name__,
                   template_folder='templates',
                   url_prefix='/cpu')
```

### Endpoints

#### `GET /cpu/`
Render dashboard HTML template.
```python
return render_template('cpu/dashboard.html')
```

#### `GET /cpu/api/today`
Returns today's records.
```python
# Call db.query_today(db_path)
# Return: {"records": [...], "count": N}
```

#### `GET /cpu/api/stats`
Query params: `period` (`week`|`month`|`custom`), `start` (YYYY-MM-DD), `end` (YYYY-MM-DD)

If `period=week`: start = today - 6 days, end = today
If `period=month`: start = first day of current month, end = today
If `period=custom`: use `start` and `end` params

Returns:
```json
{
  "summary": {
    "total": 234,
    "pass_count": 233,
    "fail_count": 1,
    "freq_anomaly_count": 1,
    "avg_duration_sec": 235
  },
  "by_family": [
    {"family": "i5", "count": 120},
    {"family": "i7", "count": 80}
  ],
  "by_generation": [
    {"generation": 8, "count": 90},
    {"generation": 7, "count": 75}
  ],
  "by_model": [
    {"cpu_full_name": "i5-8500", "count": 45}
  ],
  "daily": [
    {"date": "2026-01-02", "count": 12}
  ]
}
```

#### `GET /cpu/api/search`
Query param: `q` (string, min 2 chars)
Search on `sn` LIKE and `cpu_full_name` LIKE.
```json
{"results": [...], "count": N}
```
Return 400 if `q` is missing or < 2 chars.

#### `POST /cpu/api/scan`
Trigger a full scan in a background thread.
Returns 409 if scan already running.
```json
{"status": "started"}
```

Implementation:
```python
import threading
from .scanner import CpuScanner

status = db.get_scan_status(db_path)
if status.get('status') == 'running':
    return jsonify({"error": "scan already running"}), 409

def run():
    scanner = CpuScanner(root_dir, db_path)
    scanner.run_full()

threading.Thread(target=run, daemon=True).start()
return jsonify({"status": "started"})
```

#### `GET /cpu/api/scan/status`
```json
{
  "status": "idle",
  "total": 1432,
  "done": 1432,
  "inserted": 12,
  "skipped": 1420,
  "errors": 0,
  "started_at": "2026-01-02T12:00:00",
  "finished_at": "2026-01-02T12:01:30"
}
```

#### `GET /cpu/api/image/<int:record_id>`
Look up record by id, get `image_path`.
If `image_path` is None or file doesn't exist → return 404.
Use `flask.send_file(image_path)`.
Set cache headers: `max_age=86400`.

```python
@cpu_bp.route('/api/image/<int:record_id>')
def get_image(record_id):
    conn = db.get_conn(db_path)
    row = conn.execute("SELECT image_path FROM cpu_records WHERE id=?", (record_id,)).fetchone()
    conn.close()
    if not row or not row['image_path']:
        return '', 404
    path = row['image_path']
    if not os.path.isfile(path):
        return '', 404
    return send_file(path, max_age=86400)
```

## Record Dict Format (returned in API responses)
All list endpoints return records as dicts with these keys:
```
id, sn, manufacturer, cpu_family, cpu_model, cpu_generation,
cpu_full_name, processor_name, speed_ghz,
physical_cores, logical_cores, l3_cache_kb, memory_gb,
expected_freq_ghz, measured_freq_ghz, freq_ratio,
prime_ops_per_sec, mflops,
overall_result, fail_module,
test_date, start_time, end_time, duration_sec,
image_path (bool: true if image exists, not the path itself — security),
inserted_at
```
Note: **never return `image_path` raw string** to frontend. Return `has_image: true/false`.
Frontend loads image via `/cpu/api/image/<id>`.

## Validation
```bash
python -m py_compile modules/cpu/routes.py
```

Then with the app running:
```bash
curl http://localhost:5004/cpu/api/today
curl http://localhost:5004/cpu/api/stats?period=week
curl http://localhost:5004/cpu/api/search?q=M8VE
curl http://localhost:5004/cpu/api/scan/status
```

## Notes
- All JSON responses use `jsonify()`
- Error responses: `{"error": "message"}` with appropriate HTTP status code
- Do NOT include authentication in this phase (auth is a future task per CLAUDE.md)
- `db_path` and `root_dir` always read from `current_app.config` — never hardcoded
