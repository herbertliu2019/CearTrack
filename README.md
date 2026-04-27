# CearTrack

Cear Hardware Test & Traceability Platform — 回收公司硬件检测系统。

两个独立但关联的子项目：

1. **`laptop_test.sh`** — 笔记本 Live USB 检测脚本。运行后采集系统/硬件/电池/存储/SMART/摄像头/音频/键盘/网络/外观等信息，自动 base64 编码摄像头测试图，最终上传 JSON 到 CearTrack。
2. **`monitorcentor/`** — Flask 多模块测试日志收集平台（即 CearTrack 服务端）。
   - 每个测试模块独立目录（目前仅 `laptop`，未来扩展 RAM / CPU / GPU / Wipe）
   - 文件系统 JSON 存储（`data/<module>/latest/` + `history/YYYY/MM-DD/`）
   - SQLite 索引层支持跨 SN 模糊搜索（含存储设备 SN）
   - Alpine.js + HTMX 前端，无构建工具
   - Today / Stats / Search 三个 tab，Stats 支持本周 / 本月 / 自定义日期范围

## Tech Stack
- Python 3.12 + Flask
- Alpine.js + HTMX（vendor 本地打包，无 npm/webpack）
- SQLite（仅作索引，文件系统是 source of truth）
- Bash（laptop_test.sh）

## Layout
```
laptop_test.sh                  # 客户端检测脚本
monitorcentor/
  app.py                        # Flask 入口
  config.py                     # BASE_DIR / INDEX_DB_PATH / 等
  core/
    storage.py                  # JSON 文件读写 + 一 SN 一记录
    index_db.py                 # SQLite 索引层
    envelope.py                 # 标准 envelope 构造
  modules/
    base.py                     # TestModule 抽象类
    laptop/
      module.py                 # /laptop/api/* endpoints
      schema.json               # 前端渲染 schema
      templates/module.html
  static/
    css/dashboard.css
    js/{app.js,renderer.js}
    vendor/{alpine.min.js,htmx.min.js}
  templates/{base.html,index.html}
tasks/                          # 任务规范 + session log
```

## 部署
见 `deplayment.txt`。生产环境路径 `/opt/monitorcenter/`，systemd + gunicorn。

## 业务规则
- 一台笔记本 = 一个 SN = 一份最终测试记录。重传同一 SN 时旧 history 文件全部删除。
- SN 是跨模块主键。
- 摄像头测试图以 base64 内嵌在 JSON 中，由 CearTrack 渲染缩略图（160×120），点击放大到原尺寸。
