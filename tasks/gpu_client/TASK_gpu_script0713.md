# TASK: GPU 测试脚本改造 — 新增 operator_id 与 manual_input

> 交给 Claude Code。目标:为 GPU 测试脚本(script_version 1.4.1)新增 operator 手动录入字段,
> 使其产出的 JSON 满足 Cyclelution 导出所需。
> **必须与已改造完成的 laptop_test.sh 保持完全一致的字段格式与交互风格**——
> 两个脚本产出的 JSON 由同一套 CearTrack 归一化引擎消费,格式不统一会导致引擎要写两套逻辑。

## 0. 背景

GPU 测试脚本目前产出的 JSON 中:
- `test_info` 段**没有** `operator_id`
- **没有** `manual_input` 段

而 Cyclelution 的 T-Video Card 导入要求 Weight / Grade / Condition 必填。缺这些字段,
所有 GPU 记录会卡在 pending 无法导出。本任务补齐这些字段。

## 1. 铁律:对齐 laptop 脚本的既有实现

laptop_test.sh 已完成同类改造,其实际产出格式为(**GPU 必须照此对齐**):

```json
"test_info": {
  "test_time": "...",
  "operator_id": "0170",        // ← 工号在 test_info 段,不在 manual_input
  "script_version": "..."
},
"manual_input": {
  "weight_lbs": "3",                          // 纯数字字符串
  "grade": "Grade B",                         // ← 全称,不是单字母 "B"
  "condition": "C4 - Used Good",              // ← 全称,不是数字 "4"
  "color": "Silver",
  "mark": "-minor scratches/blemishes -BIOS Locked"   // ← 多选时用 "-" 前缀逐条拼接
}
```

**关键**: grade / condition 由**脚本侧直接存 Cyclelution 全称**(脚本内部做码值→全称的转换),
CearTrack 只做 direct 透传。**不要让脚本存 "A" / "4" 这类原始码。**

## 2. 要新增的字段

### (1) operator_id — 工号(必填,测试开始前第一步)
- 位置: 脚本最开始,SN 确认后、任何测试开始前。
- 提示: `Enter Operator ID (e.g. 0216):`
- 校验: 非空。**保留前导零,存字符串**(输 0216 存 `"0216"`,不可当数字处理)。
- 支持扫工牌条码(扫码枪 = 键盘输入 + 回车,无需特殊处理)。
- 写入 JSON 的 **`payload.test_info.operator_id`**(与 test_time / script_version 平级)。

### (2) Weight — 称重(必填,数字)
- 提示: `Enter weight in lbs (e.g. 1.0):`
- 校验: 正数(整数或小数)。空或非数字 → 重新提示,不允许跳过。
- 显卡通常 0.5~2.5 lbs,与 laptop 量级不同,但不做范围硬限制。
- → `manual_input.weight_lbs`(纯数字字符串)

### (3) Grade — 成色等级(必填)
- 提示: `Enter Grade [A/B/C/D]:`
- 校验: 只接受 A/B/C/D(大小写均可)。非法 → 重新提示。不允许空。
- **脚本内转为全称存入**: A → `"Grade A"`,以此类推。
- → `manual_input.grade`

### (4) Condition — 状况(可空,默认 4)
- 提示: `Enter Condition [0-9, Enter=4 (C4-Used Good)]:`
- 校验: 只接受 0-9 单个数字;直接回车 → 默认 4。非法 → 重新提示。
- **脚本内转为全称存入**,映射表:
  ```
  0 → C0 - Not categorized      5 → C5 - Used Very Good
  1 → C1 - Damaged              6 → C6 - Used Excellent
  2 → C2 - Used Poor            7 → C7 - Certified Pre-Owned
  3 → C3 - Used Fair            8 → C8 - Unused
  4 → C4 - Used Good            9 → C9 - New Open box
  ```
- → `manual_input.condition`

### (5) Color — 颜色(可空)
- 提示: `Enter Color (e.g. Black, Enter to skip):`
- 自由文本,空则存空串。
- → `manual_input.color`

### (6) Mark — 备注/外观描述(可空,支持多选)
- 数字菜单 + 自由文本兜底 + 回车跳过,**支持多选**:
  ```
  Mark [Enter=none, multi-select with comma e.g. 1,3]:
    1) minor scratches/blemishes
    2) bent bracket
    3) missing screws
    4) fan noise
    5) dusty
    0) Type custom text
  ```
- 多选时按 laptop 既有格式拼接: 每条以 `-` 前缀,空格分隔
  → 例: 选 1,3 得 `"-minor scratches/blemishes -missing screws"`
- 选 0 → 自由文本;回车 → 空串。
- 菜单项放脚本内数组常量(便于扩展)。**注意菜单内容应为显卡相关描述,不要照抄 laptop 的**
  (laptop 有 "worn keyboard" 等,显卡不适用)。
- → `manual_input.mark`

## 3. GPU 不需要的字段

laptop 有但 **GPU 不做**:
- `screen_size_inch`(显卡无屏幕)
- `cddvd_present`(显卡无光驱)

## 4. 交互与实现约定

- 沿用脚本现有的输入交互风格与转义处理(参考 laptop_test.sh 的 `read -rp ... </dev/tty` 与 `esc()`)。
- manual_input 录入区块统一放在**所有自动测试跑完之后、JSON 组装之前**,
  operator_id 例外(在最开始)。
- 输入校验:非法输入重新提示,不让脏值进 JSON。
- 不改动任何现有自动测试逻辑(gpu-burn / glmark2 / thermal / dmesg 等),不动上传逻辑,只增不改。
- **INFO_ONLY 模式下同样要录入这些字段**(INFO_ONLY 的卡也要导出 Cyclelution)。
- SCRIPT_VERSION 从 1.4.1 递增(如 1.5.0)。

## 5. 验收标准

- 脚本启动后第一步要求输入 Operator ID,空输入重新提示,前导零保留(输 0216 得 `"0216"`)。
- 完整跑一遍(FULL 与 INFO_ONLY 两种 tier 各一次),manual_input 五个字段均正确写入。
- Grade 输入 `B` → JSON 中为 `"Grade B"`(全称);Condition 回车 → `"C4 - Used Good"`(全称)。
- Mark 输入 `1,3` → 得 `"-minor scratches/blemishes -missing screws"`(多条 `-` 前缀拼接)。
- 生成的 JSON 用 `jq .` 校验通过;`payload.test_info.operator_id` 与 `payload.manual_input` 均存在。
- 与 laptop 脚本产出的 JSON 对比:**同名字段的格式完全一致**(grade/condition 均为全称,
  weight_lbs 均为纯数字字符串,mark 拼接格式相同)。

## 6. 后续

本任务完成后,GPU 的 Cyclelution 导出(TASK_gpu_export.md)才能正常工作。
开发顺序: **本任务 → TASK_gpu_export.md**。
