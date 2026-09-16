# Why 7,379 earnings calls still have SCRisk = 0

Audit of run `ppmi_svd_full_20260910_vocab_v2`, the corrected-vocabulary run. Same code as the
first audit, pointed at a different run through `SCRISK_AUDIT_RUN`, `SCRISK_AUDIT_OUT` and
`SCRISK_AUDIT_VOCABULARY`. Nothing in the scoring methodology was changed to produce this:
the window is still 10 tokens, the tokenizer is untouched, and the pairing rule is untouched.
What changed is the vocabulary (118 to 216 supply-chain terms, 94 to 147 risk terms) and a
transcript-integrity filter.

Every number below comes from re-reading the scored transcripts with the pipeline's own
`tokenize`, `find_indexed_occurrences` and `spans_within`, so the audit and the scorer agree
by construction. All 7,379 recomputed word counts, supply-chain counts and risk counts match
the scored CSV exactly, with zero mismatches.

Comparison against the original run is in `outputs/scrisk_vocabulary_fix/BEFORE_AFTER_SUMMARY.md`.

## The population

`SCRisk == 0` and `event_status == 'ok'` gives exactly 7,379 calls, 41.38% of the 17,833
analysable events. 10,454 have a positive score. The first audit found 9,750 zeros out of
17,848, 54.63%.

| | First audit | This audit |
|---|---:|---:|
| Analysable events | 17,848 | 17,833 |
| Zero | 9,750 (54.63%) | 7,379 (41.38%) |
| Positive | 8,098 | 10,454 |

15 events left the analysable set because their transcripts hold no spoken content. They are
listed in the before-and-after report.

## Headline

**No remaining zero is a vocabulary failure and none is a transcript-integrity failure.**
Both of the first audit's fixable causes are gone. Every zero that is left is either a window
question or a call that genuinely never put supply-chain and risk language close together.

| Mechanism | Calls | % of zeros |
|---|---:|---:|
| Both vocabularies present, never within +/-10 tokens | 7,112 | 96.38% |
| Supply-chain vocabulary but no risk vocabulary | 265 | 3.59% |
| No supply-chain vocabulary | 2 | 0.03% |
| Neither vocabulary present | 0 | 0% |
| Empty transcript | 0 | 0% |

The two calls with no supply-chain vocabulary at all are ARKR 2014Q4 (1,467 tokens) and
HPQ 2015Q3 (1,916 tokens). Both are short, both are real transcripts, and neither contains a
single one of the 216 supply-chain terms. The first audit had 14 in this bucket; 12 of those
were the content-absent transcripts that the integrity filter now removes.

## One dominant cause per call

| Cause | Calls | % of zeros |
|---|---:|---:|
| Transcript content absent | 0 | 0% |
| Vocabulary coverage gap | 0 | 0% |
| Window near miss, 11 to 25 tokens | 2,668 | 36.16% |
| Window miss, 26 to 50 tokens | 1,551 | 21.02% |
| No co-located language at any plausible window | 3,160 | 42.82% |

Against the first audit, where the vocabulary gap accounted for 2,357 calls and content
absence for 14, both now zero by construction.

## Nearest-pair distance

Among the 7,112 zeros that contain both vocabularies:

| Nearest pair distance | Calls |
|---|---:|
| 11 to 15 tokens | 1,309 |
| 16 to 25 tokens | 1,359 |
| 26 to 50 tokens | 1,551 |
| over 50 tokens | 2,893 |

Median 37 tokens, mean 84, max 3,198. The first audit had median 41, mean 99, max 3,726.
Adding vocabulary pulled the whole distribution in, as it must: more terms means more
candidate pairs, so the nearest one is closer.

1,309 calls miss by five tokens or fewer, down from 1,466.

## False-zero probes

Each probe re-scores the same text under one perturbation. These are derived columns, not
pipeline changes.

| Probe | Calls turned non-zero | % of zeros |
|---|---:|---:|
| Restore the 16 seeds | **0** | **0%** |
| Complete the vocabulary's inflections | **0** | **0%** |
| Complete inflections and restore the seeds | **0** | **0%** |
| Split hyphens, apostrophes and periods | 222 | 3.01% |
| Crude suffix stemming of both dictionaries | 890 | 12.06% |
| Widen the window to 25 tokens | 2,668 | 36.16% |
| Widen the window to 50 tokens | 4,219 | 57.18% |

The three vocabulary probes are now exactly zero. That is the check that the fix landed: the
probes are unchanged code, run against a run whose vocabulary already contains what they add.

The stemming probe falls from 32.07% to 12.06%. Most of the first audit's stemming lift was
the crude stemmer reaching inflections the corrected vocabulary now covers properly. What is
left is still an upper bound inflated by `stocking` becoming `stock` and `tracking` becoming
`track`, and should not be read as a finding.

Hyphen splitting moves 222 calls in, against 216 before. The +/-10 window remains sensitive
to tokenization policy, since splitting lengthens the token stream and the window is a fixed
count of tokens. That is the first audit's point 4 and it is unchanged.

## Terms in both vocabularies

`shortages` was in both the supply-chain library and the risk dictionary in the original run.
The inflection completion adds `shortage` to both, so the singular now behaves the same way.
A span is zero tokens from itself, so one occurrence of either word makes a call non-zero
with no second word nearby.

This was left in place deliberately rather than changed. It is measured in
`outputs/scrisk_vocabulary_fix/term_contributions_summary.json`: the shortage family accounts
for 10.95% of all SCRisk weight in this run, and 402 of the 10,454 positive-score calls owe
their entire score to it. A full sensitivity run with both words dropped from the
supply-chain vocabulary is at `sensitivity/no_shortage_family/`, and one that forbids
identical-span pairs while keeping the terms is at `sensitivity/no_self_pairs/`.

## Zero against positive

Zero-score calls still talk less about both topics, and the gap survives controlling for
length.

| Measure | Zero (n=7,379) | Positive (n=10,454) |
|---|---:|---:|
| Median tokens | 6,476 | 7,134 |
| Median supply-chain hits | 46 | 72 |
| Median risk hits | 5 | 9 |
| Median supply-chain hits per 1,000 tokens | 7.42 | 10.79 |
| Median risk hits per 1,000 tokens | 0.78 | 1.41 |

Risk density remains the sharper separator, 1.8x against 1.5x for supply-chain density. The
first audit measured 1.7x and 1.4x on a narrower vocabulary, so the separation held up.

**Length.** The zero rate falls from 61.4% in the shortest decile to about 36% and then
flattens across deciles 6 to 10. The shape is the same as before at a lower level.

| Length decile | Token range | Zero rate |
|---|---|---:|
| 1 | 1,015 to 3,889 | 61.40% |
| 2 | 3,891 to 4,861 | 46.41% |
| 3 | 4,863 to 5,594 | 44.42% |
| 5 | 6,277 to 6,892 | 40.26% |
| 7 | 7,455 to 7,989 | 35.52% |
| 10 | 9,220 to 27,868 | 35.45% |

Decile 1 now starts at 1,015 tokens rather than 22, because the integrity filter removed
everything below 1,000.

**Year.** The zero rate still tracks the real world, and more sharply than before. It bottoms
at 22.48% in 2022 at the peak of supply-chain disruption, against 37.21% in the first audit,
and climbs back to 39.04% by 2024.

| Year | First audit | This audit | Change (pp) |
|---|---:|---:|---:|
| 2013 | 64.30% | 50.50% | -13.80 |
| 2016 | 64.84% | 52.21% | -12.63 |
| 2020 | 42.73% | 27.89% | -14.84 |
| 2021 | 38.74% | 26.38% | -12.36 |
| 2022 | 37.21% | 22.48% | -14.73 |
| 2023 | 48.36% | 33.66% | -14.70 |
| 2024 | 53.01% | 39.04% | -13.97 |

The ratio of the worst year to the best widens from 1.74x (64.84% over 37.21%) to 2.33x
(52.42% over 22.48%), so the construct discriminates across the cycle more, not less.

**Sector.** Healthcare 56.6% and Real Estate 53.4% remain highest. Semiconductors 29.7% and
Industrials 31.5% are lowest. Semiconductors moves the most, from 46.06% to 29.69%, which is
the first audit's central prediction: the coverage gap bit hardest in the highest-exposure
sector.

| Sector | First audit | This audit | Change (pp) |
|---|---:|---:|---:|
| Semiconductors | 46.06% | 29.69% | -16.37 |
| Real Estate | 67.93% | 53.38% | -14.55 |
| Energy | 54.30% | 40.63% | -13.67 |
| Healthcare | 68.83% | 56.61% | -12.22 |
| Financial Services | 53.52% | 41.52% | -12.00 |
| Industrials | 43.21% | 31.51% | -11.70 |

**Company.** Median company zero rate is 40.0%, down from 56.0%, with the 10th and 90th
percentiles at 15.4% and 71.0% against 27.0% and 81.7%. 4 of 399 companies still score zero
on every call, down from 7. 10 companies are now zero on none of their calls, up from 4.

## Manual sample of 50

Random sample with seed 20260915, drawn fresh from the 7,379. Full excerpts with +/-40 tokens
of raw text around each nearest pair are in `sampled_zero_transcripts.md`.

| Verdict | Calls |
|---|---:|
| True zero, no co-located language | 30 |
| Near miss, nearest pair 11 to 25 tokens | 20 |
| False zero from dropped seed vocabulary | **0** |

The first audit's sample of 50 found 10 false zeros from dropped seeds, 20%. This one finds
none, which matches the corpus-wide probe at 0%.

## What is still open

1. **The window ignores sentence and speaker boundaries.** `transcript_text` is concatenated
   segments, so a supply-chain term at the end of one speaker's answer can pair with a risk
   term in the next speaker's question. This inflates positives rather than causing zeros.
   Unchanged and not addressed here.
2. **The +/-10 window is measured in tokens, so it silently depends on tokenization policy.**
   Splitting hyphens moves 222 calls in. Unchanged.
3. **36.16% of remaining zeros miss by 15 tokens or fewer.** Widening the window to 25 would
   recover them. That is a methodology decision, not a bug, and it was explicitly out of
   scope for this fix.
4. **`shortage` and `shortages` in both vocabularies, and `customers` at weight 1.0.** Both
   left in place and measured, with sensitivity runs. See the before-and-after report.
5. **Software-sector risk vocabulary.** The first audit's point 7, that firms like Adobe show
   high supply-chain density and near-zero risk density, is not addressed by this fix. The
   risk dictionary was inflected, not extended.

## Files

Same file set as the first audit, regenerated against this run. `dictionary_checks.json` now
reports both vocabulary versions side by side, including the 98 terms v2 adds and the 28
library terms it reweights upward.

Rebuild from the repository root:

```
SCRISK_AUDIT_RUN=artifacts/earnings_call_supply_chain/ppmi_svd_full_20260910_vocab_v2 \
SCRISK_AUDIT_OUT=outputs/scrisk_zero_audit_vocab_v2 \
SCRISK_AUDIT_VOCABULARY=v2_seeds_inflections \
./scrisk_zero_audit/run_all.sh
```

With no environment set, the same script rebuilds the first audit in
`outputs/scrisk_zero_audit/`.
