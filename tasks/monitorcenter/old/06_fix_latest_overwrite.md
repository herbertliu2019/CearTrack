# Fix: One SN = One Test Record (Latest + History)

## Business Rule

One SN = one laptop = one final test result.
If a laptop is re-tested, the new result replaces ALL previous records
for that SN — in both latest/ and history/.

Reason: duplicate SN records corrupt Statistics (same machine counted twice).

## Behavior

| Action | latest/ | history/ |
|--------|---------|----------|
| First upload for SN | Create SN.json | Create SN_timestamp.json |
| Re-upload same SN | Overwrite SN.json | Delete all old SN_*.json, write new one |

## Fix in `core/storage.py`

Replace `write_envelope()` with this implementation:

```python
def write_envelope(module_name: str, sn: str, envelope: dict):
    import json
    from datetime import datetime

    now = datetime.now()

    # 1. latest/ — always overwrite
    latest_dir = get_latest_dir(module_name)
    latest_dir.mkdir(parents=True, exist_ok=True)
    latest_file = latest_dir / f"{sn}.json"
    with open(latest_file, 'w') as f:
        json.dump(envelope, f, indent=2)

    # 2. history/ — delete ALL existing files for this SN, then write new one
    base_history = get_base_history_dir(module_name)   # data/<module>/history/
    if base_history.exists():
        # Recursive search for any file matching SN_*.json across all date dirs
        existing = list(base_history.rglob(f"{sn}_*.json"))
        for old_file in existing:
            old_file.unlink()
            # Remove empty parent dirs (MM-DD/ and YYYY/) if now empty
            try:
                old_file.parent.rmdir()        # MM-DD/
                old_file.parent.parent.rmdir() # YYYY/
            except OSError:
                pass  # Not empty, that's fine

    # Write new history record
    history_dir = get_date_subdir(module_name)
    history_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{sn}_{now.strftime('%Y%m%d_%H%M%S')}.json"
    with open(history_dir / filename, 'w') as f:
        json.dump(envelope, f, indent=2)

    # TODO: _update_index(module_name, envelope)
    # Future: append line to data/<module>/_index/YYYY-MM.jsonl
```

Also add `get_base_history_dir()` helper in `core/storage.py`:

```python
def get_base_history_dir(module_name: str) -> Path:
    """Returns data/<module>/history/ root (not date-specific)."""
    return config.BASE_DIR / module_name / "history"
```

## Verification

```bash
# 1. Upload first test for SN=TEST001
curl -X POST http://localhost:5004/laptop/api/upload \
  -H "Content-Type: application/json" \
  -d '{"system":{"serial_number":"TEST001",...},"overall_result":"FAIL",...}'

# Check: one file in history
find /opt/monitorcenter/data/laptop/history -name "TEST001_*"
# Expected: exactly 1 file

# 2. Upload second test for same SN (e.g. next day, result PASS)
curl -X POST http://localhost:5004/laptop/api/upload \
  -H "Content-Type: application/json" \
  -d '{"system":{"serial_number":"TEST001",...},"overall_result":"PASS",...}'

# Check: still only ONE file in history (old deleted, new created)
find /opt/monitorcenter/data/laptop/history -name "TEST001_*"
# Expected: exactly 1 file, newer timestamp, result PASS

# Check: latest also updated
cat /opt/monitorcenter/data/laptop/latest/TEST001.json | python3 -m json.tool | grep overall_result
# Expected: "PASS"

# 3. Statistics should show TEST001 only once
curl "http://localhost:5004/laptop/api/stats/range?range=week"
# total count should not double-count TEST001
```

## Constraints
- Only modify `core/storage.py`
- Do NOT change any other files
- `rglob` must search recursively across ALL date subdirectories
- Empty date dirs (MM-DD/ YYYY/) should be cleaned up after deletion
- Run `python -m py_compile core/storage.py` after changes
