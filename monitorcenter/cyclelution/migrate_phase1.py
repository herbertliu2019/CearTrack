"""Phase 1 migration: create the laptop_sync table and backfill every
existing laptop record as 'pending'. Idempotent — safe to run repeatedly.

Run from the monitorcenter/ directory:

    python -m cyclelution.migrate_phase1
"""

from . import sync_state


def main() -> None:
    sync_state.init_schema()
    created = sync_state.backfill_pending()
    print(f"[OK] laptop_sync backfill: +{created} new pending row(s)")
    print(f"[OK] laptop_sync status counts: {sync_state.counts()}")


if __name__ == "__main__":
    main()
