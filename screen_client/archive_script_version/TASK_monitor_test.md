# TASK: Monitor 测试脚本 + CearTrack Monitor 模块

## 0. 背景

- 目前显示器用 EizoTest 人工测试，**没有任何记录**。
- 验收标准：**坏点少于 3 个（0–2 个通过），无外观损伤**。
- 目标：参照现有的 `laptop_test.sh`，新写一个 `monitor_test.sh`，测试结果上传到 CearTrack。CearTrack 新增 `monitor` 模块，负责存储和展示这些结果。
- 运行环境：使用现有的 **Ubuntu 24.04 USB Live 系统**（和笔记本测试是同一支 U 盘）。测试机从 U 盘启动后，执行 `sudo bash monitor_test.sh`。

### 和笔记本测试的根本区别

笔记本脚本是**在被测机器本身上运行**，序列号用 `dmidecode` 读取。
显示器是被动设备，所以由**一台固定的测试机**来跑脚本：

```
[测试机（笔记本）]                                  [被测显示器 DUT]
  内建屏 eDP → 显示脚本终端（操作界面）    DP/HDMI    全屏显示测试图案
  U 盘启动 Ubuntu 24.04             ────────────→
  有线网口 → 上传 CearTrack
  USB 条码枪（相当于键盘输入）
```

- 内建屏（eDP/LVDS/DSI）**不能被当成 DUT**。
- DUT 的身份信息来自 **EDID**，加上**扫描标签 SN 条码**。

### 实物参考（用于验收）

| 型号 | 分辨率 | 接口 | 标签 SN |
|---|---|---|---|
| LG 27UD58-B（2019 年 6 月产） | 3840×2160 | DP-IN, HDMI IN 1, HDMI IN 2, H/P | `906NTZN4G765`（有条码） |
| ASUS（型号待确认） | 待确认 | DP, HDMI, 耳机, DC-IN | 有条码 |

---

## 1. 开始之前必须先读

1. `laptop_test.sh`（v2.3.17）。**沿用它的代码风格和公共函数**，包括：
   - `banner/ok/warn/err/esc`
   - `ask_manual`
   - 依赖检查和 apt 安装段
   - 有线网链路检查（`detect_eth_dev`、`eth_has_link`，以及“没有 link 就不能上传”的逻辑）
   - 用 jq 校验 JSON、本地保存报告、用 curl 上传
   - `SCRIPT_VERSION` 和服务端 `version.txt` / `deploy_script.sh` 的同步机制
   - EDID 尺寸解析（约第 2163–2210 行）和 `manual_input` 段（Grade / Condition / Color / Size / Mark）
2. CearTrack 现有的 **laptop 模块**，包括 upload API、存储方式、列表页、详情页、鉴权/审计接入。新的 monitor 模块**完全照这个结构做**，不要另起一套架构。

---

## 2. Part A：`monitor_test.sh`

### 2.1 基本要求

- 单文件 bash 脚本，Python 部分用 heredoc 内嵌，和 laptop 脚本保持一致。
- `UPLOAD_URL="http://192.168.30.18:80/monitor/api/upload"`
- 从 `SCRIPT_VERSION="1.0.0"` 起步。
- 必须以 root 运行。
- 依赖包至少包括：`python3 python3-tk x11-xserver-utils(xrandr) edid-decode curl jq ethtool`。缺少的包按 laptop 的方式自动安装。
- 需要图形会话（`$DISPLAY`）。如果没有 X/Wayland 会话，就报错退出，并提示用 Xorg 会话登录。注意：Ubuntu 24.04 默认用 Wayland，xrandr 在 Wayland 下不可靠，所以**检测到 Wayland 时要给出明确提示**。

### 2.2 批量循环

- Operator ID 在**启动时只输入一次**，之后循环测试多台显示器。
- 每台测完后提示“拔下当前显示器，接下一台（Enter 继续 / q 退出）”。
- 启动时和每台测完后，都检查 `/root/monitor_reports/pending/` 里有没有之前上传失败的报告。如果有，就自动补传，成功后移到 `sent/`。

### 2.3 单台测试流程

**Step 1：检测 DUT**

- 轮询 `/sys/class/drm/card*-*/status`，找到 `connected`、名称不是 `eDP*/LVDS*/DSI*`、并且 `edid` 文件非空的 connector。
- 超时 60 秒，期间可以重试。
- 如果同时检测到多个外接 connector，要求操作员只保留一根线。

**Step 2：解析 EDID**（内嵌 Python，不依赖 edid-decode；edid-decode 的输出只作为附加的原始信息存进报告）

- 厂商 PNP ID（bytes 8–9，3 个字母），并映射成常见厂商名：DEL→Dell, GSM→LG, ACI/AUS→ASUS, HWP→HP, LEN→Lenovo, SAM→Samsung, ACR→Acer, BNQ→BenQ, VSC→ViewSonic, PHL→Philips, AOC→AOC。没有映射的就保留原始 ID。
- Product code（bytes 10–11）
- 数字序列号（bytes 12–15）
- 生产周和年份（byte 16、byte 17 + 1990）
- 物理尺寸（bytes 21–22，单位 cm），换算成对角线英寸
- Descriptor `0xFC`（型号名）和 `0xFF`（序列号字符串）
- 第一个 Detailed Timing Descriptor，也就是原生分辨率和刷新率
- EDID checksum 是否有效
- 生成一个 **EDID 指纹**：`mfg+product+serial_num+serial_str`。后面的接口测试用它来确认插上的是同一台显示器。

**Step 3：扫描标签 SN**

- 提示“扫描显示器标签 SN 条码”。输入后去掉首尾空白，转成大写，不能为空。
- 和 EDID 序号比对：先比 `0xFF` 字符串，没有的话再比数字序列号。结果记为 `sn_match`：
  - `MATCH`：完全一致，或者其中一方包含另一方
  - `MISMATCH`：不一致。这时提示操作员重扫一次；如果仍然不一致，记为 MISMATCH 继续测试，**不判 FAIL**
  - `EDID_EMPTY`：EDID 里没有序号
- **CearTrack 以标签 SN（`label_sn`）为主键。**

**Step 4：分辨率检查**

- 把 DUT 设为扩展模式，放在内建屏右侧：`xrandr --output <DUT> --mode <native> --right-of <eDP>`。
- 回读当前生效的模式，记录 `achieved_resolution` 和 `achieved_refresh`。
- 判定：
  - 原生模式达到 ≥59Hz：PASS
  - 原生模式不在测试机的可用模式列表里，或刷新率不到 59Hz（比如测试机 HDMI 1.4 跑 4K 只有 30Hz）：WARN，并注明 `station_limited`。**这是测试机的问题，不能判显示器 FAIL。**
  - 完全点不亮：FAIL

**Step 5：图案测试**（Python tkinter）

- 无边框全屏窗口，按 xrandr 给出的 DUT 几何参数（宽×高+x+y）**只覆盖 DUT**，内建屏上的终端保持可以操作。
- 图案依次为：纯红、纯绿、纯蓝、纯白、纯黑、50% 灰、1px 网格、水平灰阶渐变、棋盘格。
- 操作键：→ / 空格 切到下一张，← 回到上一张，Esc 结束。屏幕角落用小字显示当前图案名，3 秒后自动隐藏，以免挡住坏点。
- 图案结束后，在终端里输入：
  - `dead_pixel_count`：整数 0–99，坏点和亮点合计，必填，非法输入要重新输入
  - `backlight_check`：p/f，检查漏光和亮度不均
- 判定阈值写成脚本顶部的常量 `MAX_DEAD_PIXELS=2`：`dead_pixel_count > MAX_DEAD_PIXELS` 判 FAIL。

**Step 6：接口测试**

- 先让操作员申报 DUT 有哪些接口及数量，类型包括 DP、mDP、HDMI、DVI、VGA、USB-C，例如 `DP=1 HDMI=2`。
- Step 1 用的那个接口，按它在测试机端的 connector 类型自动记为 PASS。
- 对每个还没测的接口：提示“把线换到 <接口 #n>，必要时用显示器按键切换输入源，按 Enter”。然后在 30 秒内检测是否有 connected 的外接 connector，并且 EDID 指纹和 DUT 一致：
  - 指纹一致：PASS
  - 超时：让操作员选 r=重试 / f=FAIL / n=无法测试（比如没有对应的线或转接头）→ `NOT_TESTED`
- 记录每个接口的 `{type, index, result, station_connector}`。

**Step 7：人工检查**（用 `ask_manual` 风格）

- `cosmetic_check`：p/f。如果选 f，要多选缺陷类型：crack / burn-in / severe_scratch / backlight_bleed / stand_damaged / bezel_damaged / other（other 要填备注）。
- `osd_buttons_check`：p/f/s
- `stand_included`：y/n
- `manual_input`：照搬 laptop 的 Grade / Condition / Color / Weight / Mark 段。
  - Size 默认用 EDID 对角线尺寸，可选值改为显示器的范围。
  - **TODO（Herbert 提供）**：Cyclelution 里显示器的 Size、Color、Mark 下拉列表。在拿到之前，先用占位列表 `[17,19,20,21.5,22,23,23.8,24,25,27,28,32,34,38,43]`，并在代码里标注 `# TODO Cyclelution list`。

**Step 8：判定、保存、上传**

- **FAIL**（满足任意一项）：
  - `dead_pixel_count > MAX_DEAD_PIXELS`
  - cosmetic FAIL
  - backlight FAIL
  - 分辨率检查 FAIL
  - 任一接口 FAIL
  - 有线网 FAIL（和 laptop 一样，没网就是无效测试）
- **WARN**：sn_match 不是 MATCH、分辨率 `station_limited`、OSD FAIL、有接口 NOT_TESTED
- 其余情况：**PASS**
- 报告保存到 `/root/monitor_reports/<label_sn>_<YYYYmmdd-HHMMSS>.json`，先用 jq 校验。
- 上传返回 200 或 201：报告移到 `sent/`；否则移到 `pending/`，等待下次补传。
- 终端用**大号彩色字**显示 PASS / WARN / FAIL、label_sn、型号、坏点数，同时列出导致 FAIL 或 WARN 的原因。

### 2.4 JSON 报告结构

```json
{
  "report_type": "monitor",
  "test_info": {
    "test_time": "", "operator_id": "", "duration_seconds": 0,
    "script_version": "", "station_hostname": "", "station_gpu": ""
  },
  "identity": {
    "label_sn": "906NTZN4G765",
    "edid_serial_str": "", "edid_serial_num": 0,
    "sn_match": "MATCH|MISMATCH|EDID_EMPTY",
    "vendor": "LG", "vendor_pnp": "GSM", "model": "27UD58", "product_code": "",
    "mfg_week": 0, "mfg_year": 2019,
    "edid_checksum_ok": true, "edid_fingerprint": "", "edid_raw_hex": ""
  },
  "display": {
    "native_resolution": "3840x2160", "native_refresh": 60,
    "achieved_resolution": "", "achieved_refresh": 0,
    "resolution_check": "PASS|WARN|FAIL", "station_limited": false,
    "size_inch_edid": 27.0,
    "dead_pixel_count": 0, "max_dead_pixels_allowed": 2,
    "dead_pixel_check": "PASS|FAIL",
    "backlight_check": "PASS|FAIL",
    "patterns_shown": ["red","green","blue","white","black","gray50","grid","gradient","checker"]
  },
  "ports": [
    {"type": "DP", "index": 1, "result": "PASS|FAIL|NOT_TESTED", "station_connector": "DP-1"},
    {"type": "HDMI", "index": 1, "result": "PASS", "station_connector": "HDMI-A-1"},
    {"type": "HDMI", "index": 2, "result": "PASS", "station_connector": "HDMI-A-1"}
  ],
  "appearance": {
    "cosmetic_check": "PASS|FAIL", "defects": [], "defect_note": "",
    "osd_buttons_check": "PASS|FAIL|SKIPPED", "stand_included": "Yes|No"
  },
  "manual_input": {
    "weight_lbs": "", "grade": "Grade B", "condition": "C4 - Used Good",
    "color": "", "screen_size_inch": "27 inch", "mark": ""
  },
  "network": { "ethernet_status": "PASS", "ethernet_device": "" },
  "result_reasons": [],
  "overall_result": "PASS|WARN|FAIL"
}
```

---

## 3. Part B：CearTrack `monitor` 模块

> **详细需求见 `TASK_ceartrack_monitor_module.md`，以那份文档为准。** 下面只是摘要。

完全照 laptop 模块的结构来做，技术栈是 Flask + HTMX/Alpine + 现有的存储方式。

1. **上传 API**：`POST /monitor/api/upload`。鉴权方式和 laptop upload 一样。服务端要做的事：
   - 校验必填字段：`label_sn`、`operator_id`、`overall_result`、`dead_pixel_count`
   - **服务端按同样的规则重新计算 overall_result**。如果和客户端算的不一致，以服务端结果为准，并记录日志
   - 同一个 SN 允许有多次测试记录，列表默认显示最新一次
2. **存储**：新建 monitor 测试表（或者按 laptop 的方式存 JSON）。`ports`、`defects`、`result_reasons` 原样保存。`edid_raw_hex` 和 `edid-decode` 的原始输出只存储，不在列表里展示。
3. **列表页** `/monitor`：
   - 列：时间、Label SN、厂商/型号、尺寸、坏点数、外观、接口摘要（如 `DP✓ HDMI✓✓`）、SN 匹配、结果、Operator
   - 筛选：日期范围、结果、厂商、Operator；可按 SN 搜索
   - 导出 CSV
4. **详情页**：展示全部字段，包括接口表格、缺陷、FAIL/WARN 原因，以及同一 SN 的历史测试记录。
5. **鉴权和审计**：接入现有的角色 × 模块权限，新增 `monitor` 模块的勾选项。上传、排除、删除等操作写入 `audit_log`，并在 SN 时间线里显示。
6. **脚本分发**：monitor_test.sh 的版本和 `version.txt` 走 laptop 的同一套机制，路径在 `/monitor/` 下。
7. **首页/导航**：增加 Monitor 入口。

**不在本 Task 范围内**：同步到 Cyclelution。只需保证 `manual_input` 的格式和 laptop 一致，方便以后接入。

---

## 4. 验收标准

| # | 场景 | 预期 |
|---|---|---|
| 1 | LG 27UD58 走 DP，测试机支持 4K60，0 坏点，外观 OK，DP + HDMI×2 都 PASS | PASS，CearTrack 能看到完整记录 |
| 2 | 同一台，测试机 HDMI 只能跑 4K30 | resolution WARN + `station_limited=true`，结果 WARN |
| 3 | 输入坏点数 2 | dead_pixel_check PASS |
| 4 | 输入坏点数 3 | FAIL，原因写明 dead pixels 3 > 2 |
| 5 | cosmetic f + crack | FAIL，defects 里有 crack |
| 6 | 扫的 SN 和 EDID 不一致，或 EDID 里没有序号 | 继续测试，结果 WARN，原因写明 |
| 7 | 换接口时插上的是另一台显示器（指纹不一致） | 不判 PASS，提示操作员检查 |
| 8 | 没有对应的转接头，选 n | NOT_TESTED，结果 WARN |
| 9 | 上传时拔掉网线 | 报告进入 pending/；恢复网络后，下一轮开始时自动补传成功 |
| 10 | 连测 3 台显示器 | Operator ID 只输入一次，3 条记录都正确入库 |
| 11 | 内建屏不会被识别成 DUT；同时接了两台外接显示器 | 内建屏被排除；两台外接时提示只保留一根线 |
| 12 | 服务端收到 overall_result 被篡改的报告 | 服务端按规则重新计算，以服务端结果为准，并记录日志 |
| 13 | 在 Wayland 会话里运行 | 明确提示切换到 Xorg，不能静默失败 |

---

## 5. 交付物

- `monitor_test.sh`
- CearTrack `monitor` 模块代码，以及数据库迁移（如果需要）
- `docs/monitor_test_SOP.md`：一页纸的操作员 SOP，**中英双语**，内容包括测试站接线、条码枪使用、每一步该按什么键
- `CHANGELOG` 条目
- 在 PR 描述里列出上面 13 条验收场景的自测结果

## 6. 需要 Herbert 补充或确认（可以先写代码，相关位置标 TODO）

1. Cyclelution 里显示器的 Size、Color、Mark 下拉列表
2. 测试机的具体型号，以及它的 DP/HDMI 能否跑 4K60
3. 用 LG 27UD58 实测：EDID 里的 `0xFF` 序号是否等于 `906NTZN4G765`
4. 接口 FAIL 是否判整机 FAIL（目前按 FAIL 处理）
5. 测试计划文档里写的是 “No ... dead pixel”，实际标准是“少于 3 个坏点”，需要统一文档
