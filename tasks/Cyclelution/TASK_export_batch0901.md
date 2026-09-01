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
4. **不设行数硬限制。** 超过 `large_batch_warn` 时显示提示条，但不阻止继续加入、不阻止导出。
5. **批次自动创建**：第一次成功加入记录时若无 open 批次则自动建一个。不提供"新建批次"按钮，操作员不应感知批次的创建动作。
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
    large_batch_warn: 100
    slot_numbers: true
    filters: [wipe_date]
    pool_third_column: capacity

laptop:
  batch:
    enabled: false
    large_batch_warn: 100
    slot_numbers: false
    filters: [test_date, operator]
    pool_third_column: model

gpu:
  batch:
    enabled: false
    large_batch_warn: 100
    slot_numbers: false
    filters: [test_date, test_station]
    pool_third_column: model
```

字段说明：

| 字段 | 类型 | 说明 |
|---|---|---|
| `enabled` | bool | false 时导出页保持勾选模式 |
| `large_batch_warn` | int | 达到此条数时显示提示条。纯提示，不拦截 |
| `slot_numbers` | bool | 是否分配并显示位置号。false 时队列不显示 slot 列，底部不显示 Slot sheet 按钮 |
| `filters` | list | 左栏筛选下拉，按声明顺序并排渲染。空列表则不渲染筛选区 |
| `pool_third_column` | str | 左右两栏第三列显示的字段 |

**`filters` 可选值**：`wipe_date` / `test_date` / `operator` / `test_station`。组件按声明顺序渲染，每项一个下拉，选项从当前 Ready 池中去重生成（不是全库去重，避免出现选了就空的选项）。后续要加 `grade` / `model` 等只需扩展这个枚举，不改组件结构。

**各产线可用的筛选维度**：

| 产线 | 筛选器 | 说明 |
|---|---|---|
| wipe | `wipe_date` | 擦除日志无操作员字段，不提供 operator |
| laptop | `test_date` + `operator` | 操作员取 `test_info.operator_id`，**不是** `manual_input.operator_id` |
| gpu | `test_date` + `test_station` | 工位取 `payload.test_info.test_station`（GPUTESTSTATION1 / GPUTESTSTATION2）。**不要用 `operator_id`** —— 该字段将在下一版测试脚本中移除 |

`operator` 与 `test_station` 是两个独立的筛选类型，共用同一套下拉渲染逻辑，只是取值字段和下拉标题不同（`All operators` / `All stations`）。

**GPU 字段路径**（以 `payload` 内的为准，顶层字段是冗余镜像）：

| 用途 | 路径 | 示例值 |
|---|---|---|
| 记录主键 SN | `sn`（顶层） | `0424117037990` |
| 工位筛选 | `payload.test_info.test_station` | `GPUTESTSTATION1` |
| 日期筛选 | `payload.test_info.test_time` 取日期部分 | `2026-08-24` |
| 第三列 model | `payload.gpu.vendor` + `payload.gpu.name` | `NVIDIA Quadro P1000` |
| Grade 色块 | `payload.manual_input.grade` | `Grade B` |

注意事项：

- `hostname`（顶层）与 `payload.test_info.test_station` 内容相同，**统一用后者**，避免两处不一致时行为不确定
- `payload.gpu.gpu_sn` 与顶层 `sn` 相同，**统一用顶层 `sn`**，与其他产线保持一致
- `payload.test_info.operator_id` 存在但**不得被任何逻辑引用**，下一版脚本会移除；如果代码读了它，脚本升级后 GPU 页面会直接报错
- `manual_input.grade` 已经是完整显示字符串（`Grade B`），直接透传，不做 code→label 映射

**读取时机**：页面初始化时随页面配置一起下发给前端，不等批次创建。避免前端拿到 undefined。

**启动校验**：`large_batch_warn` 非正整数 → 拒绝启动，日志打出产线名与非法值。设为 0 或省略视为不提示。

---

## 数据模型

`data/batches.db`

```sql
CREATE TABLE export_batches (
    batch_id      TEXT PRIMARY KEY,
    production    TEXT NOT NULL,
    status        TEXT NOT NULL,
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
正常流程下前端不主动调用此接口 —— 批次由 `/add` 自动创建。保留此接口供导出后开新批次及排查使用。

### `POST /lookup`
入参 `query`（SN 全串或片段）。
在该产线 Ready 池中匹配，返回候选数组（SN / 容量 / 型号 / Grade）。
- 0 条 → 返回空数组 + 原因判定：该 SN 在 Exceptions / NO_GRADE / 已导出 / 已在其他批次 / 完全不存在
- 1 条 → 仍返回数组，由前端决定是否直接加入（扫码模式全串精确匹配时可直接加）
- 多条 → 返回全部，前端必须要求确认

### `POST /add`
入参 `record_sn`、`input_mode`。服务端顺序处理：
1. 校验该 SN 在 Ready 池中 → 否则 400，带原因（Exceptions / NO_GRADE / 已导出 / 不存在）
2. 校验该 SN 不在任何 `open` 批次中 → 否则 409，带占用的 `batch_id`
3. 若当前无 `open` 批次，**自动创建一个**并返回新的 `batch_id`

不再有行数上限校验。响应中带回当前条数，前端据此决定是否显示 large batch 提示条。

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

**左右分栏，左 = 备选池，右 = 导出队列。** 界面文案一律英文。

顶部横跨两栏：扫描输入框（`Scan or type part of a serial`），常驻 autofocus。下方一行状态提示。

**扫描框同时是过滤框** —— 这是唯一输入入口，扫码与模糊查询不分开：

- 输入时左栏实时按 SN 片段过滤，状态行显示 `N matches`
- 回车且唯一命中 → 直接加入，清空输入框并重新聚焦
- 回车且多条命中 → warning 色，提示在左栏点选，**不自动加入**
- 回车且无命中 → danger 色，**不清空输入框**（让操作员看清扫到了什么），提示检查 Exceptions / No grade / 已导出

**左栏 Ready pool：**

- 顶部：标题 + 条数
- 筛选区：按 `filters` 配置渲染若干下拉并排。多个筛选条件之间是 AND 关系，且与扫描框的 SN 过滤同时生效
- 记录列表，每行：Grade 色块 / SN / `pool_third_column` 字段 / 右箭头。整行可点击加入
- **已加入的记录从左栏消失**，两栏不重复
- **必须虚拟滚动或分页**，Ready 可能上百条乃至更多，不允许一次渲染全部
- 固定高度加内部滚动，保证右栏与底部操作条始终可见

**右栏 Export queue：**

- 顶部：标题 + `batch_id`（未开始时显示 `not started`）
- **倒序**列表（最新加入在最上），每行：`slot_no`（仅 `slot_numbers: true`）/ Grade 色块 / SN / `pool_third_column` 字段 / 移除按钮
- 空态：`Pick from the left, or scan a drive`（laptop / gpu 改 `unit`）

**底部操作条：**

- 左侧计数 `12 drives selected`，无分母。laptop / gpu 用 `units`
- 右侧依次：提示音开关（喇叭图标，切换 mute 时图标变 `volume-off`）、`Slot sheet`（仅 `slot_numbers: true`）、`Clear queue`、`Export xlsx`
- 上一批次已导出时，左侧额外显示 `Redownload {batch_id}` 链接

**Large batch 提示条：**

条数 ≥ `large_batch_warn` 时，在底部操作条上方出现 warning 色提示条，文案说明大批次上传若部分导入较难核对、建议拆分。**不禁用任何按钮，不阻止导出。**

### 视觉规则

- SN 用等宽字体，字号大于其他列；**后 6 位加粗**，其余字段降灰。实际作业中人眼只核对后几位
- 行高 ≥ 44px（操作员可能戴手套、站立操作）
- Grade 用小色块非文字：A = `var(--pass)`，B = `var(--warn)`，C = `#e07b3a`
- 批次模式下不提供复选框——加入动作靠点击整行或扫描
- 两栏内的 SN 过长时用 ellipsis 截断，但保证后 6 位可见

### 反馈

- 成功：行滑入 + 绿色闪烁 + 短促提示音
- 失败：输入区红色闪烁 + 不同音调提示音
- 提示音需可在配置中关闭（工位环境可能不适用）

### 导出后

导出成功 → 右栏清空，`batch_id` 回到 `not started`。下一次加入记录时自动创建 `WIPE-20260831-02`，位置号重置为 01。
页面提示：前一批次的盘尚未贴标签时，物理上需与新批次分开存放。

---

## 位置清单打印

`slot_numbers: true` 时提供打印视图，纯 HTML 打印页，A4 纵向：

- 页眉：batch_id、导出时间、操作员、总数
- 表格列：位置号 / SN / 容量 / 型号 / Grade
- 按 slot_no 升序
- 字号足够大，供操作员在工位上查表

**用途**：Cyclelution 打印出标签后，操作员看标签上的 SN → 在清单上查到位置号 → 直接取盘。把"在 50 块盘里翻找"变成"查表 + 直接取"。

Slot sheet 已确认保留，本期实现。

**待定项**：位置号是否同时写入 xlsx 的某一列，取决于 Cyclelution 81 列模板中是否有可承载的自由字段。**本期不做**，先只走纸质清单。

---

## 分阶段执行

### Phase 1 — 批次数据层

- 建 `data/batches.db` 与两张表
- YAML 配置读取 + 启动校验
- 实现 `/current` `/create` `/add` `/remove` `/cancel`
- `batch_id` 生成逻辑（当天序号递增，并发安全）

**验证**：
- 无 open 批次时直接调 `/add` → 自动创建批次并成功加入
- 加 3 条、移除 1 条、查 `/current`，数据正确
- 同一 SN 加两次返回 409
- 移除后 slot_no 不重排，新加入的取最大值 +1
- 连续加 200 条不被拒绝（确认无隐藏上限）
- `large_batch_warn` 配成负数 / 非数字 → 启动被拒绝并打日志
- 重启 gunicorn 后 `/current` 仍返回原批次

### Phase 2 — 左右分栏组件

- Alpine.js 组件：扫描/过滤框、左栏 Ready pool（虚拟滚动 + 日期筛选）、右栏队列、底部操作条
- 三种输入反馈状态与视觉规则
- 界面文案英文
- `x-if` 模式分支，`enabled: false` 路径完全不受影响

**验证**：
- 扫码全串精确匹配 → 直接加入，输入框清空并重新聚焦
- 输入片段唯一命中 → 回车加入
- 输入片段命中多条 → 左栏过滤到这几条，回车不加入
- 输入不存在 SN → 报错且输入框保留内容
- 输入 Exceptions / NO_GRADE / 已导出的 SN → 分别显示对应原因
- 点左栏行 → 移入右栏，同时从左栏消失
- 点右栏 × → 移回左栏，slot_no 不重排
- Ready 池灌入 1000 条 → 左栏滚动流畅，页面加载时间无明显增长
- 刷新页面 → 右栏队列完整恢复
- laptop 配置 `filters: [test_date, operator]` → 两个下拉并排渲染，选项来自当前 Ready 池
- gpu 配置 `filters: [test_date, test_station]` → 下拉标题为 `All stations`，选项为实际出现过的工位名
- 同时选中日期和操作员 → AND 生效；再输入 SN 片段 → 三个条件同时生效
- `slot_numbers: false` → 队列无 slot 列，底部无 Slot sheet 按钮
- `filters: []` → 筛选区整个不渲染，布局不留空隙
- 提示音开关点击后图标切换，静音状态下扫描无声
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
- large batch 提示条
- 提示音开关

**验证**：
- wipe `enabled: true`、laptop / gpu `false`，三个页面分别正常
- 页面初始化时 `large_batch_warn` 已下发，底部计数不出现 undefined 或破折号
- 加到 `large_batch_warn` 条 → 提示条出现；移除一条 → 提示条消失
- 提示条出现时导出按钮仍可用
- 完整走一遍：扫若干块 → 导出 → 右栏清空 → 再加入 → 新批次号，位置号回到 01

---

## 不在本期范围

- 位置号写入 xlsx 列（待确认 Cyclelution 模板是否有可用字段）
- laptop / gpu 的配置项与页面适配（筛选器、第三列、slot_numbers）本期一并实现并验证，但 `enabled` 保持 false；等 wipe 试运行 2–3 周后改配置开启，届时无需再改代码
- 按 wipe 日期分组的完整性核对（依赖擦除工位分箱存放的物理纪律，未确认）
- 手输比例统计报表（`input_mode` 字段已埋点，报表后做）

---

## 试运行观察项

wipe 上线后收集，用于决定 laptop / gpu 接入时的参数：

1. 实际批次大小分布，以及 Cyclelution 对大文件的实际表现 —— 决定 `large_batch_warn` 该定在哪，以及是否需要恢复硬上限
2. 位置清单是否真的被使用 —— 决定 `slot_numbers` 在其他产线的默认值
3. 扫描失败次数与原因分布
4. 手输占比（`input_mode = manual`）
5. Cyclelution 打印的标签上是否印有 SN、打印顺序是否等于上传行序 —— 决定位置清单机制是否需要调整
