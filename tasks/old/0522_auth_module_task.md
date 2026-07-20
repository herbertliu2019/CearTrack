# Task 10 — MonitorCenter Auth 模块
**依赖 skill:** `auth_module_skill.md`  
**部署路径:** `/opt/monitorcenter/`  
**执行方式:** 交给 Claude Code 逐 Phase 完成，每 Phase 可独立验证

---

## Phase 0 — 准备工作

- [ ] **T01** 创建目录结构：
  ```
  /opt/monitorcenter/modules/auth/
  /opt/monitorcenter/modules/auth/templates/auth/
  ```
- [ ] **T02** 创建 `modules/auth/__init__.py`（空文件）
- [ ] **T03** 确认 `app.py` 有 `SECRET_KEY` 设置：
  ```python
  app.secret_key = os.environ.get('SECRET_KEY', 'change-this-in-production')
  ```
  没有则追加，不覆盖现有配置。
- [ ] **T04** 确认 `requirements.txt` 有 `werkzeug`（Flask 已依赖，通常已存在）

---

## Phase 1 — core/auth.py

**文件：** `core/auth.py`（新建）

- [ ] **T05** 实现用户数据读写：
  - `load_users()` → 读取 `data/users.json`，文件不存在返回 `{"users": []}`
  - `save_users(data)` → 写入，使用 `threading.Lock` 防并发写损坏
  - `get_user(username)` → 按 username 查找，返回 dict 或 None

- [ ] **T06** 实现认证函数：
  - `verify_password(username, password)` → 验证成功返回 user dict，失败返回 None
  - 失败时累加 `failed_attempts`，达到 5 次写入 `locked_until`（当前时间 + 15分钟）
  - 验证前检查 `locked_until`，未过期返回 None
  - 验证成功清零 `failed_attempts` 和 `locked_until`

- [ ] **T07** 实现 session 工具：
  - `login_user(user)` → 写入 `session['username']` / `session['role']` / `session['modules']`
  - `logout_user()` → `session.clear()`
  - `current_user()` → 从 session 读取 username，再从 users.json 返回完整 user dict

- [ ] **T08** 实现三个装饰器：
  - `login_required` → 未登录跳转 `/auth/login`
  - `admin_required` → 非 admin 返回 403
  - `module_required(module_name)` → 无权限返回 403

- [ ] **T09** `python -m py_compile core/auth.py`

---

## Phase 2 — manage.py

**文件：** `manage.py`（新建，项目根目录）

- [ ] **T10** 实现 `create-admin` 命令：
  ```bash
  python manage.py create-admin
  ```
  - 交互式输入 username 和 password（两次确认）
  - 检查 username 是否已存在，存在则报错退出
  - 用 `generate_password_hash` 哈希密码
  - 写入 `data/users.json`，role=admin，modules=["*"]

- [ ] **T11** 执行 `python manage.py create-admin`，创建初始管理员，确认 `data/users.json` 生成正确

---

## Phase 3 — modules/auth/module.py

**文件：** `modules/auth/module.py`

- [ ] **T12** 创建 blueprint：
  ```python
  blueprint = Blueprint('auth', __name__,
                         url_prefix='/auth',
                         template_folder='templates')
  ```

- [ ] **T13** 实现登录路由：
  - `GET /auth/login` → 已登录跳转首页，否则渲染 `login.html`
  - `POST /auth/login` → 调用 `verify_password`，成功调用 `login_user` 跳转首页，失败传递错误信息重新渲染

- [ ] **T14** 实现登出路由：
  - `GET /auth/logout` → 调用 `logout_user`，跳转 `/auth/login`

- [ ] **T15** 实现用户管理路由（均需 `@admin_required`）：
  - `GET /auth/users` → 渲染 `users.html`，传入用户列表和可用模块列表
  - `POST /auth/users/add` → 添加用户，username 唯一性校验，返回成功/失败
  - `POST /auth/users/<username>/toggle-active` → 切换 active 状态，不能操作自己
  - `POST /auth/users/<username>/reset-password` → 管理员重置他人密码
  - `POST /auth/users/<username>/modules` → 更新用户模块权限

- [ ] **T16** 实现修改密码路由（`@login_required`）：
  - `POST /auth/change-password` → 验证旧密码，更新哈希

- [ ] **T17** `python -m py_compile modules/auth/module.py`

---

## Phase 4 — 模板

**文件：** `modules/auth/templates/auth/login.html`  
**文件：** `modules/auth/templates/auth/users.html`

- [ ] **T18** 创建 `login.html`：
  - 独立页面（不依赖需要登录的 base.html）
  - 居中单列表单：username + password + 登录按钮
  - 错误提示区：显示"用户名或密码错误"（不区分两种情况）
  - 锁定提示：显示"账号已锁定，请 X 分钟后重试"
  - 深色主题，与现有 dashboard 风格一致

- [ ] **T19** 创建 `users.html`（继承 `base.html`）：
  - 顶部添加用户表单：username / password / role 下拉 / 模块多选（从 module_registry 读取）
  - 用户列表表格：username / role / 授权模块 / 状态 / 操作列
  - 操作列：重置密码按钮 / 启用禁用按钮 / 编辑权限按钮
  - 管理员自己的行隐藏"禁用"按钮
  - 所有操作通过表单 POST，无需 AJAX

---

## Phase 5 — 现有模块改造

- [ ] **T20** 检查所有现有模块的路由装饰器，统一改为从 `core.auth` 导入：
  ```python
  from core.auth import login_required, module_required
  ```
  涉及文件：`modules/gpu/module.py` / `modules/laptop/module.py` / `modules/wipe/module.py`

- [ ] **T21** 检查现有 `core/` 下是否有旧的 `login_required` / `module_required` 定义，
  确认与新 `core/auth.py` 不冲突（旧定义保留或删除，二选一，不能并存）

- [ ] **T22** 各模块语法检查：
  ```bash
  python -m py_compile modules/gpu/module.py
  python -m py_compile modules/laptop/module.py
  python -m py_compile modules/wipe/module.py
  ```

---

## Phase 6 — 集成测试

- [ ] **T23** 重启服务，访问任意页面，确认跳转到 `/auth/login`

- [ ] **T24** 用管理员账号登录，确认：
  - 登录成功跳转首页
  - 能访问所有模块
  - 导航栏显示"用户管理"入口

- [ ] **T25** 创建普通用户（只授权 gpu 模块），用该用户登录，确认：
  - 能访问 `/gpu/`
  - 访问 `/laptop/` 返回 403
  - 看不到"用户管理"入口

- [ ] **T26** 测试登录失败锁定：连续输错 5 次，确认第 6 次显示锁定提示

- [ ] **T27** 测试禁用用户：管理员禁用普通用户，该用户再次登录被拒绝

- [ ] **T28** 测试修改密码：普通用户修改自己密码，旧密码失效，新密码可登录

- [ ] **T29** 确认 Upload API 不受登录影响：
  ```bash
  curl -X POST http://192.168.30.18/gpu/api/upload \
    -H "X-API-Key: ceartrack-upload-2026" \
    -H "Content-Type: application/json" \
    -d @/tmp/test_gpu_payload.json
  ```
  返回 200（Upload 端点只验证 API Key，不需要 session）

---

## 验证命令速查

```bash
# 语法检查
python -m py_compile core/auth.py
python -m py_compile modules/auth/module.py

# 创建管理员
python manage.py create-admin

# 检查 users.json
cat /opt/monitorcenter/data/users.json

# 重启服务
systemctl restart monitorcenter
```

---

## 约束清单

- ❌ 不存明文密码
- ❌ 不引入数据库
- ❌ 不修改现有 `core/storage.py` / `core/envelope.py` / `core/module_registry.py`
- ❌ 管理员不能禁用或降级自己
- ✅ Upload API（`/*/api/upload`）只验证 X-API-Key，不需要 session
- ✅ `users.json` 写入加锁防并发损坏
- ✅ `SECRET_KEY` 通过环境变量设置
- ✅ 登录失败提示不区分"用户不存在"和"密码错误"
