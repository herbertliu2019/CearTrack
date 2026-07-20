

TASK-04｜routes.py + integration.py

文件：

/opt/monitorcenter/modules/wipe/routes.py
/opt/monitorcenter/modules/wipe/integration.py

routes.py：

Blueprint: wipe_bp, url_prefix="/wipe"
每个请求通过 current_app.config["WIPE_DB"] 获取 db_path

GET /
  render_template("wipe/dashboard.html")

GET /api/today
  conn = get_conn(db_path)
  records = query_today(conn)
  返回：
  {
    "stats": stats_summary(records),
    "records": records
  }

GET /api/stats
  参数：period=week|month|custom，start，end
  week：本周一到今天
  month：本月1日到今天
  custom：直接用 start/end
  records = query_period(conn, start, end)
  daily 统计：按 wipe_date 分组
  返回：
  {
    "period": period,
    "start": start, "end": end,
    "stats": stats_summary(records),
    "daily": [...],              -- 每日 {date, total, passed, failed}
    "by_manufacturer": by_manufacturer(records),
    "fail_reasons": fail_reasons(records),
    "records": records
  }

GET /api/search
  参数：q（必填，空则返回400）
  返回：
  {
    "query": q,
    "count": N,
    "results": query_by_sn(conn, q)
  }

POST /api/scan
  检查 scan_status.running：
    1 → 返回 {"status": "already_running"}
    0 → 启动后台线程执行 WipeScanner.run_full()
        返回 {"status": "started"}

GET /api/scan/status
  返回 get_scan_status(conn)

---

integration.py：

def register_wipe_module(app):
  1. 读取 config/wipe_paths.json（相对 app.root_path）
  2. init_db(cfg["db_path"])
  3. app.config["WIPE_DB"]  = cfg["db_path"]
  4. app.config["WIPE_CFG"] = cfg
  5. app.register_blueprint(wipe_bp)
  6. 启动后台轮询线程（调用 scheduler.start_poll_scheduler）