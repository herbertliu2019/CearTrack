# Laptop 模块 — AI 接管总结 (Handoff)

> 最后更新: 2026-06-10 · 适用于 CearTrack monitorcenter 平台的 `laptop` 模块
> 目的: 让接手的 AI 无需通读全部代码即可安全地修改本模块。

---

## 1. 模块职责

接收 `laptop_test.sh`（Live USB 客户端）上传的笔记本硬件检测 JSON，存盘、建索引、
并提供仪表盘展示 Today / This Week / This Month / Custom Range 的统计与记录。

**关键约束（来自 CLAUDE.md，必须遵守）**
- ❌ 不要修改 `laptop_test.sh` 客户端 —— 服务端只负责包装/展示。
- ❌ 不要在 `core/` 里写模块特定逻辑（只能写在 `modules/laptop/`）。
- ❌ 不引入构建工具（webpack/npm）。前端是 Alpine.js + HTMX，无构建步骤。
- 存储是**本地文件系统 JSON**，无数据库（SN 索引除外，见下）。
- 改完 Python 跑 `python -m py_compile <file>` 验证。
- 不重写未改动的函数。

---

## 2. 文件清单

| 文件 | 作用 |
|------|------|
| `modules/laptop/module.py` | 后端：Blueprint 路由 + `LaptopModule` 类（envelope/verdict/schema/validate/SN提取） |
| `modules/laptop/schema.json` | 展开详情的字段渲染配置（声明式，前端 renderer.js 消费） |
| `modules/laptop/templates/module.html` | 仪表盘页面（Alpine 模板，内含 4 个 tab） |
| `static/js/app.js` | **共享**前端逻辑 `laptopApp()`（平台共享文件，wipe/cpu 可能也引用其模式，改时小心） |
| `static/js/renderer.js` | **共享**的 schema → HTML 渲染器（`renderPayload`/`renderField`/`statusClass` 等） |
| `core/envelope.py` | `build_envelope()` 标准信封构造（共享，勿写模块逻辑） |
| `core/storage.py` | `write_envelope` / `read_latest` / `search_sn` / `purge_stale_latest`（共享） |
| `core/index_db.py` | SN 全局索引 SQLite（共享，跨模块搜索用） |

`*.py_bk*` / `app.js_bk` 是历史备份，忽略。

---

## 3. 数据流

```
laptop_test.sh ──POST /laptop/api/upload──> api_upload()
   raw JSON          │
                     ├─ validate(raw)              # 基本校验
                     ├─ extract_envelope(raw)      # 包成标准信封 + 算 verdict
                     ├─ storage.write_envelope()   # 写 latest/ 和 history/
                     └─ index_db.upsert()          # 写 SN 索引（跨模块搜索）
```

### 标准信封 (envelope) 结构
所有模块统一字段（`core/envelope.py`）：
```json
{
  "module": "laptop", "sn": "...", "timestamp": "ISO8601",
  "overall_result": "PASS|WARN|FAIL", "summary": "...",
  "hostname": "...", "payload": { ...原始客户端 JSON... },
  "warnings": [...]
}
```
- **`payload` 就是客户端原始 JSON 原封不动**。所有笔记本细节都在 `payload.*`。
- SN 来源: `payload.system.serial_number`。
- 时间戳来源: `payload.test_info.test_time`（无则用服务端 UTC now）。

### payload 关键路径（前端/schema 引用）
```
payload.test_info.{test_time, hostname, operator_id, script_version}
payload.system.{vendor, model, serial_number, bios_version}
payload.cpu.{model, cores}
payload.memory.{total_gb, type}
payload.storage[] (list: model,size,type,serial,smart,...)
payload.battery.{health_percent, cycle_count, battery_condition, status, ...}
payload.screen/camera/audio/keyboard/network/ports/appearance/kernel_health.*
```
> ⚠️ `operator_id` 在 `payload.test_info.operator_id`，**不是** `payload.operator_id`。
> 这是接手最易踩的坑（客户端 2.0.0 起加入；旧记录没有此字段，需做空值兼容）。

---

## 4. 存储布局

```
monitorcenter/data/laptop/
  latest/          # 仅当天记录（午夜后台 sweeper 清理非今日的）
  history/<YYYY>/<MM-DD>/<sn>_<timestamp>.json
```
- Today 数据 = `read_latest("laptop")`（读 latest/）。
- Week/Month/Custom = 扫描 `history/` 对应日期目录下的 `*.json`。
- 全部历史计数 = `history/**/*.json` 文件数。

---

## 5. 后端路由 (module.py)

| 路由 | 说明 |
|------|------|
| `GET /laptop/` | 渲染 module.html |
| `POST /laptop/api/upload` | 客户端上传入口 |
| `GET /laptop/api/latest` | 今日记录列表 |
| `GET /laptop/api/search?sn=` | 模块内 SN 搜索 |
| `GET /laptop/api/schema` | 返回 schema.json（前端懒加载） |
| `GET /laptop/api/stats` | 今日汇总计数 |
| `GET /laptop/api/stats/total` | 全部历史记录总数 |
| `GET /laptop/api/stats/range?range=week\|month` 或 `?from=&to=` | 区间聚合：total/passed/warned/failed/pass_rate/brands/fail_reasons/daily/records |

`/api/stats/range` 返回的 `records[]` **已包含完整 `payload`**，
所以前端按 operator 等任意维度分组都无需改后端。

### 周计算约定
一周从**周日**到周六：`days_since_sunday = (today.weekday()+1) % 7`。

### compute_verdict 规则（verdict = result/summary/warnings）
- `overall_result` 由客户端给定，服务端**不改**。
- WARNING 类问题进 `warnings[]`，不影响 overall：
  - `camera.device_status == "HARDWARE_DETECTED"`
  - `battery.battery_condition == "DATA_UNAVAILABLE"`
  - `battery.status == "WARNING"` → "Battery low (xx%) — mark note in Cyclelution"
- summary: FAIL→列失败项；WARN→列警告项；PASS 有 warnings→`PASS — N warning(s): ...`；否则 "All tests passed"。
- **fail_reasons 统计只看 `overall_result == "FAIL"` 的记录**，所以 battery WARNING 不会进 fail_reasons。

---

## 6. 前端 (module.html + app.js)

Alpine 组件 `laptopApp(moduleName)`（app.js）。4 个 tab：`today / week / month / custom`。
每个 tab 数据对象：`{ stats, by_brand, fail_reasons, daily, records, start, end }`。

### 关键状态
```js
activeTab:    'today'        // 当前 tab
groupBy:      'date'         // week/month/custom 的 Daily Breakdown 分组: 'date'|'operator'
todayGroupBy: 'all'          // today 的分组: 'all'|'operator'
detailOpen:   null           // 单条记录展开 key
openSections: {}             // 折叠区 key→bool
```

### 关键方法
| 方法 | 作用 |
|------|------|
| `loadToday/loadWeek/loadMonth/loadCustom` | 拉数据填 tab 对象 |
| `recordsForDay(tab,date)` | 某 tab 某天的记录 |
| `groupByOperator(tab)` | week/month/custom：先按 operator 再按日期分组 |
| `todayByOperator()` | today：仅按 operator 分组（单日无日期子层） |
| `toggleSection/isOpen` | 折叠区，**默认关闭** |
| `toggleOp/isOpOpen` | 折叠区，**默认打开**（用于 By Operator 分组，点开即见层级） |
| `toggleDetail(key)` | 展开单条记录详情（调用 renderDetails→renderPayload） |
| `resultClass(r)` | PASS→pass / FAIL→fail / 其它→warn 的 CSS class |

### By Date / By Operator 切换
- week/month/custom 三个 tab 的 Daily Breakdown 各有一份（代码重复，改时三处都要改）。
- today tab 是卡片视图的 All / By Operator 切换。
- 折叠 key 前缀：`wop_`(week) / `mop_`(month) / `cop_`(custom) / `top_`(today)。
- By Operator 用 `toggleOp/isOpOpen`（默认展开）；By Date 用 `toggleSection/isOpen`（默认折叠）。

---

## 7. schema.json（展开详情渲染）

声明式配置，被 `renderer.js` 的 `renderPayload(schema, data)` 消费。每个 section 必须有 `type`：
- `key_value` — 字段表，`fields:[{path,label,suffix?}]`
- `status_grid` — PASS/FAIL 彩色格子，`items:[{path,label}]`
- `list` — 数组渲染，`path` + `item_template`（`{key}` 占位）
- `camera_image` — 含图片，`image_path`

> ⚠️ 字段用 **`path`** 不是 `key`（GPU 模块曾因用 `key` + 缺 `type` 导致 "Unknown section type"）。
> `path` 是点号路径，由 `getByPath()` 从 `data` 根（即 envelope）解析，故都以 `payload.` 开头。
> `statusClass()`：PASS→pass，FAIL→fail，WARNING/HARDWARE_DETECTED/DATA_UNAVAILABLE→warn（黄色）。

---

## 8. 部署 & 缓存（重要运维提醒）

部署路径 `/opt/monitorcenter/`。改动生效需要：
1. **模板 (module.html)** → 重启 Flask（或 debug 自动重载）。
2. **静态文件 (app.js / renderer.js / dashboard.css)** → 浏览器会缓存！必须 `Ctrl+Shift+R` 硬刷新。
   - 症状：按钮在但点了没反应 = 浏览器用了旧 app.js。Network 里看到 app.js 返回 `304` 即缓存命中。
   - 排查：DevTools 勾 "Disable cache" 再刷；或 `grep -c <新函数名> /opt/monitorcenter/static/js/app.js` 确认服务器文件已更新。

---

## 9. 近期已完成的改动（上下文）

- Today/Week/Month/Custom KPI strip：ALL TIME 卡片移到**最右**（`repeat(N,1fr) 1px 1.1fr`）。
- WARN 计数修复（后端 daily_map 单列 `warned`；前端各 load* 加 `warned`）。
- 日期范围显示、周从周日起算、跨年显示年份（`fmtRange`）。
- `operator_id`：卡片 footer `👤 name`、schema System section、Daily Breakdown 子行均显示。
- **By Operator 分组**：week/month/custom 的 Daily Breakdown + today 的卡片视图，默认展开。
- battery：卡片 spec 行加 `Cond:` + `Batt:` badge；schema 加 condition/status + Test Results 加 Battery 项。
- battery **WARNING** 视为警告而非失败：进 warnings、不影响 overall、卡片显示 "⚠ Battery warning — mark note in Cyclelution"、不计入 fail_reasons。

---

## 10. 接手注意事项 (踩坑清单)

1. `operator_id` 路径是 `payload.test_info.operator_id`，旧记录无此字段 → 永远做 `?.` 空值兼容。
2. `app.js` / `renderer.js` 是**跨模块共享**文件，改之前确认不影响 wipe/cpu。
3. Daily Breakdown 的 By Date/By Operator 代码在 week/month/custom **重复三份** + today 卡片一份，改一处要同步其余。
4. 静态文件改完务必提醒用户硬刷新，否则"看起来没生效"。
5. schema 字段必须用 `path` 且 section 必须有 `type`。
6. 多个 AI agent / git worktree 并行：编辑的是**主目录**文件（非 worktree 副本），改完尽快 commit，避免被并行进程静默覆盖。
7. 不要改 `overall_result` 逻辑；battery WARNING 不能进 fail_reasons；历史数据迁移已被否决，旧记录保持原样。
8. 远端仓库: `https://github.com/herbertliu2019/CearTrack.git`。
