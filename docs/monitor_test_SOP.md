# Monitor Test SOP / 显示器测试操作规程

验收标准 Pass criteria：**坏点 0–2 个，无外观损伤** / **0–2 dead pixels, no cosmetic damage**

## 接线 / Station setup

| 接线 Connect | 说明 Notes |
|---|---|
| 网线 Network cable | 必须有 link，否则不能开测 / Link required before testing |
| USB 条码枪 Barcode scanner | 相当于键盘 / Works as a keyboard |
| 视频线 Video cable | 测试机 DP/HDMI → 显示器；**只接一台** / Connect **one** monitor only |
| 显示器电源 Monitor power | 开机 / Power on |

## 启动 / Start

1. 从 U 盘启动 Ubuntu。登录界面点齿轮，选 **Ubuntu on Xorg**（Wayland 下脚本会拒绝运行）。
   Boot the USB. On the login screen click the gear and pick **Ubuntu on Xorg** (the script refuses Wayland).
2. 打开终端 / Open a terminal：`sudo bash monitor_test.sh`
3. 输入 Operator ID（只输一次）。 / Enter your operator ID (asked once).

## 每台步骤 / Steps for each monitor

| 步骤 Step | 操作 Action | 按键 Keys |
|---|---|---|
| 1 检测 Detect | 等待自动识别（60 秒）。超时可重试或判坏 / Wait for auto-detect (60s) | `r` 重试 retry · `b` 判坏 mark bad · `q` 退出 quit |
| 3 扫 SN Scan | 扫显示器标签条码。不一致会要求重扫一次 / Scan the label barcode; a mismatch asks for one rescan | 条码枪 Scanner |
| 4 分辨率 Resolution | 确认显示器有画面 / Confirm the monitor shows a picture | `y` / `n`（`n` 记 FAIL / records FAIL） |
| 5 图案 Patterns | 看完 9 张图案，找坏点和漏光 / View all 9 patterns for dead pixels and light leaks | `→` 或 `空格` next · `←` back · `Esc` 结束 end |
| 5 录入 Enter | 坏点+亮点总数 0–99；背光 / Dead + bright pixel count 0–99; backlight | 数字 number · `p` / `f` |
| 6 接口 Ports | 填接口，如 `DP=1 HDMI=2`。按提示换线，必要时切换输入源，再按 Enter / Declare ports, e.g. `DP=1 HDMI=2`. Move the cable when asked, switch input if needed, press Enter | 超时 On timeout: `r` 重试 retry · `f` FAIL · `n` 没线/转接头 no cable or adapter |
| 7 外观 Cosmetic | 外观、OSD 按键、底座 / Cosmetic, OSD buttons, stand | `p` / `f`；OSD 另有 `s` 跳过 skip；底座 stand `y` / `n` |
| 7 录入 Enter | 重量、Grade、Condition、Color、Size、Mark / Weight, Grade, Condition, Color, Size, Mark | 按屏幕提示 Follow the prompts |
| 8 结果 Result | 看大字结果和原因，报告自动上传 / Read the large result and reasons; the report uploads automatically | — |

完成后拔下显示器，接下一台，按 **Enter** 继续；按 `q` 退出。
When done, unplug the monitor, connect the next one, press **Enter**; `q` quits.

## 结果 / Results

| 结果 Result | 含义 Meaning | 处理 Action |
|---|---|---|
| **PASS** | 全部通过 / All checks passed | 正常流转 / Continue |
| **WARN** | SN 不一致、测试机受限、OSD 故障、接口未测 / SN mismatch, station limit, OSD fault, port not tested | 看原因，按需复测 / Read the reasons, retest if needed |
| **FAIL** | 坏点 ≥3、外观/背光/接口故障、无信号 / 3+ dead pixels, cosmetic/backlight/port fault, no signal | 放到不良区 / Move to the reject area |

## 注意 / Notes

- **测试机受限 Station limited：** 测试机输出口跑不到 4K60 时结果为 WARN，不是显示器问题。换支持的接口可复测。 / A station port that cannot reach the native mode gives WARN, not a monitor fault. Retest on a capable port.
- **上传失败 Upload failed：** 报告留在 `/root/monitor_reports/pending/`，之后自动补传。 / Reports stay in `pending/` and re-upload automatically.
- **关机前 Before shutdown：** 如果退出时提示有 pending 报告，先接好网线重跑脚本补传，否则重启后可能丢失。 / If exit warns about pending reports, reconnect and re-run the script first; a reboot may lose them.
- **接口 PASS 的含义 What a port PASS means：** 只确认该口能读到同一台显示器的 EDID，换口时请顺便看一眼画面。 / It only confirms the same monitor's EDID is readable on that port, so glance at the picture when switching.
