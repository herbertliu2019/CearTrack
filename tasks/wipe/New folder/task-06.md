
TASK-06｜dashboard.html
文件：/opt/monitorcenter/templates/wipe/dashboard.html

基于已有前端框架，完成数据绑定与扫描进度 UI。

数据绑定检查清单：

Today Tab：
  ✓ /wipe/api/today → stats + records
  ✓ 顶部卡片：total / passed / warning / failed / pass_rate
  ✓ 记录卡片：drive_sn / sys_manufacturer / sys_model
              result / grade / health_score / duration_min
  ✓ 点击卡片 → 右侧详情面板
  ✓ 详情面板显示 win_path
  ✓ COPY WINDOWS PATH 按钮：navigator.clipboard.writeText(win_path)

Stats Tab：
  ✓ /wipe/api/stats?period=week|month|custom
  ✓ This Week 旁显示日期范围（MM.DD - MM.DD）
  ✓ Custom Range 显示两个 date input
  ✓ 二级统计卡片：total / passed / warning / failed / pass_rate
  ✓ By Manufacturer 面板：by_manufacturer 数组
  ✓ Common Fail Reasons 面板：fail_reasons 数组

Search Tab：
  ✓ /wipe/api/search?q=输入值
  ✓ 支持 drive_sn 和 system_sn（service tag）搜索
  ✓ 结果卡片完整字段 + win_path
  ✓ COPY WINDOWS PATH 按钮

扫描进度 Banner（全量扫描专用）：
  - 页面顶部固定 banner，默认隐藏
  - POST /wipe/api/scan 后显示
  - 每 2 秒轮询 /wipe/api/scan/status
  - 显示：INDEXING: {done} / {total} files...
  - running=0 时隐藏 banner，自动刷新 Today 数据

样式规范（不变）：
  cyan=#00bcd4  green=#4caf50
  yellow=#ff9800  red=#f44336
  Tab active = border-box
  背景 #0d1520 / #141f2e / #1a2840