# analysis/provisional_diagnostics/

Code that explains why the pipeline behaves as it does. None of it produces a
study result.

These retained methodological diagnostics explain the earlier vocabulary and
zero-score investigations. They are not inputs to the canonical fractional
results. The current definitions and final figures are in the root README;
no diagnostic table should be treated as a replacement study result.

All output goes to `outputs/`, which is gitignored. Every script takes an
explicit run directory and output directory, or reads them from the
`SCRISK_AUDIT_*` environment variables. No script has a hard-coded absolute
path.

## `scrisk_zero_audit/`

Explains why so many calls score exactly zero on SCRisk. Run the whole thing:

```
analysis/provisional_diagnostics/scrisk_zero_audit/run_all.sh
```

Four environment variables select the run being audited: `SCRISK_AUDIT_RUN`,
`SCRISK_AUDIT_OUT`, `SCRISK_AUDIT_LIBRARY`, `SCRISK_AUDIT_VOCABULARY`.

| Script | What it measures |
| --- | --- |
| `dictionary_checks.py` | Vocabulary coverage: sizes, weights, terms sitting in two dictionaries at once, seeds present or missing |
| `scan.py` | Per-call recompute of every zero-score call, plus wider-window and tokenization probes |
| `probe_detail.py` | Which term pair each probe flip turns on |
| `probe_inflection.py` | What completing singular/plural inflections would recover |
| `content_integrity.py` | Transcript integrity: empty, boilerplate, and degenerate-repetition transcripts |
| `aggregate.py` | Zero rates by company, year, sector, and transcript length |
| `build_samples.py` | Samples zero-score transcripts for manual reading |
| `attribution.py` | Assigns each zero-score call one dominant cause |
| `seed_split.py` | Splits probe flips by whether a restored seed term drove them |
| `inspect_odd.py` | Prints one named transcript's head and token counts. Takes `TICKER:QUARTER` arguments |

Tests: `conda run -n dap-env python -m pytest
tests/test_zero_audit.py -q`. Tests that need a
generated audit CSV or the local term library skip when it is absent.

## `scrisk_vocabulary_fix/`

Measures what changes between the two supply-chain vocabulary versions,
`v1_library_only` and `v2_seeds_inflections`.

| Script | What it measures |
| --- | --- |
| `compare_before_after.py` | Zero rates, score distributions, and score flips between two scoring runs. `--before --after --output-dir`, optional `--sensitivity-dir` |
| `term_contributions.py` | How much of the total SCRisk weight each supply-chain term contributes. `--run-dir --library --output-dir` |
| `self_pair_terms.py` | Self-pair detection: terms in both the supply-chain and risk vocabularies, so one occurrence pairs with itself at distance 0. `--run-dir --library --output-dir` |
| `compact_scores.py` | Copies a scored CSV without `transcript_text`, which drops it from about 750 MB to the score columns only |
| `run_sensitivity.sh` | Scores four variants, each changing exactly one arguable vocabulary property, and their event returns |

The quintile table in `compare_before_after.py` puts zero-score calls in their
own group and cuts quintiles within the positive scores only. That is not the
paper's construction and its numbers cannot be compared to a paper quintile.
