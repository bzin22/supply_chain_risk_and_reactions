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
multiword matcher come from `scoring/calculate_supply_chain_transcript_scores.py`.
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

## Market model and downstream results

Adjusted closes include splits and dividends. The Carhart model fits an
intercept, market-minus-RF, SMB, HML and momentum over exactly 200 complete
trading observations at offsets -209 through -10. Factors are converted from
percent to decimal. Day 0 is the first factor-calendar trading day on or after
the selected event date, with no after-hours shift. CAR(0,1) sums two days;
CAR(2,60) sums 59 days. Missing data, coefficients, rank and every exclusion
remain in the audit outputs.

This package builds the upstream scored-CAR dataset and preserves the original
deterministic sorting code for historical reproducibility. Its intermediate
portfolio assignments are not the published fractional allocation. The final
results are built by `analysis.fractional_reproduction` using
`analysis/charts/fractional.py`; all scores, both CAR windows and the historical
SIC assignment must be valid. The reproduction guide specifies winsorization,
fractional nested portfolios and firm-clustered uncertainty.

## Reproduce

From the repository root:

```sh
sh scripts/reproduce_fractional.sh
```

See [the reproduction guide](../../docs/FRACTIONAL_REPRODUCTION.md) for the
pinned environment, private-input preflight and inspected pilot/full raw
commands. A full raw rebuild requires private frozen inputs and an actual
pilot inspection. Existing output directories and frozen inputs are never
overwritten. Use `python -m analysis.verify_primary_event_study <run-directory>`
for the historical raw-run audit, whose dependencies include private outputs.
The obsolete deterministic gallery/PDF builders have been removed.

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
