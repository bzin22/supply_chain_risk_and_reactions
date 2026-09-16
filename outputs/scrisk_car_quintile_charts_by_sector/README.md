# CAR(0,1) against SCRisk quintile, one chart per sector

18 figures: a mean-CAR and a median-CAR chart for each of the 9 study sectors. Each is a
standalone full-size chart in the same style as
`outputs/scrisk_car_event_charts/01_mean_car_by_scrisk_quintile.png`, showing that sector's
zero-score calls followed by its own Q1 to Q5.

Built from the `no_self_pairs` sensitivity run: the corrected vocabulary with the
zero-distance self-match of `shortage` and `shortages` refused. Window still 10 tokens,
nothing rescored.

## How to read them

**Quintiles are cut inside each sector on its own positive scores.** Q5 means "high SCRisk
for this sector", not "high SCRisk in the corpus". A sector's Q1 can hold higher raw scores
than another sector's Q5, and that is deliberate: it is what makes the Q1-against-Q5
comparison a within-sector comparison rather than a restatement of which sectors talk about
supply chains.

**Zero-score calls are a separate group, not a sixth quintile.** They are 43.1% of the run,
a mass point rather than a low tail, so ranking them would make Q1 a zero count.

**All nine figures share one y-axis** so they can be read against each other. That leaves
dead space in the tighter sectors, Semiconductors most of all. Pass `--autoscale` for
per-figure ranges instead.

**The n row sits at the top of each chart.** Counts are in a fixed row rather than above each
bar, because a negative bar with a long whisker pushes its label off the axis.

## Files

| Figure | Sector | Analysable calls |
|---|---|---:|
| `01_semiconductors_*` | Semiconductors | 2,371 |
| `02_healthcare_*` | Healthcare | 2,291 |
| `03_industrials_*` | Industrials | 2,085 |
| `04_technology_*` | Technology | 2,066 |
| `05_retail_*` | Retail | 2,052 |
| `06_financial_services_*` | Financial Services | 1,917 |
| `07_energy_*` | Energy | 1,755 |
| `08_real_estate_*` | Real Estate | 1,656 |
| `09_consumer_goods_*` | Consumer Goods | 1,640 |

Numbered by call count, largest first. `*` is `mean_car_by_scrisk_quintile.png` or
`median_car_by_scrisk_quintile.png`.

`car_quintiles_by_sector.csv` holds the 54 rows behind the figures: 9 sectors x 6 groups,
with events, score range, mean and median CAR, and both confidence intervals.
`summary.json` holds the counts and each sector's Q5 minus Q1.

## The numbers plotted, mean CAR in basis points

| Sector | Calls | Zero n | Zero | Q1 | Q2 | Q3 | Q4 | Q5 | Q5-Q1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Semiconductors | 2,371 | 735 | 5.78 | 42.96 | 88.98 | 44.83 | 77.48 | 41.75 | -1.21 |
| Healthcare | 2,291 | 1,352 | 16.46 | 24.50 | -12.44 | 38.80 | 20.84 | -121.71 | -146.21 |
| Industrials | 2,085 | 682 | 41.44 | 62.15 | -23.31 | -31.69 | -8.43 | -10.28 | -72.43 |
| Technology | 2,066 | 842 | 70.30 | 61.05 | 195.01 | 50.15 | -14.67 | 126.61 | +65.56 |
| Retail | 2,052 | 821 | 37.24 | -18.07 | 42.57 | 25.21 | -2.90 | -17.58 | +0.49 |
| Financial Services | 1,917 | 808 | 15.70 | 2.70 | -26.50 | -5.03 | 16.14 | 34.55 | +31.85 |
| Energy | 1,755 | 753 | 35.72 | 6.51 | -23.44 | -1.09 | -1.50 | 32.33 | +25.82 |
| Real Estate | 1,656 | 945 | 3.29 | 55.45 | 14.95 | -37.40 | -3.43 | 8.08 | -47.37 |
| Consumer Goods | 1,640 | 740 | -18.44 | -68.73 | 36.73 | 57.00 | 48.75 | 23.15 | +91.88 |

Quintile cells run 142 to 328 calls, median 222.

**No sector shows a gradient.** Five of nine have a positive Q5 minus Q1 and four negative,
against 4.5 expected by chance. Not one sector is monotone in either direction. Semiconductors,
with the most calls and the most supply-chain exposure, comes in at -1.21 bp. The statistical
tests behind that reading, including confidence intervals on every spread and a
planted-effect check on what size of effect the data could have detected (about 48 bp), are
in `../scrisk_per_sector_quintiles/` and written up in
`../scrisk_within_sector_quintiles/WITHIN_SECTOR_QUINTILES.md`.

## Rebuild

```
MPLCONFIGDIR=work/matplotlib_config conda run -n dap-env python \
  scrisk_vocabulary_fix/per_group_quintile_charts.py
conda run -n dap-env python -m pytest test_per_group_quintile_charts.py -q
```

`--group-column industry` produces 78 figures on the provider's finer labels,
`--statistic mean` writes only the mean charts, and `--autoscale` drops the shared y-axis.
