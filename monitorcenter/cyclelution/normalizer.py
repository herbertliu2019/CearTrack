"""Config-driven normalization engine (T-Laptop).

Reads mapping_t_laptop.yaml and turns one laptop envelope into the set of
Cyclelution column values. The engine is generic: it dispatches on each
column's `type` (const / direct / table / bucket / parse) and every field
rule — domains, alias maps, regexes, keyword rules — comes from the YAML.
No field-specific logic is hardcoded here.

normalize(envelope) -> NormResult(values, exceptions, context)
  values      dict {column_name: string}
  exceptions  list of {field, reason}; non-empty means the record cannot
              go to `ready` (it belongs on the exception list)
  context     the flattened source dict (incl. wipe join) for the gate
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import wipe_lookup as _wipe_lookup
from .manual_input import read_manual_input

_CONFIG_PATH = Path(__file__).parent / "mapping_t_laptop.yaml"


@dataclass
class NormResult:
    values: dict = field(default_factory=dict)
    exceptions: list = field(default_factory=list)
    context: dict = field(default_factory=dict)


class _Skip(Exception):
    """Raised by a converter to signal 'leave this column blank'."""


class _UseValue(Exception):
    """Raised by a converter to short-circuit to a fixed value."""
    def __init__(self, value):
        self.value = value


class _Fail(Exception):
    """Raised by a converter to signal an exception-list entry."""


def load_config(path=None) -> dict:
    p = Path(path) if path else _CONFIG_PATH
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)


# --- helpers ------------------------------------------------------------
def _get_path(ctx: dict, dotted: str):
    cur = ctx
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _fmt_num(x) -> str:
    """8.0 -> '8', 1.5 -> '1.5'."""
    xf = float(x)
    return str(int(xf)) if xf == int(xf) else str(xf)


_TB_LABELS = {
    1000: "1 TB", 1200: "1.2 TB", 1500: "1.5 TB", 1600: "1.6 TB", 1800: "1.8 TB",
    1920: "1.92 TB", 2000: "2 TB", 3000: "3 TB", 3840: "3.84 TB", 6000: "6 TB",
    7680: "7.68 TB", 10000: "10 TB", 12000: "12 TB", 14000: "14 TB",
}


def _fmt_storage(gb: int) -> str:
    return _TB_LABELS.get(gb, f"{gb} GB")


# --- context ------------------------------------------------------------
def build_context(envelope: dict, wipe_fn=None) -> dict:
    """Flatten the payload into source groups and join the wipe record for
    the primary drive. wipe_fn(drive_sn) -> dict|None (injectable for tests).
    """
    wipe_fn = wipe_fn or _wipe_lookup.lookup
    payload = envelope.get("payload", {}) or {}
    raw_storage = payload.get("storage") or []

    # laptop_test.sh emits a placeholder entry (device "none", carrying a
    # fail_reason) when it detects no internal disk — that is NOT a real disk.
    real_disks = [d for d in raw_storage
                  if d.get("device") != "none" and "fail_reason" not in d]
    placeholders = [d for d in raw_storage
                    if d.get("device") == "none" or "fail_reason" in d]

    disk_reason = ""
    wipe = {}
    if real_disks:
        disk_state = "has_disk"
        primary_sn = (real_disks[0].get("serial") or "").strip()
        wipe = wipe_fn(primary_sn) or {}
    elif placeholders:
        disk_reason = (placeholders[0].get("fail_reason") or "").strip()
        # Only an operator-CONFIRMED empty bay is safe to treat as no-disk;
        # a hidden/undetected disk may hold data -> must be verified (blocked).
        disk_state = "no_disk" if disk_reason == "NO_DISK_CONFIRMED" else "disk_unverified"
    else:
        disk_state = "no_disk"   # truly empty storage list (older reports)

    return {
        "system": payload.get("system", {}) or {},
        "cpu": payload.get("cpu", {}) or {},
        "memory": payload.get("memory", {}) or {},
        "battery": payload.get("battery", {}) or {},
        "manual_input": read_manual_input(payload),
        "storage": real_disks,   # gate checks real disks only
        "wipe": wipe,
        "context": {"disk_state": disk_state, "disk_reason": disk_reason},
        "overall_result": envelope.get("overall_result", ""),
    }


# --- converters ---------------------------------------------------------
def _c_const(cfg, ctx, cfgroot):
    if "from_env" in cfg:
        env = cfgroot.get("environment", "production")
        return str(cfgroot["env_values"][cfg["from_env"]][env])
    return str(cfg.get("value", ""))


def _blank_if_no_disk(cfg, ctx):
    # Storage columns are blank whenever there is no verified real disk
    # (no_disk or disk_unverified). Only has_disk fills them. A column may
    # opt into a fixed value for the genuine no-disk case via no_disk_value
    # (e.g. Storage Size -> "No Storage").
    if cfg.get("no_disk_blank") and ctx["context"]["disk_state"] != "has_disk":
        if ctx["context"]["disk_state"] == "no_disk" and cfg.get("no_disk_value"):
            raise _UseValue(cfg["no_disk_value"])
        raise _Skip()


def _c_direct(cfg, ctx, cfgroot):
    _blank_if_no_disk(cfg, ctx)
    v = _get_path(ctx, cfg["source"])
    if v is None or v == "":
        if cfg.get("required"):
            raise _Fail(f"required field '{cfg['source']}' is empty")
        raise _Skip()
    v = str(v).strip()
    if cfg.get("numeric"):
        try:
            float(v)
        except ValueError:
            raise _Fail(f"field '{cfg['source']}' must be numeric, got {v!r}")
    domain = cfg.get("domain")
    if domain and v not in cfgroot["domains"][domain]:
        if not cfg.get("domain_soft"):
            raise _Fail(f"value {v!r} not in domain {domain}")
    return v


def _c_bucket(cfg, ctx, cfgroot):
    raw = _get_path(ctx, cfg["source"])
    if (raw is None or raw == "") and cfg.get("source_fallback"):
        raw = _get_path(ctx, cfg["source_fallback"])   # e.g. physical_gb -> total_gb
    if raw is None or raw == "":
        raise _Fail(f"field '{cfg['source']}' empty (bucket)")
    try:
        val = float(str(raw).strip())
    except ValueError:
        raise _Fail(f"field '{cfg['source']}' not numeric: {raw!r}")
    domain = cfgroot["domains"][cfg["domain"]]
    for d in sorted(domain):
        if val <= d:
            return f"{_fmt_num(d)} {cfg['unit']}".strip()
    if cfg.get("over_max_exception"):
        raise _Fail(f"{cfg['source']} {val} exceeds max domain {max(domain)}")
    return f"{_fmt_num(max(domain))} {cfg['unit']}".strip()


def _c_table(cfg, ctx, cfgroot):
    _blank_if_no_disk(cfg, ctx)
    rs = cfgroot["rulesets"][cfg["ruleset"]]
    raw = _get_path(ctx, cfg["source"])
    s = (str(raw).strip() if raw is not None else "")
    kind = rs["kind"]

    if kind == "map":
        if s in rs["map"]:
            return rs["map"][s]
        raise _Fail(f"{cfg['source']}={s!r} not in map {cfg['ruleset']}")

    if kind == "clean_alias":
        cleaned = _clean_manufacturer(s, rs["strip_suffixes"])
        return rs["aliases"].get(cleaned, cleaned)  # Txt channel: never fails

    if kind == "ordered_rules":
        if not s:
            raise _Fail(f"{cfg['source']} empty for ruleset {cfg['ruleset']}")
        low = s.lower()
        for rule in rs["rules"]:
            if any(tok in low for tok in rule["any"]):
                if "value" in rule:
                    return rule["value"]
                if "nvme_if_any" in rule:
                    if any(t in low for t in rule["nvme_if_any"]):
                        return rule["nvme_value"]
                    return rule["else_value"]
                if "has35_if_any" in rule:
                    if any(t in low for t in rule["has35_if_any"]):
                        return rule["has35_value"]
                    return rule["else_value"]
        raise _Fail(f"{cfg['source']}={s!r} matched no {cfg['ruleset']} rule")

    raise _Fail(f"unknown ruleset kind {kind!r}")


def _c_parse(cfg, ctx, cfgroot):
    _blank_if_no_disk(cfg, ctx)
    parser = cfgroot["parsers"][cfg["parser"]]
    raw = _get_path(ctx, cfg["source"])
    s = (str(raw).strip() if raw is not None else "")
    kind = parser["kind"]

    if kind == "strip_vendor_upper":
        vendor = str(_get_path(ctx, cfg.get("vendor_source", "")) or "").strip()
        out = s
        if vendor and out.upper().startswith(vendor.upper()):
            out = out[len(vendor):].strip()
        return out.upper()

    if not s:
        raise _Fail(f"field '{cfg['source']}' empty for parser {cfg['parser']}")

    if kind == "regex_first":
        text = s
        if parser.get("strip_marks"):
            text = re.sub(r"\((tm|r|c)\)", "", text, flags=re.I)
        for pat in parser["patterns"]:
            m = re.search(pat["re"], text, flags=re.I)
            if m:
                out = pat["out"]
                for i, g in enumerate(m.groups(), 1):
                    out = out.replace("{%d}" % i, g or "")
                return out
        if parser.get("no_match") == "exception":
            raise _Fail(f"{cfg['source']}={s!r} matched no {cfg['parser']} pattern")
        raise _Skip()

    if kind == "regex_extract_bucket":
        m = re.search(parser["re"], s, flags=re.I)
        if not m:
            raise _Fail(f"{cfg['source']}={s!r}: no base frequency found")
        val = float(m.group(1))
        domain = cfgroot["domains"][cfg["domain"]]
        nearest = min(domain, key=lambda d: abs(d - val))
        return f"{_fmt_num(nearest)} {parser['unit']}".strip()

    if kind == "regex_group":
        m = re.search(parser["re"], s, flags=re.I)
        if not m:
            raise _Fail(f"{cfg['source']}={s!r}: {cfg['parser']} no match")
        g = m.group(1)
        return g.upper() if parser.get("upper") else g

    if kind == "append_percent":
        return f"{s}%"

    if kind == "capacity_bucket":
        m = re.search(r"([0-9]+\.?[0-9]*)\s*(tb|gb|mb)?", s, flags=re.I)
        if not m:
            raise _Fail(f"capacity {s!r} unparseable")
        num = float(m.group(1))
        unit = (m.group(2) or "gb").lower()
        gb = num * (1000 if unit == "tb" else 1 if unit == "gb" else 0.001)
        if gb < parser.get("min_gb", 0):
            raise _Fail(f"capacity {s!r} ({gb:g} GB) below min {parser['min_gb']} GB")
        domain = cfgroot["domains"][cfg["domain"]]
        for d in sorted(domain):
            if gb <= d:
                return _fmt_storage(d)
        raise _Fail(f"capacity {s!r} exceeds max storage domain")

    raise _Fail(f"unknown parser kind {kind!r}")


def _clean_manufacturer(s: str, suffixes) -> str:
    up = s.upper().strip()
    up = re.sub(r"[.,]", " ", up)
    tokens = [t for t in up.split() if t and t not in set(suffixes)]
    return " ".join(tokens)


_DISPATCH = {
    "const": _c_const,
    "direct": _c_direct,
    "bucket": _c_bucket,
    "table": _c_table,
    "parse": _c_parse,
}


# --- entrypoint ---------------------------------------------------------
def normalize(envelope: dict, config=None, wipe_fn=None) -> NormResult:
    cfg = config or load_config()
    ctx = build_context(envelope, wipe_fn=wipe_fn)
    res = NormResult(context=ctx)

    for col, rule in cfg["columns"].items():
        conv = _DISPATCH.get(rule["type"])
        if conv is None:
            res.exceptions.append({"field": col, "reason": f"unknown type {rule['type']!r}"})
            continue
        try:
            res.values[col] = conv(rule, ctx, cfg)
        except _UseValue as u:
            res.values[col] = u.value
        except _Skip:
            res.values[col] = ""
        except _Fail as e:
            res.exceptions.append({"field": col, "reason": str(e)})

    return res
