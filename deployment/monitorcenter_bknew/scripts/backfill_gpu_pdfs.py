"""Backfill PDFs for existing GPU history records.

Run from /opt/monitorcenter/:
    python3 scripts/backfill_gpu_pdfs.py [--overwrite]

Options:
    --overwrite   Regenerate PDFs even if they already exist (default: skip)
"""

import sys
import json
import argparse
from pathlib import Path

# Allow running from repo root or /opt/monitorcenter
sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from app import app


def main():
    parser = argparse.ArgumentParser(description="Backfill GPU PDF reports")
    parser.add_argument("--overwrite", action="store_true",
                        help="Regenerate PDFs that already exist")
    args = parser.parse_args()

    history_root = config.BASE_DIR / "gpu" / "history"
    pdf_dir      = config.BASE_DIR / "gpu" / "pdf"

    if not history_root.exists():
        print(f"No history directory found at {history_root}")
        sys.exit(0)

    json_files = sorted(history_root.rglob("*.json"))
    if not json_files:
        print("No JSON files found.")
        sys.exit(0)

    print(f"Found {len(json_files)} history file(s). Generating PDFs…\n")

    ok = skip = fail = 0

    with app.app_context():
        from modules.gpu.pdf_generator import generate_pdf

        for p in json_files:
            try:
                envelope = json.loads(p.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"  [SKIP]  {p.name} — JSON read error: {e}")
                skip += 1
                continue

            sn = (envelope.get("sn") or "").strip()
            if not sn:
                print(f"  [SKIP]  {p.name} — no SN")
                skip += 1
                continue

            pdf_path = pdf_dir / f"{sn}.pdf"
            if pdf_path.exists() and not args.overwrite:
                print(f"  [SKIP]  {sn}.pdf — already exists")
                skip += 1
                continue

            try:
                out = generate_pdf(sn, envelope)
                print(f"  [OK]    {sn}.pdf  ← {p.relative_to(history_root)}")
                ok += 1
            except Exception as e:
                print(f"  [FAIL]  {sn} — {e}")
                fail += 1

    print(f"\nDone.  OK={ok}  skipped={skip}  failed={fail}")
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
