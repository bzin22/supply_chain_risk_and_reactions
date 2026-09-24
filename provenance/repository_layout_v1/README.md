# Repository layout and cleanup — 2026-09-24

The current entry point is `sh scripts/reproduce_fractional.sh` from the
repository root. The README contains the compact directory guide. This record
explains this reorganization; it is not a cumulative activity log.

## Dependency and retention decisions

- Portable reproduction uses the compact analysis dataset, frozen tables,
  canonical dictionaries, fractional allocation/renderer and clustered
  covariance module. Its shell entry point also tests scoring, CARs and dates.
- Raw rebuilding uses the immutable v1 transcripts, the 2,215-file input
  inventory, `analysis/primary_event_study/`, the shared scorer and factor
  parser. Historical deterministic sorting remains an upstream audit stage;
  only fractional figures are published in active documentation.
- Dictionary corpus/model construction and outcome-blind sensitivity/review
  records stay together under `dictionaries/`. The earlier library builder and
  zero/vocabulary diagnostics remain as methodological records.
- Raw responses, original corpora, frozen datasets, historical scored-CAR
  datasets, audits, manifests, price/factor vintages, staged dictionary work
  and collection review plans were retained. Large raw/evidence directories
  dominate the roughly 77 GB local workspace; untracked status was never a
  deletion criterion.

[`inventory.json`](inventory.json) records directory counts/sizes, imports and
entry-point dependencies. [`manifest.json`](manifest.json) maps each relocation
and pins exact edits to historically verified code. Its source snapshots are
necessary code provenance. Original naming records, raw-input paths and frozen
package manifests were not rewritten. Recorded paths to deleted generated
visualizations describe the historical run, not current files.

## Relocations

| Original path | Current path |
| --- | --- |
| `extract_earnings_call_transcript_data.py` | `collection/extract_earnings_call_transcript_data.py` |
| `collect_earnings_event_inputs.py` | `collection/collect_earnings_event_inputs.py` |
| `join_earnings_event_dates.py` | `collection/join_earnings_event_dates.py` |
| `calculate_supply_chain_transcript_scores.py` | `scoring/calculate_supply_chain_transcript_scores.py` |
| `join_supply_chain_scores_to_segments.py` | `scoring/join_supply_chain_scores_to_segments.py` |
| `calculate_carhart_event_returns.py` | `analysis/calculate_carhart_event_returns.py` |
| `build_supply_chain_library.py` | `dictionaries/build_supply_chain_library.py` |
| `analysis/build_modified_portfolio_chart_pdfs.py` | `analysis/charts/fractional.py` |
| `analysis/retry_primary_price_responses.py` | `collection/retry_primary_price_responses.py` |
| `test_calculate_supply_chain_transcript_scores.py` | `tests/test_scoring.py` |
| `analysis/test_fractional_reproduction.py` | `tests/test_fractional_reproduction.py` |
| `analysis/test_modified_portfolio_chart_pdfs.py` | `tests/test_fractional_charts.py` |
| `analysis/primary_event_study/test_primary.py` | `tests/test_primary.py` |
| `analysis/provisional_diagnostics/scrisk_zero_audit/test_scrisk_zero_audit.py` | `tests/test_zero_audit.py` |
| `dictionaries/theile_reconstruction_v1/supply_chain/test_supply_chain_reconstruction.py` | `tests/test_dictionary_reconstruction.py` |
| `earnings_call_transcripts.csv` | `data/provisional/earnings_call_transcripts.csv` |
| `earnings_call_transcript_segments.csv` | `data/provisional/earnings_call_transcript_segments.csv` |
| `source_research_paper/theile-et-al-2026-supply-chain-risk-and-resolution-an-empirical-study-of-stock-market-reactions.pdf` | `docs/references/theile-et-al-2026-supply-chain-risk-and-resolution-an-empirical-study-of-stock-market-reactions.pdf` |

Scoring, CAR and fractional calculations are unchanged. All 11 retained chart
functions have identical Python ASTs before and after the move. The removed
chart functions served deterministic/positive-only variants and the obsolete
two-variant command. The supported renderer is invoked through the portable
reproduction command. It now removes its duplicate raster-page intermediates
after saving the five named PNGs, leaving exactly 12 output files. Import paths, subprocess paths, CLI examples and tests
were updated; obsolete gallery/PDF builders were deleted.

## Deletions and recovery

Deleted **265 files**, **100,649,049 logical bytes** (101,212,160 allocated bytes before deletion). These are gross removals; new provenance and verification outputs use some space. Filesystem snapshots, compression and shared extents can affect physical free space.

Targets were runtime caches, an old spreadsheet inspection dump, superseded
deterministic/positive-only figures and galleries, duplicate fractional
renders, temporary README previews and two obsolete visualization builders.
No original raw response, corpus, immutable dataset or required methodological
record was deleted. [`deletions.json`](deletions.json) records each target,
reason, size and pre-deletion content hash.

All targets were untracked in the starting working tree. Two builders have
byte-identical reachable Git blobs (IDs are recorded in the manifest):
`analysis/build_primary_event_study_report.py` and
`analysis/build_portfolio_charts_pdf.py`. Their bytes are recoverable with
`git cat-file blob <recorded-blob-id>`. The other **263** untracked generated
files/caches had no matching reachable Git object and were removed without
archival copies; regenerability is distinct from recovery of exact old bytes.
Tracked files moved out of the root remain recoverable at their historical
paths in Git. The existing index and branch were not changed.

## Verification

Machine-readable outcomes: [`verification.json`](verification.json). Storage
measurement: [`storage.json`](storage.json), approximately 98 MB net reclaimed
after new provenance and verification outputs.

- The documented shell command succeeded in the working repository and an
  isolated portable source copy without raw data, caches or private outputs,
  using Python 3.14.7 and the previously installed pinned environment. This is
  a source-copy check, not a new Git commit or a fresh dependency-install test.
- Main command: 87 tests passed, one optional private smoke test skipped.
  Isolated command: 72 passed, 16 skipped for absent optional legacy inputs.
  The broader local suite passed 120 tests with seven optional-input skips.
- All five regenerated PNGs and six CSVs are byte-identical to the pre-layout
  renderer rerun in the same environment and to the isolated source copy.
  All five corrected tables match the published tables byte for byte. All
  historical table fields, thresholds, masses and code/dictionary hashes pass.
  The result remains 52,533 eligible calls from 2,026 firms. PNG bytes are not
  identical to every older local run; this check isolates code changes using
  the same current renderer environment. Published figure bytes are untouched.
- A fresh export matches all 13 packaged reference/input file hashes; all
  nine moved/related CLI help entry points succeed. `pip check` and
  `git diff --check` pass.
- All 2,215 private input hashes match. The frozen package, canonical
  dictionaries, historical provenance and published figures/tables retain
  their original bytes. The two provisional CSVs were moved without changes.
- Ruff E9/F passes with the documented pre-existing unused-import exception
  for the retained primary package. Current README/guide links and fractional
  image references were checked. Five regenerated panels were visually
  inspected for titles, labels, legends, values and clipping.

The full raw collection, corpus/model training and 58,305-call raw scoring/CAR
run were not repeated. The older validation record remains historical.
No commit, push, remote PR or hosted CI was performed. The no-mistakes pipeline
was inspected but not started: it validates committed feature-branch history,
whereas this cleanup preserves the existing dirty branch and staged index.
