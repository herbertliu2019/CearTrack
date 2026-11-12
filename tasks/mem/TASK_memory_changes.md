# TASK — Memory 模块变更清单（增量）

> **⚠️ 页面已开发完成并在运行。这是一份变更清单，不是重建说明。**
>
> 只改下面列出的点。**没列到的一律不动** —— 不重构、不改文件结构、不调整未提及的样式与逻辑。
> 每条都写了「现状 → 目标」，照着改即可。
>
> 背景与完整设计见 `TASK_memory_module.md`，但那份文档是**从零设计**的写法，
> **不要照它重建已有页面**。它现在只有两个用途：① 查设计理由 ② §9 Packages（尚未实现，见本文末尾）。

目标页面：`/mem/` · 版本：changes-v1 · 日期：2026-09-25

---

## A. KPI 卡片口径（必改）

### A1 · 第 1 张卡

- **现状**：`THIS WEEK TESTS` = 5（测试次数）
- **目标**：`DIMMS TESTED` = 本周测试的**不重复内存条数**

```sql
SELECT COUNT(DISTINCT module_sn) FROM mem_module_tests
WHERE test_date BETWEEN ? AND ?
```

理由：内存的业务单位是**条**，不是次。一次测 8 条，"5 次测试"对业务没意义。

### A2 · 第 5 张卡

- **现状**：`ALL TIME` = 36
- **目标**：`TOTAL DIMMS` = 台账总条数，副标题 `all time`

```sql
SELECT COUNT(*) FROM mem_modules
```

**这句 SQL 必须与 DIMMS Tab 上的计数完全相同**（同一个函数，不要各写一遍）。
截图里 `36 ALL TIME` 与 `DIMMS (28)` 不一致，就是因为一个在数测试记录、一个在数内存条。

### A3 · 其余三张卡

`PASSED` / `WARN·FAIL` / `TOTAL CAPACITY` 的单位统一为**条**，都用 `COUNT(DISTINCT module_sn)`，不要用测试记录数。

### A4 · 自查

改完后这两组数必须自洽，不自洽就是还有一处在数记录数：

| 必须相等 | |
|---|---|
| `TOTAL DIMMS` | `DIMMS` Tab 的计数 |
| `DIMMS TESTED` | `PASSED + WARN + FAIL + SUSPECT`（本周） |

---

## B. 删除 TOP 15 PART NUMBERS widget（必改）

- **现状**：BY CAPACITY / BY TYPE / BY VENDOR 下面有一整行 `TOP 15 PART NUMBERS` 横条图
- **目标**：**整块删除**，DAILY VOLUME 往上补位

理由：料号（`M386A8K40BM1-CRC`）对看板读者没有意义，它是查具体某条内存时才用的信息，属于表格列不属于统计图。

**不要用别的 widget 填补这个位置**，空出来即可。

---

## C. 日期范围的作用域（必改）

页面上有两个日期控件，目前作用域混在一起，需要**解耦**。

### C1 · 顶部 `Week / Month / Custom`

- **目标作用域**：5 张 KPI 卡、三个分布 widget、DAILY VOLUME、DAILY BREAKDOWN、**REPORTS Tab**
- **不得影响** DIMMS Tab 与 PACKAGES Tab

### C2 · DIMMS Tab 内的日期筛选器

- **现状**：`Date: This Week`
- **目标**：`Last Tested: All time`（默认 All time），选项 `All time / This Week / This Month / Custom`
- **独立于顶部控件**，切换顶部 Week/Month/Custom 时这个筛选器不跟着变

理由：DIMMS 是**库存台账**不是统计。绑上日期范围会废掉它的两个核心用途：
「这条内存测过没有？」（可能是半年前测的）、「有多少 PASS 可打包？」（打包从全部历史里挑，一盘 42 条必然跨多周）。

### C3 · REPORTS Tab

- **目标**：跟随顶部范围。范围外的报告**不预加载**，只显示计数 + 搜索框。

### C4 · 列表底部

- **目标**：`Showing 1–50 of 3,418`，与 `/cpu/` 页一致。DIMMS Tab 底部再加一句浅色说明：
  `not affected by the Week/Month range above — this is the full inventory`

---

## D. 分页与查询（核查为主，有问题才改）

现在只有 28 条数据，**前端筛选和后端筛选看起来完全一样**，等到几万条才会暴露。请逐条确认 `/mem/api/modules` 的实现：

| # | 要求 | 自查方法 |
|---|------|---------|
| D1 | 分页在 SQL 里（`LIMIT ? OFFSET ?`） | 看接口是否只返回当页数据；返回全量再让前端切就是错的 |
| D2 | 筛选在 SQL 里（`WHERE`） | 改筛选条件时应重新请求接口，不是前端 filter 数组 |
| D3 | 排序在 SQL 里（`ORDER BY`），默认 `last_tested DESC` | 翻到第 2 页时排序应连续 |
| D4 | `current_status` / `ever_fail` / `ever_warn` / `last_tested` / `size_gb` / `vendor` 有索引，且是**物化字段** | `.schema` 看索引；确认不是页面加载时现算 |
| D5 | `COUNT(*)` 单独一句，不是把全量拉回来数长度 | — |

**做到这五条，DIMMS 全量展示不会有性能问题**，页面加载成本恒定为一页 50 行，与库里有 3 千条还是 30 万条无关。**不要为了性能去缩小 DIMMS 的日期范围** —— 那是在用破坏功能换性能。

---

## E. 数字一致性核查（必查）

截图里这两组数对不上，改完 A 之后复查：

| 位置 | 截图值 | 问题 |
|------|--------|------|
| KPI 第 1 张 | `5 THIS WEEK TESTS` | 与 `REPORTS (2)` 对不上 |
| Tab | `REPORTS (2)` | 顶部说本周 5 次测试，这里只有 2 份报告 |
| KPI 第 5 张 | `36 ALL TIME` | 与 `DIMMS (28)` 对不上 |
| Tab | `DIMMS (28)` | |

先查清 `5` 和 `2` 各自是怎么算出来的 —— 很可能是一个用了 `mem_module_tests` 的行数、一个用了 `mem_reports` 的行数，或者两者的日期字段用得不一样（`report_date` vs `test_start`）。

**统计口径统一用 `test_start` 派生的 `test_date`**，不要用 `report_date`（报告生成时间与测试开始时间不同，样本里差了 28 分钟）。

---

## F. 不要动的部分

以下已经做对了，**不要重构**：

- Tab 名 `DIMMS` / `REPORTS` / `PACKAGES`
- 列名 `PART NUMBER`（不要改回 MODEL）
- 四态状态徽章 `PASS` / `WARN` / `FAIL` / `SUSPECT` 及配色
- `⚠` 历史有错标记
- SN 详情面板（测试历史 + 源文件名 + 目录 + 原始日志链接）
- 解析异常区
- BY CAPACITY / BY TYPE / BY VENDOR 三个 widget
- DAILY VOLUME / DAILY BREAKDOWN
- 扫描器、解析器、数据库结构
- 页面全英文

---

## G. 尚未实现 — PACKAGES（另起阶段，不在本次变更内）

PACKAGES Tab 目前是占位。完整设计见 `TASK_memory_module.md` **§9**（状态机、规格锁、成员校验、重量、页面布局、xlsx 字段映射、12 个 API）。

**这一块是全新功能，可以照 §9 从零建**，与本文 A–F 的增量改法不冲突。

建议等 A–F 改完、数字口径核对无误后再开始 —— 打包要从 DIMMS 台账里挑候选，台账的数不准，包就不准。

开工前需要先确认 `TASK_memory_module.md` §13 待确认清单里的第 5–10 条（xlsx 常量、TID 回填方式、速度字段、ProductName 拼写、Grade 档位、单条重量）。

---

## 执行顺序

```
B（删 widget，最简单，先拿个 quick win）
  → A（KPI 口径）
    → E（数字一致性复查，依赖 A）
      → C（日期作用域解耦）
        → D（分页核查，只查不一定改）
          → G（Packages，另起阶段）
```

每步改完在浏览器里确认一遍再进下一步，不要一次性全改。
