# CPU Module — Phase 5: Integration & Registration

## Prerequisites
All previous phases complete:
- `modules/cpu/parser.py`
- `modules/cpu/db.py`
- `modules/cpu/scanner.py`
- `modules/cpu/scheduler.py`
- `modules/cpu/routes.py` (exports `cpu_bp`)
- `modules/cpu/__init__.py` (exports `cpu_bp`, `register_cpu_module`)
- `modules/cpu/templates/cpu/dashboard.html`

## Files to Create / Modify

### 1. `monitorcenter/config/cpu_paths.json` (NEW)
```json
{
  "cpu_root_dir": "/opt/monitorcenter/cpu_test",
  "cpu_db_path": "/opt/monitorcenter/data/cpu/cpu.db",
  "poll_interval_sec": 600
}
```
Notes:
- Dev/test: set `cpu_root_dir` to local path where CPU logs are accessible
- Production: `cpu_root_dir` = `/mnt/CPU`
- This file is NOT committed with real paths — add to `.gitignore` or document as local config

### 2. `monitorcenter/modules/cpu/integration.py` (NEW)
```python
import os, json, logging
from .db import init_db
from .scheduler import CpuScheduler

logger = logging.getLogger("cpu.integration")

def register_cpu_module(app):
    """
    Load config, init DB, register blueprint, start scheduler.
    Called once from app.py at startup.
    """
    # 1. Load config
    config_path = os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'cpu_paths.json')
    config_path = os.path.abspath(config_path)
    
    if not os.path.exists(config_path):
        logger.warning(f"CPU config not found at {config_path}, module disabled")
        return
    
    with open(config_path) as f:
        cfg = json.load(f)
    
    root_dir = cfg.get('cpu_root_dir', '')
    db_path = cfg.get('cpu_db_path', '')
    interval = cfg.get('poll_interval_sec', 600)
    
    if not root_dir or not os.path.isdir(root_dir):
        logger.warning(f"CPU root_dir '{root_dir}' not found, module disabled")
        return
    
    # 2. Ensure data directory exists + init DB
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    init_db(db_path)
    
    # 3. Set app config keys
    app.config['CPU_DB_PATH'] = db_path
    app.config['CPU_ROOT_DIR'] = root_dir
    
    # 4. Register blueprint
    from .routes import cpu_bp
    app.register_blueprint(cpu_bp)
    
    # 5. Start background scheduler
    scheduler = CpuScheduler(root_dir=root_dir, db_path=db_path, interval=interval)
    scheduler.start()
    
    logger.info(f"CPU module registered. root={root_dir}, db={db_path}, poll={interval}s")
```

### 3. `monitorcenter/modules/cpu/__init__.py` (NEW)
```python
from .routes import cpu_bp
from .integration import register_cpu_module
```

### 4. `monitorcenter/app.py` (MODIFY — targeted edit only)

Find the section where wipe module is registered. Add CPU registration immediately after it.

**Find this pattern in app.py:**
```python
from modules.wipe.integration import register_wipe_module
# ... somewhere below:
register_wipe_module(app)
```

**Add after the wipe registration:**
```python
from modules.cpu.integration import register_cpu_module
register_cpu_module(app)
```

Do NOT rewrite any other part of app.py.

### 5. `monitorcenter/CLAUDE.md` (MODIFY — targeted edit only)

Find the module status table:
```markdown
| `wipe` | ✅ 已上线（XERASwin log 解析） |
| `cpu` | 🔨 下一个（实现方式同 wipe） |
```

Change `cpu` row to:
```markdown
| `cpu` | ✅ 已上线（IPDT64 log 解析，含图片） |
```

Also update Pending Tasks section — mark CPU module tasks as done.

---

## Data Directory Setup
After registering, the following must exist at runtime:
```
/opt/monitorcenter/data/cpu/
  cpu.db                  ← created by init_db()
  cpu_scan_state.json     ← created by scanner on first incremental run
```

For dev/local testing on Windows, adjust `cpu_paths.json` to use local paths:
```json
{
  "cpu_root_dir": "C:/Users/ITAD-02/OneDrive - California Electronic Asset Recovery, Inc/Desktop/Documents/ITAD Docs/03 Testing/CPU",
  "cpu_db_path": "C:/path/to/monitorcenter/data/cpu/cpu.db",
  "poll_interval_sec": 600
}
```

---

## Navigation Link (Optional — if base.html has nav)

Check `monitorcenter/templates/base.html` for the sidebar/nav links.
If there's a nav list with links to `/wipe/`, add:
```html
<a href="/cpu/" class="nav-link">CPU Tests</a>
```
Use targeted edit, do not rewrite base.html.

---

## Final Validation Checklist

```bash
# 1. Syntax check all new files
python -m py_compile modules/cpu/parser.py
python -m py_compile modules/cpu/db.py
python -m py_compile modules/cpu/scanner.py
python -m py_compile modules/cpu/scheduler.py
python -m py_compile modules/cpu/routes.py
python -m py_compile modules/cpu/integration.py

# 2. Start the app
python app.py
# Check logs for: "CPU module registered. root=..., db=..., poll=600s"
# No ImportError, no AttributeError

# 3. Hit the dashboard
curl http://localhost:5004/cpu/
# Should return HTML (200), not 404

# 4. Check API
curl http://localhost:5004/cpu/api/scan/status
# {"status": "idle", ...}

# 5. Trigger first full scan
curl -X POST http://localhost:5004/cpu/api/scan
# {"status": "started"}

# 6. Poll until done
curl http://localhost:5004/cpu/api/scan/status
# {"status": "done", "inserted": ~1432, ...}

# 7. Verify data
curl http://localhost:5004/cpu/api/stats?period=month
# Returns summary with counts > 0

# 8. Open browser → http://localhost:5004/cpu/
# Verify full UI loads and data displays
```

## Notes
- If `cpu_paths.json` is missing, the module silently disables itself (no crash)
- If `root_dir` is not mounted/accessible, same graceful disable
- The scheduler starts polling only AFTER the first manual scan or `run_full()` run
  (avoid scheduler running before data is populated on first boot)
- Do NOT run a full scan automatically at startup — user triggers it via UI or POST /cpu/api/scan
