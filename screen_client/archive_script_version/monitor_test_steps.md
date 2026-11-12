# monitor_test.sh — 测试内容与步骤

版本 1.0.0。外接显示器检测脚本，跑在固定测试站上。被测显示器（DUT）是被动设备，靠 EDID 和机身标签条码识别。结果以 JSON 上传 CearTrack（`/monitor/api/upload`）。

## 1. 运行前提

| 项 | 要求 |
|----|------|
| 运行方式 | `sudo bash monitor_test.sh`，必须 root |
| 桌面会话 | Xorg（Ubuntu on Xorg）。Wayland 会直接退出并提示切换 |
| 网络 | 必须有有线网口且 link up，否则无法上传 |
| 显示器 | 一次只接一台外接显示器 |
| 依赖 | python3、python3-tk、x11-xserver-utils(xrandr)、edid-decode、curl、jq、ethtool、pciutils；缺失时自动 apt 安装 |
| 输入 | 所有输入走 `/dev/tty`（fd 3），条码枪当键盘用 |

## 2. 启动流程（一次）

1. 检查会话类型（Wayland 退出；DISPLAY 未设置则自动找 `/tmp/.X11-unix/X*`）。
2. 检查并安装依赖；xrandr / curl / tkinter 缺失则退出。
3. 检查 X 访问权限（root 取桌面用户的 Xauthority）。
4. 创建 `/root/monitor_reports/{sent,pending}`（可用 `MONITOR_REPORT_DIR` 覆盖）。
5. 对比服务器 `version.txt`，版本不同只提示不阻止。
6. 记录测试站显卡（`lspci`）。
7. 输入 **Operator ID**（不能为空）。
8. 重传 `pending/` 中上次未传成功的报告。

## 3. 每台显示器的测试步骤

循环：检查网络 → 测一台 → 重传 pending → 提示换下一台（Enter 继续 / q 退出）。

### Network — 有线网络
- 自动识别有线网卡（排除 WiFi、虚拟网卡，含 USB-RJ45），读 `carrier` 判断 link。
- 无 link：提示插线，Enter 重查，q 退出。这是测试站问题，没有"标记坏"选项。
- 结果记入 `network.ethernet_status`。

### Step 1 — 检测显示器
- 等待最多 60 秒，找一个已连接且 EDID 可读的外接口（排除 eDP/LVDS/DSI）。
- 多于一台外接：提示只留一根线。
- 与上一台 EDID 指纹相同：询问是否重测。
- 超时后选择：`r` 重试 / `b` 标记坏（无 EDID / 无信号，记 FAIL）/ `q` 退出。
- 选 `b` 时跳过 Step 2–6，操作员手输标签上的 SN、厂商、型号，然后直接进 Step 7。

### Step 2 — 读取 EDID
- 解析：厂商 PNP、产品码、序列号（数字和字符串）、型号名、生产周/年、对角线尺寸、原生分辨率、刷新率、校验和。
- 生成指纹 `PNP+产品码+序列号+序列字符串`，用于识别同一台和端口切换后确认。
- 保存 `edid-decode` 原文和 EDID 原始 hex。
- 校验和无效只警告。

### Step 3 — 标签 SN 校验
- 扫描标签 SN 条码（转大写、去不可见字符，不能为空）。
- 与 EDID 序列号比较：
  - `MATCH`：相等，或一方包含另一方（较短一方 ≥4 字符）。
  - `MISMATCH`：提示重扫一次，仍不符则继续，结果为 WARN。
  - `EDID_EMPTY`：EDID 无序列号（空、0、0x01010101），结果为 WARN。

### Step 4 — 分辨率检查
- 通过 EDID 比对把 DRM 接口映射到 xrandr 输出名（不同驱动命名不同）。
- 将显示器设为原生分辨率 + 最高刷新率，放在内置屏右侧。设置失败则退回 `--auto`。
- 等 2 秒后读回实际模式，**操作员确认是否有画面**（xrandr 对坏屏也会成功）。
  - 选 n：记 `no_signal`，FAIL。
- 判定：
  - 实际 = 原生且刷新率 ≥59Hz → `PASS`。
  - 否则 → `WARN`，标记 `station_limited`（测试站能力限制，不算显示器故障）。

### Step 5 — 图案测试
- 在被测显示器上全屏显示 9 种图案：red、green、blue、white、black、gray50、grid、gradient、checker。
- 键盘：Right/Space 下一张，Left 上一张，Esc 结束。角落标签 3 秒后消失，避免遮住坏点。
- 少于 9 张时询问：`r` 重看 / Enter 继续。
- 输入**坏点 + 亮点总数**（0–99），超过 `MAX_DEAD_PIXELS`（2）→ FAIL。
- 背光检查（p/f）：黑、白图案下的漏光和亮度不均。

### Step 6 — 端口测试
- 输入显示器端口清单，格式 `TYPE=数量`，如 `DP=1 HDMI=2`。可选类型：DP、mDP、HDMI、DVI、VGA、USB-C。
- 当前已连接的端口自动记 PASS（类型对不上时让操作员选是哪个口）。
- 其余端口逐个测：提示把线换到指定端口，Enter 后监测拔插变化，30 秒内读到**同一台显示器的 EDID 指纹**即 PASS。
  - 没检测到线被拔：追问是否真的换了。
  - 读到别的显示器：警告。
  - 超时：`r` 重试 / `f` FAIL / `n` NOT_TESTED（无线材或转接头）。

### Step 7 — 人工检查与分级
| 项 | 输入 |
|----|------|
| Cosmetic 外观 | p/f；选 f 时多选缺陷：crack、burn-in、severe_scratch、backlight_bleed、stand_damaged、bezel_damaged、other（other 需写说明） |
| OSD 按键 | p/f/s（可跳过） |
| 是否带底座 | y/n |
| 重量 | lbs，正数，可带小数 |
| Grade | A/B/C/D |
| Condition | 0–9（C0 Not categorized … C9 New Open box），Enter 默认 4（Used Good） |
| 颜色 | 列表选择，可跳过 |
| 尺寸 | 列表选择，EDID 尺寸 0.6 英寸内自动推荐，Enter 接受，可跳过 |
| Mark | 多选标记或自定义文字，Enter 为无 |

格式与 laptop_test.sh 的 `manual_input` 相同（CearTrack 直读，不做映射）。

### Step 8 — 判定、保存、上传

**FAIL 条件**（任一）：
- 无 EDID / 无信号
- 坏点数 > 2
- Cosmetic FAIL
- 背光 FAIL
- 分辨率检查 FAIL（无信号时不重复计）
- 任一端口 FAIL
- 有线网络 FAIL

**WARN 条件**（无 FAIL 时）：
- SN 不符 / EDID 无序列号
- 测试站限制（未达原生分辨率/刷新率）
- OSD 按键 FAIL
- 端口 NOT_TESTED

否则 PASS。规则需与服务端 `monitorcenter/modules/monitor/verdict.py` 保持一致。

处理：
1. 生成 JSON 报告，文件名 `<SN>_<时间戳>.json`，用 jq 校验并格式化。
2. 终端显示大字 PASS / WARN / FAIL、SN、型号、坏点数、原因列表。
3. POST 到服务器：HTTP 200/201 → 移到 `sent/`；失败 → 保留在 `pending/`，下次启动或下一台测完后重传。
4. 关闭被测输出。

退出时若 `pending/` 仍有报告，提示联网后重跑脚本，**重启前务必完成**（Live USB 可能丢失）。

## 4. 报告 JSON 结构

| 段 | 内容 |
|----|------|
| `report_type` | 固定 `monitor` |
| `test_info` | 测试时间、操作员、耗时、脚本版本、测试站主机名、测试站显卡 |
| `identity` | 标签 SN、EDID 序列号、SN 匹配结果、厂商、型号、产品码、生产周/年、校验和、指纹、EDID 原始 hex、edid-decode 文本 |
| `display` | 原生/实际分辨率与刷新率、分辨率检查、station_limited、no_signal、EDID 尺寸、坏点数与上限、坏点检查、背光检查、已显示图案 |
| `ports` | 每个端口：类型、序号、结果、测试站接口名 |
| `appearance` | cosmetic 结果、缺陷列表、other 说明、OSD 结果、是否带底座 |
| `manual_input` | 重量、Grade、Condition、颜色、尺寸、Mark |
| `network` | 有线状态、网卡名 |
| `result_reasons` | FAIL/WARN 原因列表 |
| `overall_result` | PASS / WARN / FAIL |

## 5. 可配置项

| 变量 | 默认 | 说明 |
|------|------|------|
| `UPLOAD_URL` | `http://192.168.30.18:80/monitor/api/upload` | 上传地址 |
| `MAX_DEAD_PIXELS` | 2 | 与服务端 `MONITOR_MAX_DEAD_PIXELS` 保持一致 |
| `DETECT_TIMEOUT` | 60s | Step 1 等待时间 |
| `PORT_TIMEOUT` | 30s | Step 6 单端口等待时间 |
| `MONITOR_REPORT_DIR` | `/root/monitor_reports` | 报告目录 |
| `MONITOR_TTY` / `MONITOR_DRM_ROOT` / `MONITOR_NET_ROOT` | — | 测试用覆盖项 |
| `SIZE_OPTIONS` / `COLOR_OPTIONS` / `MARK_OPTIONS` | 占位列表 | 待替换为 Cyclelution 显示器下拉列表（脚本内 TODO） |
