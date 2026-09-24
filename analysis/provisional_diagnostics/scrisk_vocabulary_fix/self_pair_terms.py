#!/usr/bin/env python3
"""List every term that pairs with its own occurrence, and count those pairs.

A supply-chain occurrence and a risk occurrence that share the same token span
are the same tokens, so the term can only be one that sits in both
vocabularies.  The complete list is therefore the intersection of the two,
which the scoring manifest already records as
``terms_in_both_supply_chain_and_risk``.  This counts the pairs directly
instead of trusting that argument.

Provisional: the risk vocabulary it counts against is the starter dictionary
in ``scoring/calculate_supply_chain_transcript_scores.py``, not the paper's.  The
counts describe whichever scoring run is passed in.
"""
from __future__ import annotations

import argparse
import csv
import json
import multiprocessing as mp
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # repository root
sys.path.insert(0, str(ROOT))
from scoring import calculate_supply_chain_transcript_scores as S  # noqa: E402

VERSIONS = ("v1_library_only", "v2_seeds_inflections")
_CONTEXT: dict = {}
_LIBRARY_PATH: Path


def init_worker(library_path: str) -> None:
    library = S.load_supply_chain_library(Path(library_path))
    for version in VERSIONS:
        supply = S.build_supply_chain_vocabulary(library, version)
        risk = S.build_risk_vocabulary(S.load_primary_risk_dictionary())
        _CONTEXT[version] = (S.build_phrase_index(supply), S.build_phrase_index(risk))


def analyse(text: str) -> dict[str, Counter]:
    tokens = S.tokenize(text)
    result = {}
    for version, (supply_index, risk_index) in _CONTEXT.items():
        supply = S.find_indexed_occurrences(tokens, supply_index)
        risk = S.find_indexed_occurrences(tokens, risk_index)
        risk_spans = {(o.start, o.end): o.term for o in risk}
        counts: Counter = Counter()
        for occurrence in supply:
            risk_term = risk_spans.get((occurrence.start, occurrence.end))
            if risk_term is not None:
                # identical span on both sides: a self-pair
                counts[(occurrence.term, risk_term)] += 1
        result[version] = counts
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-dir", type=Path, required=True,
                        help="scoring run holding earnings_call_transcripts_scored.csv "
                             "and earnings_call_event_returns.csv")
    parser.add_argument("--library", type=Path, required=True, help="terms.jsonl the run was scored with")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=max(1, min(8, mp.cpu_count() - 1)))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    S.configure_csv_field_size_limit()
    events = args.run_dir / "earnings_call_event_returns.csv"
    scored = args.run_dir / "earnings_call_transcripts_scored.csv"
    for path in (events, scored, args.library):
        if not path.exists():
            raise SystemExit(f"missing input: {path}")

    keys = set()
    with events.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["event_status"] == "ok" and row["CAR_0_1"] and row["SCRisk"]:
                keys.add((row["ticker"], row["quarter_label"]))

    def jobs():
        with scored.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if (row["ticker"], row["quarter_label"]) in keys:
                    yield row.get("transcript_text") or ""

    totals = {version: Counter() for version in VERSIONS}
    with mp.Pool(args.workers, initializer=init_worker, initargs=(str(args.library),)) as pool:
        for result in pool.imap_unordered(analyse, jobs(), chunksize=16):
            for version, counts in result.items():
                totals[version].update(counts)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    library = S.load_supply_chain_library(args.library)
    report = {"run_dir": str(args.run_dir), "analysable_calls": len(keys)}
    with (args.output_dir / "self_pair_terms.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["vocabulary_version", "supply_chain_term", "risk_term",
                         "identical_span_pairs", "weight_each", "weight_contributed"])
        for version, counts in totals.items():
            weights = S.build_supply_chain_vocabulary(library, version)
            report[version] = {"identical_span_pairs": sum(counts.values()),
                               "terms": sorted({term for term, _ in counts})}
            print(f'== {version}: {sum(counts.values()):,} identical-span pairs')
            for (supply_term, risk_term), pairs in counts.most_common():
                writer.writerow([version, supply_term, risk_term, pairs, weights[supply_term],
                                 round(pairs * weights[supply_term], 6)])
                print(f'   supply-chain "{supply_term}"  +  risk "{risk_term}"   {pairs:,} pairs')
    (args.output_dir / "self_pair_terms.json").write_text(json.dumps(report, indent=2))
    print(f"wrote {args.output_dir}/self_pair_terms.csv and .json")


if __name__ == "__main__":
    main()
