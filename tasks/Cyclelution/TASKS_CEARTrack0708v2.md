# TASKS: CearTrack ↔ Cyclelution T-Laptop 集成 — 分阶段任务

> 执行顺序严格 Phase 1 → 2 → 3 → 4。每个 Phase 完成并通过验收后才进下一个。
> 每个 Phase 开始前重读 SKILL.md。禁止跨 Phase 提前实现后续功能。

---

## Phase 1 — 数据层:状态字段 + wipe join 模块

**目标**: 为每条 laptop 记录建立 sync_status 状态,打通 wipe 库查询。不碰 UI,不碰导出。

**任务**:
1. 调研现有 data/_index.sqlite 表结构,选改动最小的方式为 laptop 记录增加字段:
   - sync_status TEXT DEFAULT 'pending' (pending/ready/synced/excluded)
   - sync_note TEXT (异常清单原因/FAIL 标记等)
   - synced_at TEXT (导出时间, ISO)
2. 写迁移脚本(幂等,可重复执行):为存量记录补默认值 pending。
3. 新建模块 `wipe_lookup.py`:输入硬盘 SN,按 SKILL.md 第 2 节的 SQL 查 wipe_index.db,返回 dict 或 None。只读,不写 wipe 库。
4. 兼容 laptop 测试脚本新增字段:POST 接口接收并存储 JSON 的 manual_input 段(weight_lbs/grade/condition/color/screen_size_inch/mark/cddvd_present,契约见 SKILL.md 第 8 节)。向后兼容旧 JSON——无 manual_input 时各字段 None,不报错。

**验收标准**:
- 迁移脚本跑两遍无副作用,所有存量记录 sync_status='pending'。
- `wipe_lookup('PHHP945005MJ512C')` 返回 capacity=512GB, result=PASSED 的记录。
- `wipe_lookup('不存在的SN')` 返回 None 不抛异常。
- 旧 JSON(无 weight/grade)读取不报错。

---

## Phase 2 — 归一化引擎 + 校验门 + 异常清单(纯逻辑,无 UI)

**目标**: 配置驱动的归一化引擎,输入一条 laptop 记录,输出"Cyclelution 81 列值 + 校验结论"。这是全项目核心。

**任务**:
1. 修订 mapping_t_laptop.yaml,使其与需求文档第 5 章及 mapping_domains_t_laptop.yaml(九张值域/别名表,已交付)逐字段一致:Weight(lbs)/Grade(字母→Grade X)/Condition(数字→全称)来源均为 JSON manual_input;Data Sanitization 有无盘分支;Manufacturer 清洗+别名(Txt,不进异常清单);Model Txt;新增 Color(direct)/Size(screen_size_inch→"NN inch"落值域)/ddl012 CD/DVD 由 cddvd_present 映射;Mark→TxtProperty001。
2. 实现通用转换引擎 `normalizer.py`:读 YAML,支持 const/direct/table/bucket/parse 五类转换器。字段规则一律来自配置,代码零硬编码。
3. 实现 SKILL.md 第 3 节 10-14 条的具体转换逻辑(Memory 归档/Storage Size/Storage Type/Proc Type/Proc Speed),storage 数据经 Phase 1 的 wipe_lookup 获取。
4. 实现校验门 `gate.py`:
   - 硬校验(全过→ready): SN 合法、Grade 非空、Condition 非空、Weight 数字非空、所有 ddl 值落值域(注:Manufacturer/Model 走 Txt 不校验值域)、capacity>=16GB(有盘时)
   - wipe 检查条件化: storage 非空→每块盘 wipe 记录存在且 PASSED(不过→异常);storage 为空→跳过 wipe 检查,合法,但 sync_note 标 NO_DISK(软标记,队列高亮)
   - 任一硬校验失败 → sync_status 保持 pending + sync_note 写明卡住的字段(异常清单数据来源)
   - 软校验: overall_result=FAIL → 照常可 ready,sync_note 标 "TEST_FAIL";无盘 → 照常可 ready,sync_note 标 "NO_DISK"。两类软标记在 Ready 队列高亮
5. 实现 Vendor 规范化:通用清洗(去公司后缀+trim+大写)+别名修正表(见 mapping_domains_t_laptop.yaml manufacturer 节)。清洗结果直填(Txt 通道),不因值域不符进异常清单。
6. 批量扫描入口 `scan.py`:遍历所有 pending 记录跑归一化+校验门,更新状态。可手动运行(定时化留到 Phase 4 决定)。

**验收标准**:
- 黄金测试用例(SKILL.md 第 7 节)全部字段逐字通过,写成 pytest 固定测试。
- 构造反例各一并通过:wipe FAILED→不进 ready;Grade 空→异常;内存 130GB→异常;device_type 乱串→异常且 sync_note 指明字段。
- 换一份 YAML 配置(改一个 domain 值)引擎行为随之变化,证明配置驱动。

---

## Phase 3 — xlsx 导出

**目标**: 把勾选的 ready 记录批量生成 Cyclelution 可导入的 xlsx。

**任务**:
1. `exporter.py`:输入一组记录 ID,以交付包内 Adjust_Template.xlsx(生产环境官方模板,81 列,已用于实测导入验证)为底,用 openpyxl 从第 2 行起填数据,不改表头,输出到导出目录,文件名含时间戳(如 adjust_TLaptop_20260707_1030.xlsx)。多条记录写多行。
2. 只允许导出 sync_status='ready' 的记录;导出成功后置 synced + synced_at,写 sync_note 记录导出文件名。
3. 表头 81 列与模板逐字一致,未使用的列留空。ProductName 等固定值从 YAML 读(环境区分:默认生产值 "T - Laptop")。

**验收标准**:
- 用黄金用例导出的 xlsx,与人工验证成功导入过的那份字段值完全一致(可写脚本 diff)。
- 导出后记录变 synced,再次导出请求同一记录被拒绝并提示。
- 空勾选/含非 ready 记录的请求返回明确错误,不生成文件。

---

## Phase 4 — Web UI(Ready 队列 / 异常清单 / 导出)

**目标**: 操作员日常使用的三个视图,沿用现有 Flask+HTMX 风格。具体页面布局与用户(Herbert)在本阶段开始时再确认细节,先按下述功能范围实现。

**任务**:
1. Ready 队列视图:列出 ready 记录(SN/型号/Grade/Weight/日期/FAIL 标记高亮),支持日期筛选、全选/勾选,底部 "Generate Import File" 按钮 → 调 Phase 3 导出 → 返回下载链接。
2. 异常清单视图:列出 pending 且 sync_note 非空的记录,显示卡住字段与原因。仅展示,修数据回原有界面(本视图不做编辑功能)。
3. 已导出视图(或队列内切换 tab):synced 记录 + 导出时间 + 文件名,只读。
4. 每条记录提供 "Mark Excluded" 操作(带确认),excluded 记录从各队列消失,可在筛选中查看。
5. 手动触发 "Rescan" 按钮调用 Phase 2 的 scan(是否加 APScheduler 定时,实现后与用户确认再定)。
6. 权限沿用现有 admin/user 机制,操作员角色可见可操作。

**验收标准**:
- 全流程手工走通:新记录 POST → Rescan → 出现在 Ready 队列 → 勾选导出 → 下载 xlsx → 记录变 synced 且不再出现在队列 → 该 xlsx 人工上传 Cyclelution 成功。
- FAIL 标记记录在队列中有明显视觉提示。
- 异常清单能正确显示 Phase 2 反例的卡住原因。

---

## 明确不做(防止过度设计)

- 不做 CSV/字段编辑器(操作员回原界面改数据)
- 不做"手动置 ready"
- 不做两层值存储(原始值 vs 覆盖值)
- 不做 Cyclelution 上传自动化(操作员手动 Upload for Adjusting)
- 不做回流确认(等未来 API)
- 不做 T-Desktop/T-GPU(流程层预留 production 参数即可,勿实现)
