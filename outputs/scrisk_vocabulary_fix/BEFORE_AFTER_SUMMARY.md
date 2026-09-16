# SCRisk vocabulary fix: before against after

Two runs of the same pipeline on the same 27,000 transcripts. The window is 10 tokens in
both. The tokenizer, the pairing rule, the resolution dictionary, the prices, the factors and
the Carhart estimation are untouched. Every CAR, beta, estimation date and R-squared in the
corrected run is byte-identical to the original, verified field by field across all 18,177
events. Only the vocabulary and the transcript-integrity filter changed.

| | Before | After |
|---|---|---|
| Run | `ppmi_svd_full_20260910` | `ppmi_svd_full_20260910_vocab_v2` |
| Vocabulary | `v1_library_only` | `v2_seeds_inflections` |
| Supply-chain terms | 118 | 216 |
| Risk terms | 94 | 147 |
| 16 seeds scored | 0 | 16, at weight 1.0 |
| Transcript-integrity filter | none | on, 15 calls excluded |

## What changed in the code

**The 16 seeds are now scored.** `SUPPLY_CHAIN_SEEDS` was defined at
`calculate_supply_chain_transcript_scores.py:85` and never used. It is now the centre of the
vocabulary at weight 1.0. A seed's cosine similarity to itself is 1.0 by construction, which
puts every seed above the strongest generated term (`customer`, 0.916).

**Regular inflections are completed on both vocabularies.** `regular_inflections` adds or
removes a regular English plural on a phrase's head word and nothing else. It is not a
stemmer. The audit's crude stemmer turned `stocking` into `stock` and `tracking` into
`track`, which is why its 32% figure was an upper bound rather than a finding. The inflector
leaves `stocking`, `tracking`, `finished` and `shipping` alone. It also generates forms that
are not words, such as `supplys` and `assemblings`; those cost nothing because they never
appear in a transcript.

The resulting term sets are identical to the audit's `lib_seeds_and_risk_inflected` probe:
216 supply-chain terms and 147 risk terms, asserted by test.

**A form reachable from more than one term takes the larger weight.** This is the rule
`load_supply_chain_library` already applied to repeated rows in `terms.jsonl`. 98 terms are
new in v2 and 28 existing library terms were reweighted upward because they are inflections
of a seed: `customer` goes from 0.916 to 1.0, `supplier` from 0.897 to 1.0, `inventories`
from 0.906 to 1.0.

**`--vocabulary-version v1_library_only --no-transcript-integrity-filter` reproduces the
original exactly.** Verified bit for bit on all 14 score columns of the committed 500-row
smoke run.

## Zero scores

| | Before | After |
|---|---:|---:|
| Analysable calls | 17,848 | 17,833 |
| SCRisk = 0 | 9,750 | 7,379 |
| Zero rate | 54.63% | 41.38% |
| Positive | 8,098 | 10,454 |

The zero rate falls 13.25 points.

On the 17,833 calls analysable in both runs:

| Transition | Calls |
|---|---:|
| Zero to positive | 2,357 |
| Positive to zero | 0 |
| Zero in both | 7,379 |
| Positive in both | 8,097 |

2,357 is 24.21% of the before zeros. The audit predicted 2,358 calls, 24.18%, from its
vocabulary probe. The corrected pipeline flips exactly that set of calls minus PG 2013Q2,
which the integrity filter removed from the population. Set-identical, not merely
equal in count.

No call went from positive to zero, which is the expected direction: adding vocabulary can
only add pairs when the tokenization is fixed, and the tokenization was not touched.

## Transcript integrity

The filter is a rule, not a list of tickers: a transcript is `content_absent` when it
contains one of three provider markers, or its distinct-token ratio is below 0.10, or it has
fewer than 1,000 tokens. Applied to all 27,000 rows it flags 15, which is the audit's 14
zero-score calls plus PEP 2012Q4, the one positive-score call the audit also flagged. There
were no other hits anywhere in the corpus.

Flagged calls keep their raw score and their CAR, which are facts about the file and the
prices. What they lose is a standardized score: `SCRisk` and `Resolution` are written blank,
they are dropped from the standard-deviation population, and `event_status` becomes
`excluded_transcript_integrity` so the charts and the zero-rate audit drop them without any
change to those programs. The original CAR estimation status is preserved in
`car_estimation_status`.

| Call | Reason | SCRisk before |
|---|---|---:|
| ETN 2012Q4 | copyright notice repeated, 4,506 tokens and 147 distinct | 0.0000 |
| F 2012Q4 | every utterance is the placeholder `(full spoken content)` | 0.0000 |
| OHI 2021Q3 | 22 tokens, the operator's greeting only | 0.0000 |
| CAT 2012Q4, CSX 2012Q4, F 2012Q2, GSK 2010Q4, IBM 2012Q4, KLIC 2014Q1, KLIC 2014Q4, MCD 2012Q4, PG 2013Q2, SM 2022Q4, WRB 2010Q3 | truncated stub under 1,000 tokens | 0.0000 |
| PEP 2012Q4 | truncated stub, 430 tokens | 7.9498 |

PEP 2012Q4 is the one exclusion that removes a positive score, and at 7.95 it was in the top
1% of the distribution on 430 tokens of text.

## SCRisk distribution

Raw SCRisk is the weighted pair count divided by the token count. Standardized SCRisk is that
raw value divided by the population standard deviation, with no mean subtracted.

| Raw SCRisk | Before | After | Ratio |
|---|---:|---:|---:|
| Mean | 0.0001478 | 0.0003951 | 2.67x |
| Median | 0.0000000 | 0.0001184 | |
| Median of positives | 0.0001975 | 0.0003283 | 1.66x |
| p90 | 0.0004116 | 0.0010134 | 2.46x |
| Max | 0.0052217 | 0.0240418 | 4.61x |
| SD divisor (all 27,000 rows) | 0.000262367 | 0.000751395 | **2.86x** |

| Standardized SCRisk | Before | After |
|---|---:|---:|
| Mean | 0.563 | 0.526 |
| Median | 0.000 | 0.158 |
| Median of positives | 0.753 | 0.437 |
| p75 | 0.679 | 0.541 |
| p90 | 1.569 | 1.349 |
| p99 | 5.404 | 5.570 |
| Max | 19.902 | 31.996 |

**The standardized scale moved, and that is worth stating plainly.** Raw scores rose for
almost every call, but the divisor rose 2.86x, so a call whose raw score rose by less than
2.86x has a *lower* standardized score than before. That is most calls: the median change in
standardized SCRisk is 0.00 and the 25th percentile is -0.23. Standardized SCRisk was always
a relative measure, and the fix changed what it is relative to. Spearman correlation between
the two runs is 0.808, so the ordering is broadly preserved but not tightly.

## Changes by year

The audit predicted the coverage gap would bite hardest in the high-exposure years. It did.

| Year | Calls | Zeros before | Zeros after | Rate before | Rate after | Change (pp) | Recovered | Mean SCRisk before | Mean SCRisk after |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2010 | 734 | 445 | 359 | 60.63% | 48.91% | -11.72 | 86 | 0.390 | 0.300 |
| 2011 | 822 | 445 | 339 | 54.14% | 41.24% | -12.90 | 106 | 0.494 | 0.415 |
| 2012 | 1,139 | 677 | 524 | 59.44% | 46.01% | -13.43 | 153 | 0.418 | 0.325 |
| 2013 | 1,210 | 778 | 611 | 64.30% | 50.50% | -13.80 | 167 | 0.315 | 0.227 |
| 2014 | 1,230 | 776 | 623 | 63.09% | 50.65% | -12.44 | 153 | 0.326 | 0.220 |
| 2015 | 1,221 | 787 | 640 | 64.46% | 52.42% | -12.04 | 147 | 0.308 | 0.215 |
| 2016 | 1,220 | 791 | 637 | 64.84% | 52.21% | -12.63 | 154 | 0.303 | 0.216 |
| 2017 | 1,226 | 763 | 622 | 62.23% | 50.73% | -11.50 | 141 | 0.359 | 0.257 |
| 2018 | 1,283 | 713 | 542 | 55.57% | 42.24% | -13.33 | 171 | 0.513 | 0.373 |
| 2019 | 1,279 | 713 | 548 | 55.75% | 42.85% | -12.90 | 165 | 0.501 | 0.406 |
| **2020** | 1,273 | 544 | 355 | 42.73% | 27.89% | **-14.84** | 189 | 0.706 | 0.726 |
| 2021 | 1,270 | 492 | 335 | 38.74% | 26.38% | -12.36 | 157 | 1.237 | 1.408 |
| **2022** | 1,317 | 490 | 296 | 37.21% | 22.48% | **-14.73** | 194 | 1.229 | 1.422 |
| **2023** | 1,313 | 635 | 442 | 48.36% | 33.66% | **-14.70** | 193 | 0.657 | 0.670 |
| 2024 | 1,296 | 687 | 506 | 53.01% | 39.04% | -13.97 | 181 | 0.507 | 0.461 |

2020, 2022 and 2023 get the three largest reductions. 2020 to 2023 are also the only years
whose mean standardized SCRisk *rose* despite the 2.86x divisor increase, so the fix
sharpened the disruption peak rather than flattening it.

## Changes by sector

| Sector | Calls | Zeros before | Zeros after | Rate before | Rate after | Change (pp) | Recovered | Mean SCRisk before | Mean SCRisk after |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **Semiconductors** | 2,371 | 1,092 | 704 | 46.06% | 29.69% | **-16.37** | 388 | 0.834 | 0.875 |
| Real Estate | 1,656 | 1,125 | 884 | 67.93% | 53.38% | -14.55 | 241 | 0.241 | 0.194 |
| Energy | 1,755 | 953 | 713 | 54.30% | 40.63% | -13.67 | 240 | 0.383 | 0.280 |
| Consumer Goods | 1,640 | 929 | 716 | 56.65% | 43.66% | -12.99 | 213 | 0.521 | 0.580 |
| Retail | 2,052 | 1,054 | 789 | 51.36% | 38.45% | -12.91 | 265 | 0.582 | 0.629 |
| Technology | 2,066 | 1,079 | 823 | 52.23% | 39.84% | -12.39 | 256 | 0.824 | 0.788 |
| Healthcare | 2,291 | 1,577 | 1,297 | 68.83% | 56.61% | -12.22 | 280 | 0.308 | 0.285 |
| Financial Services | 1,917 | 1,026 | 796 | 53.52% | 41.52% | -12.00 | 230 | 0.543 | 0.291 |
| Industrials | 2,085 | 901 | 657 | 43.21% | 31.51% | -11.70 | 244 | 0.718 | 0.677 |

Semiconductors is the largest single beneficiary at 388 recovered calls and a 16.4 point
drop, which is 4.7 points more than Industrials at the other end. That is the pattern the
audit flagged as the one that matters most: the measurement error was concentrated in the
high-exposure sector, so any regression of CAR on SCRisk inherited it.

Financial Services loses the most mean SCRisk, 0.543 to 0.291, a 46% fall. Its raw scores
rose less than the 2.86x divisor, so the fix moves it down the relative scale.

## CAR(0,1) by SCRisk quintile

Quintiles are calculated among positive scores only, matching the chart code exactly. Values
in basis points.

| Group | Before n | Before mean | Before median | After n | After mean | After median |
|---|---:|---:|---:|---:|---:|---:|
| Score = 0 | 9,750 | 25.84 | 14.58 | 7,379 | 24.25 | 10.95 |
| Q1 | 1,620 | 13.27 | 12.16 | 2,091 | 5.07 | 9.78 |
| Q2 | 1,619 | 22.96 | 2.49 | 2,091 | 22.41 | 4.89 |
| Q3 | 1,620 | 21.87 | 5.35 | 2,090 | 37.14 | 19.66 |
| Q4 | 1,619 | -1.57 | -8.63 | 2,091 | 19.26 | 4.49 |
| Q5 | 1,620 | 33.04 | -2.65 | 2,091 | 20.72 | 4.33 |

Neither run shows a monotone relationship between SCRisk and CAR(0,1). What the fix removes
is the noisiest part of the old picture: the before run had Q4 at -1.57 bp and Q5 at +33.04 bp
with a median of -2.65 bp, a mean and median pointing opposite ways in the top quintile. After
the fix, Q2 to Q5 sit in a 20 to 37 bp band with medians of 4 to 20 bp, all positive. The
zero group is essentially unchanged at 24 to 26 bp, which makes sense because 76% of the
before zeros are still zeros.

The quintile bin edges moved a long way, because standardized scores are now divided by a
2.86x larger number. Before, Q1 started at 0.113 and Q5 topped at 19.90; after, Q1 starts at
0.040 and Q5 tops at 32.00. Comparing quintile to quintile across the runs compares
different score ranges, so read the shape, not the level.

## Largest movers

Full lists are in `largest_scrisk_changes.csv` (top and bottom 40) and
`zero_to_positive_calls.csv` (all 2,357).

Biggest increases in standardized SCRisk:

| Call | Company | Sector | Before | After | Change | Raw ratio |
|---|---|---|---:|---:|---:|---:|
| MEI 2022Q2 | Methode Electronics | Technology | 15.92 | 32.00 | +16.07 | 5.75x |
| GIS 2022Q2 | General Mills | Consumer Goods | 1.52 | 14.97 | +13.45 | 28.20x |
| ACU 2022Q4 | Acme United | Consumer Goods | 1.09 | 12.43 | +11.34 | 32.75x |
| GFF 2021Q4 | Griffon | Industrials | 3.91 | 13.49 | +9.58 | 9.88x |
| PRGO 2021Q3 | Perrigo | Healthcare | 8.06 | 16.63 | +8.57 | 5.91x |
| GIS 2023Q4 | General Mills | Consumer Goods | 0.00 | 8.38 | +8.38 | zero before |
| XRX 2021Q4 | Xerox | Industrials | 4.77 | 12.82 | +8.05 | 7.70x |
| CLFD 2021Q3 | Clearfield | Technology | 0.00 | 7.65 | +7.65 | zero before |

Biggest decreases:

| Call | Company | Sector | Before | After | Change | Raw ratio |
|---|---|---|---:|---:|---:|---:|
| NVEC 2022Q1 | NVE Corporation | Semiconductors | 16.98 | 6.66 | -10.32 | 1.12x |
| NVEC 2022Q2 | NVE Corporation | Semiconductors | 19.90 | 10.45 | -9.45 | 1.50x |
| AON 2022Q1 | Aon | Financial Services | 19.24 | 9.82 | -9.42 | 1.46x |
| BKTI 2022Q2 | BK Technologies | Technology | 12.04 | 4.59 | -7.45 | 1.09x |
| KTCC 2019Q1 | Key Tronic | Technology | 18.57 | 11.46 | -7.11 | 1.77x |
| NVEC 2021Q4 | NVE Corporation | Semiconductors | 13.80 | 6.86 | -6.94 | 1.42x |
| ROK 2023Q3 | Rockwell Automation | Industrials | 11.43 | 4.93 | -6.50 | 1.24x |
| HMC 2023Q2 | Honda Motor | Retail | 14.15 | 7.79 | -6.35 | 1.58x |

Every decrease is the divisor, not a lost pair. NVEC 2022Q1's raw score *rose* 1.12x while
the divisor rose 2.86x, so its standardized score fell by a factor of 2.55. The three NVEC
quarters and AON 2022Q1 were all near the top of the old distribution on raw scores that
barely moved, which is exactly the profile of a call whose old score was inflated relative
to the corpus.

MEI 2022Q2 is now the maximum of the dataset at 32.00. Its raw score rose 5.75x, twice the
divisor.

## The two properties left in place, measured

Both of these change scores. Both are arguable. Neither was changed in the corrected run.
Each is measured here and has a switch, and each has a full sensitivity run.

### `shortage` and `shortages` are in both vocabularies

`shortages` is a supply-chain library term at weight 0.693 and also a risk term. A token span
is zero tokens from itself, so one occurrence of `shortages` forms a valid pair with itself
and contributes 0.693 with no second word anywhere near it. The v2 inflection completion puts
`shortage` in both vocabularies as well, so the singular now behaves the same way.

Corpus-wide, across the 17,833 analysable calls:

| | Before | After |
|---|---:|---:|
| Weight contributed by the shortage family | 2,742.5 | 4,934.9 |
| Share of all SCRisk weight | **16.05%** | **10.95%** |
| Calls that become zero without it | 435 | 402 |
| Identical-span self-pairs (all terms) | 3,305 | 5,353 |
| Weight from identical-span pairs | 2,290.0 | 3,709.1 |
| Share of all SCRisk weight | 13.40% | 8.23% |
| Calls that become zero without self-pairs | 370 | 299 |

The complete list of terms that can do this is the intersection of the two vocabularies,
because two occurrences can only share a token span if they are the same tokens. It is
`['shortages']` in v1 and `['shortage', 'shortages']` in v2, recorded in every run's
`scoring_manifest.json` as `terms_in_both_supply_chain_and_risk` and counted directly in
`self_pair_terms.csv`:

| Version | Term | Self-pairs | Weight each | Weight contributed |
|---|---|---:|---:|---:|
| v1 | `shortages` | 3,305 | 0.6929 | 2,290.04 |
| v2 | `shortages` | 3,305 | 0.6929 | 2,290.04 |
| v2 | `shortage` | 2,048 | 0.6929 | 1,419.06 |

There is no overlap at all between the supply-chain and resolution vocabularies in either
version, so Resolution has no equivalent artifact.

In the original run `shortages` was the single largest contributor to SCRisk in the entire
study, 16.05% of all weight, and 435 of the 8,097 positive-score calls owed their entire
score to it. In the corrected run its share drops to 10.95% because the vocabulary around it
grew, but 402 calls still depend on it alone.

### `customers` is the broadest of the 16 seeds

In v2 `customers` carries weight 1.0 and `customer` inherits 1.0 as its inflection. The audit
called it the weakest seed semantically and quoted TMO 2022Q2: "funding concerns pressuring
those mid-cap biotech customers" becomes a supply-chain risk pair on one very common noun.

| | Before | After |
|---|---:|---:|
| Weight contributed by the customer family | 1,620.4 | 5,753.0 |
| Share of all SCRisk weight | 9.48% | **12.77%** |
| Calls that become zero without it | 511 | **849** |

In v1 only `customer` was in the vocabulary, at 0.916. In v2 both forms are there at 1.0, and
the family becomes the largest single dependency in the dataset: 849 of the 10,454
positive-score calls score nothing without it.

Top contributors overall, share of all SCRisk weight:

| Before | | After | |
|---|---:|---|---:|
| shortages | 16.05% | supply | 17.99% |
| customer | 9.48% | supply chain | 11.64% |
| production | 6.75% | customers | 8.73% |
| clients | 5.12% | shortages | 7.20% |
| retail | 3.72% | inventory | 4.99% |
| component | 3.50% | customer | 4.03% |
| orders | 3.46% | shortage | 3.75% |

### Sensitivity runs

Four full re-scorings and re-estimations, each changing exactly one thing against the
corrected default. Every one is a complete run with its own scored CSV, event returns and
manifest under
`artifacts/earnings_call_supply_chain/ppmi_svd_full_20260910_vocab_v2/sensitivity/`.

| Variant | Calls | Zeros | Zero rate | vs corrected | SD divisor |
|---|---:|---:|---:|---:|---:|
| before (`v1_library_only`) | 17,848 | 9,750 | 54.63% | +13.25 pp | 0.000262 |
| **after (`v2_seeds_inflections`)** | 17,833 | 7,379 | **41.38%** | baseline | 0.000751 |
| `no_self_pairs` | 17,833 | 7,678 | 43.06% | +1.68 pp | 0.000692 |
| `no_shortage_family` | 17,833 | 7,781 | 43.63% | +2.25 pp | 0.000662 |
| `no_customer_family` | 17,833 | 8,228 | 46.14% | +4.76 pp | 0.000699 |
| `no_shortage_no_customer` | 17,833 | 8,696 | 48.76% | +7.38 pp | 0.000609 |

The three single-change variants land on exactly the per-call attribution above: +299 zeros
for `no_self_pairs` against 299 calls attributed to self-pairs, +402 for `no_shortage_family`
against 402, and +849 for `no_customer_family` against 849. Two independent calculations, one
from re-scoring and one from labelling pairs, agree to the call.

Dropping both families still leaves the zero rate at 48.76%, nearly 6 points below the
original 54.63%, so the seed and inflection fix stands on its own without either of the
arguable terms.

## What was not changed

- The window. 10 tokens, asserted by test at 9 filler tokens (pairs) and 10 (does not).
- The tokenizer. Same `WORD_RE`, same hyphen and apostrophe handling, same dropping of
  numeric tokens.
- The pairing rule. Still every supply-chain occurrence against every risk occurrence within
  the window, still additive, still divided by token count.
- The resolution dictionary. Left exactly as written, not inflected. Resolution scores still
  move, because resolution pairs are a subset of SCRisk pairs and carry the same weights.
- Sentence and speaker boundaries. The audit's point 5, that a term at the end of one
  speaker's answer can pair with a term in the next speaker's question, is untouched and
  still open.
- The Carhart estimation, the prices, the factors, the event-date mapping.

## Files

| Path | Contents |
|---|---|
| `before_after_summary.json` | every count, percentage and distribution in this report |
| `car_quintiles_before_after.csv` | the quintile table, both runs |
| `car_quintiles_resolution_before_after.csv` | the same for Resolution |
| `zero_rate_by_year.csv` / `zero_rate_by_sector.csv` | grouped change tables |
| `largest_scrisk_changes.csv` | top and bottom 40 movers |
| `zero_to_positive_calls.csv` | all 2,357 recovered calls |
| `sensitivity_summary.csv` | the six-run sensitivity table |
| `term_contributions_by_term.csv` | weight and pair count per supply-chain term, both versions |
| `term_contributions_per_call.csv` | per-call decomposition into shortage, customer and self-pair parts |
| `term_contributions_summary.json` | the attribution totals |
| `self_pair_terms.csv` / `.json` | every term that pairs with its own occurrence, counted |

Figures, one directory per run:

| Original | Corrected |
|---|---|
| `outputs/scrisk_car_event_charts/` | `outputs/scrisk_car_event_charts_vocab_v2/` |
| `outputs/scrisk_car_descriptive_charts/` | `outputs/scrisk_car_descriptive_charts_vocab_v2/` |
| `outputs/sector_scrisk_rankings/` | `outputs/sector_scrisk_rankings_vocab_v2/` |
| `outputs/scrisk_zero_audit/` | `outputs/scrisk_zero_audit_vocab_v2/` |

Regenerate everything from the repository root:

```
# corrected scores
conda run -n dap-env python calculate_supply_chain_transcript_scores.py \
  --input earnings_call_transcripts.csv \
  --library artifacts/sec_10k_supply_chain/experiments/ppmi_svd_full_20260910/terms.jsonl \
  --vocabulary-version v2_seeds_inflections \
  --output artifacts/earnings_call_supply_chain/ppmi_svd_full_20260910_vocab_v2/earnings_call_transcripts_scored.csv

# corrected event returns
conda run -n dap-env python calculate_carhart_event_returns.py \
  --segments artifacts/earnings_call_supply_chain/ppmi_svd_full_20260910/earnings_call_transcript_segments_scored_with_event_dates.csv \
  --event-date-column event_date \
  --supply-chain-scores artifacts/earnings_call_supply_chain/ppmi_svd_full_20260910_vocab_v2/earnings_call_transcripts_scored.csv \
  --prices artifacts/earnings_call_supply_chain/ppmi_svd_full_20260910/event_study_inputs/adjusted_close_prices.csv \
  --factors artifacts/earnings_call_supply_chain/ppmi_svd_full_20260910/event_study_inputs/fama_french/fama_french_daily.zip \
  --momentum artifacts/earnings_call_supply_chain/ppmi_svd_full_20260910/event_study_inputs/fama_french/momentum_daily.zip \
  --output artifacts/earnings_call_supply_chain/ppmi_svd_full_20260910_vocab_v2/earnings_call_event_returns.csv

# sensitivity variants, zero-rate audit, charts, comparison
./scrisk_vocabulary_fix/run_sensitivity.sh
SCRISK_AUDIT_RUN=artifacts/earnings_call_supply_chain/ppmi_svd_full_20260910_vocab_v2 \
SCRISK_AUDIT_OUT=outputs/scrisk_zero_audit_vocab_v2 \
SCRISK_AUDIT_VOCABULARY=v2_seeds_inflections ./scrisk_zero_audit/run_all.sh
MPLCONFIGDIR=work/matplotlib_config conda run -n dap-env python work/create_scrisk_car_matplotlib_charts.py \
  --input artifacts/earnings_call_supply_chain/ppmi_svd_full_20260910_vocab_v2/earnings_call_event_returns.csv \
  --output outputs/scrisk_car_event_charts_vocab_v2
conda run -n dap-env python scrisk_vocabulary_fix/term_contributions.py
conda run -n dap-env python scrisk_vocabulary_fix/compare_before_after.py
```

```
# the xlsx figures
SCRISK_EVENT_RETURNS=artifacts/earnings_call_supply_chain/ppmi_svd_full_20260910_vocab_v2/earnings_call_event_returns.csv SCRISK_CHART_OUT=outputs/scrisk_car_descriptive_charts_vocab_v2   node work/build_scrisk_car_descriptive_charts.mjs
SCRISK_EVENT_RETURNS=artifacts/earnings_call_supply_chain/ppmi_svd_full_20260910_vocab_v2/earnings_call_event_returns.csv SCRISK_CHART_OUT=outputs/sector_scrisk_rankings_vocab_v2   node work/build_sector_scrisk_rankings.mjs
```

## Reproduction notes, including what did not reproduce cleanly

**The original scored CSV reproduces bit for bit.** `--vocabulary-version v1_library_only
--no-transcript-integrity-filter` gives byte-identical values on all 14 score columns of the
committed 500-row smoke run. Asserted by test.

**The original event returns reproduce exactly.** Every CAR, beta, alpha, R-squared,
estimation date and trading date in the corrected run matches the original field for field
across all 18,177 events. Only the 15 integrity exclusions change `event_status`.

**The original audit reproduces its numbers, not its file bytes.** Re-running
`./scrisk_zero_audit/run_all.sh` with no environment set reproduces every count in
`outputs/scrisk_zero_audit/`: the 9,750-call population, the 2,358-call inflection probe, the
per-call CSV row sets, and every value in `zero_audit_summary.json`. Three files differ in
form rather than content: `dictionary_checks.json` now reports both vocabulary versions,
`transcript_content_integrity.csv` gained two columns carrying the scorer's own integrity
verdict, and `probe_flip_detail.csv` and `probe_inflection_per_call.csv` come out in a
different row order because they are written from `imap_unordered`. Row sets are equal.

**The original PNGs do not reproduce byte for byte, and the difference is rendering.** The
chart script reads the original event returns file, which was never modified, and the only
code change affecting it is a skip for blank scores that no row in that file triggers. A
fresh render is visually identical and its bar heights, whiskers and n labels all match, but
the three bar charts come out one pixel taller and the scatter differs in antialiasing. Two
fresh renders in this environment are byte-identical to each other, so the committed PNGs
were produced under a different font or backend state. The data path is verified; the bytes
are not.

**I overwrote `outputs/scrisk_car_descriptive_charts/` while testing the xlsx builder.** I
ran `node work/build_scrisk_car_descriptive_charts.mjs` with its defaults before
parameterizing it, which rewrote the original workbook in place. It is a faithful
regeneration: unchanged code reading the unchanged original event returns file, and its
zero-group and Q1 figures match the independently computed before-run table to four decimal
places. But the original bytes and mtime are gone, and there was no backup. Nothing else
under `outputs/` was overwritten.

**The two chart programs bin quintiles differently, and always did.**
`create_scrisk_car_matplotlib_charts.py` uses `np.quantile` boundaries with `searchsorted`
and gets 1,620 / 1,619 / 1,620 / 1,619 / 1,620 on the before run.
`build_scrisk_car_descriptive_charts.mjs` splits by index and gets 1,620 / 1,620 / 1,619 /
1,620 / 1,619. One call sits on a tie and lands in a different quintile, which is why Q2
reads 22.71 bp in the workbook and 22.96 bp in the table above. This predates the fix and was
not changed.

Everything else original is untouched: the original run directory, the original audit in
`outputs/scrisk_zero_audit/`, the original PNGs in `outputs/scrisk_car_event_charts/`, and
`outputs/sector_scrisk_rankings/`.
