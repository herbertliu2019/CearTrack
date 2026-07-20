# CearTrack — Monitorcenter Project
## General Guidelines
- Speak as concisely as possible. Skip all pleasantries and greetings.
- Never run automated test suites, build scripts, or formatters unless explicitly commanded.

## Project Overview
回收公司（Cear）硬件检测日志聚合平台，两个关联子项目：

1. **laptop_test.sh** — 笔记本 Live USB 检测脚本（客户端，不动）
2. **CearTrack / monitorcenter** — 多模块硬件测试日志收集平台（Flask）
3. **WIPE** — 硬盘擦洗 log 分析（XERASwin，已完成）

**部署路径:** `/opt/monitorcenter/`
**服务地址:** `192.168.30.18:5004`（直连）/ `192.168.30.18`（Nginx）

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12, Flask 3.x |
| Frontend | Alpine.js v3 + HTMX v1, Vanilla CSS |
| Storage | 本地文件系统 JSON（无数据库） |
| Auth | Flask session + werkzeug password hash |
| Proxy | Nginx reverse proxy |

无构建工具，无 npm，vendor JS 本地打包。

---

## Directory Structure

```
/opt/monitorcenter/
├── app.py
├── config.py                    BASE_DIR, API key, secret
├── requirements.txt
├── auth/
│   ├── routes.py                /login /logout /admin/users
│   ├── decorators.py            @login_required @module_required @admin_required
│   └── user_store.py            users.json 读写 + 密码 hash
├── core/
│   ├── storage.py               write_envelope(), read_latest(), search_sn()
│   ├── module_registry.py       自动发现 modules/
│   ├── envelope.py              build_envelope() — 包装原始 JSON
│   └── search.py                跨模块 SN 搜索
├── modules/
│   ├── base.py                  TestModule 抽象类
│   └── laptop/
│       ├── module.py            LaptopModule + Flask blueprint
│       └── schema.json          前端渲染 schema
├── static/
│   ├── css/dashboard.css
│   ├── js/
│   │   ├── app.js               Alpine dashboardApp()
│   │   └── renderer.js          schema 驱动渲染器
│   └── vendor/
│       ├── alpine.min.js
│       └── htmx.min.js
├── templates/
│   ├── base.html
│   ├── index.html
│   ├── login.html
│   ├── admin_users.html
│   └── module.html              通用模块仪表盘（Today/Stats/Search）
└── data/
    ├── users.json
    └── laptop/
        ├── latest/<SN>.json     每个 SN 最新结果（24h TTL）
        └── history/YYYY/MM-DD/<SN>_YYYYMMDD_HHMMSS.json
```

---

## Standard JSON Envelope

```json
{
  "module": "laptop",
  "sn": "034912262653",
  "timestamp": "2026-04-22T20:17:08-0700",
  "overall_result": "PASS",
  "summary": "All tests passed",
  "hostname": "test-rig-01",
  "warnings": [],
  "payload": { "...原始模块 JSON..." }
}
```

SN 是跨模块主键。客户端不需要格式化 envelope，服务端负责包装。

---

## Auth & Roles

| Role | Permissions |
|------|------------|
| `admin` | 所有模块 + 用户管理，不可删除 |
| `user` | 仅 admin 授权的模块 |

- API Key 上传：`X-API-Key: ceartrack-upload-2026`（定义在 `config.py`）
- Session：`session.permanent = False`，关闭浏览器失效
- 默认管理员：`admin` / `admin123`，首次登录立即修改

---

## Storage Logic

- **latest/**: 同 SN 重传 → 覆盖 latest + 删除旧 history 记录
- **history/**: 新上传前递归删除该 SN 所有历史文件，写入新时间戳文件
- 无删除 API，history 永久保留
- `_index/` JSONL 索引已在 `storage.py` 中 stub，待实现

---

## Module System

- `core/module_registry.py` 启动时自动扫描 `modules/`
- 新增模块：创建 `modules/<name>/module.py`（含 blueprint）+ `schema.json`，重启自动注册
- `core/` 内不写模块特定逻辑

### 模块状态

| Module | Status |
|--------|--------|
| `laptop` | ✅ 已上线 |
| `wipe` | ✅ 已上线（XERASwin log 解析） |
| `cpu` | ✅ 已上线（IPDT64 log 解析，含图片） |
| `gpu` | 🔲 规划中 |


---

## Pending Tasks

### monitorcenter (`tasks/monitorcenter/`)

| Task | Status |
|------|--------|
| Card expand (SN+timestamp key, multi-open) | ✅ Done |
| Re-upload SN 覆盖逻辑 | ✅ Done |
| By Brand + Fail Reasons 并排等高 | ✅ Done |
| 重命名 + Stats tab + bar charts | ✅ Done |
| 日历周/月统计，细柱，Storage 详情 | ✅ Done |
| **Auth 系统**（登录/角色/模块权限/用户管理） | ⬜ Pending |
| **Camera image 显示**（base64 在详情卡中） | ⬜ Pending |

### laptop_test.sh (`tasks/`)

| Task | Status |
|------|--------|
| stderr 重定向 prompt，JSON 值清洗 | ✅ Done |
| USB 存储过滤（TRAN==usb） | ✅ Done |
| dmesg fallback HARDWARE_DETECTED (IPU3/IPU6) | ✅ Done |
| **NVMe/SATA 健康评级 A-D**（smartctl -x） | ⬜ Done |
| **Camera base64 编码上传** | ✅Done |
| **Camera false positive 过滤**（GPU/ACPI） | ⬜ Pending |
| **evdev 键盘测试 + 布局显示** | ✅ Done |
| **evdev 触摸板自动检测** | ✅ Done |

---

## Critical Constraints


- **不动** `laptop_test.sh` 客户端（服务端负责 JSON 包装）
- **不在** `core/` 里写模块特定逻辑
- **不引入** 构建工具（webpack/vite/npm）

---

## Rules

- 修改代码后运行 `python -m py_compile <file>` 验证语法
- 不重写未改动的函数，用 targeted edit
- Nginx `proxy_pass` 无 trailing slash，Flask 须用 `static_url_path='/laptop/static'`
- 每次会话开始时读取 `tasks/shared_changes.md`，了解公共代码（core/、static/js/、templates/）的最新改动

---

## Skills & Reference

- `.claude/skills/laptop-test/SKILL.md` — laptop_test.sh 脚本规范
- `.claude/skills/monitorcenter/SKILL.md` — monitorcenter 平台架构
- `PROJECT_SUMMARY.md` — 完整技术文档（字段定义、已知问题、Nginx 配置）
- `monitorcenter/docs/cpu_module.md` — CPU 模块详细文档（架构/DB/扫描/SharePoint/调试）

---

*Last updated: 2026-05*
*Maintained by: Cear Testing*
