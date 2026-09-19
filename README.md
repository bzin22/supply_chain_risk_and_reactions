# Supply chain risk and earnings call returns: recreation in progress

This repository is an in-progress 2010-2019 comparison with Theile et al. (2026),
"Supply Chain Risk and Resolution: An Empirical Study of Stock Market
Reactions." It is not a replication yet. Nothing here has been shown to match
the paper.

The pipeline runs end to end and produces numbers. Those numbers are not
comparable to the paper's, for the reasons listed under
[Known methodological gaps](#known-methodological-gaps). Treat every figure
and table this code produces as a diagnostic on the code, not as a finding
about markets.

## What the recreation targets

The paper measures how the stock market reacts when a firm talks about supply
chain risk, and about resolving it, on an earnings call. The recreation builds
the same shape of study:

1. Score each earnings call transcript for supply chain risk (SCRisk) and for
   resolution language.
2. Estimate the cumulative abnormal return (CAR) around the call, meaning the
   stock's return minus what a factor model says it should have returned.
3. Relate the score to the CAR.

## Core pipeline

Seven scripts, in order. Each writes a new file and never edits its input in
place. All of them take explicit paths.

| Stage | Script | What it does |
| --- | --- | --- |
| 1 | `build_supply_chain_library.py` | Builds a supply-chain term library from SEC 10-K filings. Writes `terms.jsonl`. |
| 2 | `extract_earnings_call_transcript_data.py` | Fetches Alpha Vantage earnings call transcripts and speaker metadata for an explicit firm universe. `--input` is required. |
| 3 | `calculate_supply_chain_transcript_scores.py` | Scores each call for SCRisk and Resolution using the 161-term risk reconstruction and the 55-term resolution reconstruction by default. |
| 4 | `collect_earnings_event_inputs.py` | Collects event dates, adjusted closes, and Fama-French / momentum factors, with raw provider payloads and a provenance manifest. |
| 5 | `join_earnings_event_dates.py` | Attaches the collected event date to each call. |
| 6 | `join_supply_chain_scores_to_segments.py` | Attaches call-level scores to every transcript segment of that call. |
| 7 | `calculate_carhart_event_returns.py` | Estimates Carhart four-factor abnormal returns and writes the event-level dataset with `CAR_0_1`. |

Run them in `dap-env`:

```
conda run -n dap-env python <script>.py --help
```

Stage 7's estimation window is 200 trading days, event day -209 through -10.
`CAR_0_1` is the sum of the day-0 and day-1 abnormal returns.

## Known methodological gaps

Every item below is a known difference from the paper. None is fixed. This
list is the gate: until each line is closed, no output of this repository can
be described as a replication result.

| Gap | Current state | Paper-equivalent target |
| --- | --- | --- |
| Risk dictionary | High-confidence 161-term reconstruction: 144 Table 3 terms plus 17 reconstructed non-occurring terms | The unpublished author-original dictionary |
| Resolution dictionary | 55-term reconstruction: the 28 distinct Table 4 keywords plus Oxford-printed forms | The unpublished author-original dictionary |
| Supply chain vocabulary | Generated from 10-K text by `build_supply_chain_library.py`, a different vocabulary | The paper's supply chain word list |
| Event dates | Reported earnings dates, led by Alpha Vantage EARNINGS `reportedDate` and mapped to transcript fiscal quarters | The paper's validated actual call dates |
| Firm universe | Versioned public-source point-in-time universe with 151,073 US-domiciled resolved firm-quarters | A proprietary historical security master matching the paper's rules |
| Sample period | Hard-bounded to 2010Q1 through 2019Q4 | The paper begins in 2008; this comparison deliberately begins in 2010 |
| Industry grouping | Current SEC SIC with historical changes unresolved | Point-in-time SIC codes |
| Quintiles | Zero-score calls in their own group, quintiles cut within positive scores only | Quintiles over the whole analysable sample |
| Outlier handling | None | 1% / 99% winsorization |
| Regression | None. Only group means and medians | The paper's fixed-effects specification |

## Where things live

Four kinds of file, kept apart on purpose.

**Source data.** Provider responses, SEC filings, prices, factor files,
manifests, hashes, and provenance records. All local and all gitignored:
`artifacts/`, `earnings_call_transcripts.csv`,
`earnings_call_transcript_segments.csv`. Never deleted by a cleanup. Large:
`artifacts/` alone is about 31 GB.

**Local artifacts.** Anything a script generates. Lands in `outputs/`, which
is gitignored except for its README. Regenerate, do not commit. See
`outputs/README.md`.

**Diagnostics.** Code that explains why the pipeline behaves as it does, not
code that produces study results. Lives in
`analysis/provisional_diagnostics/`. Each script takes an explicit run
directory and output directory. See that directory's README.

**Validated transcript corpus.** The immutable local v1 corpus is
`data/final/earnings_call_transcripts_validated_2010_2019_v1.csv`, with its
SHA-256 companion and manifest beside it. It contains 58,305 dated calls. The
file is an input to later scoring and event-study work, not a replication
result. The 2.2 GB CSV is excluded from Git; the checksum, manifest, build code,
and validation report are versioned.

Provisional inputs that are not the paper's are quarantined in
`data/provisional/` with their provenance written down.

The primary risk dictionary is
`dictionaries/theile_reconstruction_v1/risk/risk_terms_reconstructed_full.txt`.
It is a source-based reconstruction, not the unpublished author-original file.
The scorer requires exactly 161 unique lowercase terms and records the selected
file, SHA-256, term counts, and primary/override status in every scoring manifest.
`--risk-words` remains available only as an explicit non-primary development
override. The 144-term observed file is retained as provenance and is not used
by the primary scoring path.

The primary resolution dictionary is
`dictionaries/theile_reconstruction_v1/resolution/resolution_terms_conservative_baseline.txt`.
It is a source-based reconstruction of the paper's resolution library, not the
unpublished author-original file. The scorer requires exactly 55 unique
lowercase terms, emits one Resolution measure from that one file, and records
the selected file, SHA-256, term counts, and primary/override status in every
scoring manifest. `--resolution-words` is an explicit non-primary development
override. The anchor, expanded and overlap-adjusted files beside it are
predeclared sensitivity artifacts and are never a default. The overlap between
the resolution dictionary and the supply-chain vocabulary is deliberately left
open until the reconstructed supply-chain vocabulary exists.

## Hard study-period boundary

The only study period is `2010Q1` through `2019Q4`. The collector exposes no
runtime start/end-quarter options; changing the period requires a reviewed
code change to `study_period.py`. Scoring, date joining, event-input
collection, segment joining, and CAR estimation reject any input observation
outside that boundary.

Run the active-data gate with:

```
conda run -n dap-env python verify_active_study_period.py
```

The 2020-2024 material removed on 2026-09-16 is recoverable under the
gitignored `.archive/post_2019_removed_20260916/` tree. Its row- and file-level
checksums and removal report are under `provenance/post_2019_removal_20260916/`.

## Historical universe and bounded coverage work

The versioned public-source universe is built with:

```
conda run -n dap-env python build_historical_universe.py capture
conda run -n dap-env python build_historical_universe.py sec-metadata
conda run -n dap-env python build_historical_universe.py build
```

Its active tables are under
`data/universe/us_operating_companies_v20260916/`. Historical membership and
ticker intervals come from 40 quarter-end Alpha Vantage listing snapshots;
SEC CIK and issuer metadata provide identity and SIC corroboration. Unresolved
identities are retained for review but excluded from transcript request inputs.
The active resolved universe has 151,073 firm-quarters; preferred shares and
other non-common securities are excluded by both name and ticker-form rules.

The representative coverage sample is deterministic and capped at 800
firm-quarters:

```
conda run -n dap-env python sample_representative_coverage_pilot.py
conda run -n dap-env python collect_transcript_pilot.py \
  --universe data/pilot/representative_coverage_pilot_v20260916/eligible_firm_quarters.csv \
  --output-dir artifacts/representative_coverage_pilot_v20260916
```

This command is a bounded pilot, not authority to collect the complete
universe. The full transcript collection remains gated on review of the pilot.

The canonical corpus uses the reported earnings date as `earnings_call_date`.
Alpha Vantage EARNINGS `reportedDate` is preferred; Yahoo Finance and targeted
earnings-history sources fill gaps. Rows are matched to fiscal periods, not by
the calendar quarter containing the report date. The corpus excludes 467 calls
without a mapped reported date and quarantines 208 calls with unresolved ticker
reuse. Source disagreement remains explicit in the date-status fields. These
dates are not asserted to be independently verified conference-call dates.

## The rule about charts and findings

Do not present a chart, table, or empirical claim from this repository as a
replication result until the paper-alignment gaps above pass. A committed
chart reads as a result. Label anything produced now as provisional, say which
gap it is downstream of, and keep it out of version control.

## Tests

```
conda run -n dap-env python -m pytest -q
```

Tests that need a local artifact (the term library, a scored sample, a
generated audit CSV) skip when it is absent rather than fail. That is why a
clean checkout reports skips.
