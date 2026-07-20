# Task: Add Authentication & Authorization System to CearTrack

## Requirements Summary

- Login/logout with username + password
- Two roles: `admin` and `user`
- Admin can manage users (add/delete/assign module permissions) via UI
- Regular users can only view — no delete of any test records
- Session expires on browser close (no persistent cookie)
- Module-level permissions: admin accesses all modules by default;
  users need explicit per-module permission granted by admin
- All user data stored in a JSON file (no database needed)

---

## File Structure Changes

```
/opt/monitorcenter/
├── auth/
│   ├── __init__.py
│   ├── routes.py          ← /login, /logout, /admin/users
│   ├── decorators.py      ← @login_required, @module_required('laptop')
│   └── user_store.py      ← read/write users.json
├── data/
│   └── users.json         ← user accounts + permissions
└── templates/
    ├── login.html          ← login page
    └── admin_users.html    ← user management page (admin only)
```

---

## Part 1: User Store — `auth/user_store.py`

Users stored in `/opt/monitorcenter/data/users.json`:

```json
{
  "admin": {
    "password_hash": "pbkdf2:sha256:...",
    "role": "admin",
    "modules": ["*"]
  },
  "john": {
    "password_hash": "pbkdf2:sha256:...",
    "role": "user",
    "modules": ["laptop"]
  }
}
```

- `modules: ["*"]` means access to all modules (admin only)
- `modules: ["laptop", "ram"]` means access to those modules only
- Passwords stored as `werkzeug.security` hash (pbkdf2:sha256)

```python
import json
from pathlib import Path
from werkzeug.security import generate_password_hash, check_password_hash

USERS_FILE = Path("/opt/monitorcenter/data/users.json")

def load_users() -> dict:
    if not USERS_FILE.exists():
        return {}
    with open(USERS_FILE) as f:
        return json.load(f)

def save_users(users: dict):
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=2)

def verify_user(username: str, password: str) -> dict | None:
    """Returns user dict if credentials valid, else None."""
    users = load_users()
    user = users.get(username)
    if user and check_password_hash(user['password_hash'], password):
        return user
    return None

def user_has_module_access(username: str, module_name: str) -> bool:
    users = load_users()
    user = users.get(username, {})
    modules = user.get('modules', [])
    return '*' in modules or module_name in modules

def create_default_admin():
    """Create default admin if no users exist."""
    users = load_users()
    if not users:
        users['admin'] = {
            'password_hash': generate_password_hash('admin123'),
            'role': 'admin',
            'modules': ['*'],
        }
        save_users(users)
        print("Created default admin user (password: admin123)")
        print("IMPORTANT: Change admin password after first login!")
```

Call `create_default_admin()` in `app.py` at startup.

---

## Part 2: Decorators — `auth/decorators.py`

```python
from functools import wraps
from flask import session, redirect, url_for, abort
from auth.user_store import user_has_module_access

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated

def module_required(module_name: str):
    """Decorator to check user has access to a specific module."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if 'username' not in session:
                return redirect(url_for('auth.login'))
            username = session['username']
            if not user_has_module_access(username, module_name):
                abort(403)
            return f(*args, **kwargs)
        return decorated
    return decorator

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('auth.login'))
        if session.get('role') != 'admin':
            abort(403)
        return f(*args, **kwargs)
    return decorated
```

---

## Part 3: Auth Routes — `auth/routes.py`

```python
from flask import Blueprint, render_template, request, session, redirect, url_for, abort, jsonify
from werkzeug.security import generate_password_hash
from auth.user_store import load_users, save_users, verify_user
from auth.decorators import admin_required, login_required

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = verify_user(username, password)
        if user:
            session['username'] = username
            session['role'] = user['role']
            session.permanent = False   # expires on browser close
            return redirect(url_for('index'))
        error = "Invalid username or password"
    return render_template('login.html', error=error)

@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))

@auth_bp.route('/admin/users')
@admin_required
def admin_users():
    users = load_users()
    # Don't send password hashes to template
    safe_users = {
        u: {'role': d['role'], 'modules': d['modules']}
        for u, d in users.items()
    }
    from core.module_registry import get_registered_modules
    return render_template('admin_users.html',
                           users=safe_users,
                           all_modules=get_registered_modules())

@auth_bp.route('/admin/users/add', methods=['POST'])
@admin_required
def add_user():
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '')
    modules  = data.get('modules', [])

    if not username or not password:
        return jsonify({'error': 'username and password required'}), 400

    users = load_users()
    if username in users:
        return jsonify({'error': 'User already exists'}), 409

    users[username] = {
        'password_hash': generate_password_hash(password),
        'role': 'user',
        'modules': modules,
    }
    save_users(users)
    return jsonify({'status': 'ok'}), 201

@auth_bp.route('/admin/users/<username>/delete', methods=['POST'])
@admin_required
def delete_user(username):
    if username == 'admin':
        return jsonify({'error': 'Cannot delete admin'}), 403
    if username == session.get('username'):
        return jsonify({'error': 'Cannot delete yourself'}), 403
    users = load_users()
    if username not in users:
        return jsonify({'error': 'User not found'}), 404
    del users[username]
    save_users(users)
    return jsonify({'status': 'ok'})

@auth_bp.route('/admin/users/<username>/modules', methods=['POST'])
@admin_required
def update_modules(username):
    data = request.get_json()
    modules = data.get('modules', [])
    users = load_users()
    if username not in users:
        return jsonify({'error': 'User not found'}), 404
    if username == 'admin':
        return jsonify({'error': 'Cannot modify admin permissions'}), 403
    users[username]['modules'] = modules
    save_users(users)
    return jsonify({'status': 'ok'})
```

---

## Part 4: Update `app.py`

```python
from flask import Flask, render_template, session, redirect, url_for
from core.module_registry import register_modules
from auth.routes import auth_bp
from auth.user_store import create_default_admin
from auth.decorators import login_required
import config

app = Flask(...)
app.secret_key = "change-this-to-a-random-secret-key-in-production"
# SESSION_COOKIE_SECURE = True  # enable if using HTTPS

# Register auth blueprint
app.register_blueprint(auth_bp)

# Register module blueprints
MODULES = register_modules(app)

# Create default admin on startup
create_default_admin()

@app.route("/")
@login_required
def index():
    from auth.user_store import user_has_module_access
    username = session.get('username')
    role = session.get('role')
    # Only show modules user has access to
    accessible = [m for m in MODULES
                  if user_has_module_access(username, m)]
    return render_template("index.html",
                           modules=accessible,
                           username=username,
                           role=role)

@app.route("/api/search")
@login_required
def global_search():
    ...
```

---

## Part 5: Protect Module Routes

In `modules/laptop/module.py`, add `@module_required('laptop')` to
all routes:

```python
from auth.decorators import login_required, module_required

@blueprint.route("/")
@module_required('laptop')
def dashboard():
    ...

@blueprint.route("/api/upload", methods=["POST"])
# Upload from laptop_test.sh — use API key instead of session
# Add a simple API key check (not login_required)
def api_upload():
    api_key = request.headers.get('X-API-Key') or request.args.get('api_key')
    if api_key != config.UPLOAD_API_KEY:
        return jsonify({'error': 'Unauthorized'}), 401
    ...

@blueprint.route("/api/latest")
@module_required('laptop')
def api_latest():
    ...

@blueprint.route("/api/search")
@module_required('laptop')
def api_search():
    ...

@blueprint.route("/api/stats")
@module_required('laptop')
def api_stats():
    ...

@blueprint.route("/api/stats/range")
@module_required('laptop')
def api_stats_range():
    ...
```

**IMPORTANT:** `/api/upload` must NOT use `@login_required` or
`@module_required` because `laptop_test.sh` uploads via curl without
a browser session. Use API key instead.

---

## Part 6: Add UPLOAD_API_KEY to `config.py`

```python
# API key for script uploads (laptop_test.sh, future scripts)
# Change this to a random string in production
UPLOAD_API_KEY = "ceartrack-upload-2026"
```

Update `laptop_test.sh` upload command to include the key:
```bash
curl -X POST "$UPLOAD_URL" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ceartrack-upload-2026" \
  -d @"$REPORT_FILE"
```

---

## Part 7: Add `get_registered_modules()` to `core/module_registry.py`

```python
_registered_modules = []

def register_modules(app):
    global _registered_modules
    # ... existing code ...
    _registered_modules = registered
    return registered

def get_registered_modules() -> list:
    return _registered_modules
```

---

## Part 8: Login Page — `templates/login.html`

Dark theme, consistent with CearTrack style:

```html
{% extends "base.html" %}
{% block title %}Login — CearTrack{% endblock %}
{% block content %}
<div style="max-width:380px; margin:80px auto;">
  <div class="detail-panel">
    <h2 style="color:var(--accent); margin-bottom:24px; text-align:center;">
      CearTrack
    </h2>
    {% if error %}
    <div style="color:var(--fail); margin-bottom:16px; font-size:0.9em;">
      {{ error }}
    </div>
    {% endif %}
    <form method="POST">
      <div style="margin-bottom:14px;">
        <label style="color:var(--text-secondary); font-size:0.85em;">Username</label>
        <input type="text" name="username" autofocus
               style="width:100%; margin-top:6px; padding:10px 12px;
                      background:var(--bg-secondary); border:1px solid var(--border);
                      border-radius:4px; color:var(--text-primary); font-size:1em;">
      </div>
      <div style="margin-bottom:20px;">
        <label style="color:var(--text-secondary); font-size:0.85em;">Password</label>
        <input type="password" name="password"
               style="width:100%; margin-top:6px; padding:10px 12px;
                      background:var(--bg-secondary); border:1px solid var(--border);
                      border-radius:4px; color:var(--text-primary); font-size:1em;">
      </div>
      <button type="submit"
              style="width:100%; padding:11px; background:var(--accent);
                     color:var(--bg-primary); border:none; border-radius:4px;
                     font-size:1em; font-weight:600; cursor:pointer;">
        Sign In
      </button>
    </form>
  </div>
</div>
{% endblock %}
```

---

## Part 9: User Management Page — `templates/admin_users.html`

Admin-only page at `/admin/users`:

```html
{% extends "base.html" %}
{% block title %}User Management — CearTrack{% endblock %}
{% block content %}
<div x-data="userAdmin()" x-init="init()">

  <div style="display:flex; justify-content:space-between; margin-bottom:20px;">
    <h2 style="color:var(--accent);">User Management</h2>
    <button @click="showAddForm=true"
            style="padding:8px 16px; background:var(--accent); color:var(--bg-primary);
                   border:none; border-radius:4px; cursor:pointer; font-weight:600;">
      + Add User
    </button>
  </div>

  <!-- Add user form -->
  <template x-if="showAddForm">
    <div class="detail-panel" style="margin-bottom:20px;">
      <h3 style="margin-bottom:14px;">New User</h3>
      <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:12px;">
        <div>
          <label style="color:var(--text-secondary); font-size:0.85em;">Username</label>
          <input type="text" x-model="newUser.username"
                 style="width:100%; margin-top:4px; padding:8px 10px;
                        background:var(--bg-secondary); border:1px solid var(--border);
                        border-radius:4px; color:var(--text-primary);">
        </div>
        <div>
          <label style="color:var(--text-secondary); font-size:0.85em;">Password</label>
          <input type="password" x-model="newUser.password"
                 style="width:100%; margin-top:4px; padding:8px 10px;
                        background:var(--bg-secondary); border:1px solid var(--border);
                        border-radius:4px; color:var(--text-primary);">
        </div>
      </div>
      <div style="margin-bottom:14px;">
        <label style="color:var(--text-secondary); font-size:0.85em;">
          Module Access
        </label>
        <div style="display:flex; gap:12px; margin-top:8px; flex-wrap:wrap;">
          <template x-for="mod in allModules" :key="mod">
            <label style="display:flex; align-items:center; gap:6px; cursor:pointer;">
              <input type="checkbox" :value="mod"
                     @change="toggleModule(mod)"
                     :checked="newUser.modules.includes(mod)">
              <span x-text="mod" style="text-transform:capitalize;"></span>
            </label>
          </template>
        </div>
      </div>
      <div style="display:flex; gap:10px;">
        <button @click="addUser()"
                style="padding:8px 20px; background:var(--accent); color:var(--bg-primary);
                       border:none; border-radius:4px; cursor:pointer; font-weight:600;">
          Create
        </button>
        <button @click="showAddForm=false"
                style="padding:8px 20px; background:var(--bg-card); color:var(--text-secondary);
                       border:1px solid var(--border); border-radius:4px; cursor:pointer;">
          Cancel
        </button>
      </div>
    </div>
  </template>

  <!-- User list -->
  <div class="detail-panel">
    <template x-for="[username, user] in Object.entries(users)" :key="username">
      <div style="display:flex; align-items:center; gap:12px; padding:12px 0;
                  border-bottom:1px solid var(--border);">
        <div style="flex:1;">
          <div style="font-weight:600;" x-text="username"></div>
          <div style="font-size:0.8em; color:var(--text-secondary); margin-top:2px;"
               x-text="'Role: ' + user.role + ' | Modules: ' + user.modules.join(', ')">
          </div>
        </div>
        <!-- Module permission toggles (non-admin users only) -->
        <template x-if="user.role !== 'admin'">
          <div style="display:flex; gap:8px; flex-wrap:wrap;">
            <template x-for="mod in allModules" :key="mod">
              <button
                :style="`padding:4px 10px; border-radius:3px; font-size:0.8em; cursor:pointer;
                         border:1px solid var(--border);
                         background:${user.modules.includes(mod) ? 'var(--accent)' : 'var(--bg-secondary)'};
                         color:${user.modules.includes(mod) ? 'var(--bg-primary)' : 'var(--text-secondary)'}`"
                @click="toggleUserModule(username, mod)"
                x-text="mod">
              </button>
            </template>
          </div>
        </template>
        <!-- Delete button (not for admin, not for self) -->
        <template x-if="username !== 'admin' && username !== currentUser">
          <button @click="deleteUser(username)"
                  style="padding:6px 12px; background:rgba(231,76,60,0.15);
                         color:var(--fail); border:1px solid var(--fail);
                         border-radius:4px; cursor:pointer; font-size:0.85em;">
            Delete
          </button>
        </template>
      </div>
    </template>
  </div>

</div>

<script>
function userAdmin() {
  return {
    users: {{ users | tojson }},
    allModules: {{ all_modules | tojson }},
    currentUser: "{{ session.get('username') }}",
    showAddForm: false,
    newUser: { username: '', password: '', modules: [] },

    toggleModule(mod) {
      const idx = this.newUser.modules.indexOf(mod);
      if (idx === -1) this.newUser.modules.push(mod);
      else this.newUser.modules.splice(idx, 1);
    },

    async addUser() {
      if (!this.newUser.username || !this.newUser.password) return;
      const r = await fetch('/admin/users/add', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(this.newUser),
      });
      if (r.ok) {
        this.users[this.newUser.username] = {
          role: 'user',
          modules: [...this.newUser.modules]
        };
        this.newUser = { username: '', password: '', modules: [] };
        this.showAddForm = false;
      } else {
        const d = await r.json();
        alert(d.error || 'Failed to create user');
      }
    },

    async deleteUser(username) {
      if (!confirm(`Delete user "${username}"?`)) return;
      const r = await fetch(`/admin/users/${username}/delete`, {method:'POST'});
      if (r.ok) delete this.users[username];
    },

    async toggleUserModule(username, mod) {
      const user = this.users[username];
      const modules = [...user.modules];
      const idx = modules.indexOf(mod);
      if (idx === -1) modules.push(mod);
      else modules.splice(idx, 1);

      const r = await fetch(`/admin/users/${username}/modules`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ modules }),
      });
      if (r.ok) this.users[username].modules = modules;
    },
  };
}
</script>
{% endblock %}
```

---

## Part 10: Update `templates/base.html`

Add user info + logout link to header nav:

```html
<nav>
  <a href="/">Home</a>
  {% if session.get('role') == 'admin' %}
    <a href="/admin/users">Users</a>
  {% endif %}
  <span style="color:var(--text-secondary); font-size:0.85em;">
    {{ session.get('username') }}
  </span>
  <a href="/logout" style="color:var(--fail);">Logout</a>
</nav>
```

---

## Part 11: Update `laptop_test.sh`

Add API key header to upload command:

```bash
HTTP_CODE=$(curl -s -o /tmp/upload_response.txt -w "%{http_code}" \
  -X POST "$UPLOAD_URL" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ceartrack-upload-2026" \
  -d @"$REPORT_FILE" \
  --connect-timeout 10 \
  --max-time 30)
```

---

## Part 12: Handle 403 Forbidden

Add 403 handler in `app.py`:

```python
@app.errorhandler(403)
def forbidden(e):
    return render_template('login.html',
                           error="You don't have permission to access this module."), 403
```

---

## First Login

After deployment:
1. Open CearTrack → redirected to `/login`
2. Login: `admin` / `admin123`
3. Go to `/admin/users` → change admin password immediately
4. Add regular users and assign module permissions

---

## Verification

```bash
# 1. Start server
python app.py

# 2. Open browser → should redirect to /login
# 3. Login as admin → see all modules
# 4. Go to /admin/users → add a test user with laptop access only
# 5. Logout → login as test user → only laptop module visible
# 6. Test user tries /admin/users → gets 403

# 7. Test script upload still works (uses API key, not session)
curl -X POST http://localhost:5004/laptop/api/upload \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ceartrack-upload-2026" \
  -d @sample.json
# Should return 201

# 8. Upload without API key → 401
curl -X POST http://localhost:5004/laptop/api/upload \
  -H "Content-Type: application/json" \
  -d @sample.json
# Should return 401
```

## Constraints
- Do NOT delete any test records — no delete endpoints for test data
- Do NOT use a database — `users.json` only
- `admin` user cannot be deleted
- `/api/upload` uses API key, NOT session (scripts don't have browsers)
- `session.permanent = False` — session expires on browser close
- Run `python -m py_compile app.py` and all modified files after changes
- Change `app.secret_key` to a real random string
