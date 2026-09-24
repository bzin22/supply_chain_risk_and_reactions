# Fractional reproduction validation

Validated on 2026-09-23 using an isolated Git feature checkout at
`/private/tmp/fractional-candidate-20260923` and a fresh Python 3.14.7 virtual
environment populated from `requirements-fractional.lock`. The interpreter
binary came from the local Python installation; its site-packages were not
inherited. Packages were independently installed from PyPI. Validation was on
macOS arm64; other operating systems have not been tested.

## Executed checks

- The documented `sh scripts/reproduce_fractional.sh` command completed in the
  clean checkout with `PYTHON` and `FRACTIONAL_VENV` pointing to the interpreter
  and fresh environment. No raw files, private output dataset, or original
  repository imports were available through the checkout.
- Clean tests: **69 passed, 16 skipped, zero failures**. Fifteen skips belong
  to legacy tests for a local provisional term library; one needs an optional
  private 500-call scored sample. All canonical dictionary, primary CAR,
  fractional allocation and covariance tests executed. The original working
  copy, where the provisional library exists, had 84 passed and one skip.
- All five tables match every published field to the historical ten-decimal
  CSV precision before correcting pooled Resolution call counts. Original
  winsorization thresholds, sample sizes and means/intervals are preserved.
- All five table CSVs and PNGs are byte-identical between the original Conda
  package environment and the clean PyPI environment. Covariance matrices and
  comparisons agree to floating-point tolerance: the largest observed numeric
  difference is about `1.01e-16`. This is an environment-to-environment check
  on the new outputs. It is not a comparison against the README images, which
  are 1650x1275 renders of the PDF at 150 dpi while the renderer writes
  1980x1530 pages at 180 dpi. No automatic PNG comparison to the historical
  images is performed or claimed.
- Regenerated PDF: all five pages rendered with Poppler and visually inspected.
  Axis labels, legends, confidence intervals, cell values and mass labels are
  visible without clipping. PDF timestamp bytes are not an equality target.
- `pip check` passed. Ruff `E9,F` passed on the nine new modules that are not
  hash-pinned, and `git diff --check` passed on those files. Two preserved
  results are expected and were not fixed. Running the same Ruff gate over all
  18 changed Python files reports 8 unused-import (F401) errors, all inside
  `analysis/primary_event_study/`, whose files are byte-pinned in
  `reproduction/fractional_v1/manifest.json` and matched their hashes at that
  revision. The later naming revision is documented below.
  Running `git diff --check` over the whole branch flags 13 lines in
  `reproduction/fractional_v1/historical/gate_counts.csv` and
  `winsorization_thresholds.csv` as trailing whitespace. That is the CRLF line
  ending `csv.DictWriter` writes, and those two CSVs are hash-pinned as well.
- All **2,215 private raw input hashes** matched in the authorized original
  workspace, including the frozen v1 corpus. The same preflight in the clean
  checkout correctly reported 2,215 missing private files.
- A deterministic 72-call sample was rescored from the private frozen
  transcripts using clean-checkout code, and its available 140 CAR values were
  recomputed with the pinned PyPI environment. Score and CAR comparisons all
  passed; maximum absolute errors were `8.88e-16` and `7.22e-16`, respectively.
  Selection: the first 72 ascending
  `SHA256("raw-reproduction-audit-v1|" + call_id)` values.
- The candidate's tracked-file inventory contains no transcript corpus, API
  response cache, archived raw files, or large daily-price data. The compact
  CSV's columns are explicitly allowlisted; the longest string is an
  87-character exclusion reason.

Allocation tests check per-call weight conservation, equal mass within each
SIC division, tie symmetry, row-order invariance, tiny strata, and preservation
of each SCRisk parent's weight by the nested Resolution allocation. Covariance
tests independently reconstruct firm score sums, preserve marginal SEs, check
positive semidefiniteness, produce zero comparison uncertainty for identical
memberships, and retain covariance for different calls from the same firm.

The corrected Resolution table has 46,123 unique calls in each of Q1-Q3,
47,408 in Q4 and 39,220 in Q5. Corresponding membership-row counts are 77,997,
77,997, 77,997, 79,282 and 71,086. Every portfolio has fractional mass 10,506.6.
These unique-call counts overlap and must not be summed.

## Limits and stages not rerun

The full 58,305-call raw scoring/CAR run was **not** repeated. Raw validation
here consists of source-hash inventory checks, the 72-call recomputation, and
synthetic scoring/CAR tests. Public clean-checkout reproduction begins from
the compact analysis dataset because private inputs are intentionally absent.
A fresh upstream transcript collection/adjudication build is not reproducible
from this snapshot alone. Auxiliary network retrieval and historical identity
coverage remain dependent on external services and private frozen inputs.

Remote push, pull request creation and hosted CI are outside this delivery.
The original repository's branch, index and pre-existing staged work were
preserved. Implementation and validation commits are retained on a separate
local feature branch.

## Changes after this validation run

The evidence above was recorded against candidate commit `4f35baf`. Follow-up
review changes are presentation only: the corrected tables were published into
`docs/fractional_results/`, the exporter's frozen reference tables moved from
`docs/fractional_results/` to `reproduction/fractional_v1/historical/` behind a
`--reference-tables` argument, and README and guide wording was corrected. No
analysis code, dictionary, packaged dataset, mean, standard error, interval,
date policy or threshold changed, and the reproduction command's assertions
against the frozen tables are unchanged. `reproduction/fractional_v1/manifest.json`
keeps the `exporter_sha256` of the exporter at `4f35baf`; nothing verifies that
field and every hash the command does verify still matches.

Machine-readable evidence: [`fractional_validation.json`](fractional_validation.json).

## Chart filename revision

Current filenames use `portfolio_charts_fractional_ties.pdf` and corresponding
names for the other variants. Original source snapshots, record snapshots,
artifact hashes and exact text replacements are retained in
[`provenance/fractional_naming_v1/`](../provenance/fractional_naming_v1/README.md).
Two active source files differ from the historical implementation only in
descriptive labels and output names. Both reproduction and export verify that
relationship explicitly; the frozen analysis package is unchanged.

The naming revision was tested in the working copy with the previously clean
pinned environment: **86 passed, 1 skipped** (the optional private sample).
All five tables, five panel PNGs, five page PNGs and two audit CSVs are
byte-identical to the preceding run. Covariance/comparison differences across
environments remain at most `1.01e-16`. The PDF is byte-identical after ignoring
its creation timestamp. A fresh export also passed and retained the dataset
and all packaged reference-file bytes. Ruff `E9,F` passed for the changed
reproduction, export, verification and test modules. This follow-up did not
repeat the full raw-input pipeline or create another clean checkout.

The current machine-readable validation record uses the new artifact names;
its original bytes are retained in the naming provenance. Artifact content
hashes are unchanged.

The subsequent output simplification removes covariance matrices, threshold
and zero-allocation CSVs, and the per-run manifest from generated output
directories. Their internal validation checks remain active. The 20 allocation
and covariance tests passed, and a fresh reproduction retained identical
figures, tables and comparison results (ignoring the PDF timestamp). Earlier
validation records describe the larger output set at the time of those runs.

## Integration with current `main` (2026-09-24)

The publish branch was assembled on GitHub `main`. The two top-level scripts
that changed in earlier merged work have exact historical snapshots and current
hashes under `provenance/fractional_main_integration_v1/`; the frozen package
was not rewritten. Five older scorer test fixtures were given an in-period
quarter so they satisfy the current input guard. Direct validation in the
isolated publish worktree passed **207 tests, with 29 skips**. A fresh compact
reproduction verified all five historical panels and retained 52,533 eligible
calls from 2,026 firms. The private raw scoring/CAR pipeline was not rerun.
