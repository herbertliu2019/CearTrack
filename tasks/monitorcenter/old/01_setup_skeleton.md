# Task 01: Setup Project Skeleton

## Goal
Create the base Flask application structure with auto-discovery of modules.
No actual module logic yet — just the plumbing.

## Deliverables

### 1. Directory Structure
Create `/opt/monitorcenter/` with this structure:
```
/opt/monitorcenter/
├── app.py
├── config.py
├── requirements.txt
├── core/
│   ├── __init__.py
│   ├── storage.py
│   ├── module_registry.py
│   └── envelope.py
├── modules/
│   ├── __init__.py
│   └── base.py
├── static/
│   ├── css/
│   ├── js/
│   └── vendor/
├── templates/
│   ├── base.html
│   └── index.html
└── data/
    └── (empty, created by storage.py at runtime)
```

### 2. `requirements.txt`
```
Flask>=3.0.0
```

### 3. `config.py`
```python
import os
from pathlib import Path

BASE_DIR = Path("/opt/monitorcenter/data")
STATIC_DIR = Path("/opt/monitorcenter/static")
TEMPLATE_DIR = Path("/opt/monitorcenter/templates")

HOST = "0.0.0.0"
PORT = 8080
DEBUG = os.getenv("MONITORCENTER_DEBUG", "0") == "1"

# Purge entries from latest/ older than this many hours
LATEST_RETENTION_HOURS = 24
```

### 4. `core/storage.py`
Provides:
- `get_date_subdir(module_name)` → returns `data/<module>/history/YYYY/MM-DD/`,
  creates directories as needed
- `get_latest_dir(module_name)` → returns `data/<module>/latest/`
- `write_envelope(module_name, sn, envelope)` → writes to BOTH latest and history.
  **IMPORTANT:** at the end of this function, add a placeholder call:
  ```python
  # TODO: _update_index(module_name, envelope)
  # Future: append a line to data/<module>/_index/YYYY-MM.jsonl
  # with {sn, module, result, timestamp, file_path} for fast bulk queries
  # by the future analysis project. Not implemented yet.
  ```
- `read_latest(module_name)` → returns list of all envelopes in latest/,
  filters out files older than 24h (and deletes them)
- `search_sn(module_name, sn)` → recursive glob in history/ for files matching SN
- `list_history(module_name, date_range)` → list history within date range

Use `pathlib.Path` not `os.path`.

### 5. `modules/base.py`
```python
from abc import ABC, abstractmethod
from typing import Tuple

class TestModule(ABC):
    name: str
    display_name: str
    icon: str

    @abstractmethod
    def extract_envelope(self, raw_payload: dict) -> dict: ...

    @abstractmethod
    def compute_verdict(self, envelope: dict) -> dict: ...

    @abstractmethod
    def get_display_schema(self) -> dict: ...

    def validate(self, raw_payload: dict) -> Tuple[bool, str]:
        return True, "OK"
```

### 6. `core/module_registry.py`
Scans `modules/` directory, imports each subpackage (except `base`),
and looks for a `blueprint` attribute at module level. Registers each
blueprint under `/<module_name>/` prefix.

```python
def register_modules(app):
    """Auto-discover and register all modules under modules/"""
    import importlib, pkgutil
    import modules
    
    registered = []
    for _, name, is_pkg in pkgutil.iter_modules(modules.__path__):
        if name == "base" or not is_pkg:
            continue
        try:
            mod = importlib.import_module(f"modules.{name}.module")
            if hasattr(mod, "blueprint"):
                app.register_blueprint(mod.blueprint, url_prefix=f"/{name}")
                registered.append(name)
                print(f"✓ Registered module: {name}")
        except Exception as e:
            print(f"✗ Failed to register {name}: {e}")
    return registered
```

### 7. `core/envelope.py`
Helper to build standard envelope. Used by modules:
```python
def build_envelope(module_name, sn, timestamp, overall_result,
                   summary, hostname, payload):
    return {
        "module": module_name,
        "sn": sn,
        "timestamp": timestamp,
        "overall_result": overall_result,
        "summary": summary,
        "hostname": hostname,
        "payload": payload,
    }
```

### 8. `app.py`
```python
from flask import Flask, render_template
from core.module_registry import register_modules
import config

app = Flask(
    __name__,
    static_folder=str(config.STATIC_DIR),
    template_folder=str(config.TEMPLATE_DIR),
)

MODULES = register_modules(app)

@app.route("/")
def index():
    # Pass list of registered modules to template
    return render_template("index.html", modules=MODULES)

if __name__ == "__main__":
    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG)
```

### 9. `templates/base.html`
Minimal skeleton with Alpine.js + HTMX from static/vendor/:
```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{% block title %}Monitorcenter{% endblock %}</title>
  <link rel="stylesheet" href="{{ url_for('static', filename='css/dashboard.css') }}">
  <script defer src="{{ url_for('static', filename='vendor/alpine.min.js') }}"></script>
  <script src="{{ url_for('static', filename='vendor/htmx.min.js') }}"></script>
</head>
<body>
  <header>
    <h1>Monitor Center</h1>
    <nav>
      <a href="/">Home</a>
      {% for m in modules %}
        <a href="/{{ m }}/">{{ m|capitalize }}</a>
      {% endfor %}
    </nav>
  </header>
  <main>{% block content %}{% endblock %}</main>
</body>
</html>
```

### 10. `templates/index.html`
Landing page showing tiles for each registered module:
```html
{% extends "base.html" %}
{% block content %}
<div class="module-grid">
  {% for m in modules %}
    <a href="/{{ m }}/" class="module-tile">
      <h3>{{ m|capitalize }}</h3>
    </a>
  {% endfor %}
</div>
{% endblock %}
```

### 11. `static/css/dashboard.css`
Dark theme base styles. Placeholder is fine for now, full styles come in task 03.

### 12. `static/vendor/`
Download and save:
- `alpine.min.js` from https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js
- `htmx.min.js` from https://unpkg.com/htmx.org@1.9.x/dist/htmx.min.js

(Downloaded locally so server works offline.)

## Verification

```bash
cd /opt/monitorcenter
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

- Open http://localhost:8080 — should see landing page (no modules yet)
- Console should show "No modules registered" (since modules/laptop/ not created yet)
- `/search` route exists (empty response ok for now)

## Constraints
- Python 3.12 only
- No external JS via CDN — all vendor files local
- No database — JSON files only
- Use `pathlib.Path` everywhere, no `os.path` strings
- No build step
