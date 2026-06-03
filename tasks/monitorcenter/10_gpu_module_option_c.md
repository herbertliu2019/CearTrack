# Task 10 — GPU Module (Option C Hybrid Display) ✅ COMPLETED 2026-05-22

## 前置条件
- 先完成 Task 09（GPU 接收接口 POST /gpu/api/upload）
- 参考已有的 laptop 模块实现方式（modules/laptop/module.py + templates/module.html）
- 本 task 专注于**展示层**的方案 C 实现

---

## 背景：为什么用方案 C

gpu_test.sh 客户端持续添加新字段（compute_arch、bar1_mb、resizable_bar、
clock_base_gpu_mhz 等），固定写死模板每次都要改。

**方案 C（混合）**：
- 顶部摘要卡片固定展示核心信息（名称/VRAM/结果/温度/分数）
- 展开后的"GPU 规格"区块**动态遍历 payload.gpu 所有字段**自动渲染
- 客户端加新字段 → 页面自动出现，无需改模板

---

## 客户端发送的 JSON 结构（v1.1）

```json
{
  "module": "gpu",
  "sn": "NVIDIA_GeForce_RTX_2080_SUPER_20260514_130609",
  "timestamp": "2026-05-14 13:06:09",
  "overall_result": "PASS",
  "summary": "GPU:NVIDIA GeForce RTX 2080 SUPER VRAM:8192MB TEMP_MAX:83C VKMARK:20712 RESULT:PASS",
  "hostname": "192.168.30.32",
  "payload": {
    "test_info": {
      "test_time": "2026-05-14 13:06:09",
      "test_station": "GPUTESTSTATION1",
      "test_tier": "FULL",
      "script_version": "1.1.0",
      "burn_duration_seconds": 120,
      "glmark2_duration_seconds": 332,
      "total_duration_seconds": 508
    },
    "gpu": {
      "vendor": "NVIDIA",
      "name": "NVIDIA GeForce RTX 2080 SUPER",
      "chip": "TU104",
      "vram_mb": 8192,
      "vram_type": "GDDR6",
      "vram_bus_width": 256,
      "vram_bandwidth_gbps": 496.1,
      "driver_version": "535.288.01",
      "legacy_driver_needed": "",
      "bios_version": "90.04.7A.80.32",
      "pcie_gen": 3,
      "pcie_gen_current": 1,
      "pcie_width_current": 4,
      "pcie_width_max": 16,
      "clock_boost_gpu_mhz": 2100,
      "clock_boost_mem_mhz": 7751,
      "clock_base_gpu_mhz": 1500,
      "clock_base_mem_mhz": 7001,
      "compute_arch": "CUDA 7.5",
      "bar1_mb": 256,
      "resizable_bar": false,
      "power_limit_w": "250.00",
      "subvendor": "ASUSTeK Computer Inc. TU104 [GeForce RTX 2080 SUPER]",
      "device_id": "10DE:1E81",
      "gpu_sn": ""
    },
    "thermal": {
      "temp_max_c": 83,
      "temp_avg_c": 62,
      "util_avg_pct": 91,
      "power_max_w": 255.0,
      "thermal_log_path": "/tmp/gpu_logs/thermal_20260514_130609.log"
    },
    "vram_test": {
      "tool": "gpu-burn",
      "duration_seconds": 120,
      "errors": 0,
      "status": "PASS"
    },
    "vulkan_benchmark": {
      "tool": "glmark2",
      "score": 20712,
      "status": "PASS"
    },
    "dmesg_gpu_errors": [],
    "overall_result": "PASS"
  }
}
```

**INFO_ONLY 卡（低 VRAM 或 legacy 显卡）的区别：**
- `overall_result`: `"INFO_ONLY"`
- `payload.test_info.test_tier`: `"INFO_ONLY"`
- `payload.vram_test.status`: `"SKIPPED"`
- `payload.vulkan_benchmark.status`: `"SKIPPED"`
- `payload.gpu.legacy_driver_needed`: `"470xx"` 或 `"390xx"`（非空）
- `payload.gpu.compute_arch`: `""` （空字符串）

**AMD 显卡区别：**
- `payload.gpu.vendor`: `"AMD"`
- `payload.gpu.compute_arch`: `"gfx1030"` / `"gfx803"` 等 ROCm 代号
- `payload.gpu.cuda_*` 字段不存在

---

## 文件结构

```
monitorcenter/modules/gpu/
├── __init__.py          （空文件）
├── module.py            ← 主要实现
└── templates/gpu/
    └── module.html      ← 仪表盘模板
```

参考 `modules/laptop/` 的注册方式，auto-discovery 会自动找到 `module.py`。

---

## Step 1 — module.py

参考 `modules/laptop/module.py`，实现 GpuModule 类。

**关键区别：** laptop 客户端发送的是 raw payload，GPU 客户端发送的是**完整 envelope**
（顶层已有 sn / timestamp / overall_result / summary / hostname / payload）。
所以 `extract_envelope` 直接读取顶层字段，不需要再构建。

```python
class GpuModule(TestModule):
    name = "gpu"
    display_name = "GPU Test"
    icon = "gpu"

    def extract_envelope(self, raw: dict) -> dict:
        # GPU 客户端直接发完整 envelope，直接透传
        return {
            "module":         self.name,
            "sn":             raw.get("sn", "unknown"),
            "timestamp":      raw.get("timestamp", ""),
            "overall_result": str(raw.get("overall_result", "UNKNOWN")).upper(),
            "summary":        raw.get("summary", ""),
            "hostname":       raw.get("hostname", "unknown"),
            "payload":        raw.get("payload", {}),
        }

    def compute_verdict(self, envelope: dict) -> dict:
        # 客户端已计算好，直接透传
        return {
            "result":  envelope.get("overall_result", "UNKNOWN"),
            "summary": envelope.get("summary", ""),
        }

    def get_display_schema(self) -> dict:
        return {}  # 方案 C 不需要 schema，动态渲染

    def validate(self, raw: dict):
        for f in ("sn", "timestamp", "overall_result", "payload"):
            if f not in raw:
                return False, f"Missing required field: {f}"
        return True, "OK"
```

**API 端点：**

- `GET /gpu/` — 仪表盘页面
- `POST /gpu/api/upload` — 接收上传（返回 HTTP 201）
- `GET /gpu/api/latest` — 今天的记录列表
- `GET /gpu/api/search?sn=...` — 按 SN 查询
- `GET /gpu/api/schema` — 返回 `{}`
- `GET /gpu/api/stats` — 今天的统计（total/pass/warn/fail/info_only/pass_rate）
- `GET /gpu/api/stats/range?range=week|month` 或 `?from=YYYY-MM-DD&to=YYYY-MM-DD`

**stats/range 返回结构：**

```json
{
  "date_from": "2026-05-18",
  "date_to":   "2026-05-24",
  "total":     42,
  "passed":    35,
  "warned":    2,
  "failed":    1,
  "info_only": 4,
  "pass_rate": 83.3,
  "vendors":   [["NVIDIA", 38], ["AMD", 4]],
  "fail_reasons": [["VRAM Errors", 1]],
  "daily":     [{"date":"2026-05-20","total":10,"passed":8,"failed":1}],
  "records":   [...]
}
```

**fail_reasons 判断逻辑：**
```python
if p.get("vram_test", {}).get("errors", 0) > 0:
    fail_reasons["VRAM Errors"] += 1
if p.get("dmesg_gpu_errors"):
    fail_reasons["dmesg GPU Errors"] += 1
vendor = p.get("gpu", {}).get("vendor", "")
thresh = 95 if vendor == "NVIDIA" else 90
if p.get("thermal", {}).get("temp_max_c", 0) > thresh:
    fail_reasons["Overheat"] += 1
```

---

## Step 2 — templates/gpu/module.html（方案 C）

继承 `base.html`，使用 Alpine.js 组件 `gpuApp()`。

### 2.1 卡片固定显示区

每张卡片展示（无需展开即可看到）：

```
┌─────────────────────────────────────────────────────────┐  ← 左边框颜色 = 结果
│  NVIDIA GeForce RTX 2080 SUPER              [PASS]     │
│  NVIDIA  •  TU104  •  CUDA 7.5                          │
│  VRAM 8192MB GDDR6  BW 496GB/s  PCIe Gen3 x4/x16       │
│  [VRAM ✓] [glmark2 ✓] [83°C] [2m ✓]                    │  ← 状态点
│  2026-05-14 13:06  NVIDIA_GeForce_RTX_2080_SUPER_...    │
└─────────────────────────────────────────────────────────┘
```

卡片左边框颜色：
- `PASS` → `var(--pass)` 绿色
- `WARN` → `var(--warn)` 黄色
- `FAIL` → `var(--fail)` 红色
- `INFO_ONLY` → `#6b9bd2` 蓝色

副标题 `gpuSubLine(r)`：
```javascript
const g = r.payload?.gpu ?? {};
const parts = [g.vendor, g.chip, g.compute_arch].filter(Boolean);
if (g.legacy_driver_needed) parts.push(`needs ${g.legacy_driver_needed}`);
return parts.join('  •  ');
```

### 2.2 展开后的 Detail（方案 C 核心）

展开分三个区块：

**区块 1：Test Results（固定，仅 FULL tier 显示）**

```
TEST RESULTS
─ VRAM Test:   PASS — gpu-burn, 0 errors, 120s
─ Benchmark:   PASS — glmark2 20712
─ Thermal:     83°C max / 62°C avg  •  91% util  •  255W
─ dmesg:       （无错误时不显示）
```

`INFO_ONLY` 时跳过此区块（vram_test 和 vulkan_benchmark 均为 SKIPPED）。

**区块 2：GPU Specs（动态，方案 C 核心）**

```javascript
// 遍历 payload.gpu 全部字段，自动渲染
for (const [k, v] of Object.entries(r.payload?.gpu ?? {})) {
    const label = fmtKey(k);
    const val   = fmtVal(k, v);
    if (val === null) continue;  // 跳过空值
    // 渲染一行 <tr><td>label</td><td>val</td></tr>
}
```

**字段标签映射表 `fmtKey(k)`：**

| JSON key | 显示标签 |
|----------|---------|
| `vendor` | Vendor |
| `name` | Name |
| `chip` | Chip |
| `device_id` | Device ID |
| `subvendor` | Sub-Vendor |
| `bios_version` | BIOS |
| `driver_version` | Driver |
| `legacy_driver_needed` | Legacy Driver Needed |
| `vram_mb` | VRAM |
| `vram_type` | VRAM Type |
| `vram_bus_width` | Bus Width |
| `vram_bandwidth_gbps` | Bandwidth |
| `gpu_sn` | GPU SN |
| `pcie_gen` | PCIe Gen |
| `pcie_gen_current` | PCIe Gen (Current) |
| `pcie_width_current` | PCIe Width (Current) |
| `pcie_width_max` | PCIe Width (Max) |
| `clock_boost_gpu_mhz` | GPU Clock (Boost) |
| `clock_boost_mem_mhz` | Mem Clock (Boost) |
| `clock_base_gpu_mhz` | GPU Clock (Base) |
| `clock_base_mem_mhz` | Mem Clock (Base) |
| `compute_arch` | Compute Arch |
| `bar1_mb` | BAR1 Size |
| `resizable_bar` | Resizable BAR |
| `power_limit_w` | Power Limit |
| 其他 | snake_case → Title Case |

**值格式化 `fmtVal(k, v)`：**

```javascript
function fmtVal(k, v) {
    if (v === null || v === undefined) return null;
    if (v === '') return null;                        // 空字符串跳过
    if (v === true)  return '✓';                     // 布尔 true
    if (v === false) return '✗';                     // 布尔 false
    // 特定字段为 0 时跳过
    const skipZero = ['clock_base_gpu_mhz', 'clock_base_mem_mhz',
                      'bar1_mb', 'vram_bandwidth_gbps'];
    if (v === 0 && skipZero.includes(k)) return null;
    // 自动加单位
    const units = {
        vram_mb: ' MB', bar1_mb: ' MB',
        vram_bandwidth_gbps: ' GB/s',
        clock_boost_gpu_mhz: ' MHz', clock_boost_mem_mhz: ' MHz',
        clock_base_gpu_mhz:  ' MHz', clock_base_mem_mhz:  ' MHz',
        power_limit_w: ' W',
        vram_bus_width: '-bit',
    };
    return `${v}${units[k] ?? ''}`;
}
```

**特殊高亮：**
- `resizable_bar: true` → 绿色显示 ✓
- `resizable_bar: false` → 灰色显示 ✗
- 未来加新字段 → 自动出现在表格里，无需改模板

**区块 3：Test Info（固定）**

```
TEST INFO
─ Script Version:  1.1.0
─ Test Tier:       FULL
─ Station:         GPUTESTSTATION1
─ Burn Duration:   120s
─ Total Duration:  508s
```

### 2.3 统计 Tab（Week / Month / Custom）

KPI 格（5格）：Total / Pass / Warn / Fail / Info Only

两栏并排：
- 左：**By Vendor**（NVIDIA N 台 / AMD N 台）
- 右：**Fail Reasons**（VRAM Errors / Overheat / dmesg Errors）

历史记录列表（紧凑行，只显示名称 + 结果 + 日期）。

---

## Step 3 — base.html 导航更新

在 `templates/base.html` 的 `<nav>` 里添加 GPU 链接：

```html
<a href="/gpu/">GPU</a>
```

---

## 注意事项

1. **存储路径**：`data/gpu/latest/<sn>.json` 和 `data/gpu/history/YYYY/MM-DD/<sn>_<ts>.json`
   参考 `core/storage.py` 的 `write_envelope()` — 传入 module_name="gpu" 即可

2. **sn 字段**：GPU 客户端无 GPU 硬件 SN 时，sn = `GPU名称_时间戳`（如 `NVIDIA_GeForce_RTX_2080_SUPER_20260514_130609`）

3. **overall_result 有 4 种值**：`PASS` / `WARN` / `FAIL` / `INFO_ONLY`
   统计和显示都要处理 INFO_ONLY（不算 PASS 也不算 FAIL）

4. **向后兼容旧字段名**：
   旧版客户端用 `clock_gpu_mhz` / `clock_mem_mhz`，
   新版用 `clock_boost_gpu_mhz` / `clock_boost_mem_mhz`。
   动态渲染方案 C 自动兼容，两者都会显示，无需特殊处理。

5. **语法验证**：每改一个 .py 文件后运行
   `python -m py_compile <file>`

---

## 验收标准

- [ ] POST /gpu/api/upload 接收 JSON，返回 HTTP 201
- [ ] GET /gpu/ 打开仪表盘，Today 显示今天的测试记录
- [ ] 卡片左边框颜色正确（绿/黄/红/蓝）
- [ ] 展开卡片 → 显示 Test Results + 动态 GPU Specs + Test Info
- [ ] GPU Specs 区块包含 compute_arch / resizable_bar / bar1_mb 等新字段
- [ ] INFO_ONLY 卡片：Test Results 区块跳过，显示蓝色边框
- [ ] AMD 显卡：compute_arch 显示 gfx1030 等，无 CUDA 字样
- [ ] Week / Month tab：5格 KPI + By Vendor + Fail Reasons + 历史列表
- [ ] base.html nav 有 GPU 链接
