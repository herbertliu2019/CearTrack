# Shared Changes Log

记录对公共代码的改动，供各模块 session 参考。
公共代码包括：`core/`、`static/js/`、`templates/`、`app.py`、`config.py`

---

## 格式

```
YYYY-MM-DD | 文件 | 改动内容 | 影响模块
```

---

## 记录

<!-- 在下方按时间倒序添加 -->

2026-11-06 | app.py, templates/base.html, templates/index.html | console 模块显示名改为 "Game Console"（导航、首页磁贴、搜索结果标签 module_label），URL/内部名不变 | 导航栏、首页、全站搜索

2026-11-05 | app.py, config.py, requirements.txt, templates/base.html, templates/index.html | 新增 console 模块接入：`/api/search` + `/api/summary` 各加 console，导航加 Console，首页加磁贴（7 张卡），config 加 CONSOLE_DB_PATH/CONSOLE_PHOTO_DIR，requirements 加 Pillow | 所有模块导航栏多一个链接；首页布局

2026-11-03 | app.py, config.py, templates/base.html, templates/index.html | 新增 monitor 模块接入：`/api/search` + `/api/summary` 各加 monitor，导航加 Monitor，首页磁贴改 auto-fit 网格（6 张卡，窗口够宽时仍一行） | 所有模块导航栏多一个链接；首页布局

2026-06-15 | static/js/app.js | week/month chart 改为当前周期截止今天（Sunday→today / 1st→today），修复 UTC drift（toISOString 在 PST/PDT 偏移导致日期错位），引入本地 ymd() helper | laptop, wipe（cpu/wipe dashboard 同步更新，但逻辑独立写在各自 HTML 内）

