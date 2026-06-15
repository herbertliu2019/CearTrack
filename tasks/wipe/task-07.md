文件：/opt/monitorcenter/templates/wipe/dashboard.html

先读取现有文件内容，在已有功能基础上追加：

1. Header 区域追加状态栏：
   Last scan: {last_scan_at}  |  Next in: {X} min
   [⟳ Scan Now]  [↺ Full Rebuild]

2. 全量扫描进度 Banner（顶部固定）：
   x-show="scanState.running === 1"
   显示：INDEXING: {done} / {total} files...

3. Alpine.js app() 追加：

   scanState: {
     running:0, total:0, done:0,
     poller_running:false,
     last_scan_at:null, next_scan_at:null, interval:600
   },
   prevRunning: 0,

   async loadScanStatus()
     fetch /wipe/api/scan/status
     更新 scanState
     running 从 1→0 时自动刷新 loadToday()
     每 30 秒自动轮询

   async scanNow()
     POST /wipe/api/scan/poll
     3秒后 loadScanStatus()

   nextScanIn()
     计算 next_scan_at 距现在的分钟数
     <= 0 → "< 1 min"

   init() 末尾追加：
     await this.loadScanStatus()
     setInterval(() => this.loadScanStatus(), 30000)

4. Search 结果展示多条记录：
   第一条（is_latest=true）标注 "LATEST" badge
   其余标注 "HISTORY" badge（灰色）
   全部显示 win_path + COPY 按钮