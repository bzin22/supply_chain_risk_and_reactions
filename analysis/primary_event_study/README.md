# Primary 2010–2019 event study

The sole transcript input is the immutable
`data/final/earnings_call_transcripts_validated_2010_2019_v1.csv`, SHA-256
`06d4620290b4b8a66f18a8762d5042968d4b436d4aef7009f6004d9d331eece3`.
Every input row remains in the derived call-level output. Transcript text is
not duplicated; `call_id`, source ordinal, and transcript hashes support a
lossless join to v1. Existing source data and staged changes are preserved.

## Scoring

Use exactly the 254 canonical supply-chain entries, 161 reconstructed risk
terms, and 55 conservative Resolution terms. No seeds, inferred inflections,
stemming, or alternate dictionaries are added. The approved tokenizer and
multiword matcher come from `calculate_supply_chain_transcript_scores.py`.
Every supply/risk occurrence pair at closest-token distance <=10 contributes
the supply term's `max_cosine`. Resolution counts that same pair only if a
Resolution occurrence is within 10 tokens of the supply occurrence. Overlap
and identical-span matches remain included and are audited.

Weighted sums are divided by tokenized transcript length, then divided by the
population SD across all valid v1 calls, without subtracting the mean. v1 has
already adjudicated transcript content: older scorer heuristics remain
diagnostic flags and do not discard short valid calls. Raw counts, weighted
sums, length-adjusted raw scores, standard deviations, standardized scores,
zero flags, dictionary paths/hashes, and every matched pair are retained.

These libraries reconstruct unpublished author inputs. The approved <=10
pair-count implementation is retained; the paper displays a strict <10
indicator formula. Outputs therefore reproduce the specified portfolio
construction with the repository's approved scoring specification, not an
exact reproduction of the authors' dataset or estimates.

## Dates and SIC

The primary **release-date run** follows the user's subsequent instruction:
"treat earnings release dates as the call dates." Use `--date-policy release`.
It sets `call_date = earnings_call_date` on every v1 row, including rows whose
date sources disagree. `confirmed_call_date` and its evidence remain audit
fields and no longer determine inclusion. No after-hours date shift is made.
`call_date_source_*` and `call_date_evidence` describe the selected release
date; original SEC live-call provenance is retained under
`confirmed_call_date_source_*` and `confirmed_call_date_evidence`.
The separate earlier strict-date run is preserved unchanged. Its policy below
remains available with `--date-policy confirmed`.

**v1's `earnings_call_date` is an earnings-release date**, per its build report
at commit `ae9526a`; it is not automatically a confirmed conference-call date.
The derived `reported_earnings_date` preserves that value, and `call_date` /
`confirmed_call_date` holds only the independently supported live-call date.
All original source-disagreement information remains present.

Cached SEC evidence is joined by CIK, fiscal quarter label, and provider ticker.
The evidence must identify the fiscal period, contain an explicit live
conference/earnings/results-call schedule, and pass its source-file SHA-256
check. Replay expiry, archives, analyst days, and generic investor webcasts
are not conference-call date evidence. Competing live dates remain unresolved.
The date must fall from one day before to seven days after the mapped release
date as an event-identity check; that window never supplies a date. Seven
records supply an explicit month/day whose year is corroborated by the mapped
release year; this method is separately labeled. Dates lacking sufficient
evidence remain excluded.

SIC comes from SEC quarterly Financial Statement Data Sets `sub.txt` and cached
full-filing headers. The cutoff is the observed fiscal period end, not a
calendar date manufactured from `quarter_label`. The latest filing on or
before that cutoff supplies four-digit SIC and the requested broad division.
Conflicting SICs on the latest filing date, missing fiscal ends, missing
historical evidence, and unassigned divisions remain explicit. This is a
conservative quarter-end point-in-time definition; it can miss changes between
quarter end and the call. Current issuer classifications are never backfilled.

SEC ZIP submission members are obtained by HTTP byte ranges. Original ranges,
the extracted member, URL, retrieval time, byte count, CRC verification and
SHA-256 values are retained under `artifacts/primary_event_study_2010_2019_v1`.
The 2026 retrieval uses reprocessed SEC datasets; the recorded filing date is
the historical information cutoff, not the retrieval date.

## Market model and portfolios

Price data are the archived and newly collected Alpha Vantage split/dividend-adjusted closes. Their
raw response hash, retrieval time, provider symbol and date coverage are
retained. Security mapping uses v1's CIK/security ID and the committed ticker
history at `ae9526a`. Ambiguous ticker reuse is excluded. Provider tickers are
not CRSP permanent identifiers; legacy symbol continuity remains a limitation.

Daily French Mkt-RF, SMB, HML, RF and momentum are parsed from the September 15,
2026 archive vintage, percentages converted to decimals. The FF calendar is
retained even if momentum is missing. Day 0 is the first market trading date
on or after `call_date` under the run's documented date policy, with no after-hours shift. The model is
OLS of stock excess return on an intercept and four factors, using exactly
200 observations at offsets -209 through -10. Missing observations never
shorten that window. CAR sums daily abnormal returns over 0–1 (2 days) and
2–60 (59 days). Both windows use the same fitted model. Coefficients, rank,
condition number, residual RMSE, R-squared, missing dates and statuses survive.

The common portfolio sample requires both CARs, valid scores, verified price
identity and assigned historical SIC. SCRisk, Resolution and both CARs are
winsorized globally at the linear 1st and 99th percentiles of this sample;
original values remain available. SCRisk ranks are within SIC division;
Resolution ranks are within SIC division × SCRisk quintile. All zero scores
are included. Ties use SHA256(`portfolio-ties-v1|call_id`) then `call_id`, never
returns. Quintiles are `floor(5 * zero_based_rank / stratum_size) + 1`.
Counts differ by at most one. Small strata retain all calls; empty quintiles
are explicitly reported when fewer than five observations are available.

Portfolio means give every call equal weight. The 95% intervals use a
one-way CIK-clustered standard error of the mean and t critical value with
G−1 degrees of freedom, holding portfolio assignments fixed. They do not
account for common-date dependence across firms or dictionary uncertainty.
They are descriptive intervals. No controlled outcome regressions are run.

## Reproduce

Use `conda run -n dap-env`. Long commands should be wrapped in `caffeinate -i`.
Run from the repository root:

```sh
conda run -n dap-env python -m analysis.primary_event_study.prepare metadata
conda run -n dap-env python -m analysis.primary_event_study.prepare sic-download --quarters 2009q4 2019q4
# Inspect the two downloaded source.json files and sub.txt schemas first.
conda run -n dap-env python -m analysis.primary_event_study.prepare sic-download
conda run -n dap-env python -m analysis.primary_event_study.prepare sic-history
conda run -n dap-env python -m analysis.primary_event_study.prepare dates
conda run -n dap-env python -m pytest analysis/primary_event_study/test_primary.py -q
caffeinate -i conda run --no-capture-output -n dap-env python -m analysis.primary_event_study.run pilot --output outputs/primary_event_study_new/pilot
# Inspect score matches, date evidence, SIC cutoffs, and event_day_audit.csv.
# Write the inspection findings to pilot/INSPECTED.md only after they pass.
caffeinate -i conda run --no-capture-output -n dap-env python -m analysis.primary_event_study.run full --output outputs/primary_event_study_new/full --pilot outputs/primary_event_study_new/pilot
```

An existing output directory is never overwritten. Full execution checks the
pilot, code/dictionary/auxiliary input hashes, and inspection record. Output
CSVs, compressed audit, plots, and source manifests carry reproducibility
hashes. The manifest rechecks the immutable v1 hash after execution.

For the supplied run, independent final verification and report delivery use:

```sh
conda run -n dap-env python analysis/verify_primary_event_study.py outputs/primary_event_study_2010_2019_v1/full
conda run -n dap-env python analysis/build_primary_event_study_report.py
```

The report builder attaches the inspected pilot and final verification to the
delivery manifest without changing any calculated data or figures. A separate
delivery manifest hashes all completed reports, source provenance, and data.

Reference: local Theile et al. (2026), Table 8, pp. 2991–2993;
[French factor library](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html);
[SEC Financial Statement Data Sets](https://www.sec.gov/data-research/sec-markets-data/financial-statement-data-sets).

### Release-date rebuild

`analysis.primary_event_study.collect_prices` fetches only v1 historical
tickers not present in the archived cache. Original responses are preserved.
The new cache is `artifacts/primary_event_study_release_dates_v1/prices`.
Four in-flight requests share a 1.1-second start interval; explicit provider
limits stop new requests. There is no artificial daily-call quota.

Run the deterministic pilot with `--date-policy release`, independently check
it with `python -m analysis.inspect_release_date_pilot <pilot-directory>`, and
record inspection before running `full` with the same policy and pilot path.
`--reuse-scores outputs/primary_event_study_2010_2019_v1/full` is optional:
it verifies v1, dictionary, scoring-code, prior dataset and match-audit hashes,
then reuses only raw score fields and their audits. Standardization, all CARs,
eligibility, winsorization, quintiles and figures are recomputed. The pilot
always scores the source transcripts afresh and compares to the reference.
