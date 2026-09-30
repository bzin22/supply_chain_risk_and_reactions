# Publication validation

The isolated checkout started from PR #8 at
`a82c7d144dc43b291e982299b405c9d88dce5d72`. The regression extension was added
without changing the corrected baseline package, dictionaries or fractional
figures. Every one of the 263 original baseline manifest entries still matches.
The working checkout needs no source recovery or private inputs.

- Offline rerun: 11,950 calls, 378 firms; no additional complete-case exclusions;
  all four models agree with independent explicit-dummy coefficients and CR1
  covariance. Sample IDs, transformed observations and diagnostics reproduce
  the initial completed run byte-for-byte; coefficients and covariance are unchanged.
- Full test suite: **234 passed, 29 skipped**. Nine tests cover the new regression
  extension, including the compressed reference hashes and rerun parity. Skips
  require private or locally generated artifacts absent from a public checkout.
- All 27 pinned regression-environment packages pass dependency compatibility
  checks. Nonfatal third-party deprecation warnings do not affect the estimates.
- Ruff E9/F and `git diff --check` pass. No new source collection, scoring, CAR estimation,
  supplier interaction, CAR(2,60) regression or baseline chart overwrite occurs.
- The paper-ready PDF is one page and was visually checked. Its table is generated
  from the same full-precision estimates as the CSV and LaTeX source.

`clean_checkout_fingerprints.json` identifies the code, environment and generated
output hashes for this validation run; `clean_checkout_input_audit.json` confirms
zero manifest mismatches. Its git-head field names the checkout's parent before
this extension was committed, while code hashes identify the added code exactly.
The output hash entries refer to a complete regenerated local output directory;
large CSVs are committed compressed under `reproduction/hardware_regression_v1`.
That directory's manifest hashes the public compact files and review artifacts.

Commands used (with the pinned Python 3.12.13 regression environment):

```sh
PYTHON=/path/to/python sh scripts/run_hardware_regression.sh outputs/hardware_regression_v1
python -m pytest -q -p no:cacheprovider
uv pip check --python /path/to/python
git diff --check
```

Direct repository checks were used; no-mistakes was not run. GitHub PR #8 has no
hosted CI checks configured. This update is for review and does not merge the PR.
