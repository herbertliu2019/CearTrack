TASK-02｜db.py

文件：/opt/monitorcenter/modules/wipe/db.py
实现数据库初始化与查询封装。

函数清单：

init_db(db_path: str) -> None
  建三张表（见 skill.md Schema），幂等

get_conn(db_path: str) -> sqlite3.Connection
  row_factory = sqlite3.Row
  PRAGMA journal_mode=WAL
  PRAGMA synchronous=NORMAL

insert_record(conn, record: dict) -> bool
  INSERT OR IGNORE INTO wipe_records
  返回 True=实际插入，False=已存在跳过

query_today(conn) -> list[dict]
  WHERE wipe_date = date('now', 'localtime')

query_period(conn, start: str, end: str) -> list[dict]
  WHERE wipe_date BETWEEN start AND end

query_by_sn(conn, q: str) -> list[dict]
  WHERE UPPER(drive_sn)=UPPER(?) OR UPPER(system_sn)=UPPER(?)
  ORDER BY wipe_datetime DESC

stats_summary(records: list[dict]) -> dict
  返回 total/passed/failed/warning/pass_rate/avg_duration
  warning：result=PASSED AND (health_score<70 OR ssd_life<50)

by_manufacturer(records: list[dict]) -> list[dict]
  按 sys_manufacturer 分组计数，降序
  返回 [{"name": "Dell", "count": 12}, ...]

fail_reasons(records: list[dict]) -> list[dict]
  筛选 result=FAILED，按 method 分组计数，降序
  返回 [{"reason": "...", "count": N}, ...]

get_scan_status(conn) -> dict
  SELECT FROM scan_status WHERE id=1
  不存在时返回：
  {"running": 0, "total": 0, "done": 0,
   "errors": 0, "scan_type": None,
   "started_at": None, "updated_at": None}

upsert_scan_status(conn, **kwargs) -> None
  INSERT OR REPLACE，id 固定为 1
  自动写入 updated_at = datetime.now().isoformat()