#!/usr/bin/env python3
"""Print the head, token count and distinct-token count of named transcripts.

Used to eyeball a transcript whose score looks wrong before trusting any
aggregate about it. Provisional: it reads whichever scoring run you point it
at and makes no claim about the paper's sample.

    python inspect_odd.py ETN:2012Q4 ARKR:2012Q3
    SCRISK_AUDIT_RUN=artifacts/... python inspect_odd.py F:2012Q4
"""
import csv
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # repository root
sys.path.insert(0, str(ROOT))
from scoring import calculate_supply_chain_transcript_scores as S  # noqa: E402

RUN = Path(os.environ.get(
    "SCRISK_AUDIT_RUN",
    str(ROOT / "artifacts/earnings_call_supply_chain/ppmi_svd_full_20260910")))
SCORED = RUN / "earnings_call_transcripts_scored.csv"


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(f"usage: {Path(sys.argv[0]).name} TICKER:QUARTER [TICKER:QUARTER ...]")
    wanted = set()
    for argument in sys.argv[1:]:
        ticker, _, quarter = argument.partition(":")
        if not quarter:
            raise SystemExit(f"expected TICKER:QUARTER, got {argument!r}")
        wanted.add((ticker.upper(), quarter.upper()))

    S.configure_csv_field_size_limit()
    if not SCORED.exists():
        raise SystemExit(f"scored transcripts not found: {SCORED}")

    found = {}
    with SCORED.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            key = (row["ticker"], row["quarter_label"])
            if key in wanted:
                found[key] = row["transcript_text"]

    for key in sorted(wanted):
        text = found.get(key)
        if text is None:
            print(f"=== {key[0]} {key[1]} | not present in {SCORED.name}")
            continue
        tokens = S.tokenize(text)
        print(f"=== {key[0]} {key[1]} | chars={len(text)} tokens={len(tokens)} "
              f"distinct={len(set(tokens))}")
        print("HEAD:", re.sub(r"\s+", " ", text[:420]))


if __name__ == "__main__":
    main()
