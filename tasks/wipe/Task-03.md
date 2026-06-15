文件：/opt/monitorcenter/modules/wipe/db.py

如果文件已存在，验证以下函数是否存在：
  init_db / get_conn / insert_record /
  query_today / query_period / query_by_sn /
  stats_summary / by_manufacturer / fail_reasons /
  get_scan_status / upsert_scan_status

存在则跳过，缺少则补充。

重点确认：

1. init_db(db_path) 建表 SQL 包含 source 字段：
   source TEXT

2. insert_record(conn, record) 包含 source 字段写入

3. query_by_sn(conn, q) 实现：
   WHERE UPPER(drive_sn)=UPPER(?) OR UPPER(system_sn)=UPPER(?)
   ORDER BY wipe_datetime DESC
   返回全部历史记录（不限制条数）

4. stats_summary(records) 包含 warning 计数：
   result=PASSED AND (health_score<70 OR ssd_life<50)
   返回：total/passed/failed/warning/pass_rate/avg_duration

5. get_scan_status 不存在时返回默认值：
   {"running":0,"total":0,"done":0,"errors":0,
    "scan_type":None,"started_at":None,"updated_at":None}