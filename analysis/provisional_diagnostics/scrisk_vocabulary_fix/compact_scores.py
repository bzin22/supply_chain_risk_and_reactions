#!/usr/bin/env python3
"""Copy a scored transcript CSV without ``transcript_text``.

A full scored CSV is 750 MB because it carries every transcript.  A
sensitivity run only needs the score columns, so this writes the compact form
and nothing else changes.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # repository root
import calculate_supply_chain_transcript_scores as S

DROP = ("transcript_text",)


def main() -> None:
    S.configure_csv_field_size_limit()
    source, target = Path(sys.argv[1]), Path(sys.argv[2])
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = [name for name in (reader.fieldnames or []) if name not in DROP]
        with target.open("w", newline="", encoding="utf-8") as out:
            writer = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            rows = 0
            for row in reader:
                writer.writerow(row)
                rows += 1
    print(f"Wrote {target} ({rows:,} rows, {len(fields)} columns)")


if __name__ == "__main__":
    main()
