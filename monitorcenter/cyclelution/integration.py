"""Register the Cyclelution export blueprint with the Flask app.

Mirrors modules/wipe/integration.py so app.py stays a one-liner and no
existing module code changes.
"""

from .web import blueprint, _PRODUCTION_INFO
from . import sync_state, batch_store


def _validate_batch_configs() -> None:
    """Startup gate for the scan-to-batch feature (TASK_export_batch_new.md
    'config' section): a production's `batch.large_batch_warn` that isn't a
    non-negative integer refuses app startup rather than silently ignoring
    it. Unlike the old max_rows cap, this is a soft UI-only threshold — 0 or
    omitted means "never show the warning banner", which is valid, not an
    error. Checked for every production regardless of `batch.enabled`,
    since a currently-disabled production's bad value would otherwise only
    surface the moment someone flips it on."""
    for production, info in _PRODUCTION_INFO.items():
        cfg = info["config"]()
        batch_cfg = cfg.get("batch") or {}
        if not batch_cfg:
            continue
        # None covers both an absent key and an explicit `large_batch_warn:`
        # (YAML null) — both mean "disabled", same as 0, not an error.
        warn = batch_cfg.get("large_batch_warn")
        if warn is None:
            warn = 0
        valid = isinstance(warn, int) and not isinstance(warn, bool) and warn >= 0
        if not valid:
            raise SystemExit(
                f"[cyclelution] invalid batch.large_batch_warn for production {production!r}: "
                f"{warn!r} (must be a non-negative integer; 0 or omitted disables the warning) "
                "— refusing to start"
            )


def register_cyclelution_module(app):
    sync_state.init_schema(module="laptop")   # ensure laptop_sync exists on boot
    sync_state.init_schema(module="gpu")      # ensure gpu_sync exists on boot
    sync_state.init_schema(module="wipe")     # ensure wipe_sync exists on boot
    _validate_batch_configs()
    batch_store.init_schema()                 # ensure data/batches.db exists on boot
    app.register_blueprint(blueprint)

    # wipe has no upload event to trigger evaluate_one from (see
    # wipe_sync.py) — seed its sync state once at boot in the background
    # (a full run against the production wipe DB takes ~20 minutes; must
    # never block Flask startup) so the Ready/Exceptions/NO_GRADE queues
    # fill in without waiting for the first manual Rescan. Best-effort: the
    # wipe DB may not exist yet on a fresh install.
    try:
        from . import wipe_sync
        wipe_sync.run_in_background()
        # Keep resyncing afterward — otherwise drives wiped between boot and
        # the next manual Rescan click sit invisible in Ready (see
        # wipe_sync.py's poller docstring for why Rescan alone isn't enough).
        wipe_sync.start_poll_scheduler()
    except Exception as e:
        print(f"[cyclelution] initial wipe_sync failed (non-fatal): {e}")
