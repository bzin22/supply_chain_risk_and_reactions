"""Build a method-masked review sheet for semantic precision scoring.

The reviewer sees a shuffled pool of terms with no method label, no cosine, and
no run directory, so a judgement cannot be steered by which arm produced a term.
The key is written to a separate file and only merged after judgements are fixed.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--candidate-dirs", type=Path, nargs="+", required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--per-method", type=int, default=60)
    p.add_argument("--seed", type=int, required=True)
    a = p.parse_args()

    rng = random.Random(a.seed)
    pool = []
    for d in a.candidate_dirs:
        s = json.loads((d / "extraction_summary.json").read_text())
        label = f"{s['method']}|{s['multiword_seed_mode']}"
        terms = [json.loads(l) for l in (d / "supply_chain_terms.jsonl").open()]
        # Exclude the 13 seeds: they are true by construction and would inflate
        # every arm's precision identically.
        terms = [t for t in terms if t["seed_rank"]]
        pick = rng.sample(terms, min(a.per_method, len(terms)))
        for t in pick:
            pool.append({"method_label": label, "dir": str(d), "term": t["term"],
                         "max_cosine": t["max_cosine"], "frequency": t["frequency"],
                         "document_frequency": t["document_frequency"]})

    # Deduplicate across arms so the same term is judged once and consistently.
    by_term: dict[str, list[dict]] = {}
    for r in pool:
        by_term.setdefault(r["term"], []).append(r)
    items = sorted(by_term)
    rng.shuffle(items)

    a.output_dir.mkdir(parents=True, exist_ok=True)
    with (a.output_dir / "blinded_review_sheet.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["review_id", "term", "judgement", "note"])
        for i, term in enumerate(items, 1):
            w.writerow([f"R{i:04d}", term, "", ""])
    with (a.output_dir / "blinded_review_key.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["review_id", "term", "method_label", "max_cosine", "frequency", "document_frequency"])
        for i, term in enumerate(items, 1):
            for r in by_term[term]:
                w.writerow([f"R{i:04d}", term, r["method_label"], r["max_cosine"],
                            r["frequency"], r["document_frequency"]])
    print(f"{len(items)} unique terms to review across {len(a.candidate_dirs)} arms "
          f"-> {a.output_dir/'blinded_review_sheet.csv'}")
    print("judgement vocabulary: relevant | borderline | not_relevant")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
