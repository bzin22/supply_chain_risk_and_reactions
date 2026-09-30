# Hardware portfolio baseline

This is the review baseline for fiscal 2010Q1–2019Q4. The
[canonical roster](../../reproduction/hardware_baseline_v1/roster_379.csv) has
379 distinct companies, all represented in the common analysis sample. It is
the observed-coverage subset of the outcome-blind
[400-company screen](../../reproduction/hardware_baseline_v1/screened_universe_400.csv),
not a replacement claim that only 379 companies passed the company screen.
The 21 other screened companies have no usable calls. Current US headquarters
and listing requirements introduce survivorship and current-company selection.
A physical-product business does not by itself establish international supply-chain exposure.

## Coverage and exclusions

Of 16,000 issuer-quarter slots, 12,832 have valid calls: 12,690 reused from the
frozen corpus, 121 reused from other local caches, and 21 downloaded (Hubbell).
The remaining slots are 3,149 unavailable, 13 unresolved identity, 3 provider
technical failures, 2 not applicable, and 1 invalid-content call. See the
[complete pair ledger](../../reproduction/hardware_baseline_v1/pair_coverage.csv.gz).
The common sample retains 12,744 calls from 379 firms. Sequential exclusions
are 5 missing release dates, 34 failures to construct both CAR windows, and
49 historical-SIC failures. Raw reason flags overlap; use the sequential
[gate table](gate_counts.csv) when adding exclusions.

| Fiscal year | Valid calls | Retained calls | Retained firms | Excluded calls |
| --- | ---: | ---: | ---: | ---: |
| 2010 | 714 | 676 | 221 | 38 |
| 2011 | 761 | 743 | 278 | 18 |
| 2012 | 1246 | 1240 | 334 | 6 |
| 2013 | 1353 | 1347 | 346 | 6 |
| 2014 | 1447 | 1443 | 367 | 4 |
| 2015 | 1451 | 1444 | 368 | 7 |
| 2016 | 1430 | 1427 | 361 | 3 |
| 2017 | 1461 | 1461 | 370 | 0 |
| 2018 | 1485 | 1483 | 374 | 2 |
| 2019 | 1484 | 1480 | 375 | 4 |

Year means fiscal-quarter year, not event-calendar year; fiscal 2019 calls can
have 2020 release dates. Coverage differs by year, and the first/last observed
quarter in the roster does not imply complete coverage between those endpoints.
The [annual CSV](coverage_by_year.csv) also reports valid firms and zero shares.
Among all valid calls, SCRisk is zero in 3,553 (27.6886%) and Resolution in
10,710 (83.4632%). Among retained calls, these counts are 3,525 (27.6601%) and
10,634 (83.4432%). Zeros remain in the fractional sorts.

## Reproduce

From a checkout with Python 3.14.7 and `venv`/`pip`:

```sh
./scripts/reproduce_hardware.sh
# If Python is not on PATH:
PYTHON=/path/to/python3.14 ./scripts/reproduce_hardware.sh outputs/hardware_review
```

Installation uses the package index; analysis itself is offline and needs no API
key. The script uses an isolated `.venv-hardware`, runs the relevant tests, then
writes into a new output directory (never overwrites). After installation:

```sh
.venv-hardware/bin/python -m analysis.hardware_reproduction --output outputs/hardware_review_again
```

The command verifies SHA-256 hashes, recomputes score scaling from all 12,832
valid raw scores, reconstructs eligibility, then reruns winsorization,
fractional allocation, covariance, confidence intervals and all 630 existing
portfolio comparisons. It numerically checks 13 generated reference tables
and exports five PNGs and a five-page PDF. `verification.json` records the
result. It starts from derived raw scores and CARs, so it does **not** tokenize
private transcripts or refit daily-price regressions in the portable run.
[Input access and raw-stage commands](../../reproduction/hardware_baseline_v1/INPUT_ACCESS.md)
document those prerequisites without redistributing them.

## Methods

[Configuration](../../reproduction/hardware_baseline_v1/config.json) records the
254-term supply-chain, 161-term risk and 55-term Resolution dictionaries and
hashes. Scoring uses the approved exact-term tokenizer/matcher, every qualifying
supply-risk pair at closest-token distance at most 10 (including overlap),
`max_cosine` supply weights, and transcript token length as denominator.
Resolution additionally requires a Resolution occurrence within 10 tokens of
the supply occurrence. Divide each raw score by its hardware population SD
(`ddof=0`, no centering), before CAR exclusion.

The event date is the earnings **release** date. Independently confirmed call
dates remain separate. Day 0 is the first factor-calendar trading day on or
after release; there is no after-hours shift. Carhart OLS uses 200 complete
observations at offsets −209 through −10, an intercept plus market excess,
SMB, HML and momentum, full rank five, and arithmetic adjusted-close returns
minus RF. Both event windows must be complete: 2 days for CAR(0,1) and 59 days
for CAR(2,60). Missing observations never move or compress the windows.

Point-in-time SIC uses the latest filing available by observed fiscal-period
end; no current-SIC backfill. On the common eligible sample, each score and CAR
is winsorized at linear 1st/99th percentiles. Thresholds are recomputed for
hardware and published in [CSV](winsorization_thresholds.csv). Sort within SIC
divisions over the pooled study period, distribute tied groups fractionally,
then sort Resolution conditionally within each SCRisk portfolio using parent
weights. Pool corresponding portfolios across divisions. Each call has total
allocation weight one. Uncertainty is firm-clustered with 95% Student-t
intervals and joint covariance accounting for shared calls. Means are shown in
percent; call-level CARs are decimals. Results are descriptive associations.

The raw-stage driver is [`analysis/hardware_us400`](../../analysis/hardware_us400/).
Shared primary methods are reused unchanged. Two source snapshots preserve the
original scorer/factor-parser versions; a hash and AST equivalence check
verifies the primary definitions used by the active modules. Differences in
newer main concern other scoring modes and CLI validation. The canonical
libraries and original full-universe research prose remain intact.

## Figures and supporting tables

### Mean CAR(0,1) by SCRisk quintile

![Mean CAR(0,1) by SCRisk quintile](01_car_0_1_by_scrisk.png)

[Table](01_car_0_1_by_scrisk.csv) · [Joint covariance](01_car_0_1_by_scrisk_covariance.csv)

### Mean CAR(0,1) by Resolution quintile

![Mean CAR(0,1) by Resolution quintile](02_car_0_1_by_resolution.png)

[Table](02_car_0_1_by_resolution.csv) · [Joint covariance](02_car_0_1_by_resolution_covariance.csv)

### CAR(0,1): SCRisk × Resolution

![CAR(0,1): SCRisk × Resolution](03_car_0_1_heatmap.png)

[Table](03_car_0_1_heatmap.csv) · [Joint covariance](03_car_0_1_heatmap_covariance.csv)

### Mean CAR(2,60) by SCRisk quintile

![Mean CAR(2,60) by SCRisk quintile](04_car_2_60_by_scrisk.png)

[Table](04_car_2_60_by_scrisk.csv) · [Joint covariance](04_car_2_60_by_scrisk_covariance.csv)

### CAR(2,60): SCRisk × Resolution

![CAR(2,60): SCRisk × Resolution](05_car_2_60_heatmap.png)

[Table](05_car_2_60_heatmap.csv) · [Joint covariance](05_car_2_60_heatmap_covariance.csv)

[Combined PDF](us_hardware_fractional_charts.pdf) · [630 portfolio comparisons](portfolio_comparisons.csv) · [Zero/tie audit](zero_tie_audit.csv). Comparisons are the existing descriptive results; no new selection or multiple-testing adjustment is introduced.
