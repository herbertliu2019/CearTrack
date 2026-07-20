# TASK: laptop_test.sh 改造 — 新增 operator 手动录入字段

> 交给 Claude Code。目标:在现有 laptop_test.sh (v2.0.5, 1672 行) 中新增几个
> operator 手动录入字段,并写进上传的 JSON。**严格沿用脚本现有风格**,不重写结构。

## 背景与铁律

- 脚本是数据采集源头,产出 JSON 通过 `curl POST` 到 CearTrack (UPLOAD_URL)。
- 这些新字段是 CearTrack↔Cyclelution 集成需要的"看实物才能判断"的信息,
  必须在 operator 手持机器测试时录入(不能事后在网页补)。
- **JSON 字段契约是本任务与 CearTrack 集成任务的唯一接口,字段名/层级/格式必须与下方完全一致,不得改动。**

## 沿用现有约定(务必遵守)

1. 交互风格照抄现有写法:`read -rp "$(echo -e "  ${BOLD}提示语${NC}")" VAR </dev/tty`
2. 所有写入 JSON 的字符串值必须过 `esc()` 转义函数(脚本已定义)。
3. 新录入段统一放在**所有自动测试跑完之后、JSON 组装(1446 行 `JSON=$(cat <<EOF`)之前**,
   集中成一个 "MANUAL INPUT — Appearance & Grading" 区块。banner 用现有 `banner()` 函数。
4. 输入校验风格参考现有"有无盘询问"(809 行)与键盘 p/f/s 询问:非法输入重新提示或给默认值,不让脏值进 JSON。
5. 不改动任何现有自动测试逻辑,不动上传逻辑,只增不改。

## 要新增的字段与录入规则

### (1) Weight — 称重(必填,数字)
- 提示: `Enter weight in lbs (e.g. 4.5):`  (单位 lbs 还是 kg 待用户确认,先按 lbs)
- 校验: 必须是正数(整数或小数)。空或非数字 → 重新提示,不允许跳过(CearTrack 硬校验要求非空数字)。
- 变量 WEIGHT_LBS。

### (2) Grade — 成色等级(必填)
- 提示: `Enter Grade [A/B/C/D]:`
- 校验: 只接受 A/B/C/D(大小写均可,存大写)。非法 → 重新提示。不允许空。
- 变量 GRADE。JSON 存单字母(如 "A"),CearTrack 侧映射为 "Grade A"。

### (3) Condition — 状况(可空,默认 4)
- 提示: `Enter Condition [0-9, Enter=4 (C4-Used Good)]:`
- 校验: 只接受 0-9 单个数字;直接回车 → 默认 "4"。非法 → 重新提示。
- 变量 CONDITION。JSON 存数字字符(如 "4"),CearTrack 侧映射为全称。

### (4) Color — 颜色(可空)
- 提示: `Enter Color (e.g. Black / Silver, Enter to skip):`
- 无校验,自由文本;空则存空串。变量 COLOR。
- 注: Color 对应 Cyclelution 固定字段区 Color 列(此前 T-Laptop 未使用,本次新增)。

### (5) Size — 屏幕尺寸(可空)
- **优先自动**: 脚本已采集 screen.resolution;但屏幕物理尺寸(inch)通常 EDID 可读。
  先尝试从 EDID (如 `edid-decode` 或 /sys/class/drm 的 EDID) 自动读取对角线尺寸(inch)。
- 读到 → 显示并让 operator 确认或修正: `Detected screen size: 15.6 inch. Correct? [Enter=yes / or type actual]:`
- 读不到 → 提示手动输入: `Enter screen size in inch (e.g. 15.6, Enter to skip):`
- 变量 SCREEN_SIZE_INCH。存纯数字(如 "15.6"),CearTrack 侧拼 "15.6 inch" 并归档到值域。
- **注: 请先调研本机 EDID 能否稳定读出物理尺寸;若不可靠则以手动输入为主。**

### (6) Mark — 备注/外观描述(可空)
- 数字菜单 + 自由文本兜底 + 回车跳过:
  ```
  Mark [Enter=none]:
    1) Minor scratches/blemishes
    2) Scratches on lid
    3) Dent on corner
    4) Worn keyboard/palmrest
    5) Screen blemish
    0) Type custom text
  ```
- 选 1-5 → 存对应文本; 0 → 再 read 一行自由文本; 回车 → 空串。
- 菜单常用语放脚本内数组常量(便于以后加条目);变量 MARK。
- 变量 MARK 存最终字符串。

### (7) CD/DVD Drive — 光驱判断(自动,尽量不打扰 operator)
- 你列的"cd\dvd 脚本判断": 自动检测有无光驱设备(如 `lsblk` 中 type=rom, 或 /dev/sr*,
  或 `wodim --devices`)。检测到 → CDDVD="Yes",否则 "No"。
- 变量 CDDVD_PRESENT。无需 operator 输入(纯自动)。CearTrack 侧: 有=对应 Cyclelution 值,无=No。
- 注: 现代 laptop 基本无光驱,默认多为 No,故自动判断即可。

## JSON 契约(新增到 JSON 主体,放在 overall_result 之前)

在 1446 行的 heredoc 里,新增一个 `manual_input` 段(与 appearance 平级):

```
  "manual_input": {
    "weight_lbs": "$(esc "$WEIGHT_LBS")",
    "grade": "$(esc "$GRADE")",
    "condition": "$(esc "$CONDITION")",
    "color": "$(esc "$COLOR")",
    "screen_size_inch": "$(esc "$SCREEN_SIZE_INCH")",
    "mark": "$(esc "$MARK")",
    "cddvd_present": "$(esc "$CDDVD_PRESENT")"
  },
```

**字段名固定,CearTrack 归一化引擎按此读取。** condition/grade 存原始录入值(数字/字母),
由 CearTrack 侧映射为 Cyclelution 全称,脚本不做映射(保持脚本简单,映射规则集中在 CearTrack 配置)。

## 验收标准

- 跑一遍完整测试,新录入区块出现在所有自动测试之后、上传之前,交互风格与现有一致。
- Weight 输入非数字/空会重新提示;Grade 非 ABCD 重新提示;Condition 回车得 "4"。
- Mark 菜单选 1 存 "Minor scratches/blemishes",选 0 能输自由文本,回车得空串。
- 生成的 JSON 用 `jq .` 校验通过,`manual_input` 段字段齐全、值正确转义。
- CD/DVD 自动判断:有光驱机器得 "Yes",无光驱得 "No",不需人工干预。
- SCRIPT_VERSION 从 2.0.5 递增(如 2.1.0),与 server version.txt 同步(照现有 deploy 流程)。

## 交给 CearTrack 侧同步的接口约定(本任务不实现,仅告知)

CearTrack 归一化引擎从 JSON `manual_input` 读:
- weight_lbs → Weight 列(直接数字)
- grade "A" → "Grade A"
- condition "4" → "C4 - Used Good"(0-9 映射表)
- color → Color 列(direct)
- screen_size_inch "15.6" → Size 列 "15.6 inch"(归档到屏幕尺寸值域)
- mark → TxtProperty001(direct,可空,校验门不检查)
- cddvd_present "No"/"Yes" → CD/DVD Drive 槽位
