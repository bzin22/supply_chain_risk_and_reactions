# Supply chain risk and earnings call returns: recreation in progress

This repository is an in-progress attempt to recreate Theile et al. (2026),
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
| 3 | `calculate_supply_chain_transcript_scores.py` | Scores each call for SCRisk and Resolution using the high-confidence 161-term risk reconstruction by default. |
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
| Resolution dictionary | Provisional starter list defined in `calculate_supply_chain_transcript_scores.py` | The paper's resolution dictionary |
| Supply chain vocabulary | Generated from 10-K text by `build_supply_chain_library.py`, a different vocabulary | The paper's supply chain word list |
| Event dates | Proxy dates from the Alpha Vantage `EARNINGS` `reportedDate` | The paper's call dates |
| Firm universe | Provisional 450-company convenience sample, 9 sectors (`data/provisional/`) | The paper's historical US-company universe |
| Sample period | 2010Q1 to 2024Q4 as currently configured | The paper's period |
| Industry grouping | yfinance sector and industry labels | SIC codes |
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

**Validated results.** None exist. When the gaps above are closed, validated
results get their own clearly named directory and are committed with the
checks that passed.

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
