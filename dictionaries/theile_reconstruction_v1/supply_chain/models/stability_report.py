"""Stability of each arm's vocabulary under a different random seed and under a
50% document subsample. Reports both whole-list Jaccard and retention of the
highest-cosine core, because the two differ a lot."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def load(d: Path) -> dict[str, float]:
    return {json.loads(l)["term"]: json.loads(l)["max_cosine"]
            for l in (d / "supply_chain_terms.jsonl").open()}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pairs", required=True,
                   help="label:baseline_dir:variant_dir:kind, comma separated")
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()

    rows = []
    for spec in a.pairs.split(","):
        label, base, var, kind = spec.split(":")
        A, B = load(Path(base)), load(Path(var))
        ka, kb = set(A), set(B)
        order = sorted(A, key=lambda t: -A[t])
        def keep(n): 
            top = order[:n]
            return sum(1 for t in top if t in kb) / len(top) if top else 0.0
        rows.append({
            "arm": label, "perturbation": kind,
            "size_baseline": len(ka), "size_variant": len(kb),
            "jaccard": round(len(ka & kb) / len(ka | kb), 4),
            "retained_top_50": round(keep(50), 4),
            "retained_top_100": round(keep(100), 4),
            "retained_top_208": round(keep(208), 4),
            "retained_all": round(keep(len(order)), 4),
        })
    with a.output.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    for r in rows:
        print(f"  {r['arm']:<10} {r['perturbation']:<12} jaccard={r['jaccard']:.3f} "
              f"top100={r['retained_top_100']:.1%} top208={r['retained_top_208']:.1%} "
              f"all={r['retained_all']:.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
