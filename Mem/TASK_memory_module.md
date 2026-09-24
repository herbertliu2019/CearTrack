# TASK — CearTrack Memory Test 模块

> 给 Claude Code 的实现任务文档。CearTrack 新增 Memory（内存）模块，采集 MemTest86 导出的 HTML 报告，
> 按内存条（SN）与测试报告两个维度展示，支持 SN 检索并回溯原始日志文件。
> 风格、交互、配色全部对齐现有 `/cpu/` 模块。

版本：v1.0 · 日期：2026-09-22

---

## 0. 已确认的设计决策

| # | 决策点 | 结论 |
|---|--------|------|
| 1 | 日志来源 | 服务器挂载 SharePoint/OneDrive 目录，后台定时扫描新文件自动入库 |
| 2 | 多次测试的状态 | **最新一次为准**，但历史出现过错误的模组单独打 `EVER_ERR` 标记 |
| 3 | ECC Correctable Errors > 0 且整机 PASS | 该模组状态 = **WARN（黄色）**，独立状态，可单独筛选 |
| 4 | 主实体 | **内存条（module SN）** 为核心实体；测试报告（run）是它的历史事件；销售包（package）是 Phase 2 的分组维度 |
| 5 | 采集范围 | 以 `Number of RAM modules` → `Certification` 为主，另加少量报告头部字段（见 §3.3） |
| 6 | Package 粒度 | 一个 package = Cyclelution **一行**，`Qty` = 条数（实物标签实证：`Qty: 42 Unit`） |
| 7 | Grade | **整包由操作员统一指定**，不是每条定级。Grade 是 package 属性，不参与候选过滤 |
| 8 | 包的同质约束 | **硬约束**：容量 + 类型(含 ECC) + 速度 必须完全相同，不符合的候选直接不出现 |
| 9 | DIMM 加入方式 | 在候选列表里筛选后勾选批量加入（唯一方式） |
| 10 | 重量 | 按 YAML 配置的单条重量 × 条数自动算，操作员可手工覆盖，两个值都存库 |
| 11 | 导出后 | package 锁死，前后端都挡；要改只能作废重建，留审计痕迹 |

---

## 1. 背景与目标

### 1.1 现状
- 测试员用 **MemTest86 V11.2 Pro** 测内存，一次插满一台 Supermicro 服务器（本例 8 条 DIMM）同时测。
- 测完导出 HTML 报告，**手工**放到 SharePoint 的日志目录下。
- 目前没有任何汇总、检索、统计手段；查一条内存测没测过要翻文件。

### 1.2 目标
1. 自动采集 SharePoint 目录里的 MemTest86 HTML 报告，解析入库。
2. 页面按内存条列出 SN、容量规格、厂商型号、测试结果、最近测试时间。
3. **按 SN 检索**：输入 SN → 查到它的每一次测试记录，包括：测试时间、结果、所在 DIMM 槽位、**源日志文件名与所在目录**、可直接查看/下载原始 HTML。
4. 仪表盘统计（周/月/自定义），风格与 `/cpu/` 一致。
5. 为 Phase 2「打包（Package）→ Cyclelution 导出」预留数据结构。

### 1.3 分期
- **Phase 1–4（本文档 §1–§8、§10）**：采集、解析、DIMM 台账、SN 检索、仪表盘
- **Phase 5（§9）**：Package 打包 + Cyclelution xlsx 导出。设计已定稿，实现放在台账跑通之后

> ⚠️ 早期草稿曾写「内存暂不定级」，**这是错的**。实物 Cyclelution 标签上明确有 `Grade D`。
> 内存有 Grade，且由操作员按包指定 —— 见 §9。

---

## 2. 关键事实（已从样本日志验证，实现时必须遵守）

样本文件位置：`…\Desktop\script\claude_code\Mem\test_log\`
- `3 10 2025-74E07175-MemTest86-Report-20250314-142914_979757.html`（含 1 个 ECC 可纠正错误）
- `3 10 2025-74E07175-MemTest86-Report-20250314-151344_161697.html`（无错误）

### 2.1 ⚠️ 文件编码是 UTF-16 LE + BOM
不是 UTF-8。直接 `open(path)` 会得到字符间夹空字节的乱码。

```python
raw = open(path, 'rb').read()
if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
    text = raw.decode('utf-16')
else:
    text = raw.decode('utf-8', errors='replace')   # 兼容将来可能变化的导出设置
```
解析器必须**先嗅探 BOM**，不能硬编码 utf-16。

### 2.2 一份报告 = 一次测试 = N 条内存
两份样本是**同一台机器同一天测的两次**（14:29:14 与 15:13:44），8 条 SN 完全相同。
→ 同一条内存必然有多条测试记录，**主键必须是 `(module_sn, test_start)`**，不能只用 SN。

### 2.3 文件名不能当标识符
`3 10 2025-74E07175-MemTest86-Report-20250314-142914_979757.html`

结构 ≈ `<手工日期前缀> - <DIMM A1 的 SN> - MemTest86-Report - <YYYYMMDD> - <HHMMSS> _ <随机数>.html`

中间那段 `74E07175` 只是第一条内存的 SN，**不是批次号，不唯一**。
→ 文件名只作为**溯源信息**存库展示，绝不用作主键。
→ 报告唯一性用 `file_sha256` 判重；报告业务主键用 `report_uid = sha1(system_sn + '|' + test_start)`。

### 2.4 SPD 区块与 DIMM 区块的规格不一致
同一条内存：
- SPD 区块写 `64GB DDR4 **4Rx4** ECC PC4-19200`
- DIMM 区块写 `64GB DDR4 **4Rx8** ECC PC4-19200`

**以 DIMM 区块为准**（用户指定的采集范围内）。SPD 区块只用于取 `Channel/Slot`。

### 2.5 错误行自带 SN —— 可以精确定位到具体内存条
```
2025-03-14 14:46:32 - [ECC Errors] Test: 5, (Channel,Slot,Rank,Bank,Row,Col): (6,0,N/A,N/A,N/A,N/A), ECC Corrected: Yes, Syndrome: 0000, Channel-Slot: 6-0 (S/N: 35BA48C9)
```
→ 错误可归属到 `35BA48C9` 这一条。其余 7 条不受影响。
→ 所以**每条内存有独立状态**，不能简单继承整机 `Result`。

### 2.6 ⚠️ 目前没有真正 FAIL 的样本
两份样本的 `Result` 都是 **PASS**。所谓"有错误的那份"只是 `ECC Correctable Errors = 1`。
**真正 FAIL（uncorrectable / 普通 memory error）的日志行格式未知。**

实现要求：
- 错误行解析必须**宽容**：正则不匹配时，**不抛异常**，把整行原文存进 `mem_errors.raw_line`，`parse_ok = 0`，并在页面「解析异常」区域列出。
- 提供配置项 `mem/error_patterns.yaml`，错误行正则可外部追加，拿到真实 FAIL 日志后不改代码即可扩展。
- 在 UI 明确显示「本报告有 N 行错误未能解析」，避免静默丢数据。

---

## 3. 数据解析规范

### 3.1 采集主区间
从文本流中定位 `Number of RAM modules` 行，采集至 `Certification` 行为止（不含）。
区间内包含三个子块：**DIMM 列表** → **Result summary** → **Test 表 + Last 10 Errors**。

推荐用 BeautifulSoup（`lxml` parser）解析 DOM 而非纯文本正则；表格结构稳定，标签解析比行匹配更抗排版变化。若 DOM 解析失败则降级为文本行解析。

### 3.2 DIMM 区块

```
DIMM A1            64GB DDR4 4Rx8 ECC PC4-19200
Vendor Part Info   Samsung / M386A8K40BM1-CRC / 74E07175
SMBIOS Profile     2400MT/s
```

| 字段 | 解析规则 | 示例值 |
|------|----------|--------|
| `dimm_slot` | `DIMM\s+(\S+)` | `A1` |
| `size_gb` | 规格串第 1 段，去 `GB`，转 int | `64` |
| `mem_type` | 第 2 段 | `DDR4` |
| `rank_org` | 匹配 `\d+Rx\d+` | `4Rx8` |
| `is_ecc` | 规格串含 `ECC` → 1 | `1` |
| `pc_class` | 匹配 `PC\d+-\d+` | `PC4-19200` |
| `spec_raw` | 整行原文（保底） | `64GB DDR4 4Rx8 ECC PC4-19200` |
| `vendor` | Vendor Part Info 按 ` / ` 切分第 1 段 | `Samsung` |
| `part_number` | 第 2 段（= 页面显示的 **PART NUMBER** 列） | `M386A8K40BM1-CRC` |
| `module_sn` | 第 3 段，**strip + 大写** | `74E07175` |
| `smbios_profile` | SMBIOS Profile 行 | `2400MT/s` |

注意：
- `Vendor Part Info` 在 SPD 区块会多出第 4 段 `Channel: 0 Slot: 0`；DIMM 区块只有 3 段。按 ` / ` 切分后**取前 3 段**，多余段忽略。
- 若任一关键段缺失（尤其 `module_sn` 为空或为 `N/A`），该模组标 `parse_ok=0`，进入「解析异常」列表，**不进主列表**。

### 3.3 报告级字段

主区间内：

| 字段 | 来源 |
|------|------|
| `slots_count` | `Number of RAM slots` |
| `modules_count` | `Number of RAM modules` |
| `test_start` | `Test Start Time` → `2025-03-14 14:29:14` |
| `elapsed` | `Elapsed Time` → `0:22:22`，同时存 `elapsed_sec` 便于统计 |
| `mem_range` | `Memory Range Tested` |
| `mem_size_mb` | 从 `Memory Range Tested` 括号内提取 `526336MB` |
| `cpu_sel_mode` | `CPU Selection Mode` |
| `cpu_temp_raw` | `CPU Temperature Min/Max/Ave` → `43C/52C/47C`，另拆 `cpu_temp_min/max/avg` int |
| `mem_speed_low` / `mem_speed_high` | `Lowest/Highest memory speed`（可能是 `N/A`） |
| `ecc_polling` | `ECC Polling` |
| `tests_completed` | `# Tests Completed` → 存原串 + `tests_completed_pct` |
| `tests_passed` | `# Tests Passed` |
| `ecc_ce` | `ECC Correctable Errors`（缺失时 = 0） |
| `ecc_ue` | `ECC Uncorrectable Errors`（缺失时 = 0） |

⚠️ 注意：**无错误的报告里根本没有 `ECC Correctable Errors` / `ECC Uncorrectable Errors` 两行**，也没有 `Last 10 Errors` 块。解析必须容忍字段缺失，缺失按 0 / 空处理，不报错。

**额外采集报告头部（在主区间之外，但强烈建议采）**——用于回答"这是哪一台机器的哪一次测试"：

| 字段 | 来源 | 理由 |
|------|------|------|
| `report_date` | 顶部 `Report Date` | 报告生成时间，与 `test_start` 不同 |
| `overall_result` | 顶部 `Result`（PASS/FAIL） | 整机判定，状态计算需要 |
| `generated_by` | `Generated by` → `MemTest86 V11.2 Pro (64-bit)` | 版本变化会影响解析，必须留痕 |
| `system_mfr` / `system_product` / `system_sn` | System Information → System | **唯一标识测试机器**，`report_uid` 依赖它 |
| `baseboard_mfr` / `baseboard_product` / `baseboard_sn` | System Information → Baseboard | 定位测试工位 |
| `cpu_type` | `CPU Type` | 参考 |
| `ram_config` | `RAM Configuration` → `DDR4 ECC 2400MT/s` | 参考 |

SPD 区块单独解析出 `sn → (channel, slot)` 映射表，**仅用于**把错误行的 `Channel-Slot` 回填到 DIMM 槽位（当错误行没带 S/N 时的兜底）。

### 3.4 测试项表

```
Test 2 [Address test, own address]        1/1 (100%)   0
Test 5 [Moving inversions, random pattern] 1/1 (100%)  0
```
→ `mem_tests(report_uid, test_no, test_name, passed_raw, passed_pct, errors)`

### 3.5 错误行

主正则（ECC 型）：
```regex
^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*-\s*\[(?P<etype>[^\]]+)\]\s*Test:\s*(?P<test_no>\d+),\s*\(Channel,Slot,Rank,Bank,Row,Col\):\s*\((?P<csrbrc>[^)]*)\),\s*ECC Corrected:\s*(?P<corrected>Yes|No),\s*Syndrome:\s*(?P<syndrome>\S+),\s*Channel-Slot:\s*(?P<chslot>[\d\-]+)\s*\(S/N:\s*(?P<sn>[^)]+)\)
```

- `csrbrc` 按逗号切成 `channel/slot/rank/bank/row/col`，`N/A` 存 NULL。
- `sn` strip + 大写后与 `mem_modules.module_sn` 关联。
- **不匹配的行**：整行存 `raw_line`，`parse_ok=0`，尝试用 `\(S/N:\s*(\w+)\)` 与 `Channel-Slot:\s*([\d\-]+)` 做二次弱提取，能提到就归属，提不到就挂在报告级。

---

## 4. 模组状态判定（核心逻辑）

### 4.1 单次测试内某条内存的状态 `module_status`

按优先级从高到低：

| 状态 | 条件 | 颜色 |
|------|------|------|
| `FAIL` | 该 SN 命中任一 **非 ECC-corrected** 错误（`ECC Corrected: No`，或 uncorrectable，或普通 memory error） | 红 `var(--fail)` |
| `SUSPECT` | 报告 `overall_result = FAIL`，但该报告的错误行**无法归属到任何具体 SN** → 该报告**全部**模组标 SUSPECT | 橙 `#e07b3a` |
| `WARN` | 该 SN 命中 `ECC Corrected: Yes` 的错误 | 黄 `var(--warn)` |
| `PASS` | 以上都不满足，且报告 `overall_result = PASS` | 绿 `var(--pass)` |

补充规则：
- **报告有 `ecc_ce > 0` 但无一条错误行能归属到 SN**：不把 8 条全标 WARN（会污染数据）。改为：模组状态保持 `PASS`，但报告打 `has_unattributed_errors = 1`，该报告下所有模组详情页顶部显示提示条「本次测试存在 N 个未能归属到具体模组的 ECC 错误」。
- `SUSPECT` 是必需的第四态：FAIL 报告若错误无法定位，8 条都可疑，绝不能当 PASS 放走。

### 4.2 跨测试的模组汇总状态（列表页显示的状态）

按已确认决策：**最新为准 + 历史标记**。

```
current_status  = 该 SN 最新一次测试（test_start 最大）的 module_status
ever_fail       = 历史上出现过 FAIL 或 SUSPECT      → 1
ever_warn       = 历史上出现过 WARN                  → 1
test_count      = 该 SN 的测试次数
```

列表展示：状态徽章显示 `current_status`；若 `ever_fail` 或 `ever_warn` 为 1 且 `current_status = PASS`，徽章右侧加一个小三角警示图标 `⚠`，hover 提示「历史第 N 次测试出现过 WARN/FAIL」，并可在筛选器里单独筛「历史有错」。

这三个字段必须是**物化的 DB 字段**，在入库/Rescan 时更新，**绝不在页面加载时实时计算**（与 export 页 refactor 原则一致）。

---

## 5. 三个粒度的关系

```
Package（销售单位，几十条 → Cyclelution 一行）   ← Phase 5，由打包环节决定，可跨多次测试、多台机器
   └── DIMM（内存条 SN）                          ← 核心实体
          └── Test Run（一份 log，8 条一起）       ← 历史事件
```

**页面用三个 Tab 承载三个粒度**（与 export 页「工作队列 vs 归档」原则一致）：

| Tab | 内容 | 是否预加载 |
|-----|------|-----------|
| **DIMMS**（默认） | 一行 = 一条内存 SN，显示汇总状态。这是「有多少条内存、什么状态」的唯一答案 | 预加载，分页 |
| **REPORTS** | 一行 = 一份测试报告，显示机器 SN、测试时间、条数、结果分布。展开看该次 8 条明细 | 预加载最近 N 天，更早只给计数 + 搜索 |
| **PACKAGES** | 一行 = 一个销售包。Phase 5，完整设计见 §9 | 预加载 DRAFT/READY，EXPORTED 只给计数 + 搜索 |

Phase 1–4 阶段 PACKAGES Tab 显示占位卡片 + 可打包（PASS 且未入包）统计。

---

## 6. 数据库设计（SQLite）

文件：`data/mem/mem_index.db`（与 `data/wipe/wipe_index.db` 同级同风格）

```sql
-- 测试报告
CREATE TABLE mem_reports (
  report_uid        TEXT PRIMARY KEY,         -- sha1(system_sn|test_start)
  file_sha256       TEXT NOT NULL UNIQUE,     -- 文件内容哈希，用于判重
  source_dir        TEXT NOT NULL,            -- 相对扫描根的目录，如 "3 10 2025"
  source_file       TEXT NOT NULL,            -- 文件名
  source_full_path  TEXT NOT NULL,            -- 完整路径（挂载点视角），展示用
  archived_path     TEXT,                     -- 本地归档副本路径
  file_mtime        TEXT,
  imported_at       TEXT NOT NULL,

  report_date       TEXT,
  generated_by      TEXT,
  overall_result    TEXT,                     -- PASS / FAIL
  system_mfr        TEXT,
  system_product    TEXT,
  system_sn         TEXT,
  baseboard_mfr     TEXT,
  baseboard_product TEXT,
  baseboard_sn      TEXT,
  cpu_type          TEXT,
  ram_config        TEXT,

  slots_count       INTEGER,
  modules_count     INTEGER,
  test_start        TEXT,                     -- "YYYY-MM-DD HH:MM:SS"
  test_date         TEXT,                     -- "YYYY-MM-DD"，索引用
  elapsed           TEXT,
  elapsed_sec       INTEGER,
  mem_range         TEXT,
  mem_size_mb       INTEGER,
  cpu_sel_mode      TEXT,
  cpu_temp_min      INTEGER,
  cpu_temp_max      INTEGER,
  cpu_temp_avg      INTEGER,
  mem_speed_low     TEXT,
  mem_speed_high    TEXT,
  ecc_polling       TEXT,
  tests_completed   TEXT,
  tests_passed      TEXT,
  ecc_ce            INTEGER DEFAULT 0,
  ecc_ue            INTEGER DEFAULT 0,

  has_unattributed_errors INTEGER DEFAULT 0,
  unparsed_error_lines    INTEGER DEFAULT 0,
  parse_ok          INTEGER DEFAULT 1,
  parse_note        TEXT
);
CREATE INDEX idx_rep_date   ON mem_reports(test_date);
CREATE INDEX idx_rep_sysn   ON mem_reports(system_sn);

-- 单次测试中的单条内存
CREATE TABLE mem_module_tests (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  report_uid     TEXT NOT NULL REFERENCES mem_reports(report_uid) ON DELETE CASCADE,
  module_sn      TEXT NOT NULL,               -- 已 strip + upper
  dimm_slot      TEXT,                        -- A1 / B1 ...
  channel        INTEGER,                     -- 来自 SPD 映射
  spd_slot       INTEGER,
  size_gb        INTEGER,
  mem_type       TEXT,                        -- DDR3 / DDR4 / DDR5
  rank_org       TEXT,                        -- 4Rx8
  is_ecc         INTEGER,
  pc_class       TEXT,                        -- PC4-19200
  spec_raw       TEXT,
  vendor         TEXT,
  part_number    TEXT,
  smbios_profile TEXT,
  test_start     TEXT NOT NULL,               -- 冗余自 report，查询免 join
  test_date      TEXT NOT NULL,
  module_status  TEXT NOT NULL,               -- PASS / WARN / FAIL / SUSPECT
  err_total      INTEGER DEFAULT 0,
  err_ecc_ce     INTEGER DEFAULT 0,
  err_ecc_ue     INTEGER DEFAULT 0,
  parse_ok       INTEGER DEFAULT 1,
  UNIQUE(report_uid, module_sn, dimm_slot)
);
CREATE INDEX idx_mt_sn     ON mem_module_tests(module_sn);
CREATE INDEX idx_mt_date   ON mem_module_tests(test_date);
CREATE INDEX idx_mt_status ON mem_module_tests(module_status);

-- 内存条汇总（物化，入库/Rescan 时更新，页面不实时算）
CREATE TABLE mem_modules (
  module_sn        TEXT PRIMARY KEY,
  vendor           TEXT,
  part_number      TEXT,
  size_gb          INTEGER,
  mem_type         TEXT,
  rank_org         TEXT,
  is_ecc           INTEGER,
  pc_class         TEXT,
  smbios_profile   TEXT,
  first_tested_at  TEXT,
  last_tested_at   TEXT,
  last_report_uid  TEXT,
  last_dimm_slot   TEXT,
  test_count       INTEGER DEFAULT 0,
  current_status   TEXT,                      -- PASS / WARN / FAIL / SUSPECT
  ever_fail        INTEGER DEFAULT 0,
  ever_warn        INTEGER DEFAULT 0,
  package_id       INTEGER,                   -- Phase 2 预留
  note             TEXT
);
CREATE INDEX idx_mod_status ON mem_modules(current_status);
CREATE INDEX idx_mod_last   ON mem_modules(last_tested_at);
CREATE INDEX idx_mod_vendor ON mem_modules(vendor);
CREATE INDEX idx_mod_size   ON mem_modules(size_gb);

-- 测试项
CREATE TABLE mem_tests (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  report_uid  TEXT NOT NULL REFERENCES mem_reports(report_uid) ON DELETE CASCADE,
  test_no     INTEGER,
  test_name   TEXT,
  passed_raw  TEXT,
  passed_pct  INTEGER,
  errors      INTEGER
);

-- 错误明细
CREATE TABLE mem_errors (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  report_uid     TEXT NOT NULL REFERENCES mem_reports(report_uid) ON DELETE CASCADE,
  err_time       TEXT,
  err_type       TEXT,                        -- "ECC Errors" 等
  test_no        INTEGER,
  channel        INTEGER, slot INTEGER, rank INTEGER,
  bank           INTEGER, row INTEGER, col INTEGER,
  ecc_corrected  INTEGER,                     -- 1=Yes 0=No NULL=未知
  syndrome       TEXT,
  channel_slot   TEXT,
  module_sn      TEXT,                        -- 归属到的内存 SN，可为 NULL
  raw_line       TEXT NOT NULL,
  parse_ok       INTEGER DEFAULT 1
);
CREATE INDEX idx_err_sn  ON mem_errors(module_sn);
CREATE INDEX idx_err_rep ON mem_errors(report_uid);

-- Package（Phase 5，完整定义见 §9）
CREATE TABLE mem_packages (
  package_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  package_no     TEXT UNIQUE NOT NULL,        -- MEM-YYYYMMDD-NNN
  status         TEXT NOT NULL,               -- DRAFT / READY / EXPORTED / VOID
  -- 规格锁：第一条成员加入时写入，有成员时不可改
  spec_size_gb   INTEGER,
  spec_mem_type  TEXT,
  spec_is_ecc    INTEGER,
  spec_speed     TEXT,                        -- smbios_profile，如 2400MT/s
  -- 操作员指定
  grade          TEXT,                        -- Grade A/B/C/D
  data_sanitization TEXT DEFAULT 'ND-No Data',
  location       TEXT DEFAULT 'Testing Area',
  -- 自动汇总
  qty            INTEGER DEFAULT 0,
  weight_calc_lb REAL,                        -- 配置算出来的
  weight_final_lb REAL,                       -- 实际写进 xlsx 的（默认 = calc）
  weight_overridden INTEGER DEFAULT 0,
  -- 生命周期
  created_at     TEXT, created_by  TEXT,
  sealed_at      TEXT, sealed_by   TEXT,      -- Mark Ready
  exported_at    TEXT, exported_by TEXT,
  export_batch   TEXT,                        -- 关联 batches.db
  cyclelution_tid TEXT,                       -- 导出后回填，如 TI2601048-000034
  voided_at      TEXT, voided_by  TEXT, void_reason TEXT,
  note           TEXT
);
CREATE INDEX idx_pkg_status ON mem_packages(status);
CREATE INDEX idx_pkg_tid    ON mem_packages(cyclelution_tid);

-- 包成员（一条 DIMM 同时只能在一个未作废的包里）
CREATE TABLE mem_package_members (
  package_id  INTEGER NOT NULL REFERENCES mem_packages(package_id),
  module_sn   TEXT NOT NULL,
  added_at    TEXT NOT NULL,
  added_by    TEXT,
  PRIMARY KEY (package_id, module_sn)
);
CREATE UNIQUE INDEX idx_pm_sn_active ON mem_package_members(module_sn);
-- ↑ 全局唯一：移除成员时删行，作废包时删该包全部行，把 DIMM 释放回候选池

-- 审计（只增不改不删）
CREATE TABLE mem_package_events (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  package_id INTEGER NOT NULL,
  ts         TEXT NOT NULL,
  actor      TEXT,
  action     TEXT NOT NULL,   -- CREATE / ADD / REMOVE / ATTR_CHANGE / SEAL / UNSEAL / EXPORT / VOID
  detail     TEXT             -- JSON：涉及的 SN 列表、字段旧值新值等
);
CREATE INDEX idx_pe_pkg ON mem_package_events(package_id);
```

### 幂等与重扫
- 入库前先查 `file_sha256`，命中则跳过（**文件被重命名/移动也不重复入库**，但要更新 `source_dir/source_file/source_full_path`）。
- 同一 `report_uid` 但 `file_sha256` 不同（如报告被重新导出）→ 覆盖 report 及其子表，记 `parse_note`。
- Rescan 后**必须重算** `mem_modules` 的 `current_status / ever_fail / ever_warn / test_count / last_*`。

---

## 7. 采集与配置

### 7.1 挂载
SharePoint/OneDrive 目录通过 `rclone mount`（推荐）或 `davfs2` 挂到服务器，例如 `/mnt/sp_memtest/`。
挂载本身由运维配置，**不在代码范围**，但代码必须：
- 启动与每次扫描前检查挂载点可读；不可读时**不清空任何数据**，只记一条 `scan_error` 并在页面顶部显示红色横幅「日志目录不可访问，数据为最后一次成功扫描结果（时间：…）」。
- 绝不因为挂载掉线就把记录判为消失。

### 7.2 配置文件 `config/mem.yaml`

```yaml
mem:
  scan_root: /mnt/sp_memtest/MemTest_Logs
  go_live_date: "2025-01-01"          # 永久下限，早于此日期的报告不入库
  scan_interval_sec: 900              # 15 分钟
  file_globs: ["*.html", "*.htm"]
  exclude_dir_patterns: ["*_files"]   # MemTest86 导出的资源目录，必须排除
  archive_raw: true                   # 把原始 html 复制一份到本地，防 SharePoint 挪走
  archive_root: /opt/monitorcenter/data/mem/raw
  max_file_mb: 10

  # Phase 2 预留：单条重量（lb），用于 package 重量计算
  weight_by_size_gb:
    8:  0.05
    16: 0.06
    32: 0.08
    64: 0.10
    default: 0.08
```

`exclude_dir_patterns` 必须生效 —— 样本目录里就有一个 `…_161697_files/` 子目录（内含 `mt86.png`），扫进去会产生噪音。

### 7.3 扫描逻辑
1. 递归遍历 `scan_root`，按 `file_globs` 收集，排除 `exclude_dir_patterns` 命中的目录。
2. 按 `file_mtime` 与已入库集合做差集，只解析新增/变更文件。
3. 解析 → 校验 → 入库 → 归档原始文件。
4. `test_start < go_live_date` 的报告写入 `mem_reports` 但标 `excluded`，不进 modules 汇总（保留痕迹，与 export 页原则一致）。
5. 结果写 `scan_log`：本次新增 N 份、跳过 M 份、失败 K 份（含文件名与原因）。

---

## 8. 页面设计

路由前缀 `/mem/`，导航栏在 `CPU` 与 `GPU` 之间插入 **`Memory`**。
所有配色、卡片、进度条、表格样式**直接复用 `/cpu/` 的 CSS 变量与组件类**，不引入新框架。Alpine.js v3。

**⚠️ 页面 UI 文案全部使用英文**（表头、按钮、筛选器、状态徽章、提示语、空状态、错误提示），与 `/cpu/`、`/laptop/` 等现有模块保持一致。代码注释与本文档可用中文。

### 8.1 页头
```
[图标] MEMORY
       MemTest86 Module Test Dashboard
```

### 8.2 搜索条（全宽，与 CPU 页一致）
```
[ Search by module SN, part number, or report file name (partial match)…  ] [Search]
                              Next in: 0s · Last scan: 2026-09-22 10:20  [⟳ SCAN MEMORY TEST LOGS]
```
搜索行为：
- 输入内容同时匹配 `module_sn`（前缀+包含）、`part_number`、`source_file`、`system_sn`
- 命中单个 SN → 直接展开该 SN 的**历史详情面板**（§8.7）
- 命中多个 → 结果表格，点击进详情

### 8.3 时间范围切换
`Week` / `Month` / `Custom`，与 CPU 页完全一致。

### 8.4 KPI 卡片（5 张，横排）

| 卡片 | 值 | 副标题 |
|------|-----|--------|
| THIS WEEK DIMMS | 本周测试的内存条数 | 日期区间 |
| PASSED | 绿色数字 | — |
| WARN / FAIL | 黄 / 红两个数字并排 | — |
| TOTAL CAPACITY | 本周测试总容量（TB/GB 自适应） | — |
| ALL TIME | 全部时间累计模组测试次数 | — |

### 8.5 分布 Widget（三列，<1200px 折成单列，样式同 CPU 页的 BY SERIES）

- **BY CAPACITY** — 8GB / 16GB / 32GB / 64GB / 128GB
- **BY TYPE** — DDR3 / DDR4 / DDR5（含 ECC 标记）
- **BY VENDOR** — Samsung / SK Hynix / Micron / Kingston / …

下方全宽：
- **TOP 15 PART NUMBERS** — 横向条形图，同 CPU 页 TOP 15 PROCESSOR MODELS。取 MemTest86 `Vendor Part Info` 的第 2 段（厂商料号，如 `M386A8K40BM1-CRC`）
- **DAILY VOLUME** — 堆叠柱状图，分段 Pass / Warn / Fail（比 CPU 页多一个 Warn 段，用 `var(--warn)`）
- **DAILY BREAKDOWN** 表 — `DATE | REPORTS | DIMMS | PASSED | WARN | FAILED | PASS RATE`，行可展开看当日报告列表

### 8.6 主体三 Tab

#### Tab 1 · DIMMS（默认）
筛选器（英文）：`Status: All/PASS/WARN/FAIL/SUSPECT` · `Ever Errored: All/Yes/No` · `Capacity` · `Type` · `Vendor` · `Date`

| SN | CAPACITY | TYPE | VENDOR | PART NUMBER | SPEED | LAST SLOT | LAST TESTED | TESTS | STATUS |
|----|----------|------|--------|-------------|-------|-----------|-------------|-------|--------|
| 35BA48C9 | 64GB | DDR4 ECC | Samsung | M386A8K40BM1-CRC | 2400MT/s | G1 | 2025-03-14 14:29 | 2 | `WARN` |
| 74E07175 | 64GB | DDR4 ECC | Samsung | M386A8K40BM1-CRC | 2400MT/s | A1 | 2025-03-14 15:13 | 2 | `PASS ⚠` |

- 状态徽章配色：PASS 绿 / WARN 黄 / FAIL 红 / SUSPECT 橙
- `⚠` = `ever_fail` 或 `ever_warn`，hover 提示历史情况
- 点行 → 展开 §8.7 详情面板（就地展开，不跳页）
- 分页，默认 50 行/页

#### Tab 2 · REPORTS
| REPORT DATE | TEST START | SYSTEM | SYSTEM SN | DIMMS | RESULT | ECC CE/UE | ELAPSED | SOURCE FILE |
|---|---|---|---|---|---|---|---|---|
| 2025-03-14 15:13 | 14:29:14 | Supermicro SYS-6018R-MT | S16580317A07443 | 8 | `PASS` | 1 / 0 | 0:22:22 | `3 10 2025-74E07175-…142914_979757.html` |

- 点行展开：该次测试的 8 条模组表 + 测试项表 + 错误明细表
- 源文件名列可 hover 显示完整目录路径，点击下载/新窗口查看归档的原始 HTML（`/mem/raw/<report_uid>`）
- **超出当前时间范围的报告不预加载**，只给计数 + 搜索框（归档 Tab 原则）

#### Tab 3 · PACKAGES
Phase 1–4 显示占位卡片 +「可打包（PASS 且未入包）条数 / 总容量 / 待复测条数」三个统计。
Phase 5 的完整页面设计见 **§9**。

### 8.7 SN 详情面板（本需求的核心）

点任一模组 SN 展开：

```
┌─ 35BA48C9 ─────────────────────────────────── [WARN] ──┐
│ Samsung M386A8K40BM1-CRC · 64GB DDR4 4Rx8 ECC          │
│ PC4-19200 · 2400MT/s · 共 2 次测试                       │
├────────────────────────────────────────────────────────┤
│ TEST HISTORY                                           │
│                                                        │
│ ▸ 2025-03-14 15:13:44   PASS    DIMM G1   0:22:21      │
│     System : Supermicro SYS-6018R-MT (S/N S16580317A07443)
│     File   : 3 10 2025-74E07175-MemTest86-Report-20250314-151344_161697.html
│     Folder : /MemTest_Logs/3 10 2025/
│                                    [查看原始日志] [下载]
│                                                        │
│ ▾ 2025-03-14 14:29:14   WARN    DIMM G1   0:22:22      │
│     System : Supermicro SYS-6018R-MT (S/N S16580317A07443)
│     File   : 3 10 2025-74E07175-MemTest86-Report-20250314-142914_979757.html
│     Folder : /MemTest_Logs/3 10 2025/
│     Errors (1):                                        │
│       14:46:32  [ECC Errors]  Test 5  Ch-Slot 6-0      │
│                 ECC Corrected: Yes  Syndrome: 0000     │
│                                    [查看原始日志] [下载]
└────────────────────────────────────────────────────────┘
```

**必须包含**（这是用户明确要求的）：每一次测试的 **源日志文件名** 与 **所在目录**，且可直接打开原始 HTML。

### 8.8 解析异常区
仪表盘底部（仅当存在异常时显示）红色卡片：
`PARSE ISSUES (N)` —— 列出解析失败的文件名、失败原因、未解析的错误行数，可点开看原文。
这是 §2.6 未知 FAIL 格式的安全网，不能省。

---

## 9. Package 与 Cyclelution 导出（Phase 5）

### 9.1 实物标签实证

现场 Cyclelution 标签（2026-08-21）：

```
T - Memory                            CEAR
Qty: 42 Unit          Wt: 2.40 LB
TID: TI2601048-000034      08/21/2026
[barcode]
Grade D, 32 GB, , ND-No Data, ,
Testing Area,
手写补充: 2400
```

从这张标签得到的硬事实：

1. `ProductName` = **`T - Memory`**（注意 laptop 模块有过 `T - Laptop` / `T - Laptops` 的环境漂移，上线前必须在生产环境核对一次拼写）
2. 一个 package = Cyclelution **一行**，`Qty` = 条数
3. **内存有 Grade**（Grade D）
4. 标签只有**一个** Grade、**一个** Capacity → **包必须同质**
5. 速度（2400）是**手写补上去的** → 标签字段里没有速度，但实际必须区分，否则 2400 与 2666 混包卖不掉。CearTrack 必须把速度纳入同质约束并显示在包上
6. `2.40 LB ÷ 42 = 0.0571 lb/条` → 单条重量配置的基准
7. `TID` 由 Cyclelution 生成，导出后才有

### 9.2 状态机

```
DRAFT ──Mark Ready──> READY ──Export──> EXPORTED（锁死）
  ↑                     │
  └──── Unseal ─────────┘

任意状态 ──Void──> VOID（成员释放回候选池，记审计）
```

| 状态 | 可否编辑 | 说明 |
|------|---------|------|
| `DRAFT` | ✅ 唯一可编辑状态 | 可加/删成员，可改 Grade、重量、备注 |
| `READY` | ❌ | 已封包，进入 `/cyclelution/?production=T-Memory` 的 Ready 队列。可 Unseal 退回 DRAFT |
| `EXPORTED` | ❌ **永久锁死** | 已导出，回填 TID 与批次号。只读 |
| `VOID` | ❌ | 作废。成员被释放，可重新打包。原包留存 |

**锁的实现必须是双层的**：

- 前端：EXPORTED / READY 时编辑控件**隐藏**（不是 disabled —— disabled 按钮会让人以为「点不动是 bug」）
- 后端：API 对 `status != 'DRAFT'` 的包拒绝一切写操作，返回 **409 Conflict** + 明确原因。**不能只靠前端**

要修正已导出的包，唯一路径是 **Void + 新建**，`void_reason` 必填，全程记 `mem_package_events`。

### 9.3 规格锁（同质约束）

包创建时规格字段为空。**第一条成员加入时**，把它的 `size_gb / mem_type / is_ecc / smbios_profile` 写入包的 `spec_*` 字段并锁定。

此后：
- 候选列表**自动按 `spec_*` 过滤**，不符合的条根本不出现 —— 让人无从犯错，比加完再报错好
- 包内成员清空后，`spec_*` 解锁，可重新开始

`grade` **不参与过滤**：它是整包属性，由操作员指定。同规格但成色不同的，操作员建两个包、手工挑选分配 —— CearTrack 看不出成色，不该猜。

### 9.4 加入成员的校验

在候选列表里筛选后勾选批量加入。每条逐一校验，**任一不过就跳过该条并在结果里说明原因**（不要整批失败）：

| 校验 | 失败原因文案 |
|------|-------------|
| `current_status == 'PASS'` | `not PASS (WARN/FAIL/SUSPECT)` |
| 不在任何未作废的包里 | `already in MEM-20260915-002` |
| 规格与 `spec_*` 完全一致 | `spec mismatch: 16GB ≠ 32GB` |
| 目标包 `status == 'DRAFT'` | `package is not editable` |

返回格式：`{added: N, skipped: [{sn, reason}]}`，页面把 skipped 列出来。

> `ever_warn = 1`（历史有过 ECC 错误但当前 PASS）的条**允许加入**，但在候选列表和成员表里保留 `⚠` 标记，由操作员决定。不要替他判死。

### 9.5 重量

```yaml
mem:
  weight_lb_per_unit:            # 单条重量（lb）
    DDR4_RDIMM: 0.057            # 实测基准：2.40 LB / 42 条
    DDR4_UDIMM: 0.045
    DDR3_RDIMM: 0.055
    DDR3_UDIMM: 0.043
    default:    0.055
  weight_round_to: 0.01          # 标签精度 2 位小数
```

- `weight_calc_lb` = 单条重量 × qty，四舍五入到 0.01，**每次成员变动自动重算**
- `weight_final_lb` 默认 = `weight_calc_lb`；操作员可手工覆盖（现场称重），覆盖后置 `weight_overridden = 1`
- 覆盖值**不随成员变动自动刷新** —— 但成员变动后在页面显示提示「重量为手工值，成员已变更，是否重算？」
- 写进 xlsx 的是 `weight_final_lb`

### 9.6 页面布局（左右分栏）

**左栏 · 包列表**，卡片式，顶部 `+ NEW PACKAGE`：

```
┌─ MEM-20260922-003 ────────── DRAFT ─┐
│ 32GB DDR4 ECC · 2400MT/s · Grade D  │
│ 38 units · 2.17 LB · opened 09-22   │
└─────────────────────────────────────┘
┌─ MEM-20260915-002 ─────── EXPORTED ─┐ 🔒
│ 32GB DDR4 ECC · 2400MT/s · Grade D  │
│ 42 units · 2.40 LB                  │
│ TID TI2601048-000034                │
└─────────────────────────────────────┘
```

DRAFT / READY 预加载全部；EXPORTED / VOID 只给计数 + 搜索（归档原则）。

**右栏 · 包详情**，三段：

1. **属性区**（8 格）：Product Name（固定 `T - Memory`）/ Grade（下拉，DRAFT 可改）/ Capacity `locked` / Type `locked` / Speed `locked` / Qty `auto` / Weight `auto·可改` / Data Sanitization
2. **成员表**：`# | SN | PART NUMBER | VENDOR | LAST TESTED | STATUS | ×`，DRAFT 时每行有移除按钮
3. **Add DIMMs 面板**（仅 DRAFT）：顶部一行说明当前锁定的规格与匹配数量，下面是筛选器（Vendor / Part Number / Tested 时间 / SN 过滤）+ 勾选表，底部实时显示「选中 N 条 → 包将变为 X units / Y LB」

**EXPORTED 状态的详情页**额外显示：
- 顶部锁定横幅，说明「已导出，不可编辑；如需修正请作废重建，作废会记入审计日志」
- Cyclelution 区块：TID / 批次号 / 导出时间 / Location，以及 `Download xlsx`、`Audit Log` 两个链接
- 成员表只读，无移除按钮

### 9.7 Cyclelution xlsx 字段映射

| xlsx 列 | 取值 |
|---------|------|
| ProductName | `T - Memory` ← **上线前核对生产环境拼写** |
| Qty | `mem_packages.qty` |
| Weight | `weight_final_lb` |
| Grade | `mem_packages.grade` |
| Capacity | `spec_size_gb` + ` GB`（如 `32 GB`） |
| Data Sanitization | `ND-No Data` |
| Location / Office | `Testing Area` |
| Disposition / Functionality / RTS / TDM / Bus ID / Condition / Color | **待确认**，参照 wipe 模块的常量做法 |
| TID | 不写入，由 Cyclelution 生成后**回填**到 CearTrack |

导出后回填 TID：Cyclelution 导入完生成 TID 并打印标签，CearTrack 这边需要一个回填入口（手工录入或扫标签条码）。**待确认具体方式**。

速度（2400MT/s）在标签字段里没有位置 —— 待确认是否有可用列，否则继续手写，但 CearTrack 里必须存着以保证同质。

### 9.8 与 Cyclelution 导出模块的衔接

沿用 wipe 模块已建立的架构：Memory 作为新的 production 选项加入，入口 `/cyclelution/?production=T-Memory`，同一套页面框架与审计日志。

**区别**：laptop / wipe 是**一条记录一行**，Memory 是**一个包一行**。所以 Memory 进入 Cyclelution 导出队列的是 `mem_packages` 里 `status = 'READY'` 的包，不是单条 DIMM。导出成功后回写 `status = 'EXPORTED'` + `export_batch` + `exported_at`。

---

## 10. API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/mem/` | 页面 |
| GET | `/mem/api/summary?range=week\|month\|custom&from=&to=` | KPI + 各分布 widget + daily volume |
| GET | `/mem/api/modules?status=&ever_err=&size=&type=&vendor=&q=&page=&per_page=` | DIMMS 表 |
| GET | `/mem/api/module/<sn>` | 单条 SN 的完整历史（含每次的 source_file / source_dir / 错误明细） |
| GET | `/mem/api/reports?from=&to=&q=&page=` | REPORTS 表 |
| GET | `/mem/api/report/<report_uid>` | 单份报告详情（模组 + 测试项 + 错误） |
| GET | `/mem/raw/<report_uid>` | 返回归档的原始 HTML（`Content-Type: text/html; charset=utf-16`，或转码为 UTF-8 后返回） |
| POST | `/mem/api/scan` | 手动触发扫描，返回新增/跳过/失败计数 |
| GET | `/mem/api/scan_status` | 上次扫描时间、结果、下次倒计时、挂载点健康状态 |
| GET | `/mem/api/parse_issues` | 解析异常列表 |

**Package API（Phase 5）** —— 所有写接口对 `status != 'DRAFT'` 的包返回 **409**：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/mem/api/packages?status=&q=&page=` | 包列表 |
| GET | `/mem/api/package/<id>` | 包详情 + 成员 |
| POST | `/mem/api/packages` | 新建包（可带初始 grade） |
| PATCH | `/mem/api/package/<id>` | 改 grade / weight / note（仅 DRAFT） |
| GET | `/mem/api/package/<id>/candidates?vendor=&pn=&q=&page=` | 候选 DIMM，**服务端按包的 `spec_*` 过滤**，不靠前端 |
| POST | `/mem/api/package/<id>/members` | 批量加入，body `{sns:[...]}`，返回 `{added, skipped:[{sn,reason}]}` |
| DELETE | `/mem/api/package/<id>/members/<sn>` | 移除单条 |
| POST | `/mem/api/package/<id>/seal` | DRAFT → READY |
| POST | `/mem/api/package/<id>/unseal` | READY → DRAFT |
| POST | `/mem/api/package/<id>/void` | 作废，body `{reason}` 必填 |
| POST | `/mem/api/package/<id>/tid` | 回填 Cyclelution TID |
| GET | `/mem/api/package/<id>/events` | 审计日志 |

所有列表接口必须分页，`per_page` 默认 50、上限 500。

---

## 11. 实施阶段

> 按你的习惯：分阶段执行，每阶段验证后再进下一阶段。

### Phase 1 — 解析器（独立可测，先不碰 Web）
1. 写 `mem/parser.py`：输入 HTML 路径 → 输出结构化 dict。
2. 处理 UTF-16 BOM 嗅探、字段缺失、错误行宽容解析。
3. 写单元测试，用两份样本日志断言：
   - 两份都能解析出 8 条模组，SN 集合一致
   - `142914` 那份：`ecc_ce=1`，`35BA48C9` 状态 = `WARN`，其余 7 条 = `PASS`
   - `151344` 那份：无 `ecc_ce` 字段，8 条全 `PASS`
   - 两份的 `report_uid` 不同（`test_start` 不同）
4. **验证点**：`python -m mem.parser <file>` 打印 JSON，人工核对。

### Phase 2 — 数据库与扫描器
1. 建表脚本 + 迁移。
2. `mem/scanner.py`：遍历、判重、入库、归档、汇总重算。
3. 反复扫同一目录 3 次，断言记录数不变（幂等）。
4. **验证点**：`sqlite3 mem_index.db` 查 `mem_modules`，8 行，状态正确。

### Phase 3 — 页面与 API
1. Flask blueprint `mem_bp`，注册路由，导航加 `Memory`。
2. 先做 DIMMS Tab + SN 详情面板（核心需求），跑通再做统计 widget。
3. 复用 CPU 页模板与 CSS，不新写样式。
4. **验证点**：浏览器搜 `35BA48C9`，能看到两次测试、WARN、文件名、目录、错误明细。

### Phase 4 — 定时扫描与健康检查
1. 后台线程或 systemd timer，按 `scan_interval_sec` 跑。
2. 挂载点健康横幅。
3. 解析异常卡片。

### Phase 5 — Package 与 Cyclelution 导出
设计见 §9，已定稿。建议拆成两步验证：
1. **打包功能**：建包 / 加删成员 / 规格锁 / 状态机 / 锁定 / 审计。**验证点**：试着把 16GB 加进 32GB 的包（候选里应该根本看不到）；试着用 API 直接 PATCH 一个 EXPORTED 包（应返回 409）。
2. **xlsx 导出**：接入 `/cyclelution/?production=T-Memory`，导出后回写状态与批次。**验证点**：导出一个包，字段与 §9.7 表逐项核对，特别是 ProductName 拼写。

---

## 12. 实现红线

1. **不要假设编码是 UTF-8** —— 必须嗅探 BOM。
2. **不要用文件名做主键** —— 文件名里的 SN 只是 DIMM A1 的 SN。
3. **不要在页面加载时实时计算状态** —— `current_status / ever_fail / ever_warn` 必须是 DB 字段，入库/Rescan 时写入。
4. **不要因为字段缺失就抛异常** —— 无错误的报告里根本没有 ECC 计数行和 Last 10 Errors 块。
5. **不要静默丢弃解析不了的错误行** —— 存 `raw_line` + `parse_ok=0`，页面显示。
6. **不要把 FAIL 报告中无法归属的错误当作没事** —— 全部模组标 `SUSPECT`。
7. **不要扫进 `*_files` 资源目录**。
8. **不要在挂载点掉线时清空或改写已有记录**。
9. **归档 Tab 不预加载历史数据** —— 只给计数 + 搜索。
10. 所有可能调整的阈值、路径、映射表走 `config/mem.yaml`，不硬编码。
11. Tab 名用 **`DIMMS`**，不要用 `MODULES` —— CearTrack 内部 "module" 指页面模块（laptop module / GPU module），会混。
12. **Package 的锁必须在后端**。前端隐藏按钮只是体验，API 层对非 DRAFT 包的写操作必须返回 409。
13. **候选过滤必须在服务端做**（按包的 `spec_*`），不要下发全量再让前端筛 —— 前端筛出来的东西可以被绕过。
14. **一条 DIMM 只能在一个包里**，靠 `mem_package_members` 上的唯一索引保证，不要只在应用层判断。
15. **不要自动给 DIMM 定 Grade**。Grade 是整包由操作员指定的。
16. **页面 UI 文案一律英文**，不要中英混排。DB 字段名保留日志原始术语（`part_number`），页面列头用 `PART NUMBER`（与日志原话 `Vendor Part Info` 及 DB 字段 `part_number` 一致）。**不要用 "MODEL"** —— 与 "module" 只差一个字母，同屏会看混。

---

## 13. 待确认

1. ~~Cyclelution 上一个 package 是一行还是 N 行？~~ → **已由实物标签确认：一行，Qty = 条数**
2. SharePoint 日志目录的确切挂载路径与目录层级（样本里是 `3 10 2025/` 这种手写日期文件夹，是否所有日志都按这个规律放？）
3. Memory 模块的 `go_live_date` 定为哪一天？（早于此日期的历史日志是否需要回溯入库）
4. 除 MemTest86 V11.2 Pro 外，是否还有其他版本/其他工具导出的日志需要兼容？
5. **Cyclelution xlsx 的其余常量**：Disposition / Functionality / RTS / TDM / Bus ID / Condition / Color 各填什么？（参照 wipe 模块的做法）
6. **TID 回填方式**：Cyclelution 导出后生成 TID，CearTrack 这边是手工录入、扫标签条码，还是不记录？
7. **速度字段**：Cyclelution 标签上没有速度（现在靠手写 2400）。xlsx 里有没有可用的列能带上速度？
8. **ProductName 拼写**：生产环境确认是 `T - Memory` 还是有别的写法（laptop 有过 `T - Laptop` / `T - Laptops` 的漂移）
9. **Grade 可选值**：内存的 Grade 是 A/B/C/D 四档，还是有别的档位？
10. **单条重量**：`2.40 LB / 42 条 = 0.057 lb` 是配置算的还是实际称的？其他容量/形态（UDIMM、SODIMM、DDR3）的单条重量各是多少？
