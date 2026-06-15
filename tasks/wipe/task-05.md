文件：/opt/monitorcenter/modules/wipe/scheduler.py

新建文件，完整实现：

模块级状态变量：
  _poll_thread:      threading.Thread | None = None
  _stop_event      = threading.Event()
  _last_scan_at:   str | None = None
  _next_scan_at:   str | None = None
  _current_interval: int = 600

def get_poll_state() -> dict
  返回：
  {
    "poller_running": bool,
    "last_scan_at":   str | None,
    "next_scan_at":   str | None,
    "interval":       int
  }

def _poll_loop(cfg, interval) -> None
  循环流程：
    1. _next_scan_at = now + interval
    2. _stop_event.wait(timeout=interval)
    3. 收到 stop → break
    4. 检查 scan_status.running==1 → 跳过，记录日志
    5. WipeScanner.run_poll()
    6. _last_scan_at = now
    7. inserted > 0 → info 日志，否则静默
  异常处理：任何异常 → error 日志，继续循环，不退出线程

def start_poll_scheduler(cfg) -> None
  - 线程已存活则直接返回
  - daemon=True，name="wipe-poller"
  - interval 从 cfg["poll_interval"] 读取，默认 600

def stop_poll_scheduler() -> None
  - _stop_event.set()
  - join(timeout=10)