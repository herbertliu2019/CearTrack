# GPU Module — Comprehensive Build Summary

> Status: Production. Commit `80762a7` (2026-06-03).
> Repo: `herbertliu2019/CearTrack` · Branch `main`

---

## 🎯 整体目标
为 MonitorCenter 构建完整的 GPU 模块（仪表盘 + PDF 报告 + 统计分析），并迭代优化 UX。

---

## 📦 核心交付物

### 后端 (`modules/gpu/`)
| 端点 | 功能 |
|------|------|
| `POST /gpu/api/upload` | 接收测试数据，触发 PDF 生成 |
| `GET /gpu/api/today` | 今日记录 + KPI + by_station / by_vendor / by_subvendor |
| `GET /gpu/api/stats?period=week\|month\|custom` | 时间范围统计 + `by_station_daily` (per-station per-day) |
| `GET /gpu/api/records?date=` | 按日期查询记录（SQLite 索引加速） |
| `GET /gpu/api/filter?period=...&vendor=&subvendor=&station=&fail_reason=` | 下钻筛选 |
| `GET /gpu/api/stats/total` | All-Time GPU 总数 |
| `GET /gpu/report/<sn>.pdf` | WeasyPrint 生成的 PDF 报告下载 |

### 前端 (`templates/gpu/dashboard.html`)
- **4 个 Tab**：Today / This Week / This Month / Custom
- **KPI Strip**：Total / Passed / Failed (+ INFO_ONLY 副标签) / All Time
- **下钻图表**：By Vendor / By Station（横条 + 点击筛选 + CSS Grid 自适应标签列）
- **Subvendor Performance**：表格 + 点击下钻
- **Daily Volume**：立柱图（点击列出当天记录）
- **Daily Breakdown**：**3 级 station-grouped accordion**（station → date → records）
- **Today 记录区**：也按 station 分组
- **侧边详情 Drawer**：Graphics Card / Memory / Interface & Clocks 三段式
- **搜索 + Custom 日期范围筛选**

### PDF 报告 (`gpu_report.html`)
- WeasyPrint 渲染，A4
- NVIDIA / AMD 内嵌 SVG logo
- 三段式硬件信息（Graphics Card / Memory / Interface & Clocks）
- TEST RESULTS：VRAM Test + glmark2（含大字分数）
- 性能数据：Total Duration / Temp / Util / Power
- OVERALL 印章（绿 / 黄 / 红 / 灰蓝四色）
- **INFO_ONLY 专用版本**：跳过测试结果，显示蓝色 INFO banner

---

## 🛠 工具脚本 (`scripts/`)
- `backfill_gpu_pdfs.py` — 为已有 history JSON 补全 PDF
- `purge_gpu_by_station.py` — 按 station 名清理记录（含 dry-run + 同步清 SQLite + latest + pdf）

---

## 🎨 关键设计决策

1. **方案 C 之争**：先尝试动态字段渲染，确认客户端字段稳定后**回退三段式**
2. **INFO_ONLY 视觉**：完全不展示"全 0"的假数据，改用灰蓝 banner
3. **Station 分组**：用 CSS Grid `display:contents` 让所有行共享列宽，柱子完美对齐
4. **Custom Tab 切换**：切到 Custom 时清空 stats 避免数据错觉
5. **下钻交互**：By Vendor / Station / Subvendor / Fail Reason 全部可点击 → 切到 searched 视图
6. **Daily Volume 立柱**：点击列出当天扁平记录（不分 station）
7. **Logo SVG 内嵌**：不依赖外部 PNG / 网络
8. **字体补偿**：SN 列 monospace 1.35em 视觉对齐 station 文本

---

## 🐛 排查过的关键问题

| 问题 | 根因 | 解决 |
|------|------|------|
| `No module named 'weasyprint'` | 系统 Python 无包，需用 venv | `/opt/monitorcenter/venv/bin/pip install weasyprint` |
| PDF 404 | 服务运行用户无写权限 | chown / chmod 修复 |
| Daily Breakdown 不显示 | module.py 未部署 / 服务未重启 | 部署 + restart |
| Emoji 显示为方框 | DejaVu 字体不支持 emoji | 改用 Unicode 文字符号，后干脆去掉图标 |
| Custom Tab 显示旧数据错觉 | stats 没在切换时清空 | setTab 中显式清空 |
| Util Avg 字段假阳性 | 错误假设字段不存在 | 用户提供 JSON 确认真实存在 |

---

## 📝 完成的任务文档
- `tasks/monitorcenter/09_gpu_module_task.md` — 基础 GPU 模块
- `tasks/monitorcenter/0520_gpu_server_info_only_task.md` — INFO_ONLY tier
- `tasks/monitorcenter/10_gpu_module_option_c.md` — 方案 C 混合显示

---

## 🚀 Git
**Commit `80762a7`** → pushed to `origin/main`
- 15 files changed, 4223 insertions
- Branch: `main`
- Repo: `herbertliu2019/CearTrack`

---

## 🔄 未完成 / 后续可选
- `modules/cpu/*` 的改动还在 working tree（未提交）
- `tasks/wipe/*` 的改动未提交
- 多个 untracked 目录（`gpu_client/` / `laptop_client/` / `deployment/` 等）
- CPU dashboard 用同样的 CSS Grid 横条样式（已实现但 git 未捕获到，建议重新检查路径）

---

## 📁 文件清单

```
monitorcenter/
├── app.py                                          (+22 lines, GPU summary endpoint)
├── modules/gpu/
│   ├── __init__.py
│   ├── module.py                                   (main GPU module + Flask blueprint)
│   ├── pdf_generator.py                            (WeasyPrint wrapper)
│   ├── schema.json                                 (display field schema)
│   └── templates/gpu/
│       └── gpu_report.html                         (PDF Jinja template)
├── templates/gpu/
│   └── dashboard.html                              (full Alpine.js dashboard)
├── scripts/
│   ├── backfill_gpu_pdfs.py
│   └── purge_gpu_by_station.py
├── static/img/
│   ├── logo_nvidia.png
│   ├── logo_amd.png
│   └── readme.txt
└── docs/
    └── GPU_server_summary.md                       (this file)
```
