from pathlib import Path
from modules.wipe.parser import parse_log
import json

logs = sorted(Path('test_logs').glob('*.log'))
for p in logs:
    r = parse_log(p)
    print(f'=== {p.name} ===')
    if r is None:
        print('  RESULT: None (no Erasure Results line)')
    else:
        print(json.dumps(r, indent=2))
    print()
