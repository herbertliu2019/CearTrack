"""Phase 1 migration: create each production's `<module>_sync` table and
backfill every existing record of that module as 'pending'. Idempotent —
safe to run repeatedly, including after adding a new production.

Run from the monitorcenter/ directory:

    python -m cyclelution.migrate_phase1
"""

from . import sync_state

_MODULES = ("laptop", "gpu", "wipe")


def main() -> None:
    for module in _MODULES:
        sync_state.init_schema(module=module)
        created = sync_state.backfill_pending(module=module)
        print(f"[OK] {module}_sync backfill: +{created} new pending row(s)")
        print(f"[OK] {module}_sync status counts: {sync_state.counts(module=module)}")


if __name__ == "__main__":
    main()
