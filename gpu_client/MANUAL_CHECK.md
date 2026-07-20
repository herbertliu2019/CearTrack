# GPU 可疑卡人工复核清单 / Manual GPU Health Check

配套脚本: `gpu_test.sh` (v1.4.1)
适用环境: Ubuntu Live USB (现场测试系统)

自动测试(`gpu_test.sh`)已覆盖大部分硬件故障。本文档列出**自动流程看不出来、需要
技术员手工命令复核**的项目。所有命令可直接复制到 Ubuntu 终端运行。

---

## 何时需要人工复核

满足以下任一情况时,建议按本清单复核:

- 自动测试给出 **WARN**(温度偏高、glmark2 异常、非致命 dmesg 事件)
- Step 6 报告 `dmesg Events: N (fatal:0 warn:N)` —— 想确认那些 warn 是不是真问题
- 二手卡**外观可疑**(风扇卡涩、电容鼓包、金手指氧化、维修痕迹)
- 客户/下游反馈**花屏、伪影、间歇性掉显示**
- 高价值专业卡/企业卡(Quadro / RTX A 系列 / Tesla)出库前二次确认

---

## 自动已覆盖 vs 需人工补充

| 检查项 | 自动测试 | 需人工补充 |
|--------|:--------:|:----------:|
| 显存读写错误 | ✅ gpu-burn / glmark2 | — |
| 过热 / 温度失控 | ✅ thermal monitor | — |
| 掉总线 / ECC 损坏 / 引擎挂死 | ✅ Step 6 致命 dmesg+Xid | — |
| 驱动能否识别卡 | ✅ Step 0 | — |
| **ECC 计数 / 显存页退役** | ❌ | ① |
| **PCIe 链路降速/降宽** | ❌ | ② |
| **风扇 / 供电 / 功率墙** | ❌ | ③ |
| **花屏 / 伪影(肉眼)** | ❌ | ④ |
| **长时间稳定性(>2分钟)** | ❌(默认 120s) | ⑤ |
| **多卡逐张** | ❌(只测第一张) | ⑥ |

---

## ① 显存 ECC 与页退役(仅企业/专业卡支持)

**目的**: gpu-burn 跑计算+显存,但不报 ECC 累积计数。专业卡的显存物理损坏会体现在
ECC 不可纠正错误和"页退役/行重映射"上。

```bash
# ECC 总览(消费卡通常显示 N/A,正常)
nvidia-smi -q -d ECC

# 不可纠正错误累积总数(理想值 = 0)
nvidia-smi --query-gpu=ecc.errors.uncorrected.aggregate.total --format=csv

# 退役的显存页 / 行重映射(Ampere 及更新)
nvidia-smi --query-remapped-rows=remapped_rows.failure,remapped_rows.uncorrectable,remapped_rows.pending --format=csv
nvidia-smi -q -d ROW_REMAPPER
```

**判读**:
- `remapped_rows.failure` > 0 → **显存物理损坏**,坚决不出库
- `ecc.errors.uncorrected.aggregate.total` 持续 > 0 → 显存可疑
- `remapped_rows.pending` > 0 → 需重启才生效,重启后复查
- 消费卡(GeForce)大多不支持 ECC,显示 N/A 属**正常**

---

## ② PCIe 链路降速 / 降宽

**目的**: 卡的金手指脏污、插槽接触不良、卡本身 PCIe 控制器问题,会导致链路跑不到
额定速度/宽度。

```bash
# 取 GPU 的 PCI 地址
GPU=$(lspci | grep -iE 'vga|3d' | head -1 | awk '{print $1}')

# 当前(LnkSta) vs 最大(LnkCap)链路速度与宽度
sudo lspci -vvv -s "$GPU" | grep -iE 'LnkCap:|LnkSta:'

# PCIe 错误计数(看 UncorrErr / CorrErr 是否非零)
sudo lspci -vvv -s "$GPU" | grep -iE 'UncorrErr|CorrErr|DevSta'
```

**判读**:
- `LnkSta` 速度/宽度 **远低于** `LnkCap`(如 Cap x16 但 Sta x4 / Gen1)→ 先清洁金手指、
  换插槽重测;清洁后仍降 → 卡的 PCIe 故障
- `UncorrErr` 非零 → PCIe 不可纠正错误,可疑
- `CorrErr` 少量 → **可接受**(已纠正),大量持续增长才需警惕
- 注意:部分低端卡(如 Quadro P400)**设计就是 x4/x8**,不是故障 —— 对比 LnkCap 判断

---

## ③ 风扇 / 供电 / 功率墙

**目的**: 二手卡常见风扇老化、供电不稳。自动测试不单独报风扇转速和功率墙触发。

```bash
# 风扇转速 / 实时功率 / 功率上限
nvidia-smi --query-gpu=fan.speed,power.draw,power.limit,temperature.gpu --format=csv -l 2

# 功率详情(看是否触发功率墙、电压异常)
nvidia-smi -q -d POWER

# 节流原因(throttle)与供电/温度告警
sudo dmesg | grep -iE 'power|thermal|throttl|perf.*cap'

# 实时节流状态(HW Slowdown / SW Thermal 等)
nvidia-smi -q -d PERFORMANCE
```

**判读**:
- 负载下 `fan.speed` 始终 0% 或不随温度上升 → 风扇故障
- `Clocks Throttle Reasons` 出现 **HW Slowdown / HW Power Brake** → 供电或散热问题
- `power.draw` 远低于 `power.limit` 但性能差 → 可能降频/供电不足
- 注意:被动散热卡(如部分 Tesla / 工作站卡)风扇读数 N/A 属**正常**

---

## ④ 花屏 / 伪影(只能肉眼)

**目的**: 压测分数正常 **不代表** 画面没问题。坏显存/坏显示输出常表现为花屏、色块、
闪烁,这类问题任何数值检测都抓不到,**必须接显示器肉眼看**。

```bash
# 接好显示器,在图形环境下运行可视化负载,人眼观察
glxgears                          # 最简单的转动齿轮,看有无撕裂/色块
__GL_SYNC_TO_VBLANK=0 glmark2     # 脚本同款,边跑边看屏幕

# 多接口卡:逐个视频口(HDMI/DP/DVI)都插一遍显示器测试
```

**判读**:
- 出现**花屏 / 雪花 / 固定色块 / 闪烁 / 拖影** → 显存或显示输出故障,不出库
- 某个接口黑屏但其他接口正常 → 该视频接口损坏(可标注后降级出售)
- 画面完全正常 → 通过

---

## ⑤ 长时间稳定性(怀疑间歇性故障时)

**目的**: 脚本默认压测 120s。有些卡短时正常,长跑后才掉卡/报错(散热膏老化、虚焊)。

```bash
# 拉长压测到 10 分钟,观察是否中途掉卡或报错
gpu-burn 600

# 另开一个终端(Ctrl+Alt+F2)实时盯温度/功率/util 有无异常跳变或归零
watch -n1 nvidia-smi

# 压测期间/之后再查一次内核日志有无新致命信号
sudo dmesg -T | tail -50
```

**判读**:
- 长压测**中途** `nvidia-smi` 突然查不到卡、util 归零、温度读数消失 → **掉卡**,严重故障
- 出现 `Xid 48/63/64/79/92/94/95` 或 `fell off the bus` → 真坏卡(与 TROUBLESHOOTING.md 第10节一致)
- gpu-burn 报 `errors` > 0 → 显存错误
- 全程稳定、0 errors → 通过

---

## ⑥ 多卡机器逐张测

**目的**: `gpu_test.sh` v1.1 限制只测**第一张** GPU。多卡机器其余卡需手工逐张验。

```bash
# 列出所有 GPU 及其编号
nvidia-smi -L

# 指定第 N 张卡单独压测(编号从 0 开始)
CUDA_VISIBLE_DEVICES=1 gpu-burn 120
CUDA_VISIBLE_DEVICES=2 gpu-burn 120

# 逐张查 ECC / 页退役
nvidia-smi -i 1 -q -d ECC
```

**判读**: 每张卡都应单独跑过压测 + ECC 复查,任意一张不过即标记。

---

## 判定速查表

| 读数 / 现象 | 结论 |
|------------|------|
| `remapped_rows.failure` > 0 | ❌ 真坏卡(显存物理损坏)|
| ECC `uncorrected aggregate` 持续 > 0 | ❌ 显存可疑 |
| 长压测中途掉卡 / `fell off the bus` | ❌ 真坏卡 |
| 致命 Xid(48/63/64/79/92/94/95) | ❌ 真坏卡 |
| 肉眼花屏 / 色块 / 闪烁 | ❌ 真坏卡 |
| 负载下风扇不转 / HW Power Brake | ⚠️ 散热或供电故障,需维修 |
| `LnkSta` 清洁金手指后仍远低于 `LnkCap` | ⚠️ PCIe 故障 |
| PCIe `CorrErr` 少量 | ✅ 可接受(已纠正)|
| 低端卡设计为 x4/x8(对比 LnkCap) | ✅ 正常 |
| 消费卡 ECC 显示 N/A | ✅ 正常(不支持 ECC)|
| 被动散热卡风扇读数 N/A | ✅ 正常 |

---

## AMD 卡对应命令

上面 NVIDIA 命令对 AMD 不适用,改用 rocm-smi / sysfs / lspci:

```bash
# 温度 / 功率 / 时钟 / 风扇
rocm-smi --showtemp --showpower --showclocks --showfan

# 实时监控
watch -n1 rocm-smi

# ECC(部分 Instinct/专业卡支持)
rocm-smi --showrasinfo all

# 显存信息
rocm-smi --showmeminfo vram

# PCIe 链路(同 NVIDIA,用 lspci)
GPU=$(lspci | grep -iE 'vga|3d' | grep -i 'amd\|ati' | head -1 | awk '{print $1}')
sudo lspci -vvv -s "$GPU" | grep -iE 'LnkCap:|LnkSta:|UncorrErr|CorrErr'

# 花屏 / 长压测:同 NVIDIA 用 glmark2 / glxgears 肉眼看
```

**判读**: 与 NVIDIA 同理 —— LnkSta 远低于 LnkCap、负载下风扇不转、长压测掉卡、肉眼
花屏,均判故障。
