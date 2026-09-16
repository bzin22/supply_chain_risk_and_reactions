# Why 9,750 earnings calls have SCRisk = 0

Audit of run `ppmi_svd_full_20260910`. Nothing in the scoring methodology or pipeline was
changed. Every number below comes from re-reading the scored transcripts with the pipeline's
own `tokenize`, `find_indexed_occurrences` and `spans_within`, so the audit and the scorer
agree by construction. All 9,750 recomputed word counts, supply-chain counts and risk counts
match the scored CSV exactly, with zero mismatches.

## The population

`SCRisk == 0` and `event_status == 'ok'` gives exactly 9,750 calls. That is 54.6% of the
17,848 analysable events. 8,098 have a positive score.

A further 8,981 rows in `earnings_call_transcripts_scored.csv` also score 0, but 8,823 of
them have no transcript text at all (`status` of `no_transcript`, `information` or
`api_error`). Those never reach the event study. Every one of the 9,750 audited calls has
`status = success` and real text, median 6,576 tokens.

## Headline

The zeros are not a tokenization bug. They split roughly in half: about 44% are an artifact
of how narrow the supply-chain vocabulary is and how tight the window is, and about 40% are
calls that genuinely never put supply-chain and risk language next to each other.

The single largest fixable cause is that **the 16 supply-chain seed phrases are not in the
scoring library.** `SUPPLY_CHAIN_SEEDS` is defined at `calculate_supply_chain_transcript_scores.py:85`
and never used. The library loaded from `terms.jsonl` is 118 expansion terms and none of the
seeds. So `supply chain`, `supply`, `suppliers`, `inventory`, `logistics`, `manufacturing`,
`procurement`, `customers`, `distribution`, `transportation`, `warehousing`, `sourcing`,
`purchasing`, `fulfillment`, `demand management` and `channel partners` all score nothing.

A call can say "the supply chain disruption created opportunistic situations" and score zero.
Cirrus Logic 2022Q2 does exactly that.

## Requested breakdown of the 9,750

| Mechanism | Calls | % of zeros |
|---|---:|---:|
| Both vocabularies present, never within ±10 tokens | 9,462 | 97.05% |
| Supply-chain vocabulary but no risk vocabulary | 270 | 2.77% |
| No supply-chain vocabulary | 14 | 0.14% |
| Neither vocabulary present | 4 | 0.04% |
| Empty transcript | 0 | 0% |

Almost every zero already contains both vocabularies. The score fails at the proximity step,
not the lookup step.

Among the 9,462 that fail on proximity, the nearest supply-chain/risk pair sits:

| Nearest pair distance | Calls |
|---|---:|
| 11 to 15 tokens | 1,466 |
| 16 to 25 tokens | 1,715 |
| 26 to 50 tokens | 2,122 |
| over 50 tokens | 4,159 |

Median 41 tokens, mean 99, max 3,726. 1,466 calls miss by five tokens or fewer.

## False-zero probes

Each probe re-scores the same text under one perturbation and records whether the call turns
non-zero. These are derived columns, not pipeline changes.

| Probe | Calls turned non-zero | % of zeros |
|---|---:|---:|
| Complete the vocabulary's inflections and restore the 16 seeds | **2,358** | **24.18%** |
| Restore the 16 seeds only | 1,815 | 18.62% |
| Complete inflections only, no seeds | 2,109 | 21.63% |
| Split hyphens, apostrophes and periods | 216 | 2.22% |
| Crude suffix stemming of both dictionaries | 3,127 | 32.07% |
| Widen the window to 25 tokens | 3,181 | 32.63% |
| Widen the window to 50 tokens | 5,303 | 54.39% |

Read the 24.18% as the defensible false-zero rate. It changes no tokenization and no window,
only the vocabulary, so it is the cleanest measure of coverage loss.

Ignore the 32.07% stemming number as a finding. It is an upper bound inflated by the crude
stemmer truncating library terms into common business words: `stocking` becomes `stock`,
`tracking` becomes `track`, `finished` becomes `finish`, `shipping` becomes `shipp`.
"Stock" and "on track" are everywhere in an earnings call. The inflection probe exists
precisely to avoid this, and never truncates a stem.

### What drives the vocabulary lift

Flips by the seed that caused them:

| Restored seed | Calls |
|---|---:|
| customers | 641 |
| supply | 432 |
| inventory | 231 |
| supply chain | 169 |
| manufacturing | 120 |
| distribution | 88 |
| transportation | 39 |
| logistics | 26 |
| purchasing | 24 |
| suppliers | 17 |
| sourcing | 15 |
| procurement | 7 |
| channel partners, fulfillment, warehousing | 6 |

Two caveats, both worth weighing before acting on the 24%:

`customers` alone drives 641 of the 1,815 seed flips, 35%. It is the weakest seed
semantically. "Funding concerns pressuring those mid-cap biotech customers" (Thermo Fisher
2022Q2) becomes a supply-chain risk pair on the strength of one very common noun. Excluding
`customers`, the seed probe flips 1,174 calls and the full vocabulary probe flips 1,427,
which is 14.6% of the zeros.

`shortages` is in both the supply-chain library and the risk dictionary. A span is zero
tokens from itself, so any call containing `shortages` scores non-zero on that one word. The
singular `shortage` is a risk term only, so it cannot. 338 of the 2,358 flips are this
inflection asymmetry and nothing else. Excluding them leaves 2,020 flips, 20.7%.

### Tokenization, casing, punctuation, parsing, lookup

Checked and clean:

- **Casing** cannot cause a false zero. `WORD_RE` lowercases every token and every dictionary
  entry through the same `normalize_term`. Verified by test.
- **Vocabulary lookup** is sound. All 118 library terms and all 94 risk terms are reachable by
  the tokenizer. No library term is multiword. No weight is zero or negative; they range
  0.585 to 0.916. So no call scores zero through a zero weight.
- **Curly apostrophes** are handled. `supplier’s` stays one token, and 1,221 calls contain
  non-ASCII letters totalling 2,616 characters, too few to matter.
- **Transcript parsing** is a real but tiny cause: 14 of 9,750 zeros, 0.14%, against 1 of
  8,098 positives. Three concrete failures, all marked `status = success`:
  - `ETN 2012Q4` has 4,506 tokens but only 147 distinct. The body is the transcript
    provider's copyright notice repeated, not the call.
  - `F 2012Q4` has 81 tokens. Every utterance is the literal placeholder
    `(full spoken content)`.
  - `OHI 2021Q3` has 22 tokens, the operator's greeting only. It also says "Third Quarter
    2041".
- **Token counts** run about 2% below the segment-derived `word_count` (median ratio 1.022)
  because `WORD_RE` drops all numeric tokens. 200 zeros differ by more than 5%. This does not
  create zeros by itself.

Hyphenation cuts both ways, which was a surprise. Splitting hyphens creates 216 new non-zero
calls, mostly `single source` from "single-source" and `lead time` from "lead-time". It also
**destroys** pairs, because splitting lengthens the token stream and the window is a fixed
count of tokens. 26 calls that the seed probe rescues are lost again once hyphens split,
every one of them previously sitting at distance exactly 10. `ARKR 2024Q3` goes from 3,594 to
3,748 tokens and its nearest pair from 10 to 13. The ±10 window is therefore sensitive to
tokenization policy, not just to what was said.

## One dominant cause per call

| Cause | Calls | % of zeros |
|---|---:|---:|
| Transcript content absent | 14 | 0.14% |
| Vocabulary coverage gap | 2,019 | 20.71% |
| Vocabulary gap, `shortages` self-pair only | 338 | 3.47% |
| Window near miss, 11 to 25 tokens | 1,997 | 20.48% |
| Window miss, 26 to 50 tokens | 1,517 | 15.56% |
| No co-located language at any plausible window | 3,865 | 39.64% |

Fixing the vocabulary alone recovers 2,358 calls, 24.2%. Vocabulary plus a 25-token window
recovers 4,356, 44.7%. The remaining 3,865 calls look like true zeros.

## Zero against positive

Zero-score calls really do talk less about both topics, and the gap survives controlling for
length.

| Measure | Zero (n=9,750) | Positive (n=8,098) |
|---|---:|---:|
| Median tokens | 6,576 | 7,185 |
| Median supply-chain hits | 30 | 45 |
| Median risk hits | 5 | 10 |
| Median supply-chain hits per 1,000 tokens | 4.82 | 6.68 |
| Median risk hits per 1,000 tokens | 0.86 | 1.48 |

Risk density is the sharper separator, 1.7x, against 1.4x for supply-chain density.

**Length.** Zero rate falls from 72.8% in the shortest decile to about 49% and then flattens
completely across deciles 6 to 10. Length matters up to roughly 7,000 tokens and stops
mattering after that, so short transcripts are not the explanation.

| Length decile | Token range | Zero rate |
|---|---|---:|
| 1 | 22 to 3,882 | 72.77% |
| 2 | 3,883 to 4,856 | 60.91% |
| 3 | 4,857 to 5,592 | 58.19% |
| 5 | 6,273 to 6,889 | 53.39% |
| 7 | 7,453 to 7,987 | 49.16% |
| 10 | 9,219 to 27,868 | 49.02% |

**Year.** The zero rate tracks the real world, which is reassuring for the construct. It sits
between 54% and 65% through the 2010s, bottoms at 37.3% in 2022 at the peak of supply-chain
disruption, and climbs back to 53.0% by 2024.

**Sector.** Healthcare 68.9% and Real Estate 68.0% are highest. Industrials 43.3% and
Semiconductors 46.1% are lowest. That ordering is the right shape.

**Company.** Median company zero rate is 56.0%, with the 10th and 90th percentiles at 27.0%
and 81.7%. 7 of 399 companies score zero on every call, including Abeona Therapeutics across
all 27 of its calls and Ingles Markets across all 15. At the other end Aon is zero on none of
its 50 calls, with a median 69.5 supply-chain hits and 38 risk hits per call. Adobe is zero on
90% of 50 calls despite a median 42.5 supply-chain hits, because its risk hits are sparse at a
median of 5.

## The pattern that matters most

The vocabulary gap is not random with respect to the variable the study is trying to measure.
It bites hardest exactly where supply-chain risk is most discussed.

Share of that year's zeros that are vocabulary-gap false zeros:

| Year | Share |
|---|---:|
| 2017 | 18.5% |
| 2020 | 34.7% |
| 2021 | 31.8% |
| **2022** | **39.5%** |
| 2023 | 30.4% |
| 2024 | 26.3% |

By sector, Semiconductors is worst at 31.2% of its zeros, against Healthcare at 14.6%.

So the measurement error is concentrated in the high-exposure years and the high-exposure
sector. A zero in 2022 semiconductors is much more likely to be a scoring failure than a zero
in 2015 healthcare. Any regression of CAR on SCRisk inherits that structure.

## Manual sample of 50

Random sample with seed 20260915, drawn from the 9,750. Full excerpts with ±40 tokens of raw
text around each nearest pair are in `sampled_zero_transcripts.md`.

| Verdict | Calls |
|---|---:|
| True zero, no co-located language | 21 |
| Near miss, nearest pair 11 to 25 tokens | 19 |
| False zero from dropped seed vocabulary | 10 |

10 of 50, 20%, matches the corpus-wide seed probe at 18.6%.

Two unambiguous false zeros:

- **CRUS 2022Q2** (Cirrus Logic). "the once the supply chain disruption created opportunistic
  situations where that could occur". `supply` sits inside `supply chain disruption`, distance
  0. Scores 0. Under the current library the nearest pair is `planning` and `volatility` at 15
  tokens.
- **SLB 2021Q3**. "affected by temporary supply and logistics disruptions". `logistics` to
  `disruptions` is 1 token. Scores 0. The current library's nearest pair is `customer` and
  `exposure` at 11 tokens, which misses by one.

Two more where the supply-chain term is clear but the risk term is a weak one:

- **CPT 2013Q1**, `supply` to `concerns` at 1 token, against 53 under the current library.
- **UMH 2021Q3**, `inventory` to `concern` at 4 tokens, against 12.

Two that show what restoring `customers` buys, and why it is the seed to argue about:

- **HAL 2024Q1**. "how much lead time your customers are asking for". `customers` and
  `lead time` at 2 tokens. Literally a lead-time question, but the reading is about demand
  planning, not risk.
- **TMO 2022Q2**. "funding concerns pressuring those mid-cap biotech customers". `customers`
  and `concerns` at 5 tokens. This is biotech funding, not supply chain.

## Suspicious patterns, ranked

1. The 16 seeds are absent from the library. `SUPPLY_CHAIN_SEEDS` is dead code. 18.6% of
   zeros turn non-zero on this alone, and the loss concentrates in 2020 to 2023 and in
   semiconductors.
2. `shortages` appears in both dictionaries and pairs with itself at distance 0, so one word
   scores a call non-zero. `shortage` singular cannot. 338 zeros hinge on this.
3. The library's morphology is ragged. It has `customer` but not `customers`, `supplier` but
   not `suppliers`, `inventories` but not `inventory`. Completing inflections without touching
   the seeds moves 2,109 calls.
4. The ±10 window is measured in tokens, so it silently depends on tokenization policy.
   Splitting hyphens moves 216 calls in and 26 out.
5. The window ignores sentence and speaker boundaries. `transcript_text` is concatenated
   segments, so a supply-chain term at the end of one speaker's answer can pair with a risk
   term in the next speaker's question. That inflates positives rather than causing zeros, but
   it belongs in the same review.
6. 14 calls are scored on transcripts with no spoken content, marked `status = success`.
7. Adobe-type cases: high supply-chain density, near-zero risk density, 90% zeros. Worth
   checking whether the risk dictionary is missing the vocabulary software firms actually use.

## Files

| File | Contents |
|---|---|
| `SCRISK_ZERO_AUDIT.md` | this report |
| `zero_audit_per_call.csv` | 9,750 rows, one per zero call, all buckets and probe columns |
| `zero_cause_attribution.csv` / `.json` | one dominant cause per call, and the cross-tabs |
| `zero_audit_summary.json` | every count and percentage in this report |
| `zero_vs_positive_comparison.csv` | zero rate and medians by year and sector |
| `zero_rate_by_company.csv` | 399 companies, zero rate and median hit counts |
| `zero_rate_by_length_decile.csv` | zero rate against transcript length |
| `probe_flip_detail.csv` / `probe_flip_drivers.json` | which term pair drives each probe flip |
| `probe_inflection_per_call.csv` / `probe_inflection_drivers.json` | the clean vocabulary probe |
| `transcript_content_integrity.csv` / `_summary.json` | all 27,000 rows, content-absence flags |
| `dictionary_checks.json` | seed absence, weight range, dictionary overlap |
| `sampled_zero_transcripts.md` | the 50 sampled calls with raw-text excerpts |
| `sampled_zero_verdicts.csv` / `sampled_zero_call_keys.json` | per-call verdicts and the seed |
| `all_calls_metadata.csv` | the scored CSV minus `transcript_text` |

Code is in `scrisk_zero_audit/`. `./scrisk_zero_audit/run_all.sh` rebuilds everything from the
repository root in under two minutes. `conda run -n dap-env python -m pytest scrisk_zero_audit -q`
runs the 19 tests.
