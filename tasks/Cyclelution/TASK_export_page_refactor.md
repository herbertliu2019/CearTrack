# TASK: Cyclelution Export 页面重构 — 候选时间窗 + 归档类页签简化

> 交给 Claude Code。前置:先读 SKILL.md,并了解现有 Cyclelution Export 页面实现
> (T-Laptop / T-Video Card / T-Hard Drive 三个 production 共用同一套页面框架)。
> **本任务适用于全部三个 production**,是对既有页面框架的重构,不是新功能。

## 0. 背景与问题

生产环境实测发现 T-Hard Drive 页面 NO_GRADE 页签有 27250 条、Excluded 有 2198 条。
根因: wipe_index.db 是跨越数年的历史归档库,Rescan 把全部历史记录都扫描分类了,
而实际候选(实物还在仓库、真正需要处理)只是最近的一小部分。**这不是"数据量大要优化",
是"候选范围定义错了"** —— 优先从范围下手,而不是单纯做分页/虚拟滚动等性能补丁。

同时发现一个语义问题: 当前实现里,时间窗外的历史记录被临时标记为 `excluded` 状态,
与"人工判定永久排除"的 `excluded`(报废/返修/样机)混用,导致该状态数字失真、语义冲突。

## 1. 候选时间窗(核心改动,优先做)

### 1.1 窗口定义

候选条件为**两个条件同时满足**:

```
候选 = 记录时间 >= 模块上线日(永久下限,如 wipe 模块为 2026-07-29)
    且 记录时间 >= 今天 - N 天(滚动窗口)
```

- **N 可配置**,写在 YAML 中,默认 **7 天**。三个 production(T-Laptop / T-Video Card /
  T-Hard Drive)各自独立配置,可设不同值。
- **模块上线日是永久下限**,不随窗口滚动而失效 —— 防止历史记录因窗口计算而"复活"重新进入队列,
  造成对已用其他方式处理过的设备重复导入。上线日同样写在配置中。
- 记录时间: wipe 模块用 `wipe_datetime`,laptop/GPU 用测试时间。

### 1.2 窗口只管入口,不管出口(重要,防止记录静默消失)

**窗口决定"哪些记录被纳入工作流",不决定"哪些记录留在工作流"。**

```
窗口内的记录        → 纳入,参与分类(ready / exceptions / no_grade)
已进入 Ready 的记录 → 一直保留在 Ready,直到被导出(exported)或人工排除(excluded),
                      即使它已超出滚动窗口也不得自动移出
已进入 Exceptions   → 同理,一直保留直到问题被修复后转 ready,或人工排除
```

反例(必须避免): 一块 7/29 擦除的盘进入 Ready 但当天未导出,8/6 时因超出 7 天窗口
被 Rescan 移出 Ready —— operator 无从察觉,设备被漏掉。**窗口过短时这个风险尤其高,
因此该规则是本任务的硬性要求。**

### 1.3 窗口外的记录如何处理

- **不新增页签、不新增状态。** 窗口外(或上线日之前)的记录归入既有的 `excluded`。
- 理由: `excluded` 的本质是"永不进入工作流",无论该决定来自人工(报废/返修/样机)
  还是来自规则(超出扫描范围),结果一致 —— 都不会回到工作队列,故可共用一个页签。
- **绝不并入 Exceptions。** Exceptions 的定义是"数据有问题且人能修的"(现有实现的
  报错信息已很好地体现了这点: 缺 weight/grade、wipe 记录未找到、cpu_suffix 无匹配等,
  每条都是一个待办)。而"记录时间超出窗口"没有任何人能修复,混入会使 Exceptions 计数
  失去"有多少事要做"的意义。
- Excluded 页签内以既有的 **reason 列 + operator 列**区分两类:
  - 人工排除: operator 显示姓名,reason 为人工填写内容
  - 系统排除: operator 显示 `—`,reason 如 `before scan cutoff 2026-07-29` / `outside window`
- Excluded 页签内增加一个 **Manual / System 筛选**(页签内的筛选控件,不是新页签),
  便于只查看人工排除的记录。

## 2. 页签的两种性质,展示方式不同

| 类别 | 页签 | 特性 | 展示原则 |
|---|---|---|---|
| **工作队列** | Ready, Exceptions | 需要人操作,数量应保持很小 | 完整列表,可勾选/操作 |
| **归档/只增** | Exported, Excluded, NO_GRADE | 只增不减,日常几乎不需要浏览全表 | **只显示计数 + 按 SN 搜索**,不预加载全表 |

### 2.1 归档类页签的页面设计

- 页签顶部只显示一行说明 + 计数。现有 NO_GRADE 的说明文案已写得很好,保留其风格:
  `Grade is auto-measured by the erasure software. These drives wiped without one —
  not a fixable data problem, so they can never be exported and don't count as exceptions.`
- **页面加载时不拉取、不渲染列表。** 提供 SN 搜索框,输入后再按需查询并展示结果。
- Exported / Excluded 页签同样改为"计数 + SN 搜索"模式(Excluded 另需 Manual/System 筛选)。
  若确实需要偶尔查看最近若干条,可保留"最近 N 条"的小范围展示(N ≤ 50),而不是加载全部。

## 2.5 Exceptions 的人工清理机制

### 背景

生产环境 T-Laptop 的 Exceptions 有 437 条,其中绝大部分是**已在系统外处理完毕的历史积压**
(旧版测试脚本无 weight/grade/condition 字段导致自动进异常,这些设备已由人工手动导入 Cyclelution)。
这些记录留在 Exceptions 中,使该计数无法回答"还有多少事要做",operator 看到 437 不会产生任何行动。

**Exceptions 必须是工作队列,不是档案馆。** 但清理只能由人显式触发,不能由系统按时间自动移出
(与 §1.2 一致: 自动消失会让 operator 无从察觉;人工清理有人、有原因、有时间可查)。

### 设计

**在 Exceptions 页签增加批量清理动作:**

1. 支持勾选(单选 / 全选 / 按当前筛选结果全选)。
2. 点击 **"Mark as Handled"** 按钮,弹确认框,要求填写:
   - **Reason**: 预置几个常用选项(如 `Imported manually` / `Not for stock` / `Duplicate` /
     `Other`)+ 自由文本备注。
   - **不记录操作员**(CearTrack 现无登录认证,只记 reason 与时间)。
3. 确认后,这些记录:
   - 状态改为 `excluded`
   - 写入 reason(含预置选项 + 备注)、清理时间戳(operator 字段留空/`—`,与系统排除一致)
   - 从 Exceptions 页签消失,出现在 Excluded 页签,Manual/System 筛选中归为 **Manual**
     (此时 Manual/System 的区分依据改为 **reason 类型**而非 operator 有无值,
     因为两者 operator 现在都是 `—`:reason 为 "Mark as Handled" 相关预置选项 → Manual;
     reason 为 "before scan cutoff" / "outside window" → System)
4. **不可逆**(与人工 excluded 一致)。确认框中需明确提示所选条数。

### 一次性清理当前积压

- 提供按条件批量筛选的能力(至少支持: 按报错内容关键字筛选、按记录时间早于某日筛选),
  使 operator 能一次性选中"旧脚本无 weight"这类历史积压并统一清理。
- 建议 reason 统一填 `Imported manually before CearTrack export`。
- 清理完成后 Exceptions 应归零或降至个位数,此后该计数才具有"待办数量"的意义。

### 预期效果

配合 §1 的 7 天候选窗口,加上新版测试脚本已包含 weight/grade/condition,
新产生的异常将大幅减少。清理这一次之后,Exceptions 应长期维持在个位数量级。

## 3. 分类结果必须落库,不可现算

- 每条记录的分类结果(ready / exceptions / no_grade / excluded / exported)
  **作为字段存储并建索引**,不是页面加载时临时计算。
- Rescan 的职责: 遍历候选窗口内的记录,重新跑校验门/归一化,**更新该字段**。
- 页面加载/切换页签: 仅按索引字段做 `WHERE status = ?` 查询,不重新执行归一化逻辑。
- 若当前实现是页面加载时现算分类(未落库),本任务需一并修正 —— 这是比页面展示更根本的
  性能问题,请在实现前确认现状并报告。

## 4. 验收标准

- Rescan 后,T-Hard Drive 参与工作流的候选记录数从 27250+2198+21 量级,降到
  "最近 N 天(默认 7 天)内实际产生的擦除记录数"量级。
- **窗口只管入口验证**: 将一条已在 Ready 中的记录的时间改到窗口之外(或等待其自然超期),
  再执行 Rescan —— 该记录**仍留在 Ready**,未被移出。这是本任务最关键的一条验收。
- 窗口长度 N 与模块上线日均从配置读取,修改配置并 Rescan 后候选范围随之变化,无需改代码。
- 模块上线日之前的记录,无论滚动窗口如何变化,始终不进入工作流。
- Exceptions 页签只包含"人可修复"的问题(缺字段、wipe 未找到、解析失败等),
  **不含任何 "outside window" / "before scan cutoff" 类记录**。
- Excluded 页签同时包含人工排除(Mark as Handled)与系统排除(超出窗口),
  均不记录操作员,靠 **reason 类型**用 Manual / System 筛选区分。
- NO_GRADE / Excluded / Exported 页签打开时**不出现列表,只有计数 + SN 搜索框**,
  页面加载时间不随历史数据量增长而变慢。
- 按 SN 搜索能在任意归档类页签中查到对应记录,几万条同类记录下查询速度不受影响(依赖索引)。
- 分类结果为存储字段而非页面加载时现算(可通过 schema 或代码确认)。
- 三个 production(laptop / GPU / wipe)均应用同一套窗口与页签展示设计。
- **Exceptions 清理验证**: 在 Exceptions 中勾选若干条 → Mark as Handled → 填 reason →
  确认后这些记录从 Exceptions 消失,出现在 Excluded 且 Manual 筛选可见,reason 与
  时间戳完整、operator 为空;Exceptions 计数相应减少。
- Exceptions 支持按报错关键字与记录时间筛选,可一次性选中历史积压批量清理。

## 5. 待确认(实现前提出)

1. 候选时间窗默认"最近 1 个月"对三个 production 是否都合适,还是需要分别设置
   (例如 laptop 测试到出货的周期是否比 wipe 更短)?
2. 各 production 的模块上线日(永久下限)分别是哪天 —— wipe 已知为 2026-07-29,
   laptop / GPU 需确认。
3. 系统排除记录在 reason 列的文案措辞(现有 "before scan cutoff YYYY-MM-DD" 已可用,
   窗口滚动导致的可用 "outside N-day window")。
4. Exceptions 清理**不记录操作员,只记 reason 与时间**(已确认)。
   Excluded 的 Manual/System 筛选因此改为按 **reason 类型**判断,而非按 operator 有无值
   (两者 operator 现在都是 `—`)。实现时 reason 需分为可枚举的"系统类"与"人工类"
   两组,供筛选逻辑判断使用。
