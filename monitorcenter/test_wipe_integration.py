"""
验证 wipe 模块能完整注册进 Flask app，不报错。
不需要真实 SMB 挂载 — config 里的路径在 init_db 前不会被访问。
"""
import sys, os, tempfile, json
sys.path.insert(0, os.path.dirname(__file__))

# 用临时 db 路径覆盖 config，避免写入 /opt/
tmp_db = tempfile.mktemp(suffix=".db")
config_path = os.path.join(os.path.dirname(__file__), "config", "wipe_paths.json")
with open(config_path) as f:
    orig = json.load(f)
orig_db = orig["db_path"]
orig["db_path"] = tmp_db
with open(config_path, "w") as f:
    json.dump(orig, f, indent=2)

try:
    import app as flask_app

    # blueprint registered?
    rules = [r.rule for r in flask_app.app.url_map.iter_rules()]
    assert any(r.startswith("/wipe") for r in rules), "wipe blueprint not registered"
    print("Blueprint registered:", [r for r in rules if r.startswith("/wipe")])

    # config keys set?
    assert flask_app.app.config.get("WIPE_DB") == tmp_db
    assert flask_app.app.config.get("WIPE_CFG") is not None
    print("app.config WIPE_DB / WIPE_CFG: OK")

    # test /wipe/api/today responds
    with flask_app.app.test_client() as c:
        r = c.get("/wipe/api/today")
        assert r.status_code == 200
        data = r.get_json()
        assert "stats" in data and "records" in data
        print("/wipe/api/today:", data["stats"])

    # test /wipe/api/scan/status
    with flask_app.app.test_client() as c:
        r = c.get("/wipe/api/scan/status")
        assert r.status_code == 200
        print("/wipe/api/scan/status:", r.get_json())

    print("\nAll integration tests PASSED")

finally:
    # restore config
    orig["db_path"] = orig_db
    with open(config_path, "w") as f:
        json.dump(orig, f, indent=2)
    try:
        os.unlink(tmp_db)
    except FileNotFoundError:
        pass
