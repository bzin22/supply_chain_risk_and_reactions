# Hardware regression extension

The primary SCRisk estimate is -0.8227 percentage points per baseline score unit (cluster SE 0.1065; 95% CI [-1.0322, -0.6132]; p=1.04e-13). The interval excludes zero under the specified firm-clustered inference. The pooled SCRisk slope is -0.6183 in M1 and -0.7123 after adding Resolution. M3 compares score changes within firms after common calendar-quarter effects; its change is not caused by a different call sample. The R1 slope is -0.8386 (p=1.82e-13) after the one planned fiscal-2010 exclusion. This checks dependence on the early fiscal year, not causality.

Resolution estimates: M2: +0.2326 pp, p=0.0232. M3: +0.2233 pp, p=0.0317. R1: +0.2266 pp, p=0.0341. Resolution is a subset of supply-risk
language, so these slopes are conditional associations, not distinct randomized
treatments. One score unit uses the original hardware population SD before
clipping; no within-firm or sample-specific rescaling was performed.

Adding Resolution makes the negative SCRisk slope larger in magnitude; the two
scores are positively correlated, while Resolution has a positive conditional
slope. Adding fixed effects strengthens the negative association further after
removing stable firm differences and common quarter shifts. These adjustments
do not control for call-specific earnings news. The M3 slopes explain only
0.64% of outcome variation remaining after
both fixed effects; statistical precision does not imply strong predictive fit.

## Regression table

|  | M1 | M2 | M3 (primary) | R1: no FY2010 |
| --- | --- | --- | --- | --- |
| SCRisk | -0.6183 | -0.7123 | -0.8227 | -0.8386 |
| Cluster SE | (0.0830) | (0.0882) | (0.1065) | (0.1098) |
| 95% t interval | [-0.782, -0.455] | [-0.886, -0.539] | [-1.032, -0.613] | [-1.054, -0.623] |
| p-value | <0.0001 | <0.0001 | <0.0001 | <0.0001 |
| Resolution | -- | 0.2326 | 0.2233 | 0.2266 |
| Cluster SE | -- | (0.1020) | (0.1035) | (0.1066) |
| 95% t interval | -- | [0.032, 0.433] | [0.020, 0.427] | [0.017, 0.436] |
| p-value | -- | 0.0232 | 0.0317 | 0.0341 |
| Intercept | 0.8689 | 0.8628 | Absorbed | Absorbed |
| Cluster SE | (0.0978) | (0.0978) | -- | -- |
| 95% t interval | [0.677, 1.061] | [0.671, 1.055] | -- | -- |
| p-value | <0.0001 | <0.0001 | -- | -- |
| Calls | 11,950 | 11,950 | 11,950 | 11,595 |
| Firms / clusters | 378 | 378 | 378 | 378 |
| Calendar quarters | 43 | 43 | 43 | 40 |
| Overall R-squared | 0.0054 | 0.0059 | 0.0562 | 0.0563 |
| Adjusted overall R-sq. | 0.0053 | 0.0057 | 0.0217 | 0.0210 |
| Two-way partial R-sq. | -- | -- | 0.0064 | 0.0066 |
| Firm + quarter effects | No | No | Yes | Yes |
| Inference df (G - 1) | 377 | 377 | 377 | 377 |

Outcome: 100 x winsorized CAR(0,1), in percentage points. Equal call weights; zero scores retained. SCRisk and Resolution retain the baseline uncentered population-SD units and 1%/99% clipping thresholds. R1 excludes adjudicated issuer fiscal year 2010 with the original thresholds. Firm-clustered CR1 standard errors: G/(G-1) x (N-1)/(N-K), with K counting the full design rank, including fixed effects. Two-sided t inference uses G-1 degrees of freedom. The M3/R1 constant is absorbed in the fixed-effect span. No singleton or influence deletions. Overall R-squared = 1 - SSE/SST around the outcome mean, including fixed effects. Adjusted overall R-squared uses N-K and N-1 degrees of freedom. Two-way partial R-squared = 1 - SSE/SS of the outcome after removing firm and calendar-quarter effects. Calendar quarters use event_trading_date; eligible fiscal-2019 events released in 2020 remain. Corrected hardware baseline, common CAR/SIC-eligible sample. Planned analysis following descriptive exploration; not preregistered and not causal.

## Sample and input audit

The unchanged audited loader passed every manifest, method-equivalence,
dictionary, date-adjudication and unique-call check in an isolated snapshot:
263 manifest entries. Every source in this checkout matched the corrected baseline manifest; no source recovery was needed.
The baseline data package itself had no mismatch. `input_audit.json` records each
discrepancy. `audited_inputs/` preserves the verified loader and dependencies for
a self-contained offline rerun from these derived inputs.

Historical CIK matches the roster's historical issuer mapping. Marvell's current
portfolio CIK 0001835632 maps to predecessor 0001058057 for 25 observations, as
explicitly documented in the baseline roster. Historical and portfolio CIKs map
one-to-one across all 378 eligible firms. Firm effects and clustering use the
historical CIK consistently; no company is split at a ticker or current-ID change.

The baseline contains 12,832 input calls from
379 firms; its existing joint CAR/price/SIC/date gates
exclude 882 calls. The regression starts with
11,950 eligible calls from 378 firms, with 0
additional complete-case exclusions. M1-M3 use exactly the same call IDs.
R1 excludes 355 adjudicated fiscal-2010 calls and
retains 11,595 calls from 378 firms. It does not use
provider fiscal-quarter labels for the exclusion. The original clipping
thresholds and population scaling are retained.

There are 240 fiscal-2019 events released
in 2020, all retained in the main sample. Calendar effects span
2009Q3 to 2020Q1; they use
trading dates. Zero scores are retained: 3326
SCRisk zeros and 9962 Resolution zeros.
All call weights equal one. There are no fractional membership rows.
The 2009 calendar quarters arise from adjudicated issuer fiscal-2010 events;
fiscal scope was not incorrectly converted to a calendar-year exclusion.

Singleton exclusions are zero. M3 retains 2
singleton firms and 0 singleton periods;
R1 retains 2 and
1, respectively. Singleton effects provide
no within-effect slope information. Absorbed slopes: M3
[]; R1 []. The constant is
absorbed in the fixed-effect span. Full design ranks are
M1: 2, M2: 3, M3: 422, R1: 419.

## Diagnostics and numerical verification

375 firms have within-firm SCRisk variation;
350 have Resolution variation. The two-way
residualized regressor correlation is 0.4023; the
two-regressor VIF is 1.193. M3 residualized
design condition number is 1.533.
These diagnostics and firm-level variation are saved; no automatic deletion or
additional specification search was performed.

Across 1768 distinct event trading dates, the busiest date
contains 56 calls from
56 firms. The ten busiest dates account for
4.19% of calls;
96.17% occur on dates
shared by multiple firms. Quarter effects cannot remove every same-day common
shock. Per-date and per-quarter concentration tables are included.

The largest first-order firm influence relative to its cluster SE is
{"SCRisk_first_order_delta_over_cluster_se": 0.21248135686158817, "Resolution_first_order_delta_over_cluster_se": 0.27795973304578697}. These are local
influence approximations, not exact deletion estimates. Full-model leverage,
Cook's distance and residuals are saved per call. Cook's distance uses
homoskedastic MSE only as an influence diagnostic, not for inference. No rows
were removed for leverage, residuals or influence.
Cook's distance is undefined and left missing for the
2 unit-leverage singleton calls, whose
fixed effects fit them exactly; it is not given a spurious finite value.

All four coefficient vectors, residuals and CR1 covariance matrices were checked
against statsmodels OLS with explicit dummies. Maximum coefficient discrepancy:
7.88e-15; maximum
covariance discrepancy: 2.81e-15.
The main implementation uses alternating projection/FWL and a separately coded
cluster sandwich. Numerical tolerance is 1e-9 absolute/1e-8 relative for
coefficients and 1e-10 absolute/1e-7 relative for covariance. R-squared definitions
are above; they should not be conflated with each other.

CR1 method reference: [statsmodels covariance implementation](https://www.statsmodels.org/stable/_modules/statsmodels/stats/sandwich_covariance.html#cov_cluster).

## Interpretation limits

Earnings surprises, guidance changes and other simultaneous news are omitted.
They may affect both transcript language and announcement returns, so controlling
for Resolution and fixed effects does not identify a causal SCRisk effect. The
transcript can also describe information released during the return window.
Firm clustering allows within-firm error dependence but assumes independent
clusters; cross-firm same-day or industry shocks may make these intervals too
narrow. Calendar-quarter effects do not guarantee residual independence.

The current-company/US-headquarters screen, survival and transcript/price/SIC
availability limit external validity. The inherited common eligibility gate
requires both CAR horizons even though only CAR(0,1) is regressed here. This
preserves the corrected baseline but can select a different sample than a
CAR(0,1)-only gate. Reconstructed dictionaries and substantial zero scores are
measurement limitations. Null estimates are not proof of no economically
relevant relationship; the reported intervals describe precision under this
model and covariance assumption. This was planned after descriptive exploration,
not preregistered. No supplier-dependence interaction or CAR(2,60) regression ran.

## Reproduction

See [the code README](../../analysis/hardware_regression_v1/README.md) for the single rerun command.
`sample_ids.csv` identifies inclusion in every model; `regression_sample.csv`
retains original scaled and once-clipped values. `regression_results.csv` holds
full-precision coefficients, cluster SEs, intervals, p-values, sample counts and
R-squared. PDF, LaTeX and Markdown tables are generated from those same results.
`fingerprints.json` records input, code, output and dependency hashes/versions;
`protected_hashes_before.json` establishes preservation of the baseline,
dictionaries, charts and existing source files. No paper, baseline chart, remote
branch, transcript score or CAR estimate was changed.
