# GPU Test Client — Task Breakdown
**Script:** `gpu_test.sh` v1.0  
**依赖 skill:** `gpu_test_client_skill.md`

---

## Phase 0 — 脚手架（最先写，其他所有模块依赖它）

- [ ] **T01** 配置区变量（`UPLOAD_URL`, `LOG_DIR`, `TEST_DURATION`, `AUTO_MODE`, `AUTO_POWEROFF`, `SMI_INTERVAL`）
- [ ] **T02** 颜色函数：`banner()` `ok()` `warn()` `err()`（复制自 laptop_test.sh）
- [ ] **T03** `esc()` JSON转义函数（复制自 laptop_test.sh）
- [ ] **T04** `safe_exit()` 统一退出函数
- [ ] **T05** root 权限检查
- [ ] **T06** `LOG_DIR` 创建 + `TIMESTAMP` 生成 + 日志文件路径定义
- [ ] **T07** `trap` 注册：脚本退出时强制 kill SMI 后台进程

---

## Phase 1 — 依赖检查

- [ ] **T08** 检查通用依赖：`lspci`, `jq`, `curl`
- [ ] **T09** Vendor detection：`lspci | grep -iE 'vga|3d|display'` 判断 NVIDIA / AMD
- [ ] **T10** 按 vendor 检查工具：
  - NVIDIA：`nvidia-smi`, `gpu-burn`, `vkmark`
  - AMD：`rocm-smi`, `radeontop`, `vkmark`
- [ ] **T11** 缺失必要工具时打印安装命令并 `safe_exit 2`

---

## Phase 2 — L1 硬件识别

- [ ] **T12** NVIDIA 分支：`nvidia-smi --query-gpu` 采集所有 L1 字段（见 skill.md §4）
- [ ] **T13** AMD 分支：`rocm-smi --showallinfo` + 解析输出
- [ ] **T14** 公共：`lspci -v` + `lspci -n` 提取 PCIe Gen/Width/subvendor/device_id
- [ ] **T15** PCIe 降速检测：`pcie_width_current < pcie_width_max` → 设 `PCIE_DEGRADED=true`
- [ ] **T16** 将所有 L1 字段存入 bash 变量，终端打印摘要

---

## Phase 3 — 异步热监控

- [ ] **T17** NVIDIA：后台启动 `nvidia-smi -l $SMI_INTERVAL --query-gpu=... --format=csv > thermal.log &`，保存 PID
- [ ] **T18** AMD：后台启动 `rocm-smi` 循环采样 → `thermal.log &`，保存 PID
- [ ] **T19** 确认后台进程已启动（检查 PID 存活）

---

## Phase 4 — VRAM 压力测试

- [ ] **T20** NVIDIA：运行 `gpu-burn $TEST_DURATION`，捕获 stdout/stderr 到 `gpuburn.log`
- [ ] **T21** NVIDIA：解析 `gpuburn.log`，提取错误计数 → `VRAM_ERRORS`
- [ ] **T22** AMD：`timeout $TEST_DURATION vkmark --run-forever`，同步运行 `radeontop -d radeontop.log`
- [ ] **T23** AMD：从 `radeontop.log` 提取 GPU 利用率峰值

---

## Phase 5 — Vulkan 跑分

- [ ] **T24** 两个 vendor 都运行：`vkmark 2>&1 | tee vkmark.log`
- [ ] **T25** 解析 `vkmark.log`，提取最终 `Score: XXXX` → `VKMARK_SCORE`
- [ ] **T26** 若 `VKMARK_BASELINE_SCORE > 0`，比较分值，低于基准 20% 设 `VKMARK_WARN=true`

---

## Phase 6 — 热监控数据解析

- [ ] **T27** Kill SMI 后台进程（PID）
- [ ] **T28** 解析 `thermal.log`：提取 `TEMP_MAX`, `TEMP_AVG`, `UTIL_AVG`, `POWER_MAX`
- [ ] **T29** 温度阈值判断（NVIDIA >95°C FAIL，>85°C WARN；AMD >90°C FAIL，>80°C WARN）

---

## Phase 7 — dmesg GPU 错误检测

- [ ] **T30** 过滤 dmesg：`grep -iE 'gpu|nvrm|amdgpu|drm.*error|hang|reset|xid'`
- [ ] **T31** 有匹配行 → 存入数组，计入 FAIL 判定
- [ ] **T32** 构造 `DMESG_ERRORS_JSON` 数组

---

## Phase 8 — PASS/WARN/FAIL 综合判定

- [ ] **T33** 按 skill.md §6 规则，从各模块状态变量计算 `OVERALL_RESULT`
- [ ] **T34** 终端打印判定摘要（仿 ram_test 风格的表格）

---

## Phase 9 — JSON 构造与上传

- [ ] **T35** 用 `jq -n --arg / --argjson` 构造完整 JSON（结构见 skill.md §5）
- [ ] **T36** `jq . "$JSON_FILE"` 验证 JSON 合法性
- [ ] **T37** curl POST，3次重试，检测 HTTP 2xx → `UPLOAD_OK`
- [ ] **T38** 上传失败时保留本地文件并打印路径

---

## Phase 10 — 关机逻辑

- [ ] **T39** 实现与 ram_test 完全一致的关机逻辑：
  - `FAIL` → 打印 "DO NOT POWER OFF"，`touch /var/log/gpuburn_fail.flag`，无限 sleep
  - `WARN` → 30秒后 `poweroff`
  - `PASS` → 10秒后 `poweroff`
  - `AUTO_POWEROFF=0` → 按 `AUTO_MODE` 决定退出方式

---

## 任务顺序建议

```
T01-T07 → T08-T11 → T12-T16 → T17-T19 → T20-T23
→ T24-T26 → T27-T29 → T30-T32 → T33-T34
→ T35-T38 → T39
```

每个 Phase 完成后可独立测试，不需要等全部完成再跑。

---

## 测试验证检查点

| 检查点 | 验证方法 |
|--------|---------|
| Vendor detection 正确 | 在 NVIDIA/AMD 机器各跑一次 Step 1 |
| L1 字段完整 | `cat report.json \| jq .gpu` 对照 GPU-Z 截图核查 |
| PCIe 降速检测 | 手动将卡插到 x4 槽，确认 `pcie_degraded: true` |
| thermal.log 采样正常 | 压力测试中 `tail -f thermal.log` 观察 |
| FAIL 不关机 | `AUTO_POWEROFF=1` 下强制触发 FAIL，确认机器不关机 |
| JSON 上传 | MonitorCenter 收到记录，SN 可查 |

---

## 备注

- v1.0 不做多卡支持（检测到多卡时只测第一块，WARN 提示）
- v1.0 不做 `clpeak` OpenCL 带宽测试（预留 v2）
- `VKMARK_BASELINE_SCORE` 默认 0（不启用基准比较），上线后积累数据再填入
