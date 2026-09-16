# SCRisk quintiles cut within sector, then pooled

The 9 study sectors, which is the grouping variable the study is built on
(`diversified_450_companies_9_sectors.csv`). Built from the `no_self_pairs` sensitivity run:
the corrected vocabulary with the zero-distance self-match of `shortage` and `shortages`
refused. Input is
`artifacts/earnings_call_supply_chain/ppmi_svd_full_20260910_vocab_v2/sensitivity/no_self_pairs/event_returns.csv`,
read only. Window still 10 tokens, nothing rescored.

**A note on the two grouping columns.** The event returns CSV carries both `sector` (9 values:
Consumer Goods, Energy, Financial Services, Healthcare, Industrials, Real Estate, Retail,
Semiconductors, Technology) and `industry` (91 values: `REIT - Office`, `Tobacco`,
`Semiconductor Equipment & Materials`). `industry` is the data provider's finer
classification, inherited, not ours. This file uses `sector`, the 9. The 91-label versions
are in `outputs/scrisk_within_industry_quintiles/` and
`outputs/scrisk_per_industry_quintiles/`, and are worth keeping only as a robustness check,
because a 91-way split leaves a median quintile cell of 18 calls against 222 here.

## Why cut within sector

The published quintiles are cut once on the pooled distribution, so a call's quintile partly
reports how supply-chain-heavy its sector is rather than how supply-chain-heavy the call is
for its sector. Sorting on SCRisk sorts on sector.

The evidence is the composition. Under the pooled cut, every sector's share of the quintiles
drifts; under the within-sector cut, none of them move:

| Sector's share of | Q1 | Q2 | Q3 | Q4 | Q5 | Spread |
|---|---:|---:|---:|---:|---:|---:|
| Semiconductors, pooled | 6.16% | 11.23% | 15.66% | 21.71% | 25.80% | **19.65 pp** |
| Semiconductors, within-sector | 16.12% | 16.10% | 16.10% | 16.10% | 16.13% | **0.03 pp** |
| Energy, pooled | 13.59% | 13.10% | 11.32% | 8.52% | 2.81% | **10.78 pp** |
| Energy, within-sector | 9.88% | 9.85% | 9.90% | 9.85% | 9.87% | **0.05 pp** |

Pooled Q5 is a quarter semiconductor calls and 2.8% energy calls. Pooled Q1 is the reverse.
That is a sector comparison wearing a risk label. Across all 9 sectors the median spread
falls from 9.21 points under the pooled cut to 0.03 points under the within-sector cut.

## Construction

1. Keep the 17,833 events with `event_status = ok`, an estimated CAR(0,1) and a defined
   SCRisk.
2. Hold out the 7,678 zero-score calls, 43.1% of the run. They are a mass point, not a low
   tail, so cutting them into quintiles would make Q1 a statement about how many zeros a
   sector has.
3. Within each sector, rank the positive scores ascending and cut the ranks into five
   equal-count groups. Ties break on ticker then quarter.
4. Pool the Q1s, the Q2s and so on across the 9 sectors.

All 9 sectors clear the 25-positive floor, so nothing is excluded and all 10,155 positive
calls are used. Quintile cells run 142 to 328 calls, median 222.

## Result

| Group | Events | Mean CAR (bp) | 95% CI | Median CAR (bp) | Bootstrap 95% CI |
|---|---:|---:|---|---:|---|
| Score = 0 | 7,678 | 22.61 | 8.13 to 37.09 | 10.93 | 1.88 to 21.21 |
| Q1 | 2,035 | 21.68 | -5.47 to 48.83 | 26.54 | 5.44 to 55.04 |
| Q2 | 2,031 | 37.73 | 9.35 to 66.10 | 15.58 | -2.93 to 46.24 |
| Q3 | 2,031 | 17.32 | -10.34 to 44.99 | -12.80 | -32.68 to 11.98 |
| Q4 | 2,031 | 16.81 | -12.27 to 45.90 | -0.09 | -25.99 to 25.33 |
| Q5 | 2,027 | 16.77 | -13.89 to 47.43 | 12.72 | -17.61 to 44.07 |

**No gradient.** Q1 through Q5 read 21.7, 37.7, 17.3, 16.8, 16.8 bp against a confidence
half-width of about 28 bp. Q5 minus Q1 is -4.9 bp on the mean. Every quintile's interval
straddles zero except Q2's, and with six groups tested one is what chance gives.

The zero group at 22.61 bp sits in the middle of the quintiles, so zero-SCRisk calls are not
distinguishable from scored ones either.

## Sector by sector, without pooling

`outputs/scrisk_per_sector_quintiles/` runs the same cut but reports each sector separately,
so the pooled flat line can be checked against the possibility that strong positive and
negative sectors are cancelling. They are not.

| Sector | Positive calls | Q1 mean (bp) | Q5 mean (bp) | Q5 minus Q1 (bp) | Welch p |
|---|---:|---:|---:|---:|---:|
| Consumer Goods | 900 | -68.73 | 23.15 | +91.88 | 0.1773 |
| Technology | 1,224 | 61.05 | 126.61 | +65.56 | 0.3995 |
| Financial Services | 1,109 | 2.70 | 34.55 | +31.84 | 0.3986 |
| Energy | 1,002 | 6.51 | 32.33 | +25.82 | 0.6794 |
| Retail | 1,231 | -18.07 | -17.58 | +0.49 | 0.9938 |
| Semiconductors | 1,636 | 42.96 | 41.75 | -1.21 | 0.9849 |
| Real Estate | 711 | 55.45 | 8.08 | -47.37 | 0.1671 |
| Industrials | 1,403 | 62.15 | -10.28 | -72.44 | 0.1476 |
| Healthcare | 939 | 24.50 | -121.71 | **-146.21** | **0.0319** |

| Test | Result |
|---|---|
| Sectors with positive Q5 minus Q1 | 5 of 9, against 4.5 expected |
| Binomial p | 1.0 |
| Mean spread across the 9 sectors | **-5.74 bp** (95% CI -53.6 to +42.2) |
| Median spread | +0.49 bp |
| SD of the spreads | 73.31 bp |
| One-sample t on the 9 spreads | t = -0.23, p = 0.8203 |
| Wilcoxon signed-rank | p = 1.0 |
| Sectors monotone in either direction | **0**, against 0.15 expected |

Semiconductors, the sector where supply-chain risk should bite hardest and which has the most
calls, shows a Q5 minus Q1 spread of -1.21 bp with p = 0.98. That is as close to nothing as
this data can express.

One sector reaches Welch p < 0.05: Healthcare at -146.21 bp, and it points the wrong way for
a risk story. Against 9 tests at the 5% level, 0.45 false positives are expected, so one
finding is unremarkable, and a negative one is not evidence that supply-chain risk lowers
returns.

## What this design could have detected

The 9 spreads have an SD of 73.31 bp, so the standard error of their mean is
73.31 / sqrt(9) = 24.4 bp and the interval is +/-47.9 bp wide.

**The data can only resolve a Q5-minus-Q1 spread larger than about 48 bp.** Every quintile
mean in the pooled table sits between 17 and 38 bp, so an effect the size of those numbers is
inside the noise. Read this as "no effect larger than half a percent of two-day abnormal
return", not "no effect".

The tests check this rather than asserting it: `test_a_planted_effect_is_recovered` builds a
synthetic corpus with a 300 bp spread planted in every group and the analysis returns 300 bp
at p < 0.001, while a 20 bp plant against 600 bp of noise correctly disappears. The null is a
property of the data, not a bug in the analysis.

## Sector against industry

Both groupings give the same answer, which is the useful thing about having run both.

| | 9 sectors | 91 industries (78 usable) |
|---|---:|---:|
| Groups | 9 | 78 |
| Positive calls used | 10,155 | 9,944 |
| Groups excluded for thin cells | 0 | 13 (548 calls) |
| Median quintile cell | 222 | 18 |
| Pooled Q5 minus Q1 mean | -4.9 bp | -11.2 bp |
| Groups with positive spread | 5 of 9 (p = 1.0) | 37 of 78 (p = 0.73) |
| Mean spread | -5.74 bp | -9.51 bp |
| Smallest detectable spread | 47.9 bp | 53.7 bp |
| Groups monotone | 0 of 9 | 4 of 78 (2 up, 2 down) |
| Worst-balanced group spread, within cut | 0.05 pp | 0.26 pp |

The sector version is the one to quote. It uses more of the sample, excludes nothing, and its
quintile cells are 12x larger.

## Caveats

- **Zero-score calls are held out**, 43.1% of the run, and are not comparable to the
  quintiles.
- **Score ranges overlap across quintiles by design.** Q1 tops out at 0.325 and Q5 starts at
  0.535, so a call at 0.40 is in Q1 in a supply-chain-heavy sector and Q4 or Q5 in a light
  one. That is the trade: a controlled comparison in exchange for an absolute reading of the
  score.
- **This holds sector mix constant, not year mix.** A within-sector quintile can still be
  tilted toward 2022, when everybody's SCRisk was high. Cutting within sector and year
  together was not done.
- **This is the `no_self_pairs` variant**, whose SD divisor is 0.000692 against the corrected
  run's 0.000751, so score levels are not comparable to the published run.
- **`within_sector_quintiles_all_observations.csv`** ranks every call, zeros included. Q1 is
  100% zeros and Q2 is 89.7% zeros, so it is close to "zero against positive" with extra
  steps. Reported for completeness, not recommended.

## Files

| File | Contents |
|---|---|
| `within_sector_quintiles.csv` | the pooled table above, with both intervals |
| `pooled_quintiles_same_run.csv` | the published construction on the same observations |
| `within_sector_quintiles_by_sector.csv` | 9 sectors x 5 quintiles, n, score range, CAR |
| `sector_mix_by_quintile.csv` | each sector's share of each quintile, the balance check |
| `sector_mix_by_quintile_pooled.csv` | the same check for the pooled cut |
| `within_sector_quintiles_all_observations.csv` | the zeros-included variant |
| `summary.json` | every count and the balance statistics |
| `01_mean_car_by_within_sector_scrisk_quintile.png` | mean CAR, six groups |
| `02_median_car_by_within_sector_scrisk_quintile.png` | median CAR, bootstrap intervals |
| `03_pooled_against_within_sector_quintiles.png` | the two constructions side by side |

Rebuild from the repository root:

```
MPLCONFIGDIR=work/matplotlib_config conda run -n dap-env python \
  scrisk_vocabulary_fix/within_industry_quintiles.py \
  --group-column sector --output outputs/scrisk_within_sector_quintiles
MPLCONFIGDIR=work/matplotlib_config conda run -n dap-env python \
  scrisk_vocabulary_fix/per_industry_quintiles.py \
  --group-column sector --grid-columns 3 --output outputs/scrisk_per_sector_quintiles
```
