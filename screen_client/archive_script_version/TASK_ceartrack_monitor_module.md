# TASK: CearTrack 新增 Monitor 模块

> 配套文档：`TASK_monitor_test.md`（客户端脚本 `monitor_test.sh`）。本 Task 只做 **CearTrack 服务端和页面**。
> 数据格式以 `TASK_monitor_test.md` 第 2.4 节的 JSON 为准。

## 0. 原则：完全参照 laptop 模块

现有的 `http://192.168.30.18/laptop/` 是 UI 和代码结构的**唯一参考**。

动手之前，先通读 laptop 模块的以下部分：

- Blueprint、路由、upload API
- 存储方式（SQLite 表还是 JSON 文件）、数据目录
- 列表页和详情页的模板（HTMX/Alpine 的用法、结果徽章、筛选栏、分页、搜索）
- 鉴权：角色 × 模块权限，upload API 的认证方式
- `audit_log` 的写入点、SN 时间线
- 脚本分发：`version.txt`、`deploy_script.sh`
- 导出功能（如果 laptop 有）

**要求：**

- 能复用的模板、宏（macro）、CSS、JS 一律复用，不要复制一份再改。如果 laptop 里有写死的部分，先抽成公共组件，再让两个模块共用。抽组件时**不能改变 laptop 页面现有的外观和行为**。
- 视觉上要和 laptop 一致：配色、PASS/WARN/FAIL 徽章、表格风格、筛选栏位置、详情页卡片布局都一样。
- 动手前先输出一份「laptop 模块结构 → monitor 对应实现」的对照清单，给 Herbert 确认后再写代码。

---

## 1. 路由

| 路由 | 用途 |
|---|---|
| `POST /monitor/api/upload` | 接收 monitor_test.sh 上传的报告 |
| `GET /monitor/` | 列表页 |
| `GET /monitor/<id>` | 单次测试详情 |
| `GET /monitor/sn/<label_sn>` | 某个 SN 的全部测试历史（也可以直接用详情页里的历史区块） |
| `GET /monitor/export.csv` | 按当前筛选条件导出 |
| `GET /monitor/script`、`/monitor/version.txt` | 脚本分发，机制和 laptop 一致 |

laptop 有的其他功能（排除记录、重新同步、备注等），monitor 也要对应实现。

## 2. 上传 API

- 认证方式和 laptop upload 一样。
- 必填字段：`report_type == "monitor"`、`identity.label_sn`、`test_info.operator_id`、`display.dead_pixel_count`、`overall_result`。缺字段返回 400，并说明缺了哪个。
- **服务端重新判定 overall_result**，规则和脚本一致：
  - FAIL：`dead_pixel_count > 2`、cosmetic FAIL、backlight FAIL、resolution FAIL、任一接口 FAIL、ethernet FAIL
  - WARN：`sn_match != MATCH`、`station_limited`、OSD FAIL、有接口 NOT_TESTED
  - 阈值 `MAX_DEAD_PIXELS = 2` 放进配置文件，不要写死在代码里
  - 如果服务端结果和客户端上报的不一致，保存服务端结果，`result_mismatch=true`，并写日志
- 重复上传的处理：`label_sn + test_time` 相同的报告视为同一份，覆盖或忽略，返回 200，不能生成两条记录。
- 写入 `audit_log`：`monitor.upload`，带上 SN 和 tested_by。
- 原始 JSON 完整保存一份，供审计和以后对接 Cyclelution 使用。

## 3. 数据存储

存储方式和 laptop 一致。如果用 SQLite，建议的表结构如下（嵌套字段存为 JSON 列）：

```
monitor_tests
  id, label_sn (index), test_time (index), operator_id, script_version,
  vendor, vendor_pnp, model, product_code, mfg_year, mfg_week,
  edid_serial_str, sn_match,
  native_resolution, achieved_resolution, achieved_refresh, station_limited,
  size_inch, dead_pixel_count, dead_pixel_check, backlight_check,
  cosmetic_check, defects_json, osd_buttons_check, stand_included,
  ports_json, manual_input_json, result_reasons_json,
  overall_result (index), client_overall_result, result_mismatch,
  raw_json, excluded (bool), created_at
```

同一个 SN 可以有多条测试记录。「最新结果」按 `test_time` 取最大的那条。

## 4. 列表页 `/monitor/`

布局参照 laptop 列表页：顶部是统计卡片，然后是筛选栏，再下面是表格。

**统计卡片**（跟随当前的日期筛选，默认今天）：
- 测试总数、PASS、WARN、FAIL 的数量和占比
- FAIL 原因 Top 3，例如「坏点超标 5」「外观 3」「接口 1」

**筛选栏：**
- 日期范围、结果（PASS/WARN/FAIL）、厂商、Operator
- SN 搜索：同时匹配 label_sn 和 edid_serial
- 「只显示每个 SN 的最新一次」开关，默认打开

**表格列：**

| 列 | 内容 / 展示方式 |
|---|---|
| 测试时间 | 本地时间（America/Los_Angeles） |
| Label SN | 点击进入详情页 |
| 厂商 / 型号 | `LG 27UD58` |
| 尺寸 | `27"` |
| 分辨率 | `3840×2160@60`；`station_limited` 时显示黄色小标「测试机受限」 |
| 坏点 | 数字。0–2 绿色，≥3 红色 |
| 外观 | ✓ / ✗。鼠标悬停显示缺陷类型 |
| 接口 | 每个接口一个小徽章，如 `DP✓ HDMI✓ HDMI✓`，FAIL 红色，NOT_TESTED 灰色 |
| SN 匹配 | MATCH 不显示；MISMATCH 或 EDID_EMPTY 显示黄色图标 |
| Grade | 来自 manual_input |
| Operator | |
| 结果 | PASS/WARN/FAIL 徽章，用 laptop 同款组件 |

分页、排序（默认按时间倒序）、HTMX 局部刷新，都和 laptop 一致。

## 5. 详情页 `/monitor/<id>`

用卡片布局，参照 laptop 详情页：

1. **页头**：Label SN、厂商和型号、大号结果徽章；如果有 FAIL/WARN，下面逐条列出 `result_reasons`。
2. **身份信息**：Label SN、EDID 序号、SN 匹配状态（用颜色区分）、厂商（附 PNP ID）、型号、Product code、生产年月、EDID checksum。
3. **显示测试**：
   - 原生分辨率和实际达到的分辨率对比。`station_limited` 时加说明：「测试机输出口能力不足，非显示器问题」
   - 坏点数：大号数字，后面附「/ 允许 ≤2」
   - 坏点判定、背光判定
   - 已显示过的测试图案列表
4. **接口测试**：表格，列为「类型 / 编号 / 结果 / 测试机 connector」。
5. **外观**：外观判定、缺陷类型（用标签形式展示）、备注、OSD 按键、是否带底座。
6. **Manual Input**：Weight / Grade / Condition / Color / Size / Mark，显示格式和 laptop 一样。
7. **测试信息**：Operator、测试时间、用时、脚本版本、测试机 hostname 和 GPU、网口。
8. **同一 SN 的历史测试**：时间、结果、坏点数、Operator。点击可切换到对应记录。
9. **原始 JSON**：默认折叠，展开后可复制。只有 admin 能看到 `edid_raw_hex`。
10. **审计时间线**：复用 laptop 的 SN 时间线组件。

## 6. CSV 导出

- 按当前筛选条件导出。字段和列表列一致，另加 `defects`、`ports`（字符串，如 `DP:PASS;HDMI1:PASS;HDMI2:NOT_TESTED`）、`result_reasons`。
- 导出操作写入 `audit_log`。

## 7. 权限和导航

- 在角色 × 模块权限里新增 `monitor` 勾选项。viewer 只能看，operator 可以看和导出，admin 拥有全部权限（排除、删除、查看原始 EDID）。
- 顶部导航和首页增加 Monitor 入口，图标和排序位置参照 laptop。

## 8. 开发用的测试数据

写一个 `scripts/seed_monitor_samples.py`，用 upload API 灌入**至少 12 条**样例报告，覆盖以下情况：

- PASS
- 坏点为 2（PASS）和 3（FAIL）
- 外观 FAIL（crack、burn-in）
- 接口 FAIL
- 接口 NOT_TESTED
- `station_limited`
- SN 不一致、EDID 无序号
- 同一个 SN 测 3 次（先 FAIL 后 PASS）
- 客户端上报的 overall_result 被篡改

其中一条使用真实数据：LG 27UD58、SN `906NTZN4G765`、3840×2160、DP + HDMI×2、2019 年产。

用途：在 monitor_test.sh 写好之前，就能先完成页面开发和验收。

## 9. 验收标准

| # | 检查项 |
|---|---|
| 1 | 灌入 seed 数据后，列表页、统计卡片、筛选、搜索、分页都正常 |
| 2 | 列表页和详情页和 laptop 并排对比，视觉风格一致；**laptop 页面没有任何变化**（改动前后各截图对比） |
| 3 | 坏点 3 的记录：列表里显示红色，详情页的 FAIL 原因写明 |
| 4 | 篡改了 overall_result 的报告：以服务端判定为准，`result_mismatch` 有记录 |
| 5 | 同一份报告重复上传，不会产生重复记录 |
| 6 | 「只显示最新」开关打开时，同一 SN 只出现一行；关闭时显示全部 |
| 7 | viewer、operator、admin 三种角色的权限表现符合第 7 节 |
| 8 | 上传、导出、排除操作都出现在 `audit_log` 和 SN 时间线里 |
| 9 | CSV 能用 Excel 正常打开，UTF-8 带 BOM |
| 10 | `/monitor/version.txt` 和 `monitor_test.sh` 里的 `SCRIPT_VERSION` 一致 |

## 10. 不在范围内

- 同步到 Cyclelution（以后单独开 Task）
- monitor_test.sh 本身（见 `TASK_monitor_test.md`）
