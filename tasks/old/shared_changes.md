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

2026-06-15 | static/js/app.js | week/month chart 改为当前周期截止今天（Sunday→today / 1st→today），修复 UTC drift（toISOString 在 PST/PDT 偏移导致日期错位），引入本地 ymd() helper | laptop, wipe（cpu/wipe dashboard 同步更新，但逻辑独立写在各自 HTML 内）

