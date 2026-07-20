# Session Log — 2026-04-27

CearTrack (formerly Monitorcenter) + laptop_test.sh 的批量改动记录。

---

## 概览

本次会话按顺序完成 5 个任务：

1. **Task 05** — Rename Monitorcenter → CearTrack + Statistics tab
2. **Task 06** — One-SN-one-record（重传同一 SN 时清掉旧 history）
3. **Task 07** — Statistics tab UI 重设计 + Storage 详情字段扩展
4. **fix_ssd_health_grade** — laptop_test.sh 增加 SATA SSD 健康度
5. **Task 08** — Tab 重命名 + By Brand / Fail Reasons 并排
6. **追加修复** — Stats 两张卡片被 `x-show` 弄成垂直堆叠

---

## Task 05 — CearTrack rename + Statistics tab

### Part 1: 改名

**`templates/base.html`**
- `<title>` block: `Monitorcenter` → `CearTrack`
- `<h1>`: `Monitor Center` → `CearTrack`

**`templates/index.html`**
- title block、hero `<h1>`、tagline 改为 `Cear Hardware Test & Traceability Platform`

**`modules/laptop/templates/module.html`**
- title block 末尾的 `Monitorcenter` → `CearTrack`

### Part 2: Statistics 后端

**`modules/laptop/module.py`**
- 顶部 `import config`
- 新增 `GET /api/stats/range` endpoint
  - `range=week|month` 或 `from=YYYY-MM-DD&to=YYYY-MM-DD`
  - 直接遍历 `BASE_DIR/laptop/history/YYYY/MM-DD/*.json`
  - 返回 `total / passed / failed / pass_rate / brands[] / fail_reasons[] / records[]`（records 含完整 payload，前端用于展开）
  - 品牌归一化：Dell / HP / Lenovo / Microsoft / Apple / Unknown
  - Fail 项扫描 10 个 check（screen/camera/audio×2/keyboard×2/battery/network/ports/appearance）

### Part 3: Statistics 前端

**`static/css/dashboard.css`** — 新增条形图样式  
（Task 07 后已被 `.stats-row` + 行内样式取代，仅保留 `.stats-record-row` / `.stats-record-expand`）

**`modules/laptop/templates/module.html`** — Statistics tab 面板
- Tab 按钮（Today / Stats / Search 顺序在 Task 08 调整）
- 范围选择器：This Week / This Month / Custom Range（带日期选择）
- 4 个 summary stat cards：Total / Passed / Failed / Pass Rate
- By Brand + Common Fail Reasons 两栏条形图
- All Records 表格，行可点击展开（复用 `renderDetails(r)`）

**`static/js/app.js`** — 新增状态与方法
```js
statsRange: 'week', statsFrom: '', statsTo: '',
statsData: null,
statsExpandedKeys: new Set(),

async loadStatsRange() { ... }
toggleStatsExpand(key) { ... }
isStatsExpanded(key) { ... }
```

---

## Task 06 — One-SN-one-record

**业务规则**：一台笔记本 = 一个 SN = 一份最终测试记录。重传时所有旧 history 文件全部删除。

### `core/index_db.py`

新增清理钩子：
```python
def delete_by_history_path(history_path: str) -> None:
    conn = _open()
    try:
        with conn:
            conn.execute("DELETE FROM envelopes WHERE history_path = ?", (history_path,))
    finally:
        conn.close()
```
（`envelope_sns` 行通过 ON DELETE CASCADE 自动清掉）

### `core/storage.py`

新增 helper：
```python
def get_base_history_dir(module_name: str) -> Path:
    return config.BASE_DIR / module_name / "history"
```

重写 `write_envelope()`：
1. 写 `latest/<sn>.json`（覆盖）
2. 在 `history/` 全树 `rglob("<sn>_*.json")` 删旧文件，同时 `index_db.delete_by_history_path()` 删索引行
3. 尝试删空的 `MM-DD/`、`YYYY/` 目录
4. 写新的 `history/YYYY/MM-DD/<sn>_<ts>.json`

避免 storage ↔ index_db 顶层循环依赖：在函数内部 `from core import index_db`。

---

## Task 07 — Statistics UI 重设计

### Part 1: 日历周/月

**`modules/laptop/module.py`** — `/api/stats/range`
```python
import calendar

if range_param == "week":
    weekday = today.weekday()        # Mon=0, Sun=6
    date_from = today - timedelta(days=weekday)
    date_to   = date_from + timedelta(days=6)
elif range_param == "month":
    date_from = today.replace(day=1)
    last_day  = calendar.monthrange(today.year, today.month)[1]
    date_to   = today.replace(day=last_day)
```

### Part 2: 按钮上显示日期范围

**`modules/laptop/templates/module.html`**
```html
<button ...>
  This Week
  <span x-show="statsData && statsRange==='week'"
        x-text="formatDateRange(statsData?.date_from, statsData?.date_to)"
        style="font-size:0.75em; opacity:0.5; margin-left:6px;"></span>
</button>
```

**`static/js/app.js`**
```js
formatDateRange(from, to) {
  if (!from || !to) return '';
  const fmt = (d) => { const p = d.split('-'); return `${p[1]}.${p[2]}`; };
  return `(${fmt(from)} - ${fmt(to)})`;
},
```

### Part 3: By Brand / Fail Reasons 重设计

- 抛弃 `1fr 1fr` grid，改 `flex; align-items:flex-start`（Task 08 后改 stretch）
- 每行：名称（左）+ 大号 bold count（右）+ 下方 3px 细进度条
- Brand 用 `var(--accent)` cyan；Fail 用 `#e07b3a` 橙红 + `⚠` 图标

### Part 4: Storage 字段扩展

**`modules/laptop/schema.json`**
```json
"item_template": "{model} ({size}, {type}) — SMART: {smart} | Power-on: {power_on_hours}h | Written: {ssd_data_written} | Health: {ssd_health_percent}% Grade {ssd_grade}"
```

### Part 5: CSS 清理

删除 `.bar-row / .bar-label / .bar-track / .bar-fill / .bar-count`（被行内样式取代）。

---

## fix_ssd_health_grade — laptop_test.sh

支持三种磁盘的健康度：

| Disk     | type 字段    | Grade 来源                       |
|----------|--------------|----------------------------------|
| NVMe SSD | `SSD NVMe`   | `100 - Percentage Used`          |
| SATA SSD | `SSD`        | `Wear_Leveling_Count` VALUE 列   |
| HDD      | `HDD`        | `unknown`                        |

Grade 阈值：A ≥ 95, B ≥ 80, **C ≥ 70**（之前是 60，按 spec 改为 70），else D。

### 关键改动 (`laptop_test.sh` storage 段)

```bash
if [[ "$disk_type" == "SSD NVMe" ]]; then
  # 不变：Percentage Used / Available Spare / Data Units Written
  ...
elif [[ "$disk_type" == "SSD" ]]; then
  # 新增：SATA SSD
  WLC_VALUE=$(echo "$SMART_DETAIL" | awk '/Wear_Leveling_Count/{print $4}' | head -1)
  [[ -z "$WLC_VALUE" ]] && WLC_VALUE=$(... /Media_Wearout_Indicator/ ...)  # Intel fallback
  [[ -z "$WLC_VALUE" ]] && WLC_VALUE=$(... /SSD_Life_Left/ ...)
  [[ "$WLC_VALUE" =~ ^[0-9]+$ ]] && SSD_HEALTH_PCT=$WLC_VALUE
  SSD_AVAIL_SPARE="N/A"
  SSD_DATA_WRITTEN="N/A"
fi

# 统一 grade（NVMe + SATA SSD）
if [[ "$SSD_HEALTH_PCT" != "unknown" ]] && [[ "$disk_type" != "HDD" ]]; then
  if   [[ $SSD_HEALTH_PCT -ge 95 ]]; then SSD_GRADE="A"
  elif [[ $SSD_HEALTH_PCT -ge 80 ]]; then SSD_GRADE="B"
  elif [[ $SSD_HEALTH_PCT -ge 70 ]]; then SSD_GRADE="C"
  else SSD_GRADE="D"
  fi
fi
```

控制台输出条件从 `$disk == *nvme*` 改成 `$disk_type != "HDD"`，让 SATA SSD 也打印健康行。

`bash -n laptop_test.sh` 通过。

---

## Task 08 — Tab 重命名 + 卡片并排

### Part 1: Tab 标签 + 顺序

**`modules/laptop/templates/module.html`**

| 旧标签       | 新标签   | activeTab 值 |
|--------------|----------|--------------|
| Latest       | Today    | latest       |
| SN Search    | Search   | search       |
| Statistics   | Stats    | stats        |

顺序：**Today · Stats · Search**（内部 `activeTab` 值不变）。

### Part 2: By Brand / Fail Reasons 并排等高

外层 wrapper：`display:flex; flex-direction:row; gap:16px; align-items:stretch`  
子卡片：`flex:1; min-width:0`

---

## 追加修复 — `x-show` 清掉 `display:flex`

### 现象

用户截图显示 Stats tab 中区域 2（By Brand / Fail Reasons）依然垂直堆叠，区域 1（4 张 stat cards）正常并排。

### 根因

外层 wrapper 同时带 `x-show="statsData"` 和行内 `style="display:flex; ..."`：

> Alpine 的 `x-show` 切换显示时直接 `element.style.display = ""`（恢复时）或 `"none"`（隐藏时）。**恢复时空字符串会清掉行内 `display:flex`**，于是元素回退默认 block 布局，两张卡片垂直堆叠。

### 修复

把 flex 布局从行内迁到 CSS class，class 不会被 `x-show` 覆盖。

**`static/css/dashboard.css`**
```css
.stats-row {
  display: flex;
  flex-direction: row;
  gap: 16px;
  margin-bottom: 20px;
  align-items: stretch;
}
.stats-row > .detail-panel {
  flex: 1;
  min-width: 0;
  margin-bottom: 0;
}
```

**`modules/laptop/templates/module.html`**
```html
<!-- 旧 -->
<div style="display:flex; flex-direction:row; ..." x-show="statsData">
  <div class="detail-panel" style="flex:1; min-width:0;">

<!-- 新 -->
<div class="stats-row" x-show="statsData">
  <div class="detail-panel">
```

强刷（Ctrl+F5）后区域 2 与区域 1 一样左右等宽并排。

---

## 经验总结

1. **`x-show` 不要和行内 `display:` 共存** — Alpine 切换时会改写 `style.display`，行内布局会被擦掉。把 `display:flex/grid` 放到 CSS class 里更稳。
2. **一 SN 一记录的清理顺序**：先删索引行（DB 操作可恢复）→ 再删文件 → 再清空目录。文件系统是 source of truth。
3. **storage.py ↔ index_db.py 循环依赖**：用函数内 `from core import index_db` 局部导入解决。
4. **日历周/月 ≠ 滚动 7/30 天**：用户期望的 "This Week" 是周一到周日，不是 "过去 7 天"。
5. **SSD 健康度按厂家不同字段**：NVMe 用 `Percentage Used`；SATA 用 `Wear_Leveling_Count`（Samsung）/ `Media_Wearout_Indicator`（Intel）/ `SSD_Life_Left` 三级 fallback。

---

## 文件清单（本次会话改动）

### 服务端 / 后端
- `monitorcentor/core/storage.py`
- `monitorcentor/core/index_db.py`
- `monitorcentor/modules/laptop/module.py`
- `monitorcentor/modules/laptop/schema.json`

### 模板 / 前端
- `monitorcentor/templates/base.html`
- `monitorcentor/templates/index.html`
- `monitorcentor/modules/laptop/templates/module.html`
- `monitorcentor/static/js/app.js`
- `monitorcentor/static/css/dashboard.css`

### 客户端脚本
- `laptop_test.sh`（storage 段：SATA SSD 支持 + grade C 阈值 70）
