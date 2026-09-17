"""Stage 8: score every arm on the outcome-blind criteria and write method_comparison.csv.

Nothing here reads CAR data, transcript scores, or returns. The only external
reference is Table 2 of the paper.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "corpus"))
from seeds import SEEDS, SINGLE_WORD_SEEDS, TABLE_2, TABLE_2_NON_SEED, PAPER_FINAL_SIZE

# Terms that are ordinary corporate filing language rather than supply chain
# vocabulary. Used only as a precision penalty, never to edit a vocabulary.
GENERIC = {
    "company", "companies", "business", "businesses", "operations", "operating",
    "management", "results", "financial", "fiscal", "year", "years", "quarter",
    "increase", "increased", "decrease", "decreased", "significant", "significantly",
    "approximately", "additional", "certain", "various", "including", "primarily",
    "general", "total", "net", "revenue", "revenues", "income", "costs", "expenses",
    "market", "markets", "growth", "future", "period", "periods", "following",
    "however", "although", "based", "rather", "own", "house", "together", "shared",
    "directly", "overall", "largely", "continues", "experience", "turn", "level",
    "major", "large", "added", "better", "globally", "quickly", "provide", "providing",
    "needs", "advantage", "strategy", "strategic", "customers'", "ability", "may",
}


def load_terms(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.open()]


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if (a or b) else 0.0


def evaluate(d: Path, stats: dict) -> dict:
    terms = load_terms(d / "supply_chain_terms.jsonl")
    summary = json.loads((d / "extraction_summary.json").read_text())
    model_cfg = json.loads((Path(summary["run_dir"]) / "model_config.json").read_text())
    corpus = Path(model_cfg["corpus"]).name.replace("corpus_", "").replace(".txt.gz", "")
    per_seed = json.loads((d / "per_seed_top100.json").read_text())
    tset = {t["term"] for t in terms}
    cos = {t["term"]: t["max_cosine"] for t in terms}
    ndocs = stats["documents"]

    # 1. Table 2 recovery.
    rec_all = sorted(tset & set(TABLE_2))
    rec_non_seed = sorted(tset & set(TABLE_2_NON_SEED))

    # 2. Cosine ordering agreement on recovered non-seed Table 2 terms.
    if len(rec_non_seed) >= 3:
        ours = [cos[t] for t in rec_non_seed]
        theirs = [TABLE_2_NON_SEED[t][0] for t in rec_non_seed]
        rho, pval = spearmanr(ours, theirs)
    else:
        rho, pval = float("nan"), float("nan")

    # 5. Per-seed coverage: seeds that actually contributed a surviving term.
    contributing = {t["nearest_seed"] for t in terms if t["seed_rank"]}
    empty_seeds = summary["seeds_with_empty_candidate_list"]

    # 6. Frequency / document-frequency support.
    freqs = np.array([t["frequency"] for t in terms])
    dfs = np.array([t["document_frequency"] for t in terms])

    # 7. Generic corporate language.
    generic_hits = sorted(tset & GENERIC)
    # A term in >60% of all 10-Ks is filing boilerplate almost by definition.
    ubiquitous = sorted(t["term"] for t in terms if t["document_frequency"] > 0.60 * ndocs)

    return {
        "method": summary["method"],
        "corpus": corpus,
        "multiword_seed_mode": summary["multiword_seed_mode"],
        "final_size": summary["final_size"],
        "size_vs_paper_208": summary["final_size"] - PAPER_FINAL_SIZE,
        "size_ratio_vs_paper": round(summary["final_size"] / PAPER_FINAL_SIZE, 3),
        "unique_candidates_before_multiword_removal": summary["unique_candidates"],
        "multiword_removed": summary["multiword_candidates_removed"],
        "table2_recovered_of_30": len(rec_all),
        "table2_nonseed_recovered_of_17": len(rec_non_seed),
        "table2_missing": ";".join(summary["table_2_missing"]),
        "cosine_spearman_rho": round(float(rho), 4) if rho == rho else "",
        "cosine_spearman_p": round(float(pval), 4) if pval == pval else "",
        "seeds_contributing": len(contributing),
        "seeds_with_no_candidates": ";".join(empty_seeds),
        "median_frequency": int(np.median(freqs)) if len(freqs) else 0,
        "median_document_frequency": int(np.median(dfs)) if len(dfs) else 0,
        "pct_terms_df_under_100": round(100.0 * float((dfs < 100).mean()), 1) if len(dfs) else 0.0,
        "generic_term_count": len(generic_hits),
        "generic_terms": ";".join(generic_hits),
        "ubiquitous_df_over_60pct_count": len(ubiquitous),
        "ubiquitous_terms": ";".join(ubiquitous[:25]),
        "run_dir": summary["run_dir"],
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--candidate-dirs", type=Path, nargs="+", required=True)
    p.add_argument("--stats", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--stability-groups", type=str, default="",
                   help="semicolon-separated groups of dirs that differ only by random seed")
    a = p.parse_args()

    with gzip.open(a.stats, "rt") as fh:
        stats = json.load(fh)

    rows = [evaluate(d, stats) for d in a.candidate_dirs]

    # 4. Stability: Jaccard of final vocabularies within each group.
    stability = {}
    for group in filter(None, a.stability_groups.split(";")):
        dirs = [Path(x) for x in group.split(",")]
        sets = [{t["term"] for t in load_terms(d / "supply_chain_terms.jsonl")} for d in dirs]
        pairs = [jaccard(sets[i], sets[j]) for i in range(len(sets)) for j in range(i + 1, len(sets))]
        key = json.loads((dirs[0] / "extraction_summary.json").read_text())["method"]
        stability[key] = round(float(np.mean(pairs)), 4) if pairs else float("nan")
    for r in rows:
        r["stability_jaccard_across_seeds"] = stability.get(r["method"], "")

    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    cols = ["method", "corpus", "multiword_seed_mode", "final_size", "table2_recovered_of_30",
            "table2_nonseed_recovered_of_17", "cosine_spearman_rho", "generic_term_count",
            "seeds_contributing"]
    print(" | ".join(c[:18].ljust(18) for c in cols))
    for r in rows:
        print(" | ".join(str(r[c])[:18].ljust(18) for c in cols))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
