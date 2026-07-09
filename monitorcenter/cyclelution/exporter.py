"""xlsx exporter (T-Laptop).

Turns a set of `ready` records into a single Cyclelution-importable xlsx,
built on the official Adjust template so the 81-column header stays byte
-for-byte identical. Data is written from row 2; unused columns are left
blank. On success each record is marked `synced` (with the filename in its
sync_note) so it cannot be exported twice.

Transport layer only — all field values come from normalizer (Phase 2).
"""

import json
from datetime import datetime
from pathlib import Path

import openpyxl

import config
from . import sync_state, wipe_lookup
from . import normalizer as _normalizer

_TEMPLATE = Path(__file__).parent / "templates" / "Adjust_Template.xlsx"


class ExportError(ValueError):
    """Raised for bad requests (empty selection / non-ready / already synced).
    No file is produced when this is raised."""


def _default_out_dir() -> Path:
    return Path(config.BASE_DIR) / "exports"


def export_ready(
    history_paths,
    config_map=None,
    wipe_fn=None,
    db_path=None,
    template_path=None,
    out_dir=None,
    now=None,
):
    """Export the given records (by history_path) to one xlsx.

    Raises ExportError (before writing anything) if the selection is empty
    or any record is not currently `ready`. Returns a summary dict:
    {file, count, records}.
    """
    paths_in = [p for p in (history_paths or []) if p]
    if not paths_in:
        raise ExportError("no records selected")

    # --- validate ALL up front; produce no file on any failure ---
    not_ready = []
    for hp in paths_in:
        row = sync_state.get(hp, db_path=db_path)
        status = row["sync_status"] if row else "unknown"
        if status != "ready":
            not_ready.append((hp, status))
    if not_ready:
        detail = "; ".join(f"{hp} is {st}" for hp, st in not_ready)
        raise ExportError(f"only 'ready' records can be exported: {detail}")

    cfg = config_map or _normalizer.load_config()
    wipe_fn = wipe_fn or wipe_lookup.lookup

    # --- build rows in template header order ---
    tpl = Path(template_path) if template_path else _TEMPLATE
    wb = openpyxl.load_workbook(tpl)
    ws = wb.active
    headers = [c.value for c in ws[1]]

    rows = []
    for hp in paths_in:
        envelope = json.loads(Path(hp).read_text(encoding="utf-8"))
        norm = _normalizer.normalize(envelope, config=cfg, wipe_fn=wipe_fn)
        # A ready record should normalize cleanly; guard anyway.
        if norm.exceptions:
            raise ExportError(f"{hp} now has normalization exceptions: {norm.exceptions}")
        rows.append([norm.values.get(h, "") or "" for h in headers])

    for i, row in enumerate(rows):
        for j, val in enumerate(row, start=1):
            ws.cell(row=2 + i, column=j, value=val)

    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M")
    out = Path(out_dir) if out_dir else _default_out_dir()
    out.mkdir(parents=True, exist_ok=True)
    fname = f"adjust_TLaptop_{stamp}.xlsx"
    fpath = out / fname
    wb.save(str(fpath))

    # --- mark synced only after a successful write ---
    synced_at = (now or datetime.now()).isoformat()
    for hp in paths_in:
        sync_state.set_status(hp, "synced", note=f"exported: {fname}",
                              synced_at=synced_at, db_path=db_path)

    return {"file": str(fpath), "count": len(paths_in), "records": list(paths_in)}
