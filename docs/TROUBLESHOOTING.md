# gpu_test.sh — Troubleshooting 指南

记录排查过的问题、根因、修复方式,供以后参考。

---

## 1. 测试结束后屏幕黑屏(NVIDIA 卡,尤其 GeForce GTX 系列)

### 现象
- 启动初期能看到提示(扫码、依赖安装日志)
- glmark2(3D 测试)运行时屏幕有画面
- **glmark2 结束后屏幕纯黑**,看不到 PASS/verdict、看不到补扫码提示
- 机器是活的:可以 SSH 登录;在物理键盘按 Enter 会关机

### 根因(多个叠加)
1. **VT 切换**:glmark2 启动 X server 时,X 抢占一个独立的 VT(如 tty2),并把活动 VT 从脚本所在的 tty1 切到 tty2。
   - 脚本本身跑在 **tty1**(`login → bash → sudo gpu_test.sh`)
   - X 跑在 **tty2**(`/usr/lib/xorg/Xorg :0`)
2. glmark2 结束后,如果 verdict 输出在 tty1,但前台还停在 tty2 的 X 空窗口(黑),就看不见。

### 诊断命令(黑屏时通过 SSH 运行)
```bash
# 看进程占用哪个 tty,以及 X/xterm 是否在跑
ps aux | grep -E 'tty[0-9]|Xorg|/usr/bin/X|glmark|xterm' | grep -v grep
# 看当前活动 VT
sudo fgconsole
# 列出各 tty 归属
sudo ls -l /dev/tty[1-7]
```

判读:
- 若 `fgconsole` = 2 且 Xorg 在 tty2 → 前台是 X,verdict 在 tty1 被挡住
- 若**没有 xterm 进程**但脚本在等 read → 走了终端 verdict(在隐藏的 tty1)

### 手动验证 / 临时恢复
```bash
sudo chvt 1          # 切回 tty1(脚本和 verdict 所在),即可看到 PASS
# 物理键盘等效快捷键:Ctrl+Alt+F1
```

### 最终修复(当前版本采用)
**测试完 kill X + `chvt 1` 切回 tty1,所有 verdict / 补扫码都在 tty1 文本终端显示。**
- 不依赖图形界面(xterm)
- glmark2 后无条件:`kill X` → `chvt 1` → `printf '\033c'`(重置终端)

> 历史教训:曾尝试用 xterm 图形窗口显示 verdict,失败原因见下条。已放弃该方案。

---

## 2. (已废弃方案)xterm verdict 不显示

### 背景
曾经为了应对"NVIDIA tty1 黑屏假设",改用 xterm 图形窗口显示 verdict + 补扫码。

### 失败原因
- **GPU 脚本从未在依赖里安装 `xterm`** → `command -v xterm` 判断失败 → 跳过 xterm 分支 → 走 fallback 终端 verdict(又在被挡住的 tty1)→ 黑屏。
- 即使装了 xterm,NVIDIA 在 glmark2 后还有 DPMS 休眠 / VT 切换等一堆坑。

### 结论
**放弃 xterm 方案**。实测证明 GTX 1660 Ti 的 tty1 文本控制台是可见的(`Ctrl+Alt+F1` 能看到 PASS),所以回归"tty1 终端 verdict"最简单可靠。

### 教训
- 代码引用的命令(xterm/xset 等)必须确认在依赖安装列表里,否则静默走 fallback。
- 不要基于未经验证的假设(如"NVIDIA tty1 一定黑")设计复杂方案。

---

## 3. SN 字段被污染为 nvidia-smi 错误信息

### 现象
上传的 JSON 里 `sn` = `"NVIDIA-SMI has failed because it..."` 之类的错误文本。

### 根因
对 legacy 卡(老驱动无法识别),`nvidia-smi --query-gpu=serial` 返回错误字符串而非 N/A,被当作 GPU_SN 捕获,进而成为 TRACKING_ID → JSON `sn`。

### 修复
对 legacy 卡跳过 nvidia-smi SN 查询:
```bash
if [[ "${LEGACY_CARD:-0}" -eq 0 ]]; then
    _raw=$(nvidia-smi --query-gpu=serial ... )
    [[ -n "$_raw" && "$_raw" != "[N/A]" && "$_raw" != "N/A" ]] && GPU_SN="$_raw"
fi
```

---

## 4. 补扫码导致上传两份数据(重复记录)

### 现象
没扫码时,系统先用 Name+Timestamp 上传一次,补扫码后又用真 SN 上传一次。服务器以 `sn` 为主键 → 产生两条记录。

### 修复(方案 A:推迟上传)
**保证整个流程只上传一次,且用最终 SN。**
- 上传逻辑封装为 `do_upload()` 函数
- Step 9:**有 SN(扫了码)才立即上传;没扫码则推迟**,打印 "Upload deferred"
- Phase 10:补扫码确定最终 SN 后,才调 `do_upload()` 上传一次
- `_shutdown_exit_code` 计算移到上传之后(推迟上传时 UPLOAD_OK 在补扫码后才确定)

### 流程对照
```
扫了码:  Step 9 上传 → verdict → 关机
没扫码:  Step 9 跳过 → verdict → 补扫码(更新SN+重命名文件) → 上传一次 → 关机
```

---

## 5. 测试计时不准(包含安装时间)

### 现象
`total_duration_seconds` 高达 2400+ 秒(40 分钟),但实际测试只有 ~8 分钟。

### 根因
`TEST_START_EPOCH` 设在脚本最开始,把依赖安装 + 驱动安装时间(几十分钟)算进去了。

### 修复
计时起点移到 **Step 1(L1 硬件识别)之前**,即驱动安装完成后才开始计时。终点不变(Step 8 生成 JSON 时)。安装时间和关机等待都不计入。

---

## 6. Ctrl+C 关机提示不立即退出

### 现象
在"按 Enter 关机"提示处按 Ctrl+C,只打印了取消信息,但仍等操作员再按 Enter 才退出。

### 根因
INT trap 处理函数只设标志后返回,`read` 继续阻塞。

### 修复
trap 里先算好退出码,直接调 `safe_exit`,Ctrl+C 立即退出:
```bash
trap '
    echo "Shutdown cancelled. Run: sudo poweroff"
    trap - INT
    safe_exit '"$_shutdown_exit_code"'
' INT
read -r -s   # 阻塞等 ENTER
```

---

## 关键架构常识(排查前必读)

- **脚本运行在 tty1**(Live USB autologin → bash → sudo 脚本)
- **glmark2 会启动 X 占用另一个 VT(tty2)并切走前台**,测试后必须 `chvt 1` 切回
- **verdict / 补扫码统一在 tty1 文本终端显示**,不用图形界面
- **SN 优先级**:扫码 SN(CARD_LABEL) > 硬件 SN(企业卡) > Name+Timestamp
- **上传只发生一次**,用最终 SN,避免服务器重复记录
- **退出码**:0=PASS、1=FAIL、4=上传失败
- 改完脚本务必 `bash -n gpu_test.sh` 验证语法

---

## 通用诊断速查

| 症状 | 先查 |
|------|------|
| 测试后黑屏 | `sudo fgconsole`(是否停在 X 的 VT);`sudo chvt 1` 恢复 |
| 某功能静默跳过 | 对应命令是否在依赖安装列表(`command -v xxx`)|
| SN 异常 | JSON `sn` 字段;legacy 卡的 nvidia-smi 返回 |
| 重复记录 | 是否上传了两次(扫码 vs 补扫码)|
| 计时异常 | `TEST_START_EPOCH` 的位置 |
| SSH 能连但屏幕黑 | 机器是活的,纯属显示/VT 问题,不是死机 |
