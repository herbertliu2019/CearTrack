# Task 09 — MonitorCenter GPU 模块
**依赖 skill:** `gpu_module_server_skill.md`  
**依赖接口文档:** `gpu_module_interface.md`  
**部署路径:** `/opt/monitorcenter/`  
**执行方式:** 交给 Claude Code 逐 Phase 完成，每 Phase 可独立验证

> **优先级说明：** 字段定义、SN逻辑、测试工具名称以 `gpu_module_interface.md` 为准；
> 目录结构、存储逻辑、PDF/Dashboard 实现细节以 `gpu_module_server_skill.md` 为准。

---

## 准备工作（Claude Code 开始前在服务器执行）

```bash
pip install weasyprint
apt install -y libpango-1.0-0 libpangoft2-1.0-0 libpangocairo-1.0-0
echo "weasyprint>=60.0" >> /opt/monitorcenter/requirements.txt
```

---

## Phase 0 — 目录脚手架

- [ ] **T01** 创建目录结构：
  ```
  /opt/monitorcenter/modules/gpu/
  /opt/monitorcenter/modules/gpu/templates/gpu/
  /opt/monitorcenter/data/gpu/latest/
  /opt/monitorcenter/data/gpu/history/
  /opt/monitorcenter/data/gpu/pdf/
  /opt/monitorcenter/templates/gpu/
  ```
- [ ] **T02** 创建 `modules/gpu/__init__.py`（空文件）
- [ ] **T03** 验证：`ls -la /opt/monitorcenter/modules/gpu/`

---

## Phase 1 — Upload Endpoint

**文件：** `modules/gpu/module.py`

- [ ] **T04** 创建 `module.py`，定义 blueprint：
  ```python
  blueprint = Blueprint('gpu', __name__,
                         url_prefix='/gpu',
                         template_folder='templates',
                         static_url_path='/gpu/static')
  ```

- [ ] **T05** 实现 `POST /gpu/api/upload`：
  - 验证必填字段：`module / sn / timestamp / overall_result / summary / hostname / payload`
  - **SN 提取逻辑（按优先级）：**
    1. `payload.gpu.gpu_sn` 非空字符串 → 直接使用
    2. 否则：使用顶层 `sn`（系统 SN）
    3. 两者均无效 → fallback：`hostname` + timestamp hash
  - 调用 `build_envelope(module='gpu', sn=sn, data=payload)`
  - 调用 `write_envelope(envelope, module='gpu', sn=sn)`
  - try/except 调用 `generate_pdf(sn, envelope)`，失败只 log，不影响响应
  - 返回 `jsonify({'status': 'ok', 'sn': sn})` HTTP 200

- [ ] **T06** `python -m py_compile modules/gpu/module.py`

- [ ] **T07** 重启服务，curl 测试：
  ```bash
  curl -X POST http://192.168.30.18/gpu/api/upload \
    -H "Content-Type: application/json" \
    -H "X-API-Key: ceartrack-upload-2026" \
    -d @/tmp/test_gpu_payload.json
  ```
  确认：返回 200，`data/gpu/latest/<SN>.json` 和 `data/gpu/history/...` 存在

---

## Phase 2 — PDF Generator

**文件：** `modules/gpu/pdf_generator.py`  
**文件：** `modules/gpu/templates/gpu/gpu_report.html`

- [ ] **T08** 创建 `pdf_generator.py`，实现 `generate_pdf(sn, envelope) -> str`：
  - 用 `render_template_string` 渲染 `gpu_report.html`
  - `HTML(string=html_str).write_pdf(pdf_path)`
  - 返回 pdf_path；所有异常向上抛出（由 module.py 捕获）

- [ ] **T09** 创建 `gpu_report.html`（Jinja2 + WeasyPrint CSS），布局：
  ```
  ┌─────────────────────────────────────────────┐
  │  CEAR REFURBISHED  GPU TEST REPORT          │
  │  SN: XXXX  |  Date: 2026-05-08             │
  ├──────────────────────┬──────────────────────┤
  │  GRAPHICS CARD       │  MEMORY              │
  │  Name / Chip /       │  Size / Type /       │
  │  Subvendor / Driver  │  Bus Width / BW      │
  ├──────────────────────┴──────────────────────┤
  │  INTERFACE                                  │
  │  PCIe Gen / Width（degraded时橙色警告行）    │
  ├─────────────────────────────────────────────┤
  │  TEST RESULTS                               │
  │  ✅ VRAM Test  PASS (0 errors, 300s)        │
  │  ✅ glmark2    PASS (1840 pts)              │
  │  🌡 Temp Max   72°C  (Avg: 65°C)           │
  │  ⚡ Power Max  170.5W                       │
  ├─────────────────────────────────────────────┤
  │           ✅  OVERALL: PASS                 │
  │    Tested by Cear Refurbished • 2026-05-08  │
  └─────────────────────────────────────────────┘
  ```
  CSS 要求：
  - `@page { size: A4; margin: 20mm; }`
  - 字体：`font-family: 'DejaVu Sans', sans-serif`
  - 颜色：PASS=`#16a34a`，FAIL=`#dc2626`，WARN=`#d97706`
  - 无 `position:fixed`（WeasyPrint 不支持）
  - `vram_bandwidth_gbps == 0` 时显示 "N/A"

- [ ] **T10** `python -m py_compile modules/gpu/pdf_generator.py`

- [ ] **T11** Python shell 手动验证 PDF 生成，`ls /opt/monitorcenter/data/gpu/pdf/` 确认有文件

- [ ] **T12** 用 PDF viewer 目视检查布局

---

## Phase 3 — PDF 下载路由

**文件：** `modules/gpu/module.py`（追加）

- [ ] **T13** 追加 `GET /gpu/report/<sn>.pdf`：
  ```python
  @blueprint.route('/report/<sn>.pdf')
  @login_required
  def download_pdf(sn):
      pdf_path = f"/opt/monitorcenter/data/gpu/pdf/{sn}.pdf"
      if not os.path.exists(pdf_path):
          abort(404)
      return send_file(pdf_path, mimetype='application/pdf',
                       download_name=f"gpu_report_{sn}.pdf")
  ```

- [ ] **T14** 浏览器访问 `/gpu/report/<test_sn>.pdf` 能下载

---

## Phase 4 — Dashboard API Endpoints

**文件：** `modules/gpu/module.py`（追加）

- [ ] **T15** 实现 `GET /gpu/`（`@login_required @module_required('gpu')`）

- [ ] **T16** 实现 `GET /gpu/api/today`：
  - 读取 `data/gpu/latest/` 所有 JSON，过滤今日 timestamp
  - 返回：
    ```json
    {
      "stats": { "total": 0, "passed": 0, "failed": 0, "pass_rate": 0.0 },
      "records": [
        {
          "sn": "", "gpu_name": "", "vendor": "", "vram_mb": 0,
          "overall_result": "", "timestamp": "",
          "glmark2_score": 0, "temp_max_c": 0,
          "pcie_degraded": false
        }
      ]
    }
    ```

- [ ] **T17** 实现 `GET /gpu/api/stats?period=week|month|custom&start=YYYY-MM-DD&end=YYYY-MM-DD`：
  - 读取 `data/gpu/history/` 对应日期范围
  - 返回：`{ stats, by_vendor, fail_reasons, daily, start, end }`
  - `by_vendor`：NVIDIA / AMD 各计数
  - `fail_reasons`：VRAM_ERROR / OVERHEAT / PCIE_DEGRADED 计数

- [ ] **T18** 实现 `GET /gpu/api/search?q=<str>`：
  - 搜索 latest/ + history/ 中 SN 或 `gpu.name` 包含 q 的记录
  - 返回：`{ "results": [...] }`，结构同 today records

- [ ] **T19** `python -m py_compile modules/gpu/module.py`

- [ ] **T20** curl 测试三个 API，确认返回正确 JSON 结构

---

## Phase 5 — schema.json

**文件：** `modules/gpu/schema.json`

- [ ] **T21** 按 `gpu_module_server_skill.md §6` 创建 `schema.json`
  - 注意：benchmark 工具名用 `glmark2`（非 vkmark）
  - `vram_bandwidth_gbps` 加 `"zero_as_na": true` 标记，渲染时显示 "N/A"

- [ ] **T22** `python -c "import json; json.load(open('modules/gpu/schema.json'))"`

---

## Phase 6 — Dashboard HTML

**文件：** `templates/gpu/dashboard.html`

- [ ] **T23** 创建 `dashboard.html`，`{% extends "base.html" %}`，沿用 wipe 模块深色主题 + Alpine.js 模式

- [ ] **T24** 顶部搜索栏（复用 wipe 模块模式）

- [ ] **T25** Tabs：Today / This Week / This Month / Custom Range

- [ ] **T26** KPI strip：Total / Passed / Failed / Pass Rate（4格）

- [ ] **T27** Today tab 记录列表：
  - result-card，点击展开 detail-panel
  - 卡片摘要：GPU name / vendor / VRAM / overall badge
  - `pcie_degraded: true` 时显示橙色 `⚠ PCIe x{current}` 角标

- [ ] **T28** detail-panel 展开内容：
  - **规格区（双列 kv-grid，仿 GPU-Z 分组）：**
    - Graphics Card：name / chip / vendor / subvendor / device_id / bios_version / driver_version
    - Memory：vram_mb / vram_type / vram_bus_width / vram_bandwidth_gbps（0→N/A）
    - Interface：pcie_gen / pcie_width_current / pcie_width_max
    - Clocks：clock_gpu_mhz / clock_mem_mhz
    - SN 区：System SN（顶层 `sn`）/ GPU SN（`payload.gpu.gpu_sn`，空→N/A）
  - **特殊提示：**
    - `pcie_degraded: true` → 橙色提示框："PCIe 运行在 x{current}，设计最大 x{max}，请检查金手指"
    - `dmesg_gpu_errors` 非空 → 展开显示错误行列表（红色）
  - **测试结果区：**
    - VRAM Test：tool / duration / errors / status badge
    - glmark2：score（大字体突出）/ status badge
    - Thermal：temp_max / temp_avg / util_avg / power_max
    - 温度颜色：>85°C → `#d97706`，>95°C → `#dc2626`
  - **"⬇ Download PDF" 按钮**，链接 `/gpu/report/<sn>.pdf`，`target="_blank"`

- [ ] **T29** Week/Month tab：by_vendor 统计（NVIDIA/AMD），fail_reasons 统计

- [ ] **T30** Alpine.js `gpuApp()` 函数，实现：
  - `init()`：并发加载 today + week + month
  - `loadToday()` `loadWeek()` `loadMonth()` `loadCustom()`
  - `runSearch()` `clearSearch()`
  - `toggleDetail(key)`
  - `resultClass(result)` → `'pass'`/`'fail'`/`'warn'`

- [ ] **T31** 浏览器打开 `/gpu/`，目视验证：页面无 JS 报错 / Today 显示记录 / 卡片展开 / PDF 可下载

---

## Phase 7 — 集成测试

- [ ] **T32** 端到端：上传完整 GPU JSON → 确认：
  1. `data/gpu/latest/<SN>.json` 内容正确
  2. `data/gpu/history/...` 有归档文件
  3. `data/gpu/pdf/<SN>.pdf` 已生成
  4. `/gpu/` dashboard 显示这条记录
  5. PDF 下载内容正确

- [ ] **T33** 重传同一 SN → 确认：
  1. latest/ 被覆盖
  2. history/ 旧文件删除，新文件写入
  3. pdf/ 被新 PDF 覆盖

- [ ] **T34** 测试 FAIL / WARN 场景（构造含 VRAM 错误或高温 JSON）：
  - dashboard 卡片显示红/橙 badge
  - PDF 判定区显示对应颜色

- [ ] **T35** `curl http://192.168.30.18/gpu/api/today` 经 Nginx 能通

---

## 验证命令速查

```bash
# 语法检查
python -m py_compile modules/gpu/module.py
python -m py_compile modules/gpu/pdf_generator.py

# 测试上传
curl -X POST http://192.168.30.18/gpu/api/upload \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ceartrack-upload-2026" \
  -d @/tmp/test_gpu_payload.json

# 检查文件
ls -la /opt/monitorcenter/data/gpu/latest/
ls -la /opt/monitorcenter/data/gpu/pdf/

# 重启服务
systemctl restart monitorcenter
```

---

## 约束清单（Claude Code 必须遵守）

- ❌ 不修改 `core/` 下任何文件（storage.py / envelope.py / module_registry.py）
- ❌ 不修改 `modules/laptop/` 任何文件
- ❌ 不引入 npm / webpack / 任何前端构建工具
- ❌ 不引入数据库（SQLite / PostgreSQL / Redis 等）
- ❌ PDF 生成失败不能让上传 API 返回错误码
- ✅ 修改任何 Python 文件后运行 `python -m py_compile <file>`
- ✅ Blueprint：`url_prefix='/gpu'`，`static_url_path='/gpu/static'`
- ✅ 模板放在 `modules/gpu/templates/gpu/`（Flask 模板命名空间隔离）
