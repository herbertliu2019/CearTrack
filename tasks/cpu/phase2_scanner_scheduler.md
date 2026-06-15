# CPU Module — Phase 2: Scanner + Scheduler

## Prerequisites
Phase 1 must be complete:
- `monitorcenter/modules/cpu/parser.py` — `parse_log(log_path) -> dict`
- `monitorcenter/modules/cpu/db.py` — `init_db`, `insert_record`, `set_scan_status`, etc.

## Context
The CPU log directory has NO fixed year/month structure. Logs are stored in arbitrary
subdirectory trees under the root, organized by testers and CPU models. The only
consistent rule: the **leaf directory name = CPU SN**, and it contains `TESTRESULTS.TXT`.

Example structures that all coexist under one root:
```
cpu_test/
  Nicks cpu/I5-8500/M8VE287600952/TESTRESULTS.TXT
  Ryans cpu/I7-9700/80CY867000949/TESTRESULTS.TXT
  By SN/M8VE287600952/TESTRESULTS.TXT          ← duplicate SN, skip via log_path UNIQUE
  First Failed CPU/Log.TXT                      ← different filename, skip
  Carsons cpu/I3-6300/U5KS180704080/TESTRESULTS.TXT
```

## Incremental Detection Strategy
No timestamps embedded in paths. Use filesystem `mtime` on **top-level subdirectories**
(direct children of root) to detect new files:
- On each poll: compare mtime of each top-level subdir against `last_scan_mtime` stored in DB
- If any subdir mtime changed → re-scan that subdir's entire subtree
- This avoids full re-walk of 1400+ files every 10 minutes

## Files to Create

### `monitorcenter/modules/cpu/scanner.py`

```python
class CpuScanner:
    def __init__(self, root_dir: str, db_path: str): ...
    
    def collect_log_paths(self, subtree: str = None) -> list[str]:
        """
        Recursively walk subtree (or root_dir if None).
        Yield absolute paths of all TESTRESULTS.TXT files found.
        Skip dirs/files that are not readable.
        """
    
    def process_file(self, log_path: str) -> str:
        """
        Parse log_path, insert into DB.
        Returns: 'inserted' | 'skipped' | 'error'
        """
    
    def run_full(self) -> dict:
        """
        Full scan of entire root_dir.
        Updates scan_status in DB throughout.
        Returns summary: {total, inserted, skipped, errors}
        """
    
    def run_incremental(self) -> dict:
        """
        Check mtime of each top-level subdir of root_dir.
        Re-scan only subtrees that changed since last scan.
        Store last-seen mtimes in a JSON sidecar file:
          <db_path_dir>/cpu_scan_state.json
          Format: {"<subdir_abs_path>": <mtime_float>, ...}
        Returns summary dict.
        """
    
    @staticmethod
    def make_server_path(local_path: str) -> str:
        """
        Convert local Windows dev path to server Linux path if needed.
        Config-driven: if CPU_PATH_MAP set in app config, apply substitution.
        Otherwise return path as-is.
        """
```

Key implementation notes:
- `collect_log_paths`: only match filename `TESTRESULTS.TXT` (case-insensitive for safety)
- Skip `Log.TXT` and other filenames (those are one-off, not standard IPDT format)
- On `run_full`: call `set_scan_status(db_path, status='running', total=N, done=0, inserted=0, skipped=0, errors=0)` before loop, update `done` every 50 files, set `status='done'` at end
- Use `try/except` per file — one bad file must not abort the scan
- Thread-safe: scanner methods may be called from background thread

### `monitorcenter/modules/cpu/scheduler.py`

```python
import threading, time, logging

logger = logging.getLogger("cpu.scheduler")

class CpuScheduler:
    def __init__(self, root_dir: str, db_path: str, interval: int = 600):
        self.root_dir = root_dir
        self.db_path = db_path
        self.interval = interval  # seconds, default 10 min
        self._stop = threading.Event()
        self._thread = None
    
    def start(self):
        """Start background daemon thread."""
    
    def stop(self):
        """Signal thread to stop."""
    
    def _poll_loop(self):
        """
        Loop: sleep interval, then run_incremental().
        Log insertion counts. Stop when _stop is set.
        """
```

- Thread name: `"cpu-poller"`
- Daemon: `True`
- Log format: `"cpu-poller: incremental scan done — inserted={n}, skipped={m}"`

## Validation
```bash
python -m py_compile modules/cpu/scanner.py
python -m py_compile modules/cpu/scheduler.py
```

Smoke test (run from repo root, adjust path):
```python
from modules.cpu.scanner import CpuScanner
scanner = CpuScanner(
    root_dir="/opt/monitorcenter/cpu_test",
    db_path="/opt/monitorcenter/data/cpu/cpu.db"
)
# First: init DB
from modules.cpu.db import init_db
import os; os.makedirs("/opt/monitorcenter/data/cpu", exist_ok=True)
init_db("/opt/monitorcenter/data/cpu/cpu.db")

summary = scanner.run_full()
print(summary)
# Expected: {total: ~1432, inserted: ~1432, skipped: 0, errors: ~0}

# Run again — should skip all (already inserted)
summary2 = scanner.run_full()
print(summary2)
# Expected: {total: ~1432, inserted: 0, skipped: ~1432, errors: ~0}
```

## Notes
- Do NOT modify parser.py or db.py from Phase 1
- `cpu_scan_state.json` is a runtime artifact, not config — store beside the DB file
- Windows path separators are fine in dev; use `os.path` throughout (not hardcoded slashes)
