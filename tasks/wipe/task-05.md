TASK-05｜scheduler.py
文件：/opt/monitorcenter/modules/wipe/scheduler.py

使用 threading 实现当月目录定时轮询，无需额外依赖。

重要约束：
- SMB 挂载不支持 inotify，必须主动轮询
- 轮询间隔来自 wipe_paths.json 的 poll_interval（默认600秒）
- 只扫当前月份目录（WipeScanner.run_poll）
- 月份变更时自动切换到新目录（run_poll 内部用 datetime.now()）

实现：

_poll_thread = None
_stop_event  = threading.Event()

def _poll_loop(cfg: dict, interval: int):
  scanner = WipeScanner(
      log_root       = cfg["log_root"],
      db_path        = cfg["db_path"],
      win_share_root = cfg["win_share_root"]
  )
  while not _stop_event.is_set():
    try:
      # 仅在非全量扫描运行时执行
      conn = get_conn(cfg["db_path"])
      status = get_scan_status(conn)
      conn.close()
      if status["running"] == 0:
        result = scanner.run_poll()
        if result["inserted"] > 0:
          logger.info(f"Poll: {result['inserted']} new records")
    except Exception as e:
      logger.error(f"Poll error: {e}")
    _stop_event.wait(interval)

def start_poll_scheduler(cfg: dict) -> None
  global _poll_thread, _stop_event
  interval = cfg.get("poll_interval", 600)
  _stop_event.clear()
  _poll_thread = threading.Thread(
      target=_poll_loop,
      args=(cfg, interval),
      daemon=True,          # Flask 退出时自动结束
      name="wipe-poller"
  )
  _poll_thread.start()
  logger.info(f"Wipe poller started, interval={interval}s")

def stop_poll_scheduler() -> None
  _stop_event.set()

验收：
Flask 启动后日志出现：
  "Wipe poller started, interval=600s"
等待 10 分钟（或临时改为 interval=30 测试），
新放入当月目录的 log 文件出现在 /wipe/api/today 响应中。