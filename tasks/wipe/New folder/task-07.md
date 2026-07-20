TASK-07｜init.py + app.py 集成
文件：

/opt/monitorcenter/modules/wipe/__init__.py
/opt/monitorcenter/app.py（末尾追加两行）

__init__.py 内容：
  from .routes import wipe_bp
  from .integration import register_wipe_module
  __all__ = ["wipe_bp", "register_wipe_module"]

app.py 追加（仅末尾两行）：
  from modules.wipe.integration import register_wipe_module
  register_wipe_module(app)

验收：
flask run
访问 http://localhost:5000/wipe/
无报错，Today Tab 数据正常，
日志出现 "Wipe poller started"