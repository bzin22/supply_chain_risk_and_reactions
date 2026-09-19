#!/usr/bin/env python3
"""Append call-level supply-chain scores to every matching transcript segment.

The score input must contain exactly one row per (ticker, quarter_label), as
produced from the call-level ``earnings_call_transcripts.csv``.  The segment
source remains unchanged; this program writes a separate, atomically replaced
CSV and fails on missing or duplicate event keys by default.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import tempfile
from pathlib import Path

from study_period import validate_csv_in_study_period


SCORE_FIELDS = (
    "SCRisk_weight_sum", "SCRisk_raw", "SCRisk_sd", "SCRisk",
    "Resolution_weight_sum", "Resolution_raw", "Resolution_sd", "Resolution",
    "score_word_count", "supply_chain_occurrences", "risk_occurrences",
    "resolution_occurrences", "supply_chain_risk_pairs", "supply_chain_resolution_pairs",
)


def configure_csv_field_size_limit() -> None:
    """Accept transcript segments that exceed the stdlib's small CSV limit."""

    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


def event_key(row: dict[str, str]) -> tuple[str, str]:
    return (
        (row.get("ticker") or row.get("symbol") or "").strip().upper(),
        (row.get("quarter_label") or "").strip().upper(),
    )


def load_scores(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = {"ticker", "quarter_label", "SCRisk", "Resolution"} - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path} is missing required score columns: {sorted(missing)}")
        scores: dict[tuple[str, str], dict[str, str]] = {}
        for row in reader:
            key = event_key(row)
            if not all(key):
                raise ValueError(f"Score row lacks ticker or quarter_label in {path}")
            if key in scores:
                raise ValueError(f"Duplicate score row for event {key} in {path}")
            scores[key] = {field: (row.get(field) or "").strip() for field in SCORE_FIELDS}
    if not scores:
        raise ValueError(f"No score rows found in {path}")
    return scores


def join_scores(segments: Path, scores_path: Path, output: Path) -> None:
    if output.resolve() in {segments.resolve(), scores_path.resolve()}:
        raise ValueError("Refusing to overwrite an input file; choose a separate --output path")
    validate_csv_in_study_period(segments, context="segment input")
    validate_csv_in_study_period(scores_path, context="scoring input")
    scores = load_scores(scores_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    matched = 0
    missing: list[tuple[str, str]] = []
    with segments.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        source_fields = list(reader.fieldnames or [])
        required = {"ticker", "quarter_label"}
        absent = required - set(source_fields)
        if absent:
            raise ValueError(f"{segments} is missing required columns: {sorted(absent)}")
        duplicates = set(source_fields) & set(SCORE_FIELDS)
        if duplicates:
            raise ValueError(f"{segments} already has score columns: {sorted(duplicates)}")
        with tempfile.NamedTemporaryFile(
            mode="w", newline="", encoding="utf-8", dir=output.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            writer = csv.DictWriter(handle, fieldnames=source_fields + list(SCORE_FIELDS), extrasaction="ignore")
            writer.writeheader()
            for row in reader:
                key = event_key(row)
                score = scores.get(key)
                if score is None:
                    missing.append(key)
                    continue
                row.update(score)
                writer.writerow(row)
                matched += 1
    if missing:
        temporary.unlink(missing_ok=True)
        sample = ", ".join(f"{ticker}/{quarter}" for ticker, quarter in missing[:5])
        raise ValueError(f"{len(missing):,} segments have no score row; examples: {sample}")
    os.replace(temporary, output)
    print(f"Joined {matched:,} segments to {len(scores):,} event scores")
    print(f"Wrote {output}")


def main() -> None:
    configure_csv_field_size_limit()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--segments", type=Path, required=True)
    parser.add_argument("--supply-chain-scores", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        join_scores(args.segments, args.supply_chain_scores, args.output)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
