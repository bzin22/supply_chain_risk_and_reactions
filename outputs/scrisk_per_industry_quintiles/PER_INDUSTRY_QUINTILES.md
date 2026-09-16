# SCRisk quintiles inside each industry, not pooled

> **This file uses the 91-value `industry` column, the data provider's fine-grained
> classification, not the study's 9 sectors.** `industry` is an inherited name: it splits
> Semiconductors into `Semiconductors` and `Semiconductor Equipment & Materials`, and Real
> Estate into eleven REIT subtypes. The 9-sector version is the one to quote and lives in
> `outputs/scrisk_within_sector_quintiles/WITHIN_SECTOR_QUINTILES.md`; it uses more of the
> sample, excludes nothing, and its quintile cells are 12x larger (median 222 calls against
> 18 here). Keep this file as a robustness check: it reaches the same conclusion.

Same cut as `outputs/scrisk_within_industry_quintiles/`, stopped one step earlier. Each
industry's positive SCRisk scores are ranked and split into five equal-count quintiles; this
time the quintiles are reported per industry instead of pooled. Input is the `no_self_pairs`
sensitivity run, read only. Window still 10 tokens, nothing rescored.

## Why look at this

Pooling hides whether a pattern is shared. A flat pooled line comes out of 78 industries
that each have no relationship, and equally out of 39 with a strong positive relationship
cancelling 39 with a strong negative one. Those are very different findings and the pooled
table cannot tell them apart.

## What the 78 industries look like

9,944 positive calls across 78 industries. Quintile cells run from 5 to 194 calls, median 18.

`01_quintile_pattern_by_industry_grid.png` shows all 78 panels, ordered by size. There is no
shared shape. Semiconductors, the largest at 967 positive calls, is roughly flat with a Q5
bump. Most panels scatter.

## Does the direction beat a coin flip

Under no relationship, each industry's Q5 minus Q1 spread is a coin flip, so 39 of 78 should
come out positive.

| Test | Result |
|---|---|
| Industries with positive Q5 minus Q1 | **37 of 78**, against 39 expected |
| Binomial p on that count | 0.7343 |
| Mean spread across the 78 industries | **-9.51 bp** (95% CI -63.2 to +44.2) |
| Median spread | -23.02 bp |
| SD of the spreads | 241.81 bp |
| One-sample t on the 78 spreads | t = -0.35, p = 0.7294 |
| Wilcoxon signed-rank | p = 0.8168 |

Every test is a null, and the point estimate is slightly negative rather than positive. This
agrees with the pooled result, which had Q5 minus Q1 at -11.2 bp on the mean.

## What this design could have detected

The 78 spreads have an SD of 241.81 bp, so the standard error of their mean is
241.81 / sqrt(78) = 27.4 bp and the interval is +/-53.7 bp wide.

**The data can only resolve a Q5-minus-Q1 spread larger than about 54 bp.** A real effect of
20 bp would be invisible here. Read the null as "no effect larger than half a percent of
two-day abnormal return", not as "no effect".

For scale: the pooled quintile means all sit between 9 and 43 bp, and the zero-score group is
at 22 bp. An effect the size of those numbers is inside the noise.

The tests check this claim rather than asserting it. `test_a_planted_effect_is_recovered`
builds a synthetic corpus with a 300 bp spread planted in all 40 industries and 300 bp of
noise, and the analysis returns 300 bp with a binomial p below 0.001.
`test_a_planted_effect_below_the_resolution_is_not_recovered` plants 20 bp against 600 bp of
noise and confirms it disappears. The null is a property of the data, not a bug in the
analysis.

## Individual industries

Three of 78 industries reach Welch p < 0.05 on Q5 against Q1, against 3.9 expected from 78
tests at the 5% level. One of the three points the other way.

| Industry | Q1 calls | Q5 calls | Q1 mean (bp) | Q5 mean (bp) | Spread (bp) | Welch p |
|---|---:|---:|---:|---:|---:|---:|
| Tobacco | 9 | 8 | -110.98 | 502.56 | +613.55 | 0.0367 |
| REIT - Healthcare Facilities | 9 | 8 | -91.25 | 213.31 | +304.56 | 0.0422 |
| REIT - Office | 18 | 17 | 132.24 | -58.19 | -190.43 | 0.0376 |

All three rest on cells of 8 to 18 calls. Tobacco's +614 bp comes from 8 calls against 9.
None of these is a finding.

Largest spreads either way, for the record:

| Industry | Positive calls | Q1 mean (bp) | Q5 mean (bp) | Spread (bp) | Welch p |
|---|---:|---:|---:|---:|---:|
| Tobacco | 41 | -110.98 | 502.56 | +613.55 | 0.0367 |
| Specialty Retail | 66 | -201.86 | 306.69 | +508.55 | 0.1526 |
| Industrial Distribution | 48 | -230.91 | 169.49 | +400.39 | 0.1076 |
| Farm Products | 76 | -350.78 | 10.88 | +361.67 | 0.1191 |
| ... | | | | | |
| Grocery Stores | 25 | 94.66 | -353.41 | -448.07 | 0.0650 |
| Discount Stores | 87 | 99.70 | -348.75 | -448.45 | 0.1419 |
| Business Equipment & Supplies | 27 | 575.12 | -254.03 | -829.15 | 0.0628 |
| Drug Manufacturers - Specialty & Generic | 28 | 98.54 | -759.40 | -857.95 | 0.1528 |

The spread distribution is in `02_q5_minus_q1_spread_histogram.png`: roughly symmetric about
zero, centred slightly negative, with tails out past +/-600 bp driven by the smallest
industries.

## Shape, not just direction

An industry counts as monotone when its five quintile means rise or fall in strict order.
Five means have 120 orderings and 2 are monotone, so under exchangeable means each industry
is monotone either way with probability 1/60, and 1.3 of 78 are expected.

**Four industries are monotone, which is marginally more than chance at p = 0.0417. Two rise
and two fall.**

| Industry | Direction | Spearman rho |
|---|---|---:|
| Banks - Diversified | increasing | +1.0 |
| Specialty Retail | increasing | +1.0 |
| Electronic Components | decreasing | -1.0 |
| Food Distribution | decreasing | -1.0 |

This is the one test in the file that is not a clean null, so it is worth being precise about
what it says. The elevated count is monotone runs in *either* direction. The directional test
is the one that would matter, and 2 of 78 monotone increasing carries p = 0.1381, a null. Two
up and two down is what you get when a few small industries produce a clean run by luck, not
evidence that SCRisk orders returns.

## Caveats

- **A median quintile cell is 18 calls.** No single industry panel can carry a conclusion.
  The per-industry tables exist to show the spread of outcomes, not to be read one at a time.
- **13 of 91 industries are excluded** for having fewer than 25 positive calls, 548 calls or
  3.1% of the sample. Listed in `../scrisk_within_industry_quintiles/excluded_industries.csv`.
- **Zero-score calls are held out**, 43.1% of the run. This file is about the positive scores
  only.
- **Industry labels are the data provider's and do not change over the 15 years.**
- **78 industries is 78 tests.** Every per-industry number here should be read with that in
  mind, which is why the file leads with the count of positives rather than the winners.
- **This is the `no_self_pairs` variant**, whose SD divisor is 0.000692 against the corrected
  run's 0.000751, so score levels are not comparable to the published run.

## Files

| File | Contents |
|---|---|
| `per_industry_quintiles.csv` | 78 industries x 5 quintiles: n, score range, mean and median CAR with intervals |
| `per_industry_q5_minus_q1.csv` | one row per industry: Q1 and Q5 means, spread, Welch interval and p |
| `per_industry_monotonicity.csv` | Spearman rho of quintile against mean CAR, and the monotone flags |
| `summary.json` | every test statistic, including the detectable-effect calculation |
| `01_quintile_pattern_by_industry_grid.png` | all 78 panels, Q1 to Q5, shared clipped axis |
| `02_q5_minus_q1_spread_histogram.png` | the distribution of the 78 spreads |

Rebuild from the repository root:

```
MPLCONFIGDIR=work/matplotlib_config conda run -n dap-env python \
  scrisk_vocabulary_fix/per_industry_quintiles.py
conda run -n dap-env python -m pytest test_per_industry_quintiles.py -q
```

`--group-column sector` does the same inside the 9 sectors, `--min-positives` moves the
floor, and `--input` points it at another run.
