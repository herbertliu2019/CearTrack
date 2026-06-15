文件：
  /opt/monitorcenter/modules/wipe/routes.py
  /opt/monitorcenter/modules/wipe/integration.py

先读取两个文件的现有内容，然后：

routes.py 修改点：

1. 顶部追加 import：
   from modules.wipe.scheduler import get_poll_state

2. 更新 GET /api/scan/status：
   合并 db_status 和 get_poll_state()
   返回字段包含：
     running/total/done/errors/scan_type（来自DB）
     poller_running/last_scan_at/next_scan_at/interval（来自scheduler）

3. 新增 POST /api/scan/poll：
   检查 running==1 → {"status":"already_running"}
   否则后台线程执行 WipeScanner.run_poll()
   返回 {"status":"started","type":"poll"}

4. GET /api/search 确认实现：
   query_by_sn(conn, q) 返回全部历史记录
   结果中第一条（最新）标注 "is_latest": True
   其余标注 "is_latest": False

integration.py 修改点：

在 register_wipe_module(app) 末尾追加：
  from modules.wipe.scheduler import start_poll_scheduler
  if not app.testing:
      start_poll_scheduler(app.config["WIPE_CFG"])