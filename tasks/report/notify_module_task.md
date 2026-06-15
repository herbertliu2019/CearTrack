# Task 11 — MonitorCenter Teams 通知模块
**依赖 skill:** `notify_module_skill.md`  
**部署路径:** `/opt/monitorcenter/`  
**执行方式:** 交给 Claude Code 逐 Phase 完成，每 Phase 可独立验证

---

## 准备工作（Claude Code 开始前在服务器执行）

```bash
pip install apscheduler requests
echo "apscheduler>=3.10.0" >> /opt/monitorcenter/requirements.txt
echo "requests>=2.31.0"    >> /opt/monitorcenter/requirements.txt
```

---

## Phase 0 — 目录脚手架

- [ ] **T01** 创建目录结构：
  ```
  /opt/monitorcenter/modules/admin/
  /opt/monitorcenter/modules/admin/templates/admin/
  ```
- [ ] **T02** 创建 `modules/admin/__init__.py`（空文件）
- [ ] **T03** 创建初始 `data/notify_config.json`：
  ```json
  {
    "teams_webhook_url": "",
    "timezone": "America/Los_Angeles",
    "daily_report": {
      "enabled": false,
      "time": "17:30",
      "weekdays_only": true
    },
    "weekly_report": {
      "enabled": false,
      "day": "friday",
      "time": "17:30"
    }
  }
  ```
- [ ] **T04** 验证：`python -c "import json; json.load(open('data/notify_config.json'))"`

---

## Phase 1 — core/notifier.py

**文件：** `core/notifier.py`（新建）  
**依赖 skill:** `notify_report_format_skill.md`（各模块字段映射和 Card JSON 结构）

- [ ] **T05** 实现配置读写：
  - `load_config()` → 读取 `data/notify_config.json`，文件不存在返回默认结构
  - `save_config(config)` → 写入，使用 `threading.Lock` 防并发写

- [ ] **T06** 实现通用辅助函数：
  - `_load_day_records(module, date_str)` → 读取 `data/<module>/history/YYYY/MM-DD/` 下所有 JSON，返回列表
  - `_theme_color(pass_rate)` → 返回 themeColor 字符串（≥90% `"16a34a"` / 70-89% `"d97706"` / <70% `"dc2626"`）
  - `_no_data_card(module, date)` → 返回无数据占位 MessageCard dict（themeColor `"6b7280"`）
  - `send_to_teams(card)` → POST 到 webhook URL，timeout=10，失败只 log 返回 False

- [ ] **T07** 实现 Laptop Card 构造：
  - `build_laptop_daily_card(date)` → 按 `notify_report_format_skill.md §2` 构造 MessageCard
  - 聚合：total / pass / warn / fail / pass_rate / by_brand / fail_reasons
  - Warn=0 隐藏 `⚠ Warn` 行；Fail=0 隐藏 Fail Reasons section
  - Brand 未知归入"Other"

- [ ] **T08** 实现 GPU Card 构造：
  - `build_gpu_daily_card(date)` → 按 `notify_report_format_skill.md §3` 构造 MessageCard
  - 聚合：total / pass / warn / fail / pass_rate / by_vendor / by_subvendor / by_station / fail_reasons
  - fail_reasons 动态聚合：`vram_test.errors > 0` → "VRAM Error"；temp 超阈值 → "Overheat"；`pcie_degraded=true` → "PCIe Degraded"
  - Subvendor 未知归入"Other"；Warn=0 / Fail=0 时隐藏对应行

- [ ] **T09** 实现 CPU Card 构造：
  - `build_cpu_daily_card(date)` → 按 `notify_report_format_skill.md §4` 构造 MessageCard
  - 聚合：total / pass / by_series / by_core_count
  - Series 解析：名称含 i3/i5/i7/i9 → Intel 系列；含 Ryzen 3/5/7/9 → AMD 系列；其他归"Other"
  - By Core Count 动态生成，不硬编码
  - themeColor 固定绿色（默认全 Pass）

- [ ] **T10** 实现 Wipe Card 构造：
  - `build_wipe_daily_card(date)` → 按 `notify_report_format_skill.md §5` 构造 MessageCard
  - 聚合：total / pass / fail / pass_rate / by_device_type / by_manufacturer / fail_reasons
  - device_type 分三档：HDD / SSD / NVMe
  - fail_reasons 从数据动态读取，不硬编码
  - Manufacturer 未知归入"Other"；Fail=0 时隐藏 Fail Reasons section

- [ ] **T11** 实现统一推送函数：
  - `send_daily_reports(date=None)` → date 为 None 用今天，依次调用四个模块的 build + send
  - 每个模块独立 try/except，一个模块失败不影响其他模块推送

- [ ] **T12** `python -m py_compile core/notifier.py`

- [ ] **T13** Python shell 手动验证各模块 Card 结构：
  ```python
  import json
  from core.notifier import (build_laptop_daily_card, build_gpu_daily_card,
                              build_cpu_daily_card, build_wipe_daily_card)
  for fn in [build_laptop_daily_card, build_gpu_daily_card,
             build_cpu_daily_card, build_wipe_daily_card]:
      card = fn('2026-05-24')
      print(json.dumps(card, indent=2))
      print('---')
  ```

---

## Phase 2 — core/scheduler.py

**文件：** `core/scheduler.py`（新建）

- [ ] **T14** 实现 scheduler 初始化：
  - `init_scheduler(app)` → 从 config 读取时区，启动 BackgroundScheduler，注册任务
  - `reload_scheduler(config)` → 清除所有 job，按新 config 重新注册
  - `_register_jobs(config)` → 解析 HH:MM，按 skill §6 逻辑注册 CronTrigger
  - 每日任务调用 `send_daily_reports()`（四个模块统一推送）

- [ ] **T15** `python -m py_compile core/scheduler.py`

- [ ] **T16** 改造 `app.py`，在 app context 内调用 `init_scheduler`：
  ```python
  from core.scheduler import init_scheduler
  with app.app_context():
      init_scheduler(app)
  ```

- [ ] **T17** 重启服务，确认 scheduler 启动无报错：
  ```bash
  journalctl -u monitorcenter -n 30 --no-pager | grep -i scheduler
  ```

---

## Phase 3 — modules/admin/module.py

**文件：** `modules/admin/module.py`

- [ ] **T18** 创建 blueprint：
  ```python
  blueprint = Blueprint('admin', __name__,
                         url_prefix='/admin',
                         template_folder='templates')
  ```

- [ ] **T19** 实现 `GET /admin/settings`（`@admin_required`）：
  - 读取 `notify_config.json`
  - 渲染 `settings.html`，传入 config 和时区列表

- [ ] **T20** 实现 `POST /admin/settings/save`（`@admin_required`）：
  - 从 form 读取所有字段，构造新 config dict
  - 验证 time 格式（HH:MM），非法返回错误提示
  - `save_config(config)`
  - `reload_scheduler(config)`（立即生效，无需重启）
  - flash 成功提示，redirect 回 settings 页

- [ ] **T21** 实现 `POST /admin/settings/test`（`@admin_required`）：
  - 调用 `send_daily_reports()`，立即推送四个模块的今日报告
  - 返回 JSON：`{"ok": true}` 或 `{"ok": false, "error": "..."}`

- [ ] **T22** `python -m py_compile modules/admin/module.py`

---

## Phase 4 — settings.html

**文件：** `modules/admin/templates/admin/settings.html`

- [ ] **T23** 创建 `settings.html`，继承 `base.html`，深色主题

- [ ] **T24** Webhook 配置区：
  - Teams Webhook URL：全宽输入框，`type="password"`，placeholder 提示格式
  - 时区下拉：至少包含 `America/Los_Angeles` / `America/New_York` / `America/Chicago` / `UTC`

- [ ] **T25** 每日报告区：
  - 启用开关（checkbox styled as toggle）
  - 推送时间：`<input type="time">` 默认 17:30
  - 仅工作日：checkbox

- [ ] **T26** 每周报告区：
  - 启用开关
  - 推送时间：`<input type="time">` 默认 17:30

- [ ] **T27** 操作按钮区：
  - "Save Settings" 提交表单
  - "Send Test Message" → fetch POST `/admin/settings/test`，显示成功/失败提示（四个模块均推送）

- [ ] **T28** Flash 提示区：保存成功显示绿色提示条，失败显示红色

---

## Phase 5 — 导航栏集成

- [ ] **T29** 在 `base.html` 的导航栏中，管理员用户显示"⚙ Settings"链接指向 `/admin/settings`
  （只在 `session.role == 'admin'` 时显示）

- [ ] **T30** 重启服务，管理员登录后确认导航栏有 Settings 入口

---

## Phase 6 — 集成测试

- [ ] **T31** 管理员进入 `/admin/settings`，填写真实 Teams Webhook URL，保存

- [ ] **T32** 点击"Send Test Message"，确认 Teams 频道收到四个模块的卡片

- [ ] **T33** 检查每张卡片内容：
  - themeColor 颜色正确
  - 统计数字正确
  - 对应模块 Dashboard 链接可点击
  - 无数据模块显示占位卡片而非报错

- [ ] **T34** 修改推送时间为当前时间 + 2分钟，等待触发，确认四个模块自动推送

- [ ] **T35** 修改配置后确认 scheduler 立即重载（无需重启服务）：
  ```bash
  journalctl -u monitorcenter -n 20 --no-pager | grep -i job
  ```

- [ ] **T36** 测试无数据场景：构造一个无历史记录的日期，确认四个模块均推送占位卡片而非报错

- [ ] **T37** 验证 webhook URL 为空时"Send Test Message"返回友好错误，不崩溃

---

## 验证命令速查

```bash
# 语法检查
python -m py_compile core/notifier.py
python -m py_compile core/scheduler.py
python -m py_compile modules/admin/module.py

# 检查配置文件
cat /opt/monitorcenter/data/notify_config.json

# 查看 scheduler 日志
journalctl -u monitorcenter -n 50 --no-pager | grep -i "scheduler\|job\|notify"

# 重启服务
systemctl restart monitorcenter
```

---

## 约束清单

- ❌ 不改 `core/storage.py` / `core/envelope.py` / `core/module_registry.py`
- ❌ 不引入 Celery / Redis / 任何消息队列
- ❌ `send_to_teams()` 失败不能抛异常影响主服务
- ❌ Webhook URL 不在前端明文显示（`type="password"`）
- ✅ gunicorn 多 worker 时 scheduler 只在一个进程启动（`--preload` 模式或 `worker=1`）
- ✅ 当天无数据推送占位卡片，不跳过不报错
- ✅ 管理员保存配置后 scheduler 立即重载，无需重启
- ✅ 时区从 config 读取，不硬编码
