# Laptop Test & Monitorcenter Project

## Project Overview
回收公司硬件检测系统，两个独立但关联的子项目：

1. **laptop_test.sh** — 笔记本 Live USB 检测脚本
2. **monitorcenter** — 多模块硬件测试日志收集平台（Flask）

## Current Work
先完成 monitorcenter 的基础架构，支持 laptop 模块。
未来扩展 RAM / CPU / GPU / Wipe 模块。

## Skills
- `.claude/skills/laptop-test/SKILL.md` — laptop_test.sh 脚本规范
- `.claude/skills/monitorcenter/SKILL.md` — monitorcenter 平台架构

## Active Tasks
实现 monitorcenter，分 4 个任务按顺序完成：
- `tasks/monitorcenter/01_setup_skeleton.md` — 目录结构 + Flask 骨架
- `tasks/monitorcenter/02_laptop_module.md` — Laptop 模块实现
- `tasks/monitorcenter/03_frontend_dashboard.md` — Alpine.js 仪表盘
- `tasks/monitorcenter/04_landing_and_search.md` — 首页 + 全局搜索

## Critical Constraints — Do NOT Touch
- 不要修改任何现有的 RAM 测试代码（独立项目，生产运行中）
- 不要修改 `laptop_test.sh` 客户端（服务端负责 JSON 包装）
- 不要在 `core/` 里写模块特定逻辑（只能在 `modules/<n>/`）
- 不要引入构建工具（webpack/npm），vendor JS 本地打包

## Rules
- 部署路径: `/opt/monitorcenter/`
- Python 版本: 3.12
- 前端: Alpine.js + HTMX，无构建步骤
- 存储: 本地文件系统 JSON（无数据库）
- 所有模块 JSON 必须包含标准字段: `module, sn, timestamp, overall_result, summary, hostname, payload`
- SN 是跨模块主键，必须准确提取
- 修改完代码运行 `python -m py_compile <file>` 验证语法
- 不重写未改动的函数
