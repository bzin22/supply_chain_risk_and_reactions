# SCRisk quintiles inside each of the 9 sectors, not pooled

Same cut as `../scrisk_within_sector_quintiles/`, stopped before the pooling step. Each
sector's positive SCRisk scores are ranked and split into five equal-count quintiles, and the
quintiles are reported per sector.

The write-up lives in `../scrisk_within_sector_quintiles/WITHIN_SECTOR_QUINTILES.md`, which
covers both the pooled and the unpooled sector results in one place. This directory holds the
data behind the unpooled half.

Headline: 5 of 9 sectors show a positive Q5 minus Q1 spread against 4.5 expected by chance
(binomial p = 1.0), the mean spread is -5.74 bp with a 95% CI of -53.6 to +42.2, no sector is
monotone in either direction, and the one sector reaching Welch p < 0.05 is Healthcare at
-146.21 bp, pointing the wrong way for a risk story. Semiconductors, with the most calls and
the most supply-chain exposure, comes in at -1.21 bp with p = 0.98.

The design can only resolve a spread larger than about 48 bp, so this is "no effect larger
than half a percent", not "no effect".

| File | Contents |
|---|---|
| `per_sector_quintiles.csv` | 9 sectors x 5 quintiles: n, score range, mean and median CAR with intervals |
| `per_sector_q5_minus_q1.csv` | one row per sector: Q1 and Q5 means, spread, Welch interval and p |
| `per_sector_monotonicity.csv` | Spearman rho of quintile against mean CAR, and the monotone flags |
| `summary.json` | every test statistic, including the detectable-effect calculation |
| `01_quintile_pattern_by_sector_grid.png` | all 9 panels, Q1 to Q5, shared axis |
| `02_q5_minus_q1_spread_histogram.png` | the distribution of the 9 spreads |
