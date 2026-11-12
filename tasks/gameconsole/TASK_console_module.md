# TASK: Console 模块（游戏主机测试录入 + QC）

> 依据：CEAR 8.6.2.3-OP Testing Procedure – Gaming Consoles 1.0
> 定位：主机测试为人工测试，CearTrack 只负责**结构化录入、证据、追溯、QC 抽检**。ERP 仍为正式记录系统。
> 技术栈：沿用现有 Flask / HTMX / Alpine.js / SQLite，复用 auth（role × module）与 audit_log。

---

## 1. 目标与范围

**做：**
- 测试员在平板/工位电脑上逐台录入：扫码 → 按型号出检查项 → 点 Pass/Fail/N/A → 数据清除 → 生成 ERP Marks → 保存
- Factory reset 拍照上传（初始设置界面）作为证据
- 每日自动抽 5% 生成 QC 待办，QC 结果录入
- 按 SN / Traveler ID 查询完整时间线

**不做（本期）：**
- 回写 ERP / Cyclelution（第二阶段，走现有 Cyclelution 集成）
- 标签打印（ERP 已有）
- 任何主机端自动化测试

---

## 2. 数据库表

### 2.1 `console_models` — 型号配置（admin 维护）
| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | |
| manufacturer | TEXT | Sony / Microsoft / Nintendo / … |
| model | TEXT | PlayStation 3 / Xbox One / Switch / … |
| storage_kind | TEXT | `removable` / `fixed` / `none` |
| has_data | INTEGER | 0/1，是否可能存有用户数据 |
| active | INTEGER | 0/1 |
| UNIQUE(manufacturer, model) | | |

### 2.2 `console_check_items` — 检查项字典
| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | |
| code | TEXT UNIQUE | `power`, `video`, `disc`, `hdd_slot`, `cartridge`, `sd_slot`, `screen`, `controller`, `memory_port`, `accessory`, `wifi`, `usb`, `expansion`, `headphone`, `ethernet`, `sensor_bar` |
| label | TEXT | 显示名，如 "Video (HDMI)" |
| default_type | TEXT | `key` / `secondary`（按 SOP 表格） |

### 2.3 `console_model_items` — 型号 ↔ 检查项
| 字段 | 类型 | 说明 |
|---|---|---|
| model_id | INTEGER FK | |
| item_id | INTEGER FK | |
| type | TEXT | `key` / `secondary`，可覆盖默认 |
| label_override | TEXT NULL | 如 Switch 的 power 显示 "Power (USB-C)" |
| sort | INTEGER | |
| PK(model_id, item_id) | | |

### 2.4 `console_tests` — 每台主机一次测试
| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | |
| traveler_id | TEXT | 索引 |
| serial_no | TEXT | 索引 |
| model_id | INTEGER FK | |
| color | TEXT NULL | |
| cosmetic_flags | TEXT | JSON 数组：`["Scratches","Missing faceplate"]` |
| sanitize_method | TEXT | `EPS` / `Factory Reset` / `Manual Delete` / `No data` / `Locked` |
| sanitize_result | TEXT | `Pass` / `Fail` / `N/A` |
| sanitize_date | TEXT | ISO date |
| storage_desc | TEXT NULL | 如 `128 GB 2.5" SSD` |
| hdd_sn | TEXT NULL | 可拆盘 SN |
| hdd_traveler_id | TEXT NULL | |
| wipe_record_id | INTEGER NULL | 关联 WipeTrack 记录 |
| reset_photo | TEXT NULL | 文件相对路径 |
| result | TEXT | `Pass` / `Fail`（系统计算，不可手改） |
| marks | TEXT | 生成的 ERP Marks 字符串 |
| notes | TEXT NULL | |
| station | TEXT | （已取消：界面不再录入，列保留为空） |
| tested_by | INTEGER FK users | 登录用户 |
| tested_at | TEXT | |
| superseded_by | INTEGER NULL | 重测时指向新记录，旧记录保留 |

### 2.5 `console_test_items` — 逐项结果
| 字段 | 类型 | 说明 |
|---|---|---|
| test_id | INTEGER FK | |
| item_id | INTEGER FK | |
| type | TEXT | 快照 key/secondary（防止型号配置后改影响历史） |
| status | TEXT | `Pass` / `Fail` / `N/A` |
| PK(test_id, item_id) | | |

### 2.6 `console_qc`
| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | |
| test_id | INTEGER FK | |
| sampled_on | TEXT | 抽样日期 |
| status | TEXT | `Pending` / `Passed` / `Rejected` |
| note | TEXT | 默认 `Verified Functionality and Data Erasure by <name>, <date>` |
| qc_by | INTEGER FK users NULL | |
| qc_at | TEXT NULL | |
| UNIQUE(test_id) | | |

---

## 3. 业务规则

1. **整机结果**：任一 key 项 = Fail，或 `sanitize_method = Locked`，或 `sanitize_result = Fail` → `result = Fail`；否则 Pass。Secondary 项 Fail 不影响整机结果，但写入 Marks。
2. **检查项默认值**：页面加载时全部为 Pass，测试员只改例外项。
3. **数据清除校验**（服务端强制）：
   - 选 `EPS` → 必须填 `hdd_sn`、`hdd_traveler_id`、`sanitize_date`（SOP 第 D 节要求）
   - 选 `Factory Reset` → `reset_photo` 为可选（可手工记录，不强制拍照）
   - `has_data = 0` 的型号 → 默认 `No data`
4. **Marks 生成**（顺序固定，逗号分隔）：
   ```
   <方法> on <MM/DD/YY>, <外观问题...>, <Fail 项> not working
   ```
   示例：`EPS on 11/05/26, Scratches, Disc drive not working`
   `Factory Reset on 11/05/26, Missing faceplate`
   `Locked - cannot reset`
5. **重测**：同一 SN 再次录入时提示"已有记录"，确认后新建记录并把旧记录 `superseded_by` 指向新记录。查询默认只显示最新。
6. **QC 抽样**：每天 15:30（下班前）cron 从当日 `result = Pass` 且未被 superseded 的记录中随机抽 `ceil(5%)`，至少 1 台，写入 `console_qc (Pending)`。允许 QC 员手动加抽。
7. **QC Rejected**：不自动改原测试结果，在详情页标红，并记录 audit。
8. 所有写操作写入 `audit_log`（module = `console`）。

---

## 4. WipeTrack 关联（本期不做）

SOP 允许可拆盘用 Factory Reset、擦除软件或换盘三种方式之一，擦除软件不是必选，因此本期不做 WipeTrack 接口。
`wipe_record_id` 字段保留为 NULL，以后需要时再接。

---

## 5. 路由

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/console/` | operator+ | 录入页 |
| GET | `/console/items?model_id=` | operator+ | HTMX：返回该型号的检查项片段 |
| GET | `/console/sn-check?sn=` | operator+ | HTMX：是否已有记录 |
| POST | `/console/marks-preview` | operator+ | HTMX：实时计算 result + marks |
| POST | `/console/tests` | operator+ | 保存，成功后清空表单、焦点回 Traveler ID |
| POST | `/console/tests/<id>/photo` | operator+ | 上传 reset 照片 |
| GET | `/console/tests` | viewer+ | 列表，按日期 / 结果 / 型号筛选，导出 CSV |
| GET | `/console/tests/<id>` | viewer+ | 详情 + 照片 + audit 时间线 |
| GET | `/console/qc` | operator+ | 今日 QC 待办 |
| POST | `/console/qc/<id>` | operator+ | 提交 QC 结果 |
| GET/POST | `/console/admin/models` | admin | 型号与检查项配置 |

---

## 6. 录入页 UI 要求

- 单列布局，按钮最小 44px，适配平板竖屏
- 顺序：Traveler ID → SN → 厂商/型号 → 外观 chips → Key 项 → Secondary 项 → 数据清除 → Marks + 结果徽章 → 保存
- 扫码枪是键盘模式：Traveler ID 扫完自动跳到 SN，SN 扫完自动跳到型号
- 检查项用三段按钮 Pass / Fail / N/A；结果徽章显示 `Pass · blue dot` / `Fail · red dot`
- Marks 只读，旁边放复制按钮（Alpine：`navigator.clipboard.writeText`）
- 保存后显示 toast，并保留上一台的厂商/型号（同批型号通常相同）
- 照片：`<input type="file" accept="image/*" capture="environment">`，服务端压缩到长边 1600px，存到 `data/console_photos/YYYY/MM/<test_id>.jpg`

---

## 7. 初始型号种子数据

至少包含：PS3、PS4、PS4 Pro、PS5、Xbox 360、Xbox One、Xbox One S/X、Xbox Series S/X、Wii、Wii U、Switch、Switch Lite、Original Xbox。
检查项按 SOP 表格映射。不确定的项由 admin 后台调整，种子数据仅作起点。

---

## 8. 验收

- [ ] 一台 Pass 主机从扫码到保存 ≤ 60 秒
- [ ] 任一 key 项 Fail → 结果自动为 Fail
- [ ] 选 EPS 但缺 HDD SN / HDD TID / 擦除日期 → 无法保存
- [ ] Factory Reset 无照片 → 允许保存（照片可选）
- [ ] Marks 格式与第 3.4 节一致，可一键复制
- [ ] 重测保留历史，列表只显示最新
- [ ] 每日 QC 自动抽样 ≥ 5%，至少 1 台
- [ ] 所有写操作可在 audit_log 按 SN 查到
- [ ] viewer 只读，operator 可录入/QC，admin 可改型号配置

## 9. 第二阶段（不在本期）
- 通过 Cyclelution 集成直接回写 ERP 字段（Data Sanitization、Functionality、Marks、HDD SN/TID）
- 统计看板：按型号的 Fail 率、Top 故障项、各工位产量
