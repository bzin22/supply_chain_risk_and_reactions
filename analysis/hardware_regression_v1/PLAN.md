# Planned hardware regression extension

Recorded before coefficient estimation, following descriptive exploration. This
is a planned analysis, not a preregistered study. No source collection, transcript
scoring, CAR estimation, supplier-dependence variables or interactions are run.

## Data and units

Use `analysis.hardware_reproduction.load_package` on the corrected
`reproduction/hardware_baseline_v1`. Require all hash/method/dictionary, release
date adjudication, identity, eligibility and uniqueness checks to pass. Expect
11,950 eligible calls and 378 stable issuer CIKs; stop on discrepancies.

One row per call, equal call weights. Retain zero scores. Use SCRisk and
Resolution in the hardware loader's existing units: raw length-adjusted scores
divided by the population SD across all score-valid hardware calls, without
mean subtraction. Do not standardize again. Apply the existing linear 1%/99%
winsorization function once to the eligible sample and verify its thresholds
against the baseline configuration. Outcome is 100 times winsorized CAR(0,1),
in percentage points. No fractional memberships or quintile labels enter.

Identify firms by stable historical CIK (`cik`), checking its mapping to
`portfolio_cik`. Time effects use calendar year-quarter of `event_trading_date`.
Retain eligible fiscal-2019 calls released in 2020. Fiscal years use the first
four digits of adjudicated `issuer_fiscal_period_label`, including transition
periods; never use the legacy provider quarter identifier.

Pre-estimation identity clarification: the roster maps Marvell's current CIK
0001835632 to historical predecessor CIK 0001058057 for this study. Verify that
mapping against `roster_379.csv` and one-to-one correspondence across the 378
eligible firms; do not require current and historical CIK strings to be equal.
Retain the two observed singleton firms under the common-sample rule above.

Require finite scores/outcome, nonblank valid firm and trading date and resolved
adjudicated fiscal period. M1–M3 use the identical complete-case sample. Report
any attrition before estimation. Retain singletons in all three models rather
than silently changing the common sample; count them and note their lack of
within-effect information. No influential-observation deletion is authorized.

## Specifications, inference and validation

M1: CAR percentage points on intercept and continuous SCRisk.

M2: M1 plus continuous Resolution.

M3 (primary): SCRisk and Resolution plus firm and event-calendar year-quarter
fixed effects. The constant is represented by the fixed-effect span; its chosen
dummy normalization is not a substantive estimate. Report any absorbed slopes.

R1 (only planned robustness model): M3 excluding adjudicated issuer fiscal year
2010. Reuse full baseline scaling and clipping thresholds; never recalculate them
on the restricted sample. Retain zeros and singletons, documenting sample changes.

OLS with equal call weights. Cluster on stable firm CIK. Use CR1 covariance
`c * (X'X)^(-1) [sum_g X_g' u_g u_g' X_g] (X'X)^(-1)`, where
`c = G/(G-1) * (N-1)/(N-K)`, G is the number of firms and K is the full model
rank including fixed effects. For absorbed estimates use residualized regressors
but retain the full rank in c. This deliberately counts firm effects even though
they are nested in clusters; it matches the explicit-dummy CR1 convention rather
than software defaults that exempt nested effects. Use two-sided t tests and
95% t intervals with G-1 degrees of freedom.

Primary estimation uses Frisch–Waugh–Lovell residualization via alternating firm
and time demeaning. Independently verify coefficients, residuals and clustered
covariance using statsmodels OLS with explicit fixed-effect dummies and its
`cov_cluster(..., use_correction=True)`. Require agreement within stated
floating-point tolerances. Full design rank is checked; stop on unidentified
nonabsorbed slopes or disconnected/rank-deficient dummy designs.

Report overall centered R-squared as 1 - SSE / sum((y-mean(y))^2), including all
fitted fixed effects. Report adjusted overall R-squared using N-K residual and
N-1 total degrees of freedom. For M3/R1 also report two-way partial R-squared:
1 - SSE / sum((M_FE y)^2). It measures added fit of the two slopes after removing
both effects, not between-firm fit or a correlation-squared measure.

Diagnostics: pooled and within-firm score variation, two-way residualized score
correlation/VIF and rank/condition number, singletons, call leverage and Cook's
distance, and first-order firm influence (bread times clustered score, scaled by
cluster SE). The influence quantities are diagnostics, not additional fitted
specifications or reasons to delete rows. Examine dates shared across firms and
the share of calls concentrated in the busiest dates/time periods. Do not search
specifications, thresholds or samples for significance.

## Delivery and limitations

Save sample IDs, transformed call-level inputs, exclusions, frozen specification,
input/code/dependency fingerprints, regression CSV, covariance matrices,
paper-ready table, checks and a short interpretation in a separate output
directory. Refuse output overwrite. Verify protected inputs/charts before and
after. Do not rewrite the paper, push or merge.

Discuss omitted earnings surprises/guidance and other concurrent news, possible
cross-firm residual dependence despite quarter effects, current-company and
data-availability selection (including joint CAR/SIC gates inherited from the
baseline), and noncausal interpretation. Explain null or contrary estimates.

Method reference: statsmodels' documented CR1 implementation:
https://www.statsmodels.org/stable/_modules/statsmodels/stats/sandwich_covariance.html#cov_cluster
