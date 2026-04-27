# Task 02: Implement Laptop Module

## Prerequisites
Task 01 complete — skeleton running with no modules yet.

## Goal
Create the first real module: `modules/laptop/`.
After this task, POSTing a laptop JSON will store it and the laptop
dashboard URL will return JSON APIs.

## Deliverables

### 1. `modules/laptop/__init__.py`
Empty file.

### 2. `modules/laptop/schema.json`
Display schema for the frontend renderer. Based on the actual laptop
test JSON structure.

```json
{
  "sections": [
    {
      "title": "System",
      "type": "key_value",
      "fields": [
        {"path": "payload.system.vendor", "label": "Vendor"},
        {"path": "payload.system.model", "label": "Model"},
        {"path": "payload.system.serial_number", "label": "SN / Service Tag"},
        {"path": "payload.system.bios_version", "label": "BIOS"}
      ]
    },
    {
      "title": "Hardware",
      "type": "key_value",
      "fields": [
        {"path": "payload.cpu.model", "label": "CPU"},
        {"path": "payload.cpu.cores", "label": "Cores", "suffix": " cores"},
        {"path": "payload.memory.total_gb", "label": "Memory", "suffix": " GB"},
        {"path": "payload.memory.type", "label": "Memory Type"},
        {"path": "payload.battery.health_percent", "label": "Battery Health", "suffix": "%"},
        {"path": "payload.battery.cycle_count", "label": "Battery Cycles"}
      ]
    },
    {
      "title": "Storage",
      "type": "list",
      "path": "payload.storage",
      "item_template": "{model} ({size}, {type}) — SMART: {smart}"
    },
    {
      "title": "Test Results",
      "type": "status_grid",
      "items": [
        {"path": "payload.screen.dead_pixel_check", "label": "Screen"},
        {"path": "payload.camera.device_status", "label": "Camera"},
        {"path": "payload.audio.speaker_quality_check", "label": "Speaker"},
        {"path": "payload.audio.mic_record_check", "label": "Microphone"},
        {"path": "payload.keyboard.keys_check", "label": "Keyboard"},
        {"path": "payload.keyboard.touchpad_check", "label": "Touchpad"},
        {"path": "payload.network.wifi_status", "label": "WiFi"},
        {"path": "payload.network.ethernet_status", "label": "Ethernet"},
        {"path": "payload.network.internet_test", "label": "Internet"},
        {"path": "payload.ports.physical_check", "label": "Ports"},
        {"path": "payload.appearance.hinge_check", "label": "Hinge"},
        {"path": "payload.appearance.scratch_check", "label": "Scratches"}
      ]
    }
  ]
}
```

### 3. `modules/laptop/module.py`

```python
import json
from pathlib import Path
from datetime import datetime
from flask import Blueprint, request, jsonify, render_template, current_app
from modules.base import TestModule
from core.envelope import build_envelope
from core import storage

SCHEMA_PATH = Path(__file__).parent / "schema.json"

class LaptopModule(TestModule):
    name = "laptop"
    display_name = "Laptop Test"
    icon = "laptop"

    def extract_envelope(self, raw_payload: dict) -> dict:
        system = raw_payload.get("system", {})
        test_info = raw_payload.get("test_info", {})
        
        sn = system.get("serial_number", "unknown")
        timestamp = test_info.get("test_time") or datetime.utcnow().isoformat() + "Z"
        hostname = test_info.get("hostname", "unknown")
        overall = raw_payload.get("overall_result", "UNKNOWN").upper()
        
        envelope = build_envelope(
            module_name=self.name,
            sn=sn,
            timestamp=timestamp,
            overall_result=overall,
            summary="",
            hostname=hostname,
            payload=raw_payload,
        )
        
        verdict = self.compute_verdict(envelope)
        envelope["summary"] = verdict["summary"]
        envelope["warnings"] = verdict.get("warnings", [])
        return envelope

    def compute_verdict(self, envelope: dict) -> dict:
        payload = envelope.get("payload", {})
        overall = envelope.get("overall_result", "UNKNOWN")
        
        warnings = []
        # Camera driver failed but hardware present
        cam_status = payload.get("camera", {}).get("device_status", "")
        if cam_status == "HARDWARE_DETECTED":
            warnings.append("Camera driver init failed — verify in OEM OS")
        # Battery data unavailable
        bat_cond = payload.get("battery", {}).get("battery_condition", "")
        if bat_cond == "DATA_UNAVAILABLE":
            warnings.append("Battery data unreadable — verify manually")
        
        if overall == "FAIL":
            # Find what failed
            failed = []
            for section_name, section in payload.items():
                if isinstance(section, dict):
                    for k, v in section.items():
                        if isinstance(v, str) and v == "FAIL":
                            failed.append(f"{section_name}.{k}")
            summary = f"{len(failed)} check(s) failed: {', '.join(failed[:3])}"
            if len(failed) > 3:
                summary += f" (+{len(failed)-3} more)"
        elif warnings:
            summary = f"PASS with {len(warnings)} warning(s)"
        else:
            summary = "All tests passed"
        
        return {"result": overall, "summary": summary, "warnings": warnings}

    def get_display_schema(self) -> dict:
        with open(SCHEMA_PATH) as f:
            return json.load(f)

    def validate(self, raw_payload: dict):
        if not isinstance(raw_payload, dict):
            return False, "Payload is not a JSON object"
        if "system" not in raw_payload:
            return False, "Missing 'system' section"
        if "serial_number" not in raw_payload.get("system", {}):
            return False, "Missing 'system.serial_number'"
        if "overall_result" not in raw_payload:
            return False, "Missing 'overall_result'"
        return True, "OK"


# Singleton instance
_module = LaptopModule()
blueprint = Blueprint(
    "laptop",
    __name__,
    template_folder="templates",
    static_folder=None,
)


@blueprint.route("/")
def dashboard():
    return render_template(
        "module.html",
        module_name=_module.name,
        display_name=_module.display_name,
    )


@blueprint.route("/api/upload", methods=["POST"])
def api_upload():
    raw = request.get_json(silent=True)
    if raw is None:
        return jsonify({"error": "Invalid or missing JSON"}), 400
    
    ok, msg = _module.validate(raw)
    if not ok:
        return jsonify({"error": msg}), 400
    
    envelope = _module.extract_envelope(raw)
    storage.write_envelope(_module.name, envelope["sn"], envelope)
    
    return jsonify({
        "status": "ok",
        "sn": envelope["sn"],
        "result": envelope["overall_result"],
        "summary": envelope["summary"],
    }), 201


@blueprint.route("/api/latest")
def api_latest():
    records = storage.read_latest(_module.name)
    records.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return jsonify(records)


@blueprint.route("/api/search")
def api_search():
    sn = request.args.get("sn", "").strip()
    if not sn:
        return jsonify({"error": "sn parameter required"}), 400
    results = storage.search_sn(_module.name, sn)
    results.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return jsonify(results)


@blueprint.route("/api/schema")
def api_schema():
    return jsonify(_module.get_display_schema())


@blueprint.route("/api/stats")
def api_stats():
    records = storage.read_latest(_module.name)
    total = len(records)
    pass_count = sum(1 for r in records if r.get("overall_result") == "PASS")
    fail_count = sum(1 for r in records if r.get("overall_result") == "FAIL")
    return jsonify({
        "total_today": total,
        "pass": pass_count,
        "fail": fail_count,
        "pass_rate": round(pass_count / total * 100, 1) if total else 0,
    })
```

### 4. `modules/laptop/templates/module.html`
Placeholder — the real dashboard is built in task 03.
```html
{% extends "base.html" %}
{% block title %}{{ display_name }} — Monitorcenter{% endblock %}
{% block content %}
<div x-data="dashboardApp('{{ module_name }}')" x-init="init()">
  <h2>{{ display_name }}</h2>
  <p>Dashboard loaded for module: <strong>{{ module_name }}</strong></p>
  <p>APIs:</p>
  <ul>
    <li><a href="/laptop/api/latest">api/latest</a></li>
    <li><a href="/laptop/api/schema">api/schema</a></li>
    <li><a href="/laptop/api/stats">api/stats</a></li>
  </ul>
</div>
{% endblock %}
```

## Verification

```bash
# 1. Restart server, verify module registered
python app.py
# Should print: ✓ Registered module: laptop

# 2. POST a real laptop test JSON
curl -X POST http://localhost:8080/laptop/api/upload \
  -H "Content-Type: application/json" \
  -d @sample_laptop.json

# 3. Verify file exists in both latest and history
ls /opt/monitorcenter/data/laptop/latest/
ls /opt/monitorcenter/data/laptop/history/$(date +%Y)/$(date +%m-%d)/

# 4. Query APIs
curl http://localhost:8080/laptop/api/latest
curl http://localhost:8080/laptop/api/search?sn=034912262653
curl http://localhost:8080/laptop/api/stats

# 5. Browser
open http://localhost:8080/laptop/
```

## Constraints
- Do NOT modify any file in core/ — this task only adds files under modules/laptop/
- The real laptop_test.sh client is NOT modified — server handles wrapping
- Keep `schema.json` as a SEPARATE file so it can be edited without touching Python
