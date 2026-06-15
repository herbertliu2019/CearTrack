# CPU Module — Phase 1: Parser + Database

## Context
CearTrack monitorcenter Flask app at `/opt/monitorcenter/` (dev: local repo).
This phase creates the data layer for the CPU test module.
Reference: wipe module at `monitorcenter/modules/wipe/` for patterns (parser.py, db.py).

## Log Format Reference

Tool: Intel Processor Diagnostic Tool (IPDT64 v4.1.9.41)
File: `TESTRESULTS.TXT` inside each SN leaf directory.

### Directory Structure
```
<root>/                         ← e.g. /opt/monitorcenter/cpu_test/
  <any subdir structure>/       ← tester names, model folders, arbitrary nesting
    <SN>/                       ← leaf dir name IS the CPU serial number
      TESTRESULTS.TXT
      pass.png  (or fail.png, or *.jpg)
```
- SN = leaf directory name (e.g. `M8VE287600952`)
- No fixed depth — scan recursively, detect leaf by presence of TESTRESULTS.TXT

### Key Fields to Extract from TESTRESULTS.TXT

```
--- IPDT64 - Revision: 4.1.9.41
--- IPDT64 - Start Time: 1/2/2026 12:09:03 PM
--- IPDT64 - End Time: 1/2/2026 12:12:53 PM
--- IPDT64 - Result: Pass          ← or "Fail"

# From "CPU Brand String Test" section:
Detected: Intel(R) Core(TM) i5-8500 CPU @ 3.00GHz

# From "Cache Test" section:
- Detected L3 Cache Size --> 9216

# From "IMC Test" section:
Detected Memory Size is --> 32.00GB

# From "Frequency Check" section:
Expected Processor Frequency: 3.00
Measured Processor Frequency: 2.999305
Test Result - PASS   (or FAIL)

# From "System Information" section:
Processor Name: Intel(R) Core(TM) i5-8500 CPU @ 3.00GHz
Processor Information: Family 6 Model 9E Stepping A
Number of Physical Cores: 6
Number of Logical Cores: 6
Operating System: Microsoft Windows 10 Home 64-bit
Graphics Information: Intel(R) UHD Graphics 630

# From "Prime Number Generation Test" (take MAX value across multiple occurrences):
Operation Per Second: 616690

# From "Floating Point Test" (take MAX value across multiple occurrences):
Million Floating Points per Second, MFLOPS: 6.37
```

### Derived Fields
- `cpu_family`: parse from processor_name → `i3` / `i5` / `i7` / `i9`
- `cpu_model`: parse from processor_name → `8500` (number after family)
- `cpu_generation`: first digit(s) of model → `8500` → gen `8`, `10700` → gen `10`
- `cpu_full_name`: `i5-8500`
- `manufacturer`: always `Intel` for now (AMD = future)
- `speed_ghz`: parse `@ 3.00GHz` from processor_name
- `freq_ratio`: `measured_freq / expected_freq` (float, 2 decimal places)
- `duration_sec`: `end_time - start_time` in seconds
- `test_date`: date portion of start_time (YYYY-MM-DD)
- `image_path`: absolute path to .png/.jpg in same dir as TESTRESULTS.TXT (None if not found)
- `log_path`: absolute path to TESTRESULTS.TXT (UNIQUE dedup key)

## Files to Create

### `monitorcenter/modules/cpu/__init__.py`
```python
from .routes import cpu_bp
from .integration import register_cpu_module
```

### `monitorcenter/modules/cpu/parser.py`

Parse a single TESTRESULTS.TXT file. Return a dict with all fields above.
Key requirements:
- Accept `log_path` (str) as input
- Derive `sn` from `os.path.basename(os.path.dirname(log_path))`
- Find image: scan same dir for first `.png` or `.jpg` file
- Parse `start_time` / `end_time` from format `M/D/YYYY H:MM:SS AM/PM`
- Convert to ISO datetime string for storage
- `overall_result`: normalize to `"Pass"` or `"Fail"`
- `fail_module`: if result is Fail, extract which module section has `Test Result - FAIL`
- `prime_ops_per_sec`: find all `Operation Per Second:` lines, take max integer
- `mflops`: find all `Million Floating Points per Second, MFLOPS:` lines, take max float
- All fields must handle missing data gracefully (return None, not raise)
- Encoding: open with `utf-8`, fallback to `latin-1`

Return dict keys:
```python
{
  "sn", "log_path", "image_path",
  "manufacturer", "cpu_family", "cpu_model", "cpu_generation",
  "cpu_full_name", "processor_name", "speed_ghz",
  "physical_cores", "logical_cores",
  "l3_cache_kb", "memory_gb",
  "expected_freq_ghz", "measured_freq_ghz", "freq_ratio",
  "prime_ops_per_sec", "mflops",
  "overall_result", "fail_module",
  "test_date", "start_time", "end_time", "duration_sec",
  "ipdt_revision", "os_info", "graphics_info"
}
```

### `monitorcenter/modules/cpu/db.py`

SQLite database at path from app config `CPU_DB_PATH`.

#### Table: `cpu_records`
Columns (all NOT NULL unless noted):
```sql
id INTEGER PRIMARY KEY AUTOINCREMENT,
sn TEXT NOT NULL,
log_path TEXT NOT NULL UNIQUE,   -- dedup key
image_path TEXT,                  -- nullable
manufacturer TEXT,
cpu_family TEXT,                  -- i3/i5/i7/i9
cpu_model TEXT,                   -- 8500
cpu_generation INTEGER,           -- 8
cpu_full_name TEXT,               -- i5-8500
processor_name TEXT,
speed_ghz REAL,
physical_cores INTEGER,
logical_cores INTEGER,
l3_cache_kb INTEGER,
memory_gb REAL,
expected_freq_ghz REAL,
measured_freq_ghz REAL,
freq_ratio REAL,
prime_ops_per_sec INTEGER,
mflops REAL,
overall_result TEXT,
fail_module TEXT,
test_date TEXT,                   -- YYYY-MM-DD
start_time TEXT,                  -- ISO datetime
end_time TEXT,
duration_sec INTEGER,
ipdt_revision TEXT,
os_info TEXT,
graphics_info TEXT,
inserted_at TEXT DEFAULT (datetime('now'))
```

#### Table: `scan_status`
```sql
id INTEGER PRIMARY KEY,
status TEXT,          -- idle / running / done
started_at TEXT,
finished_at TEXT,
total INTEGER DEFAULT 0,
done INTEGER DEFAULT 0,
inserted INTEGER DEFAULT 0,
skipped INTEGER DEFAULT 0,
errors INTEGER DEFAULT 0
```

#### Functions to implement:
```python
def init_db(db_path: str) -> None
def get_conn(db_path: str) -> sqlite3.Connection
def insert_record(db_path: str, record: dict) -> bool  # True=inserted, False=skipped(dup)
def query_today(db_path: str) -> list[dict]
def query_period(db_path: str, start: str, end: str) -> list[dict]  # YYYY-MM-DD strings
def query_by_sn(db_path: str, q: str) -> list[dict]  # LIKE search on sn + cpu_full_name
def stats_summary(db_path: str, start: str, end: str) -> dict
def by_family(db_path: str, start: str, end: str) -> list[dict]   # [{family, count}]
def by_generation(db_path: str, start: str, end: str) -> list[dict]  # [{generation, count}]
def by_model(db_path: str, start: str, end: str) -> list[dict]    # [{cpu_full_name, count}] top 15
def daily_counts(db_path: str, start: str, end: str) -> list[dict]  # [{date, count}]
def get_scan_status(db_path: str) -> dict
def set_scan_status(db_path: str, **kwargs) -> None
```

`stats_summary` returns:
```python
{
  "total": int,
  "pass_count": int,
  "fail_count": int,
  "freq_anomaly_count": int,  # freq_ratio < 0.5
  "avg_duration_sec": float
}
```

## Validation
After writing, run:
```bash
cd /opt/monitorcenter  # or local repo path
python -m py_compile modules/cpu/parser.py
python -m py_compile modules/cpu/db.py
```

Then do a quick smoke test:
```python
from modules.cpu.parser import parse_log
result = parse_log("/opt/monitorcenter/cpu_test/Nicks cpu/I5-8500/M8VE287600952/TESTRESULTS.TXT")
print(result)
# Expected: sn=M8VE287600952, cpu_family=i5, cpu_model=8500, generation=8, speed_ghz=3.0
```

## Notes
- Do NOT modify any existing files in this phase
- Follow wipe module patterns for db.py (INSERT OR IGNORE for dedup)
- `log_path` stored as absolute path (Linux path on server, Windows path in dev — parser should work on both)
