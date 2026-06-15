文件：
  /opt/monitorcenter/modules/wipe/__init__.py
  /opt/monitorcenter/app.py

__init__.py：
  from .routes import wipe_bp
  from .integration import register_wipe_module
  __all__ = ["wipe_bp", "register_wipe_module"]

app.py（仅末尾追加两行，其他不动）：
  from modules.wipe.integration import register_wipe_module
  register_wipe_module(app)

验收：
  flask run
  # 日志出现：[WipePoller] started, interval=600s
  # 访问 http://localhost:5000/wipe/ 无报错
  curl http://localhost:5000/wipe/api/scan/status
  # poller_running: true