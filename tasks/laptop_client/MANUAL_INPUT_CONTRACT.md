# manual_input 字段说明 —— 给 CearTrack 侧

**一句话:** laptop_test.sh（v2.1.3 起）在采集端就把 operator 录入的值组装成
**Cyclelution 下拉框里一模一样的完整字符串**。CearTrack **直接读取入库即可，不需要再做任何码值映射**。

## 为什么这样做

- 测试脚本是数据源头，改脚本最直观、所见即所传。
- 值域（颜色/成色/尺寸列表）在脚本里以编号菜单固定，operator 只能选合法项，脏值进不来。
- 映射只放一处（脚本端），CearTrack 不用再维护一张对照表，少一层就少一处对不上的风险。

## JSON 契约（上传报告中的 `manual_input` 段）

```json
"manual_input": {
    "weight_lbs": "3.38",
    "grade": "Grade B",
    "condition": "C4 - Used Good",
    "color": "Gray",
    "screen_size_inch": "14 inch",
    "mark": "Scratches on lid",
    "cddvd_present": "No"
}
```

## 逐字段规则（CearTrack 按此直读，**不要再转换**）

| 字段 | 值的形态 | 说明 | 可空 |
|------|----------|------|------|
| `weight_lbs` | 纯数字字符串，如 `"3.38"` | 单位 lbs，operator 必填正数 | 否 |
| `grade` | `"Grade A"` / `"Grade B"` / `"Grade C"` / `"Grade D"` | 已是完整字符串，直接写 Grade 列 | 否 |
| `condition` | `"C4 - Used Good"` 等完整串 | 见下方 C0–C9 全表，格式 `Cn - 文本` | 否（默认 C4） |
| `color` | 颜色名，如 `"Gray"` | 取自固定颜色列表（见下），规范拼写 | 是（空串=未填） |
| `screen_size_inch` | `"14 inch"`（数字+空格+`inch`） | 已带单位，直接写 Size 列 | 是（空串=跳过） |
| `mark` | 自由文本，如 `"Scratches on lid"` | 外观备注，写 TxtProperty001，可空、不校验 | 是 |
| `cddvd_present` | `"Yes"` / `"No"` | 脚本自动检测，无人工输入 | 否 |

### condition 取值全表（C0–C9）
```
C0 - Not categorized
C1 - Damaged
C2 - Used Poor
C3 - Used Fair
C4 - Used Good          ← 默认
C5 - Used Very Good
C6 - Used Excellent
C7 - Certified Pre-Owned
C8 - Unused
C9 - New Open box
```

### color 取值列表（10 项，其余为空串）
```
Black  Blue  Gold  Gray  Green  Purple  Red  Silver  White  Yellow
```

### screen_size_inch 取值范围（笔记本 10–17.3 inch）
```
10  10.2  10.5  10.9  11  11.6  12  12.3  12.5  13
13.3  13.5  14  15  15.6  16  16.4  17  17.1  17.3
```
（值后统一带 ` inch`，如 `"15.6 inch"`；operator 跳过时为空串。）

## 约定

- **字段名/层级/字符串格式固定**，脚本端如需变更值域会同步更新本文件并递增 SCRIPT_VERSION。
- CearTrack 侧只做：非空校验 + 直接入库。不要再拆 `"Grade B"→B`、`"C4 - Used Good"→4` 之类的反向解析。

*对应脚本: laptop_client/laptop_test.sh ≥ v2.1.3*
