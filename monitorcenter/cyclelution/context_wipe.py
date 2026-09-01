"""Context builder for the wipe / T-Hard Drive Cyclelution production.

Unlike T-Laptop and T-Video Card, wipe has no test-script upload — its
source is a synthetic envelope wipe_sync.py builds from the latest
wipe_records row for a drive_sn (see wipe_sync.sync_all()). This builder
just flattens that envelope's payload.wipe block for the generic
normalizer.normalize() engine, and pre-computes `storage_type` so the
Weight/Color columns (looked up *by* Storage Type, see mapping_t_hard_drive
.yaml section 4.5) can read it back out via a plain table:map converter
without needing cross-column dependencies in the engine.

storage_type's keyword rules are intentionally duplicated from
mapping_t_laptop.yaml's `storage_type` ordered_rules ruleset (same pattern
context_gpu.py already uses for GPU subvendor aliasing) rather than shared,
extended with "10k"/"15k" as synonyms of "10000"/"15000" — both are real
wipe_records device_type values (e.g. "2.5 SAS 10k") not seen in laptop's
storage join, confirmed against the local wipe_index.db mirror.
"""

from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "mapping_t_hard_drive.yaml"


def _determine_storage_type(device_type: str, protocol: str):
    dt = (device_type or "").lower()
    proto = (protocol or "").lower()
    if not dt:
        return None
    if "m.2" in dt or "small" in dt:
        return "M.2 SSD NVME" if ("nvme" in dt or "nvme" in proto) else "M.2 SSD"
    if "msata" in dt:
        return "mSATA SSD"
    if any(k in dt for k in ("hdd", "5400", "7200", "10000", "15000", "10k", "15k")):
        return '3.5" HDD' if "3.5" in dt else '2.5" HDD'
    if "ssd" in dt or "2.5" in dt:
        return '2.5" SSD'
    return None


def build_context(envelope: dict, wipe_fn=None) -> dict:
    """wipe_fn is accepted (unused) only to match normalizer.normalize()'s
    ctx_builder(envelope, wipe_fn=wipe_fn) call signature."""
    payload = envelope.get("payload", {}) or {}
    wipe = dict(payload.get("wipe", {}) or {})
    wipe["storage_type"] = _determine_storage_type(
        wipe.get("device_type", ""), wipe.get("protocol", "")
    )
    return {
        "sn": envelope.get("sn", ""),
        "wipe": wipe,
        "overall_result": "",   # wipe has no operator judgement call to flag
    }
