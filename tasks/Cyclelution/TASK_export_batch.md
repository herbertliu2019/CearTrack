# TASK: Export Batch (扫码建批次导出)

适用范围：CearTrack 三条产线共用导出页（laptop / gpu / wipe）。
本次仅在 **wipe** 启用，laptop / gpu 保持现有行为不变。

---

## 背景与目标

### 现状问题

wipe 记录进入 Ready 池后，操作员在页面上勾选记录导出 xlsx。存在三个问题：

1. **物理对应无保证**：裸盘外观无区分度，从 200 行 SN 列表中勾选，无法验证勾中的是否就是手上这批盘。
2. **贴标签环节风险高**：xlsx 上传 Cyclelution 后在 Cyclelution 端打印标签，操作员需在一堆裸盘中找到每张标签对应的盘（N×N 配对）。
3. **导出粒度不可控**：单次导出行数无约束。

### 设计原则

> **导出批次由物理动作生成，不是由数据库查询生成。**

操作员逐块拿起硬盘 → 扫码或手输 SN → 记录加入批次 → 全部扫完后一次性导出单个 xlsx → 上传 Cyclelution 一次完成。

凡是出现在 xlsx 里的行，都被人手拿过一次。

### 目标

- 扫码/手输建立批次，批次驻留服务端，可跨页面刷新、跨设备恢复
- 每块盘分配批次内递增的**位置号 (slot)**，用于上传后的贴标签环节
- 单次导出生成一个 xlsx，包含批次全部记录
- 批次行数上限可配置，硬限制
- 逻辑写在共享层，靠 YAML 配置控制哪条产线启用

---

## 硬性规则

1. **批次数据必须落服务端 DB**，前端只做显示。每扫一块立即写库，不允许仅存在于浏览器 state。
2. **批次库独立**：新建 `data/batches.db`，不写入 `wipe_index.db`（擦除软件写的历史归档）或 `data/_index.sqlite`。
3. **表结构一次建好**，含 `production` 字段，laptop / gpu 现在不产生记录但结构已就位。
4. **`max_rows` 为硬限制**，达到上限后禁止继续加入。不提供"允许超限"开关。
5. **服务端每次加入都校验行数**，不能只靠前端禁用输入框。
6. **手输 SN 绝不自动匹配**：必须显示候选（SN + 容量 + 型号 + Grade）由操作员确认后才加入。
7. **一条记录同时只能属于一个 open 批次**。已在批次中的记录，其他批次扫描时拒绝。
8. **位置号在批次内从 01 递增**，不跨批次连续。
9. **导出失败可重下**：批次记录保留，允许重新生成同一个 xlsx，不需重扫。
10. **`enabled: false` 时页面行为与现在完全一致**，不得有任何回归。
11. 页面上所有出现 `max_rows` 的位置从配置读取，前端不写死。
12. **不改动现有 xlsx 生成逻辑的字段映射**。批次导出复用现有 mapping / 校验管线，只改"记录来源"。

---

## 配置

`config/` 下现有产线 YAML 新增 `batch` 段：

```yaml
wipe:
  batch:
    enabled: true
    max_rows: 50
    slot_numbers: true

laptop:
  batch:
    enabled: false
    max_rows: 50
    slot_numbers: false

gpu:
  batch:
    enabled: false
    max_rows: 50
    slot_numbers: false
```

字段说明：

| 字段 | 类型 | 说明 |
|---|---|---|
| `enabled` | bool | false 时导出页保持勾选模式 |
| `max_rows` | int | 批次行数硬上限。范围 1–500 |
| `slot_numbers` | bool | 是否分配并显示位置号 |

**读取时机**：每次创建新批次时重新读 YAML，不做进程级缓存。改配置无需重启 gunicorn，当前进行中的批次不受影响（批次创建时的 `max_rows` 存入 `export_batches` 行）。

**启动校验**：`max_rows` 非正整数或超出 1–500 → 拒绝启动，日志打出产线名与非法值。

---

## 数据模型

`data/batches.db`

```sql
CREATE TABLE export_batches (
    batch_id      TEXT PRIMARY KEY,
    production    TEXT NOT NULL,
    status        TEXT NOT NULL,
    max_rows      INTEGER NOT NULL,
    slot_numbers  INTEGER NOT NULL,
    operator_id   TEXT,
    created_at    TEXT NOT NULL,
    exported_at   TEXT,
    export_file   TEXT
);

CREATE TABLE export_batch_items (
    batch_id    TEXT NOT NULL,
    record_sn   TEXT NOT NULL,
    slot_no     INTEGER,
    added_at    TEXT NOT NULL,
    input_mode  TEXT NOT NULL,
    PRIMARY KEY (batch_id, record_sn)
);

CREATE INDEX idx_items_sn ON export_batch_items(record_sn);
CREATE INDEX idx_batches_status ON export_batches(production, status);
```

**`batch_id` 格式**：`{PREFIX}-{YYYYMMDD}-{NN}`，序号当天从 01 递增。
前缀：wipe → `WIPE`，laptop → `LAPTOP`，gpu → `GPU`。

**`status` 取值**：
- `open` — 正在扫入
- `exported` — 已生成 xlsx
- `cancelled` — 操作员放弃

**`input_mode` 取值**：`scan` / `manual`。留作后续统计手输比例，不参与业务逻辑。

**`record_sn`**：wipe 对应 `drive_sn`；laptop / gpu 后续接入时对应各自主键。存 SN 而非内部 ID，便于跨库查询与人工排查。

---

## 接口

统一前缀 `/{production}/api/batch`。

### `GET /current`
返回当前 `open` 批次；不存在则返回 `null`（不自动创建）。
响应含：`batch_id`、`max_rows`、`slot_numbers`、`items[]`（按 `slot_no` 倒序，最新在前）、`count`。

### `POST /create`
创建新批次。若已存在 `open` 批次则返回 409 及现有 `batch_id`。

### `POST /lookup`
入参 `query`（SN 全串或片段）。
在该产线 Ready 池中匹配，返回候选数组（SN / 容量 / 型号 / Grade）。
- 0 条 → 返回空数组 + 原因判定：该 SN 在 Exceptions / NO_GRADE / 已导出 / 已在其他批次 / 完全不存在
- 1 条 → 仍返回数组，由前端决定是否直接加入（扫码模式全串精确匹配时可直接加）
- 多条 → 返回全部，前端必须要求确认

### `POST /add`
入参 `record_sn`、`input_mode`。服务端顺序校验：
1. 存在 `open` 批次
2. 当前条数 < 该批次 `max_rows` → 否则 409 `batch_full`
3. 该 SN 在 Ready 池中 → 否则 400，带原因
4. 该 SN 不在任何 `open` 批次中 → 否则 409，带占用的 `batch_id`

通过后写入，`slot_no = 当前最大 slot_no + 1`（`slot_numbers: false` 时写 NULL）。返回该条的 slot_no 与记录详情。

### `POST /remove`
入参 `record_sn`。从批次移除。
**已分配的 slot_no 不回收、不重排** —— 位置号已经写在物理便签/托盘上，重排会导致实物与系统不一致。移除后该号位空缺。

### `POST /export`
生成 xlsx：走现有 mapping / 校验管线，记录来源改为批次成员，行序按 `slot_no` 升序。
成功后：`status` → `exported`，写 `exported_at` / `export_file`，批次成员在 Ready 池标记为已导出。

### `POST /redownload`
入参 `batch_id`。对 `exported` 批次重新生成同一文件。不改变任何状态。

### `POST /cancel`
`status` → `cancelled`，成员释放回 Ready 池。需前端二次确认。

---

## 页面

### 模式分支

Ready 标签页根据 `batch.enabled` 分两种形态，共用同一套 tab 计数条与数据源：

- `false` → 现有完整列表 + 复选框（不改）
- `true` → 扫描面板 + 批次列表 + 右栏统计

Alpine.js 用 `x-if` 分支，不做两套页面。

### 启用批次模式时的布局

左栏（约 60%）：

- 顶部扫描输入框，常驻 autofocus，扫描成功后自动清空并重新聚焦
- 输入框下方状态行，三种反馈：
  - 成功 → success 色，显示"已加入 · SN · 容量 · 型号"
  - 多候选 → warning 色，下方展开候选列表待点选
  - 失败 → danger 色，**不清空输入框**（让操作员看清扫到了什么），显示具体原因
- `slot_numbers: true` 时，成功后显示大号位置号卡片：位置号（等宽、约 34px）+ SN + 规格 + "放入 27 号位"
- 批次列表**倒序**（最新扫入在最上），每行：slot_no / SN / 容量 / Grade 色块 / 移除按钮
- 底部：计数 `27 / 50`、导出 xlsx、打印位置清单、清空批次

右栏（约 40%）：

- Ready 池总数（不预加载列表）
- 按 wipe 日期分组的计数（仅统计，不作为选择入口）
- SN 查询框：查某块盘为什么不在 Ready 池

### 视觉规则

- SN 用等宽字体，字号大于其他列；**后 6 位加粗**，其余字段降灰。实际作业中人眼只核对后几位
- 行高 ≥ 44px（操作员可能戴手套、站立操作）
- Grade 用小色块非文字：A = `var(--pass)`，B = `var(--warn)`，C = `#e07b3a`
- 批次模式下 Ready 主列表整个不渲染，也不提供复选框——选择动作由物理扫描驱动
- 计数 ≥ `max_rows - 5` 时变 warning 色；`= max_rows` 时输入框 disabled，占位文字改为"批次已满，请导出"，导出按钮成为唯一主动作

### 反馈

- 成功：行滑入 + 绿色闪烁 + 短促提示音
- 失败：输入区红色闪烁 + 不同音调提示音
- 提示音需可在配置中关闭（工位环境可能不适用）

### 导出后

导出成功 → 自动创建下一个批次（`WIPE-20260831-02`），输入框恢复可用，位置号重置为 01。
页面提示：前一批次的盘尚未贴标签时，物理上需与新批次分开存放。

---

## 位置清单打印

`slot_numbers: true` 时提供打印视图，纯 HTML 打印页，A4 纵向：

- 页眉：batch_id、导出时间、操作员、总数
- 表格列：位置号 / SN / 容量 / 型号 / Grade
- 按 slot_no 升序
- 字号足够大，供操作员在工位上查表

**用途**：Cyclelution 打印出标签后，操作员看标签上的 SN → 在清单上查到位置号 → 直接取盘。把"在 50 块盘里翻找"变成"查表 + 直接取"。

**待定项**：位置号是否同时写入 xlsx 的某一列，取决于 Cyclelution 81 列模板中是否有可承载的自由字段。**本期不做**，先只走纸质清单。

---

## 分阶段执行

### Phase 1 — 批次数据层

- 建 `data/batches.db` 与两张表
- YAML 配置读取 + 启动校验
- 实现 `/current` `/create` `/add` `/remove` `/cancel`
- `batch_id` 生成逻辑（当天序号递增，并发安全）

**验证**：
- 用 curl 建批次、加 3 条、移除 1 条、查 `/current`，数据正确
- 加到 `max_rows` 后再加返回 409 `batch_full`
- 同一 SN 加两次返回 409
- 移除后 slot_no 不重排，新加入的取最大值 +1
- `max_rows` 配成 0 / 600 / 非数字 → 启动被拒绝并打日志
- 重启 gunicorn 后 `/current` 仍返回原批次

### Phase 2 — 扫描面板组件

- Alpine.js 组件：输入框、`/lookup` 调用、候选确认、批次列表、位置号卡片
- 三种反馈状态与视觉规则
- `x-if` 模式分支，`enabled: false` 路径完全不受影响

**验证**：
- 扫码全串精确匹配 → 直接加入
- 输入后 6 位命中唯一 → 显示候选，确认后加入
- 输入片段命中多条 → 列出全部，不自动选
- 输入不存在 SN → 报错且输入框保留内容
- 输入 Exceptions / NO_GRADE / 已导出的 SN → 分别显示对应原因
- 刷新页面 → 批次完整恢复
- laptop 页面（`enabled: false`）行为与改动前逐项一致

### Phase 3 — 导出接口

- `/export`：从批次成员生成 xlsx，行序按 slot_no
- 状态流转、Ready 池标记
- `/redownload`
- 位置清单打印视图

**验证**：
- 导出文件行数与批次条数一致，行序与 slot_no 一致
- 字段内容与改造前勾选导出的结果逐字段一致（同一批 SN 对比）
- 导出后批次 `status` = exported，成员从 Ready 移出
- `/redownload` 生成的文件与首次导出逐字节一致
- 导出中途模拟失败 → 批次仍为 open，成员未被标记，可重试
- 打印视图在 A4 上排版正确

### Phase 4 — 配置接入与联调

- 三条产线配置项就位
- 导出后自动开新批次
- 计数临界态、满批次禁用
- 提示音开关

**验证**：
- wipe `enabled: true`、laptop / gpu `false`，三个页面分别正常
- wipe 配置改 `max_rows: 10` 后无需重启，下一个批次生效，当前批次不变
- 完整走一遍：扫 10 块 → 满 → 导出 → 自动新批次 → 位置号回到 01

---

## 不在本期范围

- 位置号写入 xlsx 列（待确认 Cyclelution 模板是否有可用字段）
- laptop / gpu 启用批次模式（等 wipe 试运行 2–3 周后按配置开启）
- 按 wipe 日期分组的完整性核对（依赖擦除工位分箱存放的物理纪律，未确认）
- 手输比例统计报表（`input_mode` 字段已埋点，报表后做）

---

## 试运行观察项

wipe 上线后收集，用于决定 laptop / gpu 接入时的参数：

1. 实际批次大小分布 —— `max_rows: 50` 是否合适
2. 位置清单是否真的被使用 —— 决定 `slot_numbers` 在其他产线的默认值
3. 扫描失败次数与原因分布
4. 手输占比（`input_mode = manual`）
5. Cyclelution 打印的标签上是否印有 SN、打印顺序是否等于上传行序 —— 决定位置清单机制是否需要调整
