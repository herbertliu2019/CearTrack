# TASK: T - Hard Drive (Wipe 模块) — Cyclelution 导出

> 交给 Claude Code。前置:先读 SKILL.md,并参照已完成的 T-Laptop 与 T-Video Card(GPU)实现。
> 本任务复用既有流程层与页面框架,**只新增 wipe 模块的适配层**(映射配置 + wipe 专属规则 + 范围过滤)。

## 0. 与前两个 production 的根本差异(务必先理解)

| | T-Laptop / T-Video Card | **T - Hard Drive(本任务)** |
|---|---|---|
| 数据来源 | 测试脚本 POST 的 JSON | **wipe_index.db 的 wipe_records 表**(解析擦除日志入库) |
| 人工录入字段 | operator 在测试脚本录入 | **无测试脚本、无 operator 交互** → 全部用常量或从 wipe 记录推导 |
| Grade | 一律 operator 人工判定 | **例外: 取 wipe 日志的 grade 字段**(擦除软件自动评级) |
| 导出范围 | 全部 | **仅擦除日志含 grade 的记录**(无 grade → NO_GRADE 不导出) |

**Grade 是本模块的特例**: 全项目原则是"Grade 一律人工判定,系统绝不自动填",但硬盘的 Grade 由擦除软件自动测定并写入日志,故直接取用。这是**唯一例外**,不适用于其他 production。

## 1. 数据源

```sql
-- 一台硬盘一条记录; 同一 drive_sn 可能有多次擦除,取最近一次
SELECT drive_sn, manufacturer, drive_model, capacity, device_type, protocol,
       result, grade, health_score, wipe_datetime
FROM wipe_records
WHERE drive_sn = ?
ORDER BY wipe_datetime DESC LIMIT 1;
```
库路径 `data/wipe/wipe_index.db`(与 laptop 的 `data/_index.sqlite` 是不同库,单独连接)。
**只读 wipe 库,不写。** 导出状态(sync_status 等)存在 CearTrack 自己的库/表中,不污染 wipe 库。

## 2. 导出范围过滤(本模块特有)

**唯一的不导出规则: 擦除日志中 `grade` 为空 → 标记 `NO_GRADE`,不进 Ready 队列。**

原因: Cyclelution 的 Grade 为必填,而 grade 由擦除软件自动测定;日志里没有,operator 也补不出来
(不是可修复的数据问题)。因此这类记录既不导出,也**不进异常清单**。

**不做类型过滤。** 只要有 grade,任何类型(M.2 / 2.5" SSD / HDD 等)都正常导出;
Weight 与 Color 按 Storage Type 查表填入(见 §4.5,HDD 用估计值)。

实现要求:
- `grade` 为空 → 标记 `NO_GRADE`,独立筛选项/视图展示。
- **绝不要把 NO_GRADE 混进异常清单** —— 异常清单是"数据有问题且人能修的"(如 capacity 解析失败);
  无 grade 是人修不了的,混在一起会让异常清单堆满修不了的记录,失去意义。
- 观察到的规律(供参考,**不作为判定依据**): grade 缺失多见于 source=eps / 较早软件版本
  (如 v14.36.0),已见 2.5" SSD 与 2.5" HDD 均为空;有 GRADE 的多为 source=pxe / v15.3.1 的 M.2 NVMe。
  **判定依据始终是 grade 字段本身是否为空,与盘的类型无关。**

## 3. 校验门

**硬校验**(不过 → 不可导出):
- `drive_sn` 非空且格式合法
- **`result = PASSED`**(擦除失败的盘绝不可进 Cyclelution — 全项目铁律)
- Storage Type 能判定(判不出 → 异常清单;类型本身不限制导出范围)
- Storage Size 能归档成功(capacity 解析出且落值域;< 16GB 视为采集异常 → 异常清单)
- Manufacturer / Model 非空

**注**: Grade 为空**不进异常清单**,而是标 `NO_GRADE` 不导出(见 §2) —— 因为这不是可修复的数据问题。

**无软校验**(本模块无 overall_result 之类的人工判断项)。

## 4. 字段映射(T - Hard Drive)

### 4.1 常量

| 列 | 值 |
|---|---|
| ProductName | **T - Hard Drive** |
| Office | 05 Testing/Resale |
| Qty / QtyBase | 1 / Unit |
| RTS / TDM | N / N (Normal) |
| **Bus ID** | **IT23041900028**(常量,写死 — 已确认) |
| Condition | C4 - Used Good |
| ddl002 Inventory Location | Testing Area |
| **ddl005 Data Sanitization** | **Pass** |
| ddl006 Disposition | 03 Tested |
| ddl009 Functionality | F3 - Key Functions Working |
| ddl013 R2 Applicability | C-R2 Controlled Streams |
| ddl014 Next Process | Commodity Storage |
| ddl015 Key Functions Test | Pass |
| ddl032 R2 Category | **Harvested/removed components of electronics**(与 T-Video Card 一致:硬盘同为拆机部件) |

**留空的槽位**(硬盘无此属性): Memory、Memory Type、Memory Size、Size、Processor Type、
Processor Speed、OS、CD/DVD Drive、Technology、Video Card、Battery Condition、Mark、
HDD SN、HDD TravelerID、Speed、Part No.、Addtional SN。

> 注意: 固定字段区的 **Model** 要填(见 4.2),而 txt 区那个 "Model"(CPU 型号尾码)留空。

### 4.2 映射字段

| Cyclelution 列 | 来源 | 转换 |
|---|---|---|
| Serial No. | `drive_sn` | direct |
| Manufacturer | `manufacturer` | 清洗+别名(复用现有厂商规范化逻辑,大写) |
| **Model** | `drive_model` | **去厂商名 + trim(见 4.3)** |
| Grade | `grade`("GRADE A") | **格式转换 → "Grade A"**(见 4.4) |
| Storage Size | `capacity` | 与 laptop 完全一致的解析+向上归档(如 "1TB" → "1 TB") |
| Storage Type | `device_type` (+ `protocol`) | 与 laptop 完全一致的判定规则 |
| **Weight** | 按 Storage Type 查重量表 | 见 4.5 |
| **Color** | 按 Storage Type 查颜色表 | 见 4.5 |

### 4.3 Model — 去厂商名

规则: 若 `drive_model` 以 `manufacturer`(或其常见变体/别名)开头,去掉该前缀;其余原样保留;trim 多余空格。

```
manufacturer=MICRON, drive_model="MICRON 2300"              → "2300"
manufacturer=HYNIX,  drive_model="PC711 512GB"              → "PC711 512GB"   (无厂商前缀,原样)
manufacturer=TOSHIBA,drive_model="KBG40ZNS512G KIOXIA 512GB"→ 原样(KIOXIA 不在开头,不动)
manufacturer=SEAGATE,drive_model="ST1000LM035-1RK172"       → 原样
```

**实测要求**: 用 wipe 库中至少 20 条真实记录(覆盖 Micron/Samsung/WD/Toshiba/Hynix/Intel/
Seagate/LITEON 等)跑一遍,把 `drive_model → Model` 的结果打印出来人工抽验,
**确认没有把型号本身的一部分误删**。若发现规则不足(如厂商名出现在中间),提出后再调整,不要自行加复杂规则。

### 4.4 Grade 格式转换

wipe 库存 `"GRADE A"`(全大写),Cyclelution 需要 `"Grade A"`。
做一张显式映射表(不要用通用的大小写转换,避免出现 "Grade a" 之类):
```
GRADE A → Grade A    GRADE C → Grade C
GRADE B → Grade B    GRADE D → Grade D
```
空值或表外值 → 硬校验不过,进异常清单(不猜)。

### 4.5 Weight 与 Color — 按 Storage Type 查表

两张表都放 YAML 配置,键为归一化后的 Storage Type:

```yaml
weight_by_type:            # 单位与 laptop/GPU 一致(lbs)
  "M.2 SSD": 0.1
  "M.2 SSD NVME": 0.1
  "2.5\" SSD": 0.2
  "2.5\" HDD": 0.8        # 估计值(经验值),日后可用实物称重校准
  "3.5\" HDD": 1.4        # 估计值(经验值),日后可用实物称重校准

color_by_type:
  "M.2 SSD": Green
  "M.2 SSD NVME": Green
  "2.5\" SSD": Silver
  "2.5\" HDD": Silver
  "3.5\" HDD": Silver
```
HDD 的重量为估计值(0.8~1.4 lbs 区间的经验值),用户已确认按此填写,日后可实物称重校准。
查不到对应类型 → 进异常清单(说明出现了表中未覆盖的新类型,需补配置)。

## 5. 页面接入(与 GPU 模块保持一致)

- CearTrack 现有 Cyclelution Export 模块的 production 选项**目前只有 laptop / GPU**,
  需将 **wipe(T - Hard Drive)** 加入/取消注释,与前两者同一套页面框架。
- 入口链接形式与 GPU 一致:
  `/cyclelution/?production=T-Hard%20Drive`
  (production 参数命名规则与现有 `T-Video Card` 保持一致的风格)
- 页面功能沿用: Ready 队列(可勾选)、生成导出文件、已导出(synced)视图、异常清单、
  **新增 NO_GRADE 筛选/视图**(展示因无 grade 而未导出的记录,与异常清单分开)。
- 权限与审计沿用 TASK_auth_audit.md 的机制: 模块权限勾选中需支持 wipe 模块;
  导出动作记审计日志(action=export_xlsx, module=wipe, serials=本批 drive_sn 列表)。

## 6. 验收标准

- 用截图那条真实记录(drive_sn=20342A148AEE, MICRON, 1TB, M.2 SSD NVME, Grade A)导出,
  结果与截图逐字一致: ProductName="T - Hard Drive"、Manufacturer=MICRON、Model=2300、
  Storage Size="1 TB"、Storage Type="M.2 SSD NVME"、Grade="Grade A"、Weight=0.1、
  Color=Green、Data Sanitization="Pass"、Condition="C4 - Used Good"、
  Disposition="03 Tested"、Inventory Location="Testing Area"、Next Process="Commodity Storage"。
- `result=FAILED` 的盘不可导出(硬校验)。
- grade 为空的记录(如 Seagate ST1000LM035、LITEON CV8-CE256-11 这类 source=eps 的记录)
  不出现在 Ready 队列,标 NO_GRADE,**且不出现在异常清单**。
- 有 grade 的非 M.2 记录(如某块带 GRADE 的 2.5" SSD)**能正常导出**,
  Weight/Color 按其 Storage Type 从表中取值。
- 同一 drive_sn 有多条擦除记录时,取 wipe_datetime 最新的一条。
- 导出后置 synced,不可重复导出。
- Model 转换在 20 条以上真实记录上抽验无误删(附输出清单供人工核对)。
- 只改配置与 wipe 适配层,**未复制流程层代码**(状态机/导出引擎/页面框架仍是同一套)。

## 7. 实现时注意

- 截图中 R2 Category 栏显示为空(Please Select),但按规则应填
  `Harvested/removed components of electronics`。若导入时该值被 Cyclelution 拒绝,
  说明该 production 的值域不含此项,需回报并改为留空。
- Bus ID 为固定常量,所有导出记录共享同一值(已确认为预期行为)。
