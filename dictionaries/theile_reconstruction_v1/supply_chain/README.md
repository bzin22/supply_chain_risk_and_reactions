# Supply chain keyword library, reconstructed

A reconstruction of the supply chain keyword library in Theile et al. (2026),
built without the authors' files and without metaHeuristica. It is an
approximation. Do not call anything built on it a replication.

**Baseline: 254 terms**, windowed PPMI plus truncated SVD on a phrase-augmented
corpus of 50,000 10-K filings, 1997-2021. The paper reports 208.

## Files

| File | What it is |
| --- | --- |
| `supply_chain_terms.jsonl` | The baseline library. One record per term with cosine, nearest seed, rank, all seed matches, corpus frequency, document frequency, method, Table 2 flag, review status. |
| `supply_chain_terms.txt` | Same terms, one per line. |
| `per_seed_top100.json` | Raw top-100 candidates per seed, before consolidation and multiword removal. |
| `corpus_manifest.json` | Discovery, sampling, and coverage for all 50,246 selected filings. |
| `coverage_report.md` | Per-year corpus gate. Training did not start until this passed. |
| `model_config.json` | Model fingerprint, every random seed, both conda environments. |
| `method_comparison.csv` | All seven arms scored on the outcome-blind criteria. |
| `stability.csv` | Vocabulary stability under a different seed and a 50% corpus subsample. |
| `table2_comparison.csv` | Term by term against the paper's Table 2, each miss classified. |
| `validation_report.md` | The argument for the baseline, and what it is not. |
| `review/` | Blinded review sheet, key, and per-arm precision. |
| `sensitivity/` | Every alternative arm. Never merged into the baseline. |
| `corpus/`, `models/` | The code. |

## How it was chosen

Outcome-blind. No CAR, transcript score, or quintile return was computed or
inspected while selecting this vocabulary. Selection used Table 2 recovery,
cosine ordering agreement, blinded semantic precision, stability across seeds and
subsamples, per-seed coverage, frequency support, generic-language avoidance, and
final size. See `validation_report.md` section 8.

## The one thing to know

The paper cuts 1,600 candidates to 208 by removing multiword n-grams. That only
works if the model proposes multiword phrases. A unigram model proposes none, so
its list survives nearly intact at 1,109 terms. Training on a phrase-augmented
corpus and dropping multiword candidates after ranking is what reproduces the
paper's funnel. This is section 6 of the validation report and it is the reason
the earlier 1,093-term library in this repository came out five times too large.

## Running it

```
conda run --no-capture-output -n dap-env python -u corpus/discover_population.py --help
bash run_pipeline.sh
```

Word2Vec arms need the `dap-w2v` environment. gensim does not build on dap-env's
Python 3.14.
