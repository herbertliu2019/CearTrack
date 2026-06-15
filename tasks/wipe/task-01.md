文件：/opt/monitorcenter/modules/wipe/parser.py

如果文件已存在且能正确解析 82TPGJ8XQ69K.log，
用以下命令验证后跳过本 Task：

  python3 -c "
  from pathlib import Path
  from modules.wipe.parser import parse_log
  import json
  r = parse_log(Path('test_logs/82TPGJ8XQ69K.log'))
  assert r['drive_sn'] == '82TPGJ8XQ69K'
  assert r['result'] == 'PASSED'
  assert r['wipe_date'] == '2026-04-09'
  print('parser.py OK')
  "

如果验证失败或文件不存在，实现以下函数：

def parse_log(log_path: Path) -> dict | None
  - 读取 XERASwin .log 文件
  - 提取 skill.md 中列出的全部字段
  - 必须存在 Erasure Results 行才有效，否则返回 None
  - result 统一大写：PASSED / FAILED
  - wipe_date：MM/DD/YYYY → YYYY-MM-DD
  - duration_min：hrs * 60 + min → float
  - 不处理 log_path / win_path / source 字段
  - 任何字段提取失败值为 None，不抛异常