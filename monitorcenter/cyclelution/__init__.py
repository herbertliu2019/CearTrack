"""CearTrack -> Cyclelution integration layer (T-Laptop).

This package is the reusable data-preparation + transport flow that turns
tested laptop records into a Cyclelution-importable xlsx:

    sync_state   Phase 1  per-record sync status (pending/ready/synced/excluded)
    wipe_lookup  Phase 1  read-only join into wipe_index.db by drive SN
    manual_input Phase 1  read operator-entered fields (already client-mapped)
    normalizer   Phase 2  config-driven field mapping engine (5 converters)
    gate         Phase 2  hard/soft pre-check gate
    scan         Phase 2  batch pending -> normalize -> gate -> status
    exporter     Phase 3  ready records -> Adjust-template xlsx

Design: the data-preparation layer (state machine + gate + mapping) is
decoupled from the transport layer (xlsx today, API later). Only the
transport swaps when Cyclelution's new API ships.
"""
