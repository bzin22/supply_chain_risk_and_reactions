# SCRisk quintiles cut within industry, then pooled

> **This file uses the 91-value `industry` column, the data provider's fine-grained
> classification, not the study's 9 sectors.** `industry` is an inherited name: it splits
> Semiconductors into `Semiconductors` and `Semiconductor Equipment & Materials`, and Real
> Estate into eleven REIT subtypes. The 9-sector version is the one to quote and lives in
> `outputs/scrisk_within_sector_quintiles/WITHIN_SECTOR_QUINTILES.md`; it uses more of the
> sample, excludes nothing, and its quintile cells are 12x larger (median 222 calls against
> 18 here). Keep this file as a robustness check: it reaches the same conclusion.

Built from the `no_self_pairs` sensitivity run: the corrected vocabulary with the
zero-distance self-match of `shortage` and `shortages` refused. Input is
`artifacts/earnings_call_supply_chain/ppmi_svd_full_20260910_vocab_v2/sensitivity/no_self_pairs/event_returns.csv`,
read only. Nothing was rescored and the window is still 10 tokens.

## Why cut within industry

The published quintiles are cut once on the pooled distribution, so a call's quintile
partly reports how supply-chain-heavy its industry is rather than how supply-chain-heavy the
call is for its industry. Sorting on SCRisk sorts on industry.

The evidence is in the composition. Semiconductors is the largest industry in the sample, and
under the pooled cut its share climbs monotonically across the quintiles. Under the
within-industry cut it is flat:

| Semiconductors' share of | Q1 | Q2 | Q3 | Q4 | Q5 | Spread |
|---|---:|---:|---:|---:|---:|---:|
| Pooled cut | 4.38% | 7.04% | 9.46% | 12.22% | 15.54% | **11.16 pp** |
| Within-industry cut | 9.60% | 9.71% | 9.73% | 9.71% | 9.86% | **0.26 pp** |

Both rows are computed on the same 78 industries and the same 9,944 positive calls, so this
is one population and only the cut differs. Across all 78 industries the median spread
between an industry's largest and smallest quintile share falls from 0.96 points under the
pooled cut to 0.04 points under the within-industry cut. Semiconductors is the worst-balanced
industry under both, and it is 43x better balanced under the new cut.

Cutting inside each industry and then pooling is what achieves that. Each industry
contributes about a fifth of its positive calls to every quintile, so the mix is held
constant and Q5 against Q1 is a within-industry comparison.

## Construction

1. Keep the 17,833 events with `event_status = ok`, an estimated CAR(0,1) and a defined
   SCRisk.
2. Hold out the zero-score calls. They are a 43.1% mass point, not a low tail, so cutting
   them into quintiles would make Q1 a statement about how many zeros an industry has. They
   are reported as their own pooled group, which is what the existing figures do.
3. Within each industry, rank the positive scores ascending and cut the ranks into five
   equal-count groups. Ties break on ticker then quarter, which is reproducible; only 25 of
   10,155 positives sit in a within-industry tie and the largest tie is 3, so a
   quantile-boundary cut that keeps ties together gives the same answer to within a handful
   of calls.
4. Require at least 25 positive calls in an industry, five per quintile. 13 of 91 industries
   fall below it and are excluded, listed in `excluded_industries.csv`. They hold 548 calls,
   3.1% of the sample. `Real Estate - Diversified` has no positive call at all.
5. Pool the Q1s, the Q2s and so on across the 78 remaining industries.

9,944 positive calls are ranked. The zero group is restricted to the same 78 industries, so
it is 7,341 calls rather than the run's full 7,678.

## Result

| Group | Events | Mean CAR (bp) | 95% CI | Median CAR (bp) | Bootstrap 95% CI |
|---|---:|---:|---|---:|---|
| Score = 0 | 7,341 | 21.77 | 7.17 to 36.37 | 11.33 | 1.36 to 21.77 |
| Q1 | 2,020 | 22.45 | -5.37 to 50.27 | 22.59 | 1.98 to 46.98 |
| Q2 | 1,987 | 42.67 | 14.17 to 71.17 | 18.83 | -2.84 to 48.96 |
| Q3 | 1,993 | 9.49 | -18.14 to 37.12 | -18.16 | -40.04 to 5.26 |
| Q4 | 1,987 | 23.05 | -6.98 to 53.09 | 2.49 | -18.45 to 30.47 |
| Q5 | 1,957 | 11.24 | -18.99 to 41.48 | 25.04 | -7.52 to 49.62 |

**There is no monotone relationship, and most of these groups are not distinguishable from
zero.** Only Q2's mean (14.17 to 71.17 bp) and Q1's median (1.98 to 46.98 bp) have intervals
that exclude zero, and with six groups tested that is what chance produces. Every mean sits
between 9 and 43 bp against a confidence half-width of about 30 bp. The honest reading is a
flat line at roughly 20 bp with noise on top, not a risk gradient.

Q5 minus Q1 is -11.2 bp on the mean and +2.5 bp on the median, which point in opposite
directions. That is the signature of a difference smaller than the noise.

Against the pooled cut on the same observations:

| Quintile | Pooled mean (bp) | Within-industry mean (bp) | Difference |
|---|---:|---:|---:|
| Q1 | 8.11 | 22.45 | +14.34 |
| Q2 | 27.08 | 42.67 | +15.59 |
| Q3 | 33.52 | 9.49 | -24.03 |
| Q4 | 27.65 | 23.05 | -4.60 |
| Q5 | 13.97 | 11.24 | -2.73 |

Neither construction is monotone. The pooled cut looks like a hump peaking at Q3; the
within-industry cut scatters. Both are consistent with no relationship.

## Score ranges now overlap, by design

Because the cut is industry-relative, the quintiles no longer partition the score axis:

| Quintile | Min SCRisk | Median SCRisk | Max SCRisk |
|---|---:|---:|---:|
| Q1 | 0.043 | 0.153 | 0.440 |
| Q2 | 0.121 | 0.279 | 0.849 |
| Q3 | 0.148 | 0.486 | 1.561 |
| Q4 | 0.236 | 0.883 | 3.166 |
| Q5 | 0.372 | 2.057 | 32.613 |

Q1's maximum, 0.440, is above Q5's minimum, 0.372. A call scoring 0.40 is in Q1 if its
industry talks about supply chains a lot and in Q5 if it does not. Under the pooled cut the
ranges are disjoint by construction (Q1 tops out at 0.194, Q5 starts at 1.209). This is the
intended trade: the within-industry cut buys a controlled comparison and gives up an
absolute reading of the score.

## The other reading of the instruction

`within_industry_quintiles_all_observations.csv` ranks every call, zeros included, rather
than holding zeros out. Reported for completeness and not recommended, because the low
quintiles become a zero count:

| Quintile | Events | Zero share | Max SCRisk | Mean CAR (bp) | Median CAR (bp) |
|---|---:|---:|---:|---:|---:|
| Q1 | 3,601 | 98.58% | 0.296 | 10.55 | 0.18 |
| Q2 | 3,562 | 77.29% | 0.788 | 36.40 | 30.92 |
| Q3 | 3,568 | 33.44% | 1.111 | 24.02 | 9.81 |
| Q4 | 3,562 | 4.72% | 2.692 | 24.58 | 1.74 |
| Q5 | 3,530 | 0.11% | 32.613 | 15.93 | 9.03 |

Q1 is 98.6% zeros, so "Q1 against Q5" here is close to "zero against positive" with extra
steps. It is still not monotone.

## Caveats

- **Industry labels come from the segment metadata and are the provider's, not ours.** 91
  labels over 450 companies, so some are thin. 13 are too thin to cut.
- **Within-industry quintiles are relative to a fixed industry definition over 15 years.** A
  company's industry label does not move in this data, so a firm that changed business is
  ranked against its label throughout.
- **This holds industry mix constant, not year mix.** A within-industry quintile can still
  be tilted toward 2022, when everybody's SCRisk was high. Cutting within industry and year
  together is a further step and was not done here.
- **Zero-score calls are not comparable to the quintiles.** They are held out, not ranked,
  and 43.1% of the run is in that group.
- **The standardized-score level is not comparable to the published run.** This is the
  `no_self_pairs` variant, whose SD divisor is 0.000692 against the corrected run's
  0.000751.

## Files

| File | Contents |
|---|---|
| `within_industry_quintiles.csv` | the pooled table above, with both confidence intervals |
| `pooled_quintiles_same_run.csv` | the published construction on the same observations |
| `within_industry_quintiles_by_industry.csv` | 78 industries x 5 quintiles, n, score range, CAR |
| `industry_mix_by_quintile.csv` | each industry's share of each quintile, the balance check |
| `industry_mix_by_quintile_pooled.csv` | the same balance check for the pooled cut, same industries |
| `within_industry_quintiles_all_observations.csv` | the zeros-included variant |
| `excluded_industries.csv` | the 13 industries below the 25-positive floor |
| `summary.json` | every count and the balance statistics |
| `01_mean_car_by_within_industry_scrisk_quintile.png` | mean CAR, six groups |
| `02_median_car_by_within_industry_scrisk_quintile.png` | median CAR, bootstrap intervals |
| `03_pooled_against_within_industry_quintiles.png` | the two constructions side by side |

Rebuild from the repository root:

```
MPLCONFIGDIR=work/matplotlib_config conda run -n dap-env python \
  scrisk_vocabulary_fix/within_industry_quintiles.py
conda run -n dap-env python -m pytest test_within_industry_quintiles.py -q
```

`--group-column sector` cuts within the 9 sectors instead, `--min-positives` moves the floor,
and `--input` points it at any other run's event returns.
