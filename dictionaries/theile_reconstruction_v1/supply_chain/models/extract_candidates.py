"""Stage 7: turn any trained vector space into a candidate keyword library.

Implements the paper's funnel literally:
  1. 100 nearest terms per seed, with cosine similarity          (16 x 100 = 1,600)
  2. consolidate, keeping the MAXIMUM cosine for terms reached by several seeds
  3. remove duplicates
  4. remove multiword n-grams
  5. seeds that survive step 4 are assigned cosine 1.0  (Table 2 note)

Multiword seed vectors resolve one of two documented ways:
  phrase          - use the joined phrase token, and fail the seed if absent
  average         - L2-normalise each component vector, mean, renormalise
  phrase_fallback - phrase token when present, component average otherwise
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "corpus"))
from vector_space import load
from seeds import SEEDS, SINGLE_WORD_SEEDS, TABLE_2


def seed_vector(seed, idx, V, mode):
    """Return (vector, resolution) or (None, reason)."""
    words = seed.split()
    if len(words) == 1:
        i = idx.get(seed)
        return (V[i], "direct") if i is not None else (None, "seed_out_of_vocabulary")
    if mode in ("phrase", "phrase_fallback"):
        i = idx.get("_".join(words))
        if i is not None:
            return V[i], "phrase_token"
        if mode == "phrase":
            return None, "phrase_token_absent"
    parts = [V[idx[w]] for w in words if w in idx]
    if len(parts) != len(words):
        return None, "component_out_of_vocabulary"
    v = np.mean(parts, axis=0)
    n = np.linalg.norm(v)
    how = "component_average" if mode == "average" else "component_average_fallback"
    return (v / n if n else v), how


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--stats", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--multiword-seed-mode", choices=["phrase", "average", "phrase_fallback"], required=True)
    p.add_argument("--top-k", type=int, default=100)
    a = p.parse_args()

    vocab, V, config = load(a.run_dir)
    idx = {w: i for i, w in enumerate(vocab)}
    with gzip.open(a.stats, "rt") as fh:
        stats = json.load(fh)
    tf, df = stats["term_frequency"], stats["document_frequency"]

    per_seed, resolution = {}, {}
    for seed in SEEDS:
        sv, how = seed_vector(seed, idx, V, a.multiword_seed_mode)
        resolution[seed] = how
        if sv is None:
            per_seed[seed] = []
            continue
        sims = V @ sv
        # top_k+4 so the seed's own tokens can be dropped without shrinking the
        # list. Clamped to the vocabulary: argpartition raises when kth exceeds
        # the array, which a small vocabulary would otherwise hit.
        n = min(a.top_k + 4, sims.size - 1)
        cand = np.argpartition(-sims, n)[: n + 1] if n > 0 else np.arange(sims.size)
        cand = cand[np.argsort(-sims[cand])]
        drop = set(seed.split()) | {"_".join(seed.split())}
        rows = []
        for i in cand:
            w = vocab[i]
            if w in drop:
                continue
            rows.append({"term": w, "cosine": round(float(sims[i]), 6), "rank": len(rows) + 1})
            if len(rows) == a.top_k:
                break
        per_seed[seed] = rows

    # Consolidate with max cosine.
    best: dict[str, dict] = {}
    for seed, rows in per_seed.items():
        for r in rows:
            e = best.setdefault(r["term"], {"term": r["term"], "max_cosine": -1.0,
                                            "nearest_seed": None, "seed_rank": None,
                                            "all_seed_matches": []})
            e["all_seed_matches"].append({"seed": seed, "cosine": r["cosine"], "seed_rank": r["rank"]})
            if r["cosine"] > e["max_cosine"]:
                e.update(max_cosine=r["cosine"], nearest_seed=seed, seed_rank=r["rank"])

    raw_candidates = len(best)
    multiword = [t for t in best if "_" in t]
    for t in multiword:
        del best[t]

    # Seeds are added at cosine 1.0, but only the ones that survive multiword removal.
    seeds_added = []
    for s in SINGLE_WORD_SEEDS:
        if s not in idx:
            continue
        seeds_added.append(s)
        # Overwrite the cosine to 1.0 per Table 2's note, but keep any matches this
        # seed earned in other seeds' lists rather than discarding that evidence.
        prior = best.get(s, {}).get("all_seed_matches", [])
        best[s] = {"term": s, "max_cosine": 1.0, "nearest_seed": s, "seed_rank": 0,
                   "all_seed_matches": [{"seed": s, "cosine": 1.0, "seed_rank": 0}] + prior}

    terms = sorted(best.values(), key=lambda e: (-e["max_cosine"], e["term"]))
    for e in terms:
        e["all_seed_matches"].sort(key=lambda m: -m["cosine"])
        e["frequency"] = tf.get(e["term"], 0)
        e["document_frequency"] = df.get(e["term"], 0)
        e["method"] = config["method"]
        e["multiword_seed_mode"] = a.multiword_seed_mode
        e["in_paper_table_2"] = e["term"] in TABLE_2
        e["review_status"] = "unreviewed"

    a.output_dir.mkdir(parents=True, exist_ok=True)
    with (a.output_dir / "supply_chain_terms.jsonl").open("w") as fh:
        for e in terms:
            fh.write(json.dumps(e) + "\n")
    (a.output_dir / "supply_chain_terms.txt").write_text(
        "\n".join(e["term"] for e in terms) + "\n")
    (a.output_dir / "per_seed_top100.json").write_text(json.dumps(per_seed, indent=2))

    recovered = sum(1 for e in terms if e["in_paper_table_2"])
    summary = {
        "method": config["method"],
        "multiword_seed_mode": a.multiword_seed_mode,
        "run_dir": str(a.run_dir),
        "seed_vector_resolution": resolution,
        "seeds_with_empty_candidate_list": [s for s, r in per_seed.items() if not r],
        "candidates_before_dedup": sum(len(r) for r in per_seed.values()),
        "unique_candidates": raw_candidates,
        "multiword_candidates_removed": len(multiword),
        "single_word_seeds_added": seeds_added,
        "final_size": len(terms),
        "paper_final_size": 208,
        "table_2_recovered": recovered,
        "table_2_total": len(TABLE_2),
        "table_2_missing": sorted(set(TABLE_2) - {e["term"] for e in terms}),
    }
    (a.output_dir / "extraction_summary.json").write_text(json.dumps(summary, indent=2))
    print(f"{config['method']}/{a.multiword_seed_mode}: "
          f"1600 -> {raw_candidates} unique -> -{len(multiword)} multiword "
          f"-> {len(terms)} final (paper 208); Table 2 {recovered}/30")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
