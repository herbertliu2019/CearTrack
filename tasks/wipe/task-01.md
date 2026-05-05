TASK-01｜parser.py

/opt/monitorcenter/modules/wipe/parser.py
实现 parse_log(log_path: Path) -> dict | None

要求：
- 读取单个 XERASwin .log 文件，UTF-8，errors='replace'
- 必须存在 "Erasure Results" 行才视为有效，否则返回 None
- result 统一大写：PASSED / FAILED
- wipe_date：MM/DD/YYYY → YYYY-MM-DD
- wipe_datetime：ISO 8601
- duration_min：float，hrs * 60 + min
- health_score：float
- ssd_life / power_on_hrs：int
- 所有字段提取失败时值为 None，不抛异常
- 不处理路径字段（log_path / win_path 由 scanner 填入）

验收命令：
python3 -c "
from pathlib import Path
from modules.wipe.parser import parse_log
import json
r = parse_log(Path('test_logs/82TPGJ8XQ69K.log'))
assert r['drive_sn'] == '82TPGJ8XQ69K'
assert r['result'] == 'PASSED'
assert r['wipe_date'] == '2026-04-09'
print(json.dumps(r, indent=2))
print('PASS')
"