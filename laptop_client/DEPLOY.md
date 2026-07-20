# deploy_script.sh — 部署说明

把客户端测试脚本(`laptop_test.sh` / `gpu_test.sh`)发布到 CearTrack 服务器,供测试机的
launcher 自动下载运行。

---

## 在哪里运行

**必须在服务器上运行**(192.168.30.18),不是在测试机、也不是在开发机。
脚本会把文件复制到服务器的静态目录 `/opt/monitorcenter/static/scripts/<module>/`。

前提:
- 已把最新的 `*_test.sh`(及其同目录的 `.conf` 等伴随文件)放到服务器某个目录
- 在该目录下运行 `deploy_script.sh`(它读取**当前目录**里的源脚本)

---

## 用法

```bash
# 指定脚本(推荐)
sudo bash deploy_script.sh laptop_test.sh    # 部署 laptop 模块
sudo bash deploy_script.sh gpu_test.sh       # 部署 gpu 模块

# 不带参数 → 交互式选择 1=laptop / 2=gpu
sudo bash deploy_script.sh
```

---

## 它做了什么(按顺序)

1. **确定源脚本**:用参数指定,或交互选择。源文件必须在当前目录存在。
2. **语法校验**:`bash -n` 检查源脚本,有语法错误就**拒绝部署**(绝不发布坏脚本)。
3. **自动识别模块**:从脚本里的 `UPLOAD_URL="http://.../<module>/api/upload"` 解析出
   `laptop` 还是 `gpu`。识别不到就报错退出。
4. **提取版本号**:从脚本里的 `SCRIPT_VERSION="x.y.z"` 这一行读取版本。
   这是**唯一版本来源**,自动生成服务器的 `version.txt`,保证脚本和版本号永不脱节。
5. **发布**:
   - 复制脚本 → `/opt/monitorcenter/static/scripts/<module>/<脚本名>`
   - 写版本 → `/opt/monitorcenter/static/scripts/<module>/version.txt`
   - 复制同目录所有 `*.conf` 伴随文件(如 gpu 的 `nvidia_legacy_db.conf`)到同一目录
6. **打印结果**:模块、版本、落地路径、对外 URL。

---

## 关键前提:先 bump 版本号

部署前**务必**在源脚本里把 `SCRIPT_VERSION` 改大(如 `1.1.1 → 1.2.0`)。
原因:测试机的 launcher 通过比对 `version.txt` 决定是否重新下载。
**版本号不变 → launcher 认为已是最新 → 继续跑旧缓存版本**,改动不生效。

源脚本里的位置:
```bash
SCRIPT_VERSION="1.2.0"   # gpu_test.sh 第 16 行附近
```

---

## 发布后对外地址

注意:两个模块的脚本都挂在 `/laptop/static` 路径下(Flask 的 STATIC_DIR 在此)。

```
http://192.168.30.18:80/laptop/static/scripts/<module>/version.txt
http://192.168.30.18:80/laptop/static/scripts/<module>/<脚本名>
```

例如 gpu:
```
http://192.168.30.18:80/laptop/static/scripts/gpu/version.txt
http://192.168.30.18:80/laptop/static/scripts/gpu/gpu_test.sh
http://192.168.30.18:80/laptop/static/scripts/gpu/nvidia_legacy_db.conf
```

这些正是 `launcher.sh` 里 `VERSION_URL` / `SCRIPT_URL` / `CONF_URL` 指向的地址。

---

## 完整发布流程(以 gpu 为例)

```bash
# 1.(开发机)改完 gpu_test.sh,bump SCRIPT_VERSION
# 2. 把 gpu_test.sh + nvidia_legacy_db.conf 传到服务器某目录,例如 ~/deploy/
# 3.(服务器)进入该目录,确保 deploy_script.sh 也在
cd ~/deploy
sudo bash deploy_script.sh gpu_test.sh
# 4. 验证对外可访问、版本正确
curl http://192.168.30.18:80/laptop/static/scripts/gpu/version.txt
```

测试机重启 / 重跑 launcher 时,会发现服务器版本变高 → 自动下载新脚本 → 运行。

---

## 常见问题

| 现象 | 原因 / 处理 |
|------|------------|
| `Source script not found` | 没在源脚本所在目录运行,或参数名拼错 |
| `has syntax errors — aborting` | 源脚本 `bash -n` 不过,先修语法 |
| `Could not detect module from UPLOAD_URL` | 脚本里 `UPLOAD_URL` 不是 `http://.../<module>/api/upload` 格式 |
| `Could not find SCRIPT_VERSION` | 脚本缺 `SCRIPT_VERSION="..."` 行 |
| 部署成功但测试机仍跑旧版 | **忘了 bump `SCRIPT_VERSION`**,launcher 版本号没变不下载;改大后重新部署 |
| 改了 `.conf` 但没生效 | `.conf` 必须和源脚本**同目录**,deploy 才会一起发布 |
