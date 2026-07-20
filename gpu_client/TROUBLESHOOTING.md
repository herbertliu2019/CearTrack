# gpu_test.sh — Troubleshooting Guide

Script version: **1.4.0**  
Last updated: 2026-06-17

---

## 已记录问题总表 / Known Issues

| # | 现象 | 根因 | 解决 |
|---|------|------|------|
| 1 | glmark2 结束后屏幕全黑 | VT 切换问题 | `chvt 1` 回到 tty1 |
| 2 | SN 扫码提示不可见 | 旧版本缺少补扫码逻辑 | 更新到 v1.4.0 |
| 3 | 服务器出现重复记录 | 补扫码后二次上传 | 方案A: 延迟上传 |
| 4 | INFO_ONLY 卡显示上传失败 | verdict 屏幕在 do_upload() 之前读取 UPLOAD_OK | 先 do_upload 后 show_verdict |
| 5 | 计时 40 分钟（包含驱动安装）| TEST_START_EPOCH 在 Phase 0 之前 | 移至 Step 1 之前 |
| 6 | 新卡 "not supported by 535 driver" | 显卡太新，535 不支持 | ubuntu-drivers 自动选版本 |
| 7 | 老卡误报 REPLACE GPU | 驱动不匹配被判为硬件坏 | 安全闸门：驱动不匹配 → 不判坏卡 |
| 8 | 重启后测试不续跑 | 无自动恢复机制 | one-shot systemd 服务自动续跑 |
| 9 | SN 字段填入 nvidia-smi 错误文本 | 老卡 nvidia-smi 返回错误字符串 | LEGACY_CARD 保护，跳过 SN 查询 |

---

## 1. glmark2 结束后屏幕全黑

**触发场景**: GTX 1660 Ti、RTX 2060 等 NVIDIA 卡，glmark2 跑完后屏幕变黑，操作员什么都看不到。

**根因**: glmark2 在 tty2 起 X server，结束后 X 退出但 framebuffer 没有归还给 tty1，导致 tty1 不可见。  
（某些 NVIDIA 卡没有 fbdev framebuffer console，tty1 在 X 运行期间完全无输出。）

**解决方案**（已在 v1.4.0 实现）:
- glmark2 结束后执行：
  ```bash
  kill "$X_PID"
  chvt 1            # 切回 tty1
  sleep 1
  printf '\033c'    # 全终端复位（清屏 + 重置光标）
  ```
- 所有 verdict / 补扫码提示均在 tty1 文字终端输出，不依赖 X。

**现场验证方法**: 测试结束后按 `Ctrl+Alt+F1`，若能看到 PASS/WARN/FAIL 大字，说明工作正常。

---

## 2. SN 扫码提示不可见（黑屏时操作员不知道要扫码）

**根因**: 脚本在 Phase 1 提示扫码，此时 X 可能刚启动还在 tty2，tty1 的文字无法显示。

**解决方案**（已在 v1.4.0 实现）:  
补扫码逻辑移至 Phase 10（所有测试结束、X 已关闭、chvt 1 之后）：
- 如果 Phase 1 没有扫到 SN，测试完成后在 tty1 弹出：
  ```
  No SN was scanned at start. Scan card SN now (or Enter to skip):
  ```
- 操作员在大字 PASS/FAIL 屏前有明确扫码机会。

---

## 3. 服务器出现重复记录（同一张卡两条记录）

**触发条件**: Phase 1 没扫 SN，测试完成后在 Phase 10 补扫 SN。旧逻辑：Step 9 上传一次，Phase 10 补扫后再上传一次 → 共两条。

**解决方案（方案A）— 已在 v1.4.0 实现**:
- Step 9: 如果 `$CARD_LABEL` 为空，**跳过上传**，打印 "Upload deferred"。
- Phase 10: 补扫 SN → 更新 JSON 文件 → **唯一一次** `do_upload`。
- 无论有没有扫 SN，服务器最多收到一条记录。

---

## 4. INFO_ONLY 卡显示"上传 FAILED"（实际已成功）

**根因**: `show_verdict_screen()` 里读取 `$UPLOAD_OK` 变量，但该函数在 `do_upload()` 之前被调用，`UPLOAD_OK` 还是 0。

**解决方案**（已在 v1.4.0 实现）:  
执行顺序改为：
1. Phase 10 补扫 SN（如需要）
2. `do_upload`（设置 `UPLOAD_OK`）
3. `show_verdict_screen`（读取正确的 `UPLOAD_OK`）

---

## 5. 测试计时 40 分钟（包含驱动安装时间）

**根因**: `TEST_START_EPOCH` 设置在 Phase 0 之前，而 Phase 0 的驱动安装可能长达 30-40 分钟。实际 GPU 测试本身只需约 6-8 分钟。

**解决方案**（已在 v1.4.0 实现）:  
`TEST_START_EPOCH=$(date +%s)` 移至 Step 1（L1 识别）之前，Phase 0 安装时间不计入测试时长。

---

## 6. 新卡不支持（"not supported by NVIDIA 535 driver"）

**触发场景**: 安装了 535 驱动，`nvidia-smi` 报错：  
```
GPU 0000:01:00.0: not supported by the NVIDIA 535.xx.xx driver release
```

**根因**: 很新的 GPU（如 RTX 5000 系列 / Blackwell）需要 570+ 驱动，535 不识别它。

**解决方案**（已在 v1.4.0 实现）:
1. `nvidia_recommended_version()` — 查询 ubuntu-drivers 推荐的驱动分支号（如 "570"）。
2. `install_best_nvidia_driver()` — 安装匹配当前 GPU 的驱动（而不是硬编码 535）。
3. 若 dmesg 显示 "not supported by..."，尝试添加 `graphics-drivers/ppa` 再装一次。
4. 驱动装好后若需要重启 → 友好重启流程（见 Issue #8）。

**老卡政策（Kepler / Fermi）**:  
`ubuntu-drivers` 推荐版本 < 535 → 设置 `LEGACY_CARD=1`，跳过安装，仅采集 L1 信息（INFO_ONLY），**不安装** legacy 470/390 驱动，**不做压力测试**。

---

## 7. 坏卡误判 / REPLACE GPU 过度提示

**问题**: 以下情况不应该触发 REPLACE GPU 提示，但旧版本会误判：
- 新卡（驱动太旧，不支持该 GPU）
- 老卡（需要 legacy 驱动）
- 重启后驱动刚安装好，模块还没加载

**解决方案**（已在 v1.4.0 实现）:

### 三层保护

**第一层 — 安全闸门**（`detect_gpu_fatal_dmesg` 内部）:  
若 dmesg 包含驱动不匹配字样，直接 `return 1`（不判坏卡）：
```
not supported by the NVIDIA
supported through the NVIDIA
NVRM.*legacy
NVRM.*will ignore
```

**第二层 — 窄口径致命信号**:  
只认真正的硬件死亡信号（铁证）：
```
GPU has fallen off the bus
fell off the bus
RmInitAdapter failed
rm_init_adapter failed
GPU board failed to initialize
amdgpu.*GPU reset
ring gfx.*timeout
amdgpu.*fatal error
PCIe Bus Error: severity=Fatal
```
不包含 `NVRM: Xid`（多为软件/驱动内部错误）和 `nvidia.*probe.*failed`（与太新卡重叠）。

**第三层 — Step 0 独立判断**:  
Step 0 优先检查驱动不匹配 (`nvidia_driver_too_old`)，只有在排除驱动问题后，才调用 `detect_gpu_fatal_dmesg`。

### 验证用例
| 场景 | 预期 |
|------|------|
| 真坏卡（掉总线 fell off the bus） | → REPLACE GPU ✓ |
| 太新卡（10de:2d05, 535 不支持） | → NOT replace（驱动问题）✓ |
| 老卡 Kepler（需要 legacy 470）| → NOT replace（驱动问题）✓ |
| 健康卡（正常运行）| → NOT replace（无致命信号）✓ |

---

## 8. 重启后测试不自动续跑

**触发场景**: 新卡安装好驱动后提示需要重启。旧版本：打印一行 "run: sudo reboot"，操作员重启后要手动重跑。

**解决方案**（已在 v1.4.0 实现）:

### 友好重启屏幕
- 青色/绿色大字 "RESTART"（不用红色，不让操作员以为是报错）
- 中英双语：驱动已装好、需重启、**重启后自动继续测试**
- 按 **ENTER** 重启 / **Ctrl+C** 取消

### 自动续跑（one-shot systemd 服务）
- `schedule_resume_after_reboot()` 写入 `/etc/systemd/system/gpu-resume.service`
- 服务特点：
  - 重启后在 **tty1** 自动 exec 测试脚本
  - **第一条指令先自删**（`systemctl disable` + `rm -f`），绝不重复触发
  - 属于 `multi-user.target`，适用于命令行启动的测试系统
- `clear_resume_unit()` 在脚本每次启动时调用，清理残留单元

**注意**: 若现场机器重启后进入图形桌面（GNOME/KDE）而非命令行，systemd 单元仍会在后台运行，但 tty1 可能被桌面占用，自动续跑可能不可见。应确认测试 Live USB 以命令行模式（`multi-user.target`）启动。

---

## 9. SN 字段填入 nvidia-smi 错误文本

**触发场景**: 老卡（LEGACY_CARD=1）运行 `nvidia-smi --query-gpu=serial` 时，535 驱动拒绝识别该卡，返回的不是序列号而是错误字符串，导致 JSON 里 `sn` 字段填入错误内容。

**解决方案**（已在 v1.4.0 实现）:  
SN 查询代码用 `LEGACY_CARD` 保护：
```bash
if [[ "${LEGACY_CARD:-0}" -eq 0 ]]; then
    _raw=$(nvidia-smi --query-gpu=serial ...)
    ...
fi
```
老卡跳过 SN 查询，直接使用 barcode 扫码或 `GPU名+时间戳` 作为 ID。

---

## 10. dmesg 误报 FAIL（陈旧开机日志 / 非致命信号）

**触发场景 A — 陈旧开机日志**: 卡本身正常，但开机时驱动安装前产生大量 `NVRM: probe routine failed` 日志，Step 6 全部扫到 → OVERALL FAIL。(如 336 条集中在 t≈101s)

**触发场景 B — 非致命 Xid**: 压力测试期间出现 Xid 13/31/43/45 等应用/驱动层错误，旧版本"Xid 一律 FAIL"，好卡被误杀。

**解决方案（v1.4.1）**:

### 修复 A — 测试前清空环形缓冲

Step 1b 健康检查之后、压力测试之前执行 `dmesg -C`。Step 6 此后只看**测试期间**产生的信号，开机陈旧日志物理上不存在了。

### 修复 B — 三级分类

Step 6 不再把所有 GPU 相关 dmesg 行一律判 FAIL，改为三级：

| 级别 | 判定 | 包含的信号 |
|------|------|-----------|
| **FATAL → FAIL** | 硬件死亡铁证 | 掉总线、RmInitAdapter failed、board failed、amdgpu reset/timeout/fatal、PCIe Fatal、**致命 Xid 48/63/64/79/92/94/95**（ECC 损坏/掉总线）|
| **非致命 → WARN** | 可恢复/瞬态 | 其余 GPU error/reset/hang/fault、**非致命 Xid 13/31/43/45**（应用/驱动层）|
| **噪音 → 忽略** | 不影响 verdict | `warn` 关键词、probe routine failed、firmware load、severity=Corrected、i2c timeout |

verdict 表新格式:
```
dmesg Events:      3 (fatal:0 warn:3)
```

### 关键原则

**Xid 不能一刀切**：Xid 是事件代码族，大多数是软件层：
- 软件层（WARN）: 13=graphics exception, 31=FIFO, 43=channel preemption, 45=preempt timeout
- 硬件层（FAIL）: 48=双比特 ECC, 63/64=ECC 页退役, 79=掉总线, 92/94/95=不可纠正显存错误

真正坏卡的信号：`GPU has fallen off the bus`、`RmInitAdapter failed`、**测试期间**反复出现的致命 Xid、gpu-burn 报 VRAM errors。

---

## 部署流程快速参考

```bash
# 开发机改好 gpu_test.sh，确认 SCRIPT_VERSION 已 bump
# 将文件传到服务器，然后在服务器上：
cd ~/deploy   # 含 gpu_test.sh + deploy_script.sh + nvidia_legacy_db.conf
sudo bash deploy_script.sh gpu_test.sh
# 验证：
curl http://192.168.30.18:80/laptop/static/scripts/gpu/version.txt
```

测试机重跑 launcher.sh 后会自动下载新版本。

---

## 驱动版本兼容性速查

| GPU 世代 | 推荐驱动分支 | 脚本策略 |
|----------|------------|---------|
| Fermi (GF1xx) | 390.xx | INFO_ONLY（不安装 legacy）|
| Kepler (GK1xx) | 470.xx | INFO_ONLY（不安装 legacy）|
| Maxwell/Pascal/Turing/Ampere | 535+ | FULL test |
| Ada Lovelace / Blackwell | 565-570+ | ubuntu-drivers 自动选版 + FULL test |

判断逻辑：`nvidia_recommended_version()` 返回的版本号 < 535 → INFO_ONLY，否则 → 安装并测试。
