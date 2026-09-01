"""Context builder for the GPU / T-Video Card Cyclelution production.

Mirrors normalizer.build_context (T-Laptop) but flattens a gpu envelope
instead: no storage/wipe/battery/cpu — a GPU never holds user data, so
there is nothing to sanitize and no drive to check. Consumed by the same
generic normalizer.normalize() engine via its context_builder param.
"""

from pathlib import Path

from .manual_input import read_manual_input

CONFIG_PATH = Path(__file__).parent / "mapping_t_video_card.yaml"

# Kept in sync with modules/gpu/module.py's SUBVENDOR_ALIASES /
# _normalize_subvendor() (duplicated, not imported, so this package stays
# decoupled from the test modules — see module docstring above). lspci
# often reports gpu.subvendor as the full PCI subsystem string (vendor +
# chip codename + marketing name, e.g. "Hewlett-Packard Company GA106
# [GeForce RTX 3060 Lite Hash Rate]"), which the mapping yaml's
# clean_alias ruleset can't match since it does an exact lookup after
# stripping only a few suffix words — it needs an already-clean brand
# name as input, same as the dashboard's "By Vendor" widget requires.
_SUBVENDOR_ALIASES = {
    "asustek":          "ASUS",
    "asus":             "ASUS",
    "micro-star":       "MSI",
    "microstar":        "MSI",
    "msi":              "MSI",
    "gigabyte":         "Gigabyte",
    "giga-byte":        "Gigabyte",
    "sapphire":         "Sapphire",
    "evga":             "EVGA",
    "pny":              "PNY",
    "zotac":            "ZOTAC",
    "palit":            "Palit",
    "gainward":         "Gainward",
    "inno3d":           "Inno3D",
    "colorful":         "Colorful",
    "leadtek":          "Leadtek",
    "asrock":           "ASRock",
    "xfx":              "XFX",
    "powercolor":       "PowerColor",
    "his":              "HIS",
    "club3d":           "Club 3D",
    "club 3d":          "Club 3D",
    "pc partner":       "PC Partner",
    "pcpartner":        "PC Partner",
    "shenzhen bitland": "Bitland",
    "shenzen bitland":  "Bitland",
    "bitland":          "Bitland",
    "dell":             "Dell",
    "hp":               "HP",
    "hewlett-packard":  "HP",
    "lenovo":           "Lenovo",
    "nvidia":           "NVIDIA",
    "ati":              "AMD",
    "amd":              "AMD",
    "intel":            "Intel",
}


def _normalize_subvendor(raw: str) -> str:
    if not raw:
        return ""
    s = raw.lower().strip()
    if s in _SUBVENDOR_ALIASES:
        return _SUBVENDOR_ALIASES[s]
    for key, canonical in _SUBVENDOR_ALIASES.items():
        if key in s:
            return canonical
    first = raw.strip().split()[0] if raw.strip() else ""
    return first[:20]


def build_context(envelope: dict, wipe_fn=None) -> dict:
    """wipe_fn is accepted (unused) only to match normalizer.normalize()'s
    ctx_builder(envelope, wipe_fn=wipe_fn) call signature."""
    payload = envelope.get("payload", {}) or {}
    gpu = dict(payload.get("gpu", {}) or {})
    gpu["subvendor"] = _normalize_subvendor(gpu.get("subvendor", ""))
    vram_mb = gpu.get("vram_mb")
    # Derived: mapping_t_video_card.yaml buckets VRAM in GB (same domain as
    # laptop's system memory), the raw field is only in MB.
    if vram_mb not in (None, ""):
        try:
            gpu["vram_gb"] = float(vram_mb) / 1024
        except (TypeError, ValueError):
            pass
    return {
        "sn": envelope.get("sn", ""),
        "gpu": gpu,
        "test_info": payload.get("test_info", {}) or {},
        "manual_input": read_manual_input(payload),
        "overall_result": envelope.get("overall_result", ""),
    }
