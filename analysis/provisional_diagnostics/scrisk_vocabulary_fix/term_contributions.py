#!/usr/bin/env python3
"""Attribute every SCRisk pair to the supply-chain term that produced it.

This exists to answer one question with numbers instead of argument: exactly
how much of the SCRisk score comes from the two vocabulary properties the
audit flagged, under both the original and the corrected vocabulary.

    shortage / shortages   in both the supply-chain and the risk vocabulary,
                           so one occurrence pairs with itself at distance 0
    customer / customers   the broadest of the 16 seeds, weighted 1.0 in v2

For each version it writes a per-term contribution table and a per-call
decomposition of the weight sum into three parts: the shortage family, the
customer family, and identical-span self-pairs.  A call is "non-zero only
because of" a part when removing that part takes its weight sum to exactly 0.

Nothing here changes a score.  It re-runs the pipeline's own
``calculate_raw_scores`` logic with the pairs labelled.

Provisional: the supply-chain and risk vocabularies it decomposes are the
repository's own, not the paper's dictionaries, so the shares below describe
this pipeline and nothing else.
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
import calculate_supply_chain_transcript_scores as S  # noqa: E402

SHORTAGE_FAMILY = {"shortage", "shortages"}
CUSTOMER_FAMILY = {"customer", "customers"}
VERSIONS = ("v1_library_only", "v2_seeds_inflections")

_CTX: dict = {}


def init_worker(library_path: str) -> None:
    library = S.load_supply_chain_library(Path(library_path))
    for version in VERSIONS:
        weights = S.build_supply_chain_vocabulary(library, version)
        risk = S.build_risk_vocabulary(S.STARTER_RISK_WORDS, version)
        _CTX[version] = {
            "weights": weights,
            "sc_index": S.build_phrase_index(weights),
            "risk_index": S.build_phrase_index(risk),
        }


def decompose(tokens, context) -> tuple[dict[str, list[float]], dict[str, float]]:
    """Return per-term (weight, pair count) and the three-part decomposition."""
    supply = S.find_indexed_occurrences(tokens, context["sc_index"])
    risk = S.find_indexed_occurrences(tokens, context["risk_index"])
    weights = context["weights"]
    by_term: dict[str, list[float]] = {}
    parts = {"total": 0.0, "shortage_family": 0.0, "customer_family": 0.0, "identical_span": 0.0,
             "pairs": 0.0, "identical_span_pairs": 0.0}
    for occurrence in supply:
        weight = weights[occurrence.term]
        for other in risk:
            if not S.spans_within(occurrence, other, S.WINDOW):
                continue
            entry = by_term.setdefault(occurrence.term, [0.0, 0])
            entry[0] += weight
            entry[1] += 1
            parts["total"] += weight
            parts["pairs"] += 1
            if occurrence.term in SHORTAGE_FAMILY:
                parts["shortage_family"] += weight
            if occurrence.term in CUSTOMER_FAMILY:
                parts["customer_family"] += weight
            if occurrence.start == other.start and occurrence.end == other.end:
                parts["identical_span"] += weight
                parts["identical_span_pairs"] += 1
    return by_term, parts


def analyse(job):
    key, text = job
    tokens = S.tokenize(text)
    result = {"key": key, "tokens": len(tokens)}
    for version in VERSIONS:
        by_term, parts = decompose(tokens, _CTX[version])
        result[version] = {"by_term": by_term, "parts": parts}
    return result


def analysable_keys(events: Path) -> set[str]:
    """Event keys this run's analysis uses: an estimated CAR and a defined SCRisk."""
    keys = set()
    with events.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["event_status"] == "ok" and row["CAR_0_1"] and row["SCRisk"]:
                keys.add(f"{row['ticker']}|{row['quarter_label']}")
    return keys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-dir", type=Path, required=True,
                        help="scoring run holding earnings_call_transcripts_scored.csv "
                             "and earnings_call_event_returns.csv")
    parser.add_argument("--library", type=Path, required=True,
                        help="terms.jsonl the run was scored with")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=max(1, min(8, mp.cpu_count() - 1)))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    scored = args.run_dir / "earnings_call_transcripts_scored.csv"
    events = args.run_dir / "earnings_call_event_returns.csv"
    for path in (scored, events, args.library):
        if not path.exists():
            raise SystemExit(f"missing input: {path}")
    OUT = args.output_dir
    S.configure_csv_field_size_limit()
    OUT.mkdir(parents=True, exist_ok=True)
    keys = analysable_keys(events)
    print(f"analysable calls: {len(keys):,}")

    def jobs():
        with scored.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                key = f"{row['ticker']}|{row['quarter_label']}"
                if key in keys:
                    yield (key, row.get("transcript_text") or "")

    term_weight = {version: Counter() for version in VERSIONS}
    term_pairs = {version: Counter() for version in VERSIONS}
    term_calls = {version: Counter() for version in VERSIONS}
    totals = {version: Counter() for version in VERSIONS}
    per_call_rows = []

    with mp.Pool(args.workers, initializer=init_worker,
                 initargs=(str(args.library),)) as pool:
        for index, result in enumerate(pool.imap_unordered(analyse, jobs(), chunksize=8), start=1):
            row = {"ticker_quarter": result["key"], "tokens": result["tokens"]}
            for version in VERSIONS:
                by_term = result[version]["by_term"]
                parts = result[version]["parts"]
                for term, (weight, pairs) in by_term.items():
                    term_weight[version][term] += weight
                    term_pairs[version][term] += pairs
                    term_calls[version][term] += 1
                totals[version]["weight"] += parts["total"]
                totals[version]["pairs"] += parts["pairs"]
                totals[version]["calls_nonzero"] += int(parts["total"] > 0)
                totals[version]["calls_nonzero_without_shortage_family"] += int(
                    parts["total"] - parts["shortage_family"] > 0)
                totals[version]["calls_nonzero_without_customer_family"] += int(
                    parts["total"] - parts["customer_family"] > 0)
                totals[version]["calls_nonzero_without_identical_span"] += int(
                    parts["total"] - parts["identical_span"] > 0)
                totals[version]["shortage_family_weight"] += parts["shortage_family"]
                totals[version]["customer_family_weight"] += parts["customer_family"]
                totals[version]["identical_span_weight"] += parts["identical_span"]
                totals[version]["identical_span_pairs"] += parts["identical_span_pairs"]
                prefix = "v1" if version == VERSIONS[0] else "v2"
                row[f"{prefix}_weight_sum"] = round(parts["total"], 8)
                row[f"{prefix}_pairs"] = int(parts["pairs"])
                row[f"{prefix}_shortage_family_weight"] = round(parts["shortage_family"], 8)
                row[f"{prefix}_customer_family_weight"] = round(parts["customer_family"], 8)
                row[f"{prefix}_identical_span_weight"] = round(parts["identical_span"], 8)
                row[f"{prefix}_identical_span_pairs"] = int(parts["identical_span_pairs"])
            per_call_rows.append(row)
            if index % 2500 == 0:
                print(f"  {index:,}", flush=True)

    per_call_rows.sort(key=lambda r: r["ticker_quarter"])
    with (OUT / "term_contributions_per_call.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(per_call_rows[0].keys()))
        writer.writeheader()
        writer.writerows(per_call_rows)

    with (OUT / "term_contributions_by_term.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["vocabulary_version", "supply_chain_term", "pairs", "weight_contributed",
                         "percent_of_total_weight", "calls_it_contributed_to"])
        for version in VERSIONS:
            total = totals[version]["weight"] or 1.0
            for term, weight in term_weight[version].most_common():
                writer.writerow([version, term, term_pairs[version][term],
                                 round(weight, 6), round(100 * weight / total, 4),
                                 term_calls[version][term]])

    report = {"run_dir": str(args.run_dir), "analysable_calls": len(keys)}
    for version in VERSIONS:
        counts = totals[version]
        nonzero = counts["calls_nonzero"]
        report[version] = {
            "total_weight": round(counts["weight"], 4),
            "total_pairs": int(counts["pairs"]),
            "calls_nonzero": int(nonzero),
            "shortage_family": {
                "weight": round(counts["shortage_family_weight"], 4),
                "percent_of_total_weight": round(100 * counts["shortage_family_weight"] / counts["weight"], 4),
                "calls_that_become_zero_without_it": int(nonzero - counts["calls_nonzero_without_shortage_family"]),
            },
            "customer_family": {
                "weight": round(counts["customer_family_weight"], 4),
                "percent_of_total_weight": round(100 * counts["customer_family_weight"] / counts["weight"], 4),
                "calls_that_become_zero_without_it": int(nonzero - counts["calls_nonzero_without_customer_family"]),
            },
            "identical_span_self_pairs": {
                "pairs": int(counts["identical_span_pairs"]),
                "weight": round(counts["identical_span_weight"], 4),
                "percent_of_total_weight": round(100 * counts["identical_span_weight"] / counts["weight"], 4),
                "calls_that_become_zero_without_it": int(nonzero - counts["calls_nonzero_without_identical_span"]),
            },
            "top_10_terms_by_weight": [
                [term, round(weight, 2), round(100 * weight / counts["weight"], 2)]
                for term, weight in term_weight[version].most_common(10)
            ],
        }
    (OUT / "term_contributions_summary.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
