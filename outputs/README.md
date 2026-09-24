# Generated outputs

Run `sh scripts/reproduce_fractional.sh` from the repository root to create
`fractional_reproduction_v1/`: five fractional figures, a five-page PDF, five
tables and covariance-aware comparisons. Existing run directories are never
overwritten. Pass a new output directory to repeat the command.

Published figures and corrected tables are retained in
[`docs/fractional_results/`](../docs/fractional_results/). Frozen comparison
inputs are in [`reproduction/fractional_v1/`](../reproduction/fractional_v1/).

Historical primary-event-study runs remain local because their scored-CAR
files, match audits, inspection records and manifests support provenance and
raw reconstruction. Their intermediate deterministic portfolio tables are
historical diagnostics. Superseded visualizations and redundant render copies
were deleted; recorded manifest paths and hashes were not rewritten.

Everything here except this README is ignored. Private source data belong in
the paths specified by `reproduction/fractional_v1/raw_inputs.json`.
