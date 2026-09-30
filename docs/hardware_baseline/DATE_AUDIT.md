# Fiscal-period and release-date audit

Audit parent: `afd1a615123fe8300be082467eee23ea0e44ba2d` (latest PR #8 commit
when this correction started). The earnings-release specification is unchanged.
No dates were inferred from quarter labels, broad windows, or conference calls.

## Scope and decisions

Every one of the 12,832 records was checked for issuer/event collisions, fiscal
quarter ordering, exact transcript duplicates, historical SEC fiscal ends and
quarter designations, opening-period statements, explicit current-call-date
conflicts (diagnostics only), release lags, weekend dates, and existing provider
source disagreements. All calls from the identified Mercury, Oshkosh, Deckers,
VF, PVH, Oxford and Park calendar families were placed in review, including
those without original collisions. Current annual year ends cannot establish
historical quarterly calendars. SEC `fy` labels can also use different year
conventions; exact historical ends/quarter designations are evidence, not a
license to shift issuer fiscal years automatically.

The audit read existing local transcript/SEC/provider caches and searched
primary issuer announcements selectively. It did not bulk-download SEC/IR
content. 1,253 exact-end cached issuer release candidates were compared;
conflicts were held unless separately adjudicated. Another 194 provider disagreements
were resolved by inspecting competing fiscal ends: only Yahoo broad-window
assignments to different ends disagreed, while the observed Alpha Vantage end
matched SEC history. These remain consistency-screened, not primary-release-verified.
See `provider_conflict_adjudications.csv` in the reproduction package. Automatic text flags can
refer to forecasts/comparisons or operator slips, so reviewed false positives
are described in the decision ledger. Absence of a cached historical period is
an unresolved-evidence condition, not a claim that the provider date is wrong.

| Disposition | Calls |
| --- | ---: |
| Existing mapping passes consistency screen | 10,693 |
| Existing mapping corroborated by issuer evidence | 1,235 |
| Corrected issuer-period/release mapping | 54 |
| Unresolved and excluded | 850 |

The 10,693 screened mappings **were not all independently reverified against
new issuer announcements**. The distinction is retained per call. The 850
holds span 234 firms; 54 corrections span 8 firms. In total 904 call records
across 235 firms have corrected mappings or unresolved dispositions. Of the
corrections, 44 change release dates, 53 change fiscal ends, and one changes
historical SIC. All accepted events are ordered consistently by fiscal end.

All 12 original collision groups now have separately evidenced release dates
and documented dispositions. No transcript was automatically accepted or
arbitrarily deduplicated. Mercury's 33 records were checked against issuer
announcements; fiscal 2014 Q3 ends March 31 and releases April 29. Oxford's
provider 2013 Q1/Q2 transcripts actually identify issuer FY2012 Q1/Q2. VF's
provider 2018 Q1 is the March transition period, released May 4. Deckers changed
from December to March year-end in 2014; the code uses explicit period evidence.
PVH's release datelines sometimes precede the website header by one day; the
issuer's actual release dateline controls.

The transcript audit also found 36 AMD-labeled records containing Xilinx calls,
7 Curtiss-Wright records containing pre-acquisition Williams Controls calls,
one NN record containing Philips, and one Ford record naming 2023 rather than
2012. Those 45 records and 74 unresolved transcript-period conflicts leave both
CAR analysis and score scaling. Their raw texts are preserved. Valid scores
for date-only holds remain in the established pre-CAR scaling population.

See [all decisions](../../reproduction/hardware_baseline_v1/date_audit.csv.gz),
[changed mappings](mapping_changes.csv), [collision adjudications](../../reproduction/hardware_baseline_v1/collision_adjudications.csv),
and [machine-readable summary](date_audit_summary.json). Each decision records
CIK/ticker, provider and issuer fiscal period, fiscal end, release date,
source URL/hash where available, evidence, flags and transcript disposition.
The read-only diagnostic code is `analysis.hardware_us400.audit`; the
adjudication gate is `release_dates.py`. Neither creates inferred dates.

## Recomputed results

Common eligibility changes from **12,744 calls / 379 firms** to **11,950 calls /
378 firms**: 795 prior observations leave and one enters. The roster stays at
379. Raw scores are unchanged; 75 pilot calls were independently rescored and
matched. All 12,832 records went through fresh CAR/SIC logic. For unchanged
events with available CARs, 11,911 short-window and 11,910 long-window refits
match the prior estimates exactly. Forty-four changed events have new CARs.
Population SDs are SCRisk **0.00046213448135835205** and Resolution
**0.00009594827658613581**. Thresholds, common eligibility, fractional portfolios,
cluster covariance and all 630 comparisons were regenerated. No outcome or
monotonicity criterion entered any mapping or exclusion decision.

Means below are percentages, ordered Q1 through Q5.

| Panel | Prior means | Corrected means |
| --- | --- | --- |
| 01_car_0_1_by_scrisk | 1.1020, 0.4965, 0.8342, 0.3091, -0.4551 | 1.1308, 0.4318, 0.8564, 0.3139, -0.5565 |
| 02_car_0_1_by_resolution | 0.4319, 0.4319, 0.4254, 0.4190, 0.5784 | 0.4068, 0.4068, 0.4016, 0.4166, 0.5444 |
| 04_car_2_60_by_scrisk | -0.8378, -0.4515, -0.4885, -0.0342, -0.1794 | -0.9292, -0.3392, -0.3983, 0.0202, -0.2272 |

The [before/after CSV](chart_before_after.csv) reports means and confidence intervals for **all 65 cells across all five panels**, including both heatmaps. These prior values are labeled audit comparisons, not active analysis inputs.

- 03_car_0_1_heatmap: corrected cell means range from -0.6159% to 1.1308%; largest absolute change is 0.1274 percentage points.
- 05_car_2_60_heatmap: corrected cell means range from -0.9292% to 0.0766%; largest absolute change is 0.2768 percentage points.

## Validation and removal

The bounded pilot contained 75 calls, including all corrected mappings,
Mercury calls, original collision members and 20 unaffected controls. The
corrected release-date, fiscal-calendar-shift, unresolved-identity and collision
gates have regression tests. Clean-checkout reproduction checks the full
package, score scaling, eligibility, fractional weights and 13 reference tables.
[CAR validation](car_refit_validation.csv) records unchanged-event parity.

[Permanent removals](permanently_removed_files.csv) enumerates **495 permanently deleted files (235,409,558 bytes)** and exact deleted
paths and hashes after replacements passed validation. Sixteen mixed prepared/reference/manifest
CSVs were corrected in place, preserving their valid rows and raw-source
references. Raw transcripts, adjusted prices and source evidence remain outside
Git. The original full-universe research and raw provider/frozen corpus remain
unrelated source material; their historical metadata is never an authoritative
hardware event mapping. The current hardware pipeline requires the audited
ledger even for frozen-corpus rows. No handoff log was created.
