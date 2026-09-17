"""Per-term comparison against Table 2, with each discrepancy classified.

Classification is decided by evidence available in our own artifacts, in this
order, so the label is reproducible rather than a judgement call:

  corpus                 term never occurs, or occurs too rarely to clear
                         min_count, in our 50k-document sample
  preprocessing          term exists in the corpus but our cleaning produced a
                         different surface form, or it survived ranking and was
                         then removed as a multiword n-gram
  model                  term is in the model vocabulary with adequate support
                         but no seed ranks it inside its top-100
  proprietary_algorithm  term has adequate corpus support and is in the model
                         vocabulary, yet EVERY method misses it. No single model
                         explains that, so it points at metaHeuristica's term
                         extraction rather than at any one arm.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "corpus"))
from vector_space import load
from seeds import SEEDS, SINGLE_WORD_SEEDS, TABLE_2

# Deliberately NOT a hardcoded acronym list. Table 2 glosses vars, pims and isvs
# as acronyms, and it is tempting to write all three off as artifacts of
# metaHeuristica's extraction. But vars and isvs ARE recovered here by plain
# distributional models, so "acronyms are unreachable" is false. The
# proprietary_algorithm label is therefore earned by cross-arm evidence only:
# a term every method misses despite having the corpus support to be reachable.


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--candidate-dir", type=Path, required=True)
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--stats", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    # Comma-separated, not nargs: conda run re-joins space-separated values into
    # a single argument.
    p.add_argument("--all-candidate-dirs", default="",
                   help="comma-separated arms, used to decide which misses are unanimous")
    a = p.parse_args()

    terms = {json.loads(l)["term"]: json.loads(l)
             for l in (a.candidate_dir / "supply_chain_terms.jsonl").open()}
    per_seed = json.loads((a.candidate_dir / "per_seed_top100.json").read_text())
    summary = json.loads((a.candidate_dir / "extraction_summary.json").read_text())
    vocab, V, config = load(a.run_dir)
    idx = {w: i for i, w in enumerate(vocab)}
    with gzip.open(a.stats, "rt") as fh:
        stats = json.load(fh)
    tf, df = stats["term_frequency"], stats["document_frequency"]
    min_count = config.get("min_count", 25)

    missed_by_all = set(TABLE_2)
    all_dirs = [Path(x) for x in a.all_candidate_dirs.split(",") if x] or [a.candidate_dir]
    for d in all_dirs:
        found = {json.loads(l)["term"] for l in (d / "supply_chain_terms.jsonl").open()}
        missed_by_all -= found

    # Best rank the term achieved in ANY seed list, even if later removed.
    best_rank = {}
    for seed, rows in per_seed.items():
        for r in rows:
            k = r["term"]
            if k not in best_rank or r["rank"] < best_rank[k][0]:
                best_rank[k] = (r["rank"], seed, r["cosine"])

    rows = []
    for term, (paper_cos, paper_freq) in sorted(TABLE_2.items(), key=lambda kv: (-kv[1][0], -kv[1][1])):
        got = terms.get(term)
        in_corpus = term in tf
        in_model = term in idx
        ranked = best_rank.get(term)

        if got:
            cls, why = "", "recovered"
        elif not in_corpus:
            cls, why = "corpus", "term never appears in the 50k-document sample"
        elif tf[term] < min_count:
            cls, why = "corpus", f"appears {tf[term]}x, below min_count={min_count}"
        elif not in_model:
            cls, why = "corpus", "filtered out of the model vocabulary by min_count/min_df"
        elif ranked:
            cls, why = "preprocessing", f"ranked #{ranked[0]} under '{ranked[1]}' but dropped after ranking"
        else:
            # How far off was it? Report the best cosine any seed gives it.
            i = idx[term]
            best = max(float(V[i] @ V[idx[s]]) for s in SINGLE_WORD_SEEDS if s in idx)
            if term in missed_by_all:
                cls = "proprietary_algorithm"
                why = (f"in vocabulary (tf={tf[term]:,}) with max seed cosine {best:.3f}, and missed "
                       f"by every method tested, so no single model explains it")
            else:
                cls = "model"
                why = (f"in vocabulary (tf={tf[term]:,}) but max seed cosine {best:.3f} is outside "
                       f"every top-100; other arms do recover it")

        rows.append({
            "term": term,
            "is_seed": term in SINGLE_WORD_SEEDS,
            "paper_cosine": paper_cos,
            "paper_transcript_frequency": paper_freq,
            "recovered": bool(got),
            "our_max_cosine": got["max_cosine"] if got else "",
            "our_nearest_seed": got["nearest_seed"] if got else "",
            "our_seed_rank": got["seed_rank"] if got else "",
            "corpus_frequency": tf.get(term, 0),
            "corpus_document_frequency": df.get(term, 0),
            "in_model_vocabulary": in_model,
            "discrepancy_class": cls,
            "diagnosis": why,
        })

    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    n_rec = sum(r["recovered"] for r in rows)
    import collections
    cls_counts = collections.Counter(r["discrepancy_class"] for r in rows if not r["recovered"])
    print(f"{summary['method']}/{summary['multiword_seed_mode']}: recovered {n_rec}/30")
    for k, v in cls_counts.most_common():
        print(f"  missing, {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
