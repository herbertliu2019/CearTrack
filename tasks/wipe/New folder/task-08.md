TASK｜为已有 Wipe 模块添加定时轮询
前提条件
以下文件已存在且功能完整，本 Task 不得修改其核心逻辑：
  modules/wipe/parser.py
  modules/wipe/db.py
  modules/wipe/scanner.py      ← 需确认 run_poll() 是否已实现
  modules/wipe/routes.py
  modules/wipe/integration.py
  templates/wipe/dashboard.html
第一步：确认 scanner.py 是否有 run_poll()
检查 modules/wipe/scanner.py 是否已有：
  - collect_current_month() 方法
  - run_poll() 方法

如果没有，在 WipeScanner 类中补充：

MONTH_DIRS = {
    1:"01 January",  2:"02 February", 3:"03 March",
    4:"04 April",    5:"05 May",      6:"06 June",
    7:"07 July",     8:"08 August",   9:"09 September",
    10:"10 October", 11:"11 November",12:"12 December"
}

def collect_current_month(self) -> list[Path]:
    now = datetime.now()
    month_dir = MONTH_DIRS[now.month]
    target = Path(self.log_root) / "logs" / str(now.year) / month_dir
    if not target.exists():
        logger.warning(f"[WipeScanner] current month dir not found: {target}")
        return []
    return sorted(target.glob("*.log"))

def run_poll(self) -> dict:
    files = self.collect_current_month()
    return self._process_files(files, scan_type="poll")

不修改已有的 run_full() 和其他方法。
第二步：新建 scheduler.py
新建文件：/opt/monitorcenter/modules/wipe/scheduler.py

import threading
import logging
from datetime import datetime, timedelta
from modules.wipe.scanner import WipeScanner
from modules.wipe.db import get_conn, get_scan_status

logger = logging.getLogger(__name__)

_poll_thread:    threading.Thread | None = None
_stop_event    = threading.Event()
_last_scan_at: str | None = None
_next_scan_at: str | None = None
_current_interval: int = 600


def get_poll_state() -> dict:
    return {
        "poller_running": _poll_thread is not None and _poll_thread.is_alive(),
        "last_scan_at":   _last_scan_at,
        "next_scan_at":   _next_scan_at,
        "interval":       _current_interval,
    }


def _poll_loop(cfg: dict, interval: int) -> None:
    global _last_scan_at, _next_scan_at

    scanner = WipeScanner(
        log_root       = cfg["log_root"],
        db_path        = cfg["db_path"],
        win_share_root = cfg["win_share_root"],
    )

    logger.info(
        f"[WipePoller] started, interval={interval}s, "
        f"target={cfg['log_root']}/logs/<current_month>/"
    )

    while not _stop_event.is_set():
        # 记录下次扫描时间
        _next_scan_at = (
            datetime.now().replace(microsecond=0) + timedelta(seconds=interval)
        ).isoformat()

        # 等待 interval 秒，可被 stop 提前中断
        if _stop_event.wait(timeout=interval):
            break

        # 全量扫描运行中则跳过
        try:
            conn = get_conn(cfg["db_path"])
            status = get_scan_status(conn)
            conn.close()
            if status.get("running") == 1:
                logger.info("[WipePoller] skipped: full scan in progress")
                continue
        except Exception as e:
            logger.warning(f"[WipePoller] DB check failed, skipping: {e}")
            continue

        # 执行当月轮询
        try:
            result = scanner.run_poll()
            _last_scan_at = datetime.now().replace(microsecond=0).isoformat()
            if result["inserted"] > 0:
                logger.info(
                    f"[WipePoller] inserted={result['inserted']} "
                    f"skipped={result['skipped']} "
                    f"errors={result['errors']}"
                )
            # 无新文件时静默
        except Exception as e:
            logger.error(f"[WipePoller] poll error: {e}")
            # 异常不退出线程，等下次


def start_poll_scheduler(cfg: dict) -> None:
    global _poll_thread, _stop_event, _current_interval

    if _poll_thread is not None and _poll_thread.is_alive():
        logger.warning("[WipePoller] already running, skip")
        return

    _current_interval = int(cfg.get("poll_interval", 600))
    _stop_event.clear()
    _poll_thread = threading.Thread(
        target=_poll_loop,
        args=(cfg, _current_interval),
        daemon=True,
        name="wipe-poller",
    )
    _poll_thread.start()


def stop_poll_scheduler() -> None:
    global _poll_thread
    _stop_event.set()
    if _poll_thread is not None:
        _poll_thread.join(timeout=10)
        _poll_thread = None
    logger.info("[WipePoller] stopped")
第三步：修改 integration.py
在现有 register_wipe_module(app) 函数末尾追加两行：

  from modules.wipe.scheduler import start_poll_scheduler

  def register_wipe_module(app):
      # ... 已有代码不动 ...

      # 追加：启动定时轮询（非测试环境）
      if not app.testing:
          start_poll_scheduler(app.config["WIPE_CFG"])

仅追加，不修改已有任何逻辑。
第四步：修改 routes.py
在 /wipe/api/scan/status 端点中合并轮询状态。

找到现有的 api_scan_status() 函数，修改返回值：

  # 在文件顶部 import 区域追加：
  from modules.wipe.scheduler import get_poll_state

  # 修改 api_scan_status()：
  @wipe_bp.route("/api/scan/status")
  def api_scan_status():
      conn       = get_conn(current_app.config["WIPE_DB"])
      db_status  = get_scan_status(conn)
      conn.close()
      poll_state = get_poll_state()
      return jsonify({**db_status, **poll_state})

  # 返回结构新增字段：
  # "poller_running": true/false
  # "last_scan_at":   "2026-05-05T10:42:18" 或 null
  # "next_scan_at":   "2026-05-05T10:52:18" 或 null
  # "interval":       600
第五步：修改 dashboard.html
在 Header 右侧（Rebuild Index 按钮旁）追加状态行：

  <div class="scan-status-bar">
    <span x-show="scanState.last_scan_at">
      Last scan: <span x-text="scanState.last_scan_at"></span>
    </span>
    <span x-show="scanState.next_scan_at">
      &nbsp;|&nbsp; Next in:
      <span x-text="nextScanIn()"></span>
    </span>
  </div>

在 Alpine.js app() 中追加：

  // 状态轮询（每30秒刷新一次状态栏，轻量）
  scanState: {
    poller_running: false,
    last_scan_at:   null,
    next_scan_at:   null,
    interval:       600,
  },

  async loadScanStatus() {
    const d = await (await fetch('/wipe/api/scan/status')).json();
    this.scanState = d;
    // 全量扫描进行中时更新进度 banner
    if (d.running === 1) {
      this.showBanner = true;
      this.bannerText = `INDEXING: ${d.done} / ${d.total} files...`;
    } else {
      this.showBanner = false;
    }
  },

  nextScanIn() {
    if (!this.scanState.next_scan_at) return '—';
    const diff = new Date(this.scanState.next_scan_at) - new Date();
    const mins = Math.ceil(diff / 60000);
    if (mins <= 0) return '< 1 min';
    return `${mins} min`;
  },

  // init() 中追加：
  // setInterval(() => this.loadScanStatus(), 30000);
  // await this.loadScanStatus();
第六步：wipe_paths.json 确认 poll_interval 字段存在
{
  "log_root":       "/mnt/win_logs",
  "db_path":        "/opt/monitorcenter/data/wipe_index.db",
  "win_share_root": "\\\\SERVER\\EPS",
  "poll_interval":  600
}

如果文件中没有 poll_interval，追加这一行即可。

验收标准
1. Flask 启动日志出现：
   [WipePoller] started, interval=600s, target=.../logs/<current_month>/

2. 临时修改 poll_interval=60 快速测试：
   手动复制一个 .log 到当月挂载目录
   60秒内 GET /wipe/api/scan/status 的 last_scan_at 更新
   GET /wipe/api/today 出现新记录

3. Dashboard 右上角显示：
   Last scan: 2026-05-05T10:42:18 | Next in: 8 min

4. 模拟挂载异常（临时 umount）：
   轮询线程不崩溃
   日志出现 [WipePoller] poll error: ...
   重新挂载后自动恢复正常

5. 全量扫描与轮询不冲突：
   POST /wipe/api/scan 触发全量时
   日志出现 [WipePoller] skipped: full scan in progress

改动文件汇总
新建：modules/wipe/scheduler.py        ← 全新文件
修改：modules/wipe/integration.py      ← 末尾追加 2 行
修改：modules/wipe/routes.py           ← scan/status 端点合并新字段
修改：modules/wipe/scanner.py          ← 仅在缺少时补充 run_poll()
修改：templates/wipe/dashboard.html    ← Header 追加状态栏
修改：config/wipe_paths.json           ← 确认 poll_interval 字段Sonnet 4.6