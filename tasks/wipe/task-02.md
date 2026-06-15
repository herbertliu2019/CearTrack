文件：/opt/monitorcenter/modules/wipe/parser_makor.py

实现：
def parse_makor_xml(xml_path: Path) -> dict | None
  - 使用 xml.etree.ElementTree 解析
  - 提取 skill.md 中 EDE xml 字段提取表的所有字段
  - 必须存在 ErasureResults 节点才有效，否则返回 None
  - result：PASS → PASSED，FAIL → FAILED，统一大写
  - wipe_date：MM/DD/YYYY → YYYY-MM-DD
  - wipe_datetime：wipe_date + T + ErasureTime → ISO 8601
  - duration_min：
      ErasureDuration 格式为 "MM:SS"
      转换：int(MM) + int(SS)/60 → float
      "00:00" → 0.0
  - ssd_life：XML 无此字段 → None
  - 任何字段提取失败值为 None，不抛异常
  - 不处理 log_path / win_path / source 字段

验收：
  python3 -c "
  from pathlib import Path
  from modules.wipe.parser_makor import parse_makor_xml
  import json
  r = parse_makor_xml(Path('test_logs/sample_makor.xml'))
  assert r is not None
  assert r['result'] in ('PASSED', 'FAILED')
  assert r['wipe_date'] is not None
  print(json.dumps(r, indent=2))
  print('parser_makor.py OK')
  "