# Task 09 — MonitorCenter GPU 模块

## 目标
实现 MonitorCenter 的 GPU 模块，接收 `gpu_test.sh` 客户端上传的 JSON 报告，
并在仪表盘中展示检测结果。

## 参考文档
- 对接规范：`.claude/skills/monitorcenter/gpu_module_interface.md`
- 平台架构：`.claude/skills/monitorcenter/SKILL.md`
- 参考模块：`monitorcenter/modules/laptop/`（文件管理方式与此模块一致）

## 目录结构

```
monitorcenter/modules/gpu/
├── __init__.py
├── routes.py          # POST /gpu/api/upload + 页面路由
├── parser.py          # JSON 字段提取与验证
├── storage.py         # latest / history 文件管理（复用 laptop 模式）
└── templates/gpu/
    ├── dashboard.html  # 列表页（卡片）
    └── detail.html     # 详情页
```

## 任务步骤

### Step 1 — 接收接口
实现 `POST /gpu/api/upload`：
- 验证标准字段：`module / sn / timestamp / overall_result / summary / hostname / payload`
- 写入 `data/gpu/latest/{sn}.json`
- 归档到 `data/gpu/history/{sn}/{timestamp}.json`
- 返回 `{"status": "ok"}` (HTTP 200) 或错误信息 (HTTP 400)

### Step 2 — 列表页（dashboard）
卡片展示每台设备最新测试结果：
- 显卡名称（`payload.gpu.name`）
- VRAM（`payload.gpu.vram_mb` MB，`payload.gpu.vram_type`）
- 温度峰值（`payload.thermal.temp_max_c`°C）
- glmark2 分数（`payload.vulkan_benchmark.score`）
- PASS / WARN / FAIL 颜色标识
- 测试时间（`timestamp`）

### Step 3 — 详情页
展示单次测试完整信息：

**规格区（对齐 GPU-Z）**
- vendor / name / chip / vram_mb / vram_type / vram_bus_width
- driver_version / bios_version
- pcie_gen / pcie_width_current / pcie_width_max
- clock_gpu_mhz / clock_mem_mhz
- subvendor / device_id
- `gpu_sn`（显卡 SN，空时显示"N/A"）
- 顶层 `sn`（系统 SN，标注"System SN"）

**测试结果区**
- VRAM 测试：tool / duration / errors / status
- 温度：temp_max / temp_avg / util_avg / power_max
- glmark2：score / status

**特殊提示**
- `pcie_degraded: true` → 橙色提示框："PCIe 运行在 x{current}，设计最大 x{max}，请检查金手指接触"
- `dmesg_gpu_errors` 非空 → 展开显示错误行列表

### Step 4 — 历史记录
同一 sn 的多次测试结果时间线（参考 laptop 模块实现）

## 注意事项
- `overall_result` 在顶层和 `payload` 内各出现一次，以**顶层**为准
- `gpu_sn`（显卡 SN）与顶层 `sn`（系统 SN）含义不同，详情页需分别标注
- `pcie_degraded` 不影响 PASS/WARN/FAIL 判定，只做提示
- `vram_bandwidth_gbps` v1.0 固定为 0，展示时显示"N/A"
- VRAM 压力测试时长 `test_duration_seconds` 为 300s（5分钟）
