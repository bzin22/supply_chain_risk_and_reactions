# Compact hardware regression references

These files contain derived observations from the public corrected hardware
baseline, not raw transcripts or daily prices. The regression rerun loads
`reproduction/hardware_baseline_v1` through its audited loader; it does not use
these references as substitute inputs.

- `sample_ids.csv.gz`: stable call IDs, historical CIK, adjudicated fiscal period,
  event date/calendar quarter, and main/robustness inclusion flags.
- `regression_sample.csv.gz`: one equal-weighted row per call, original scaled
  scores, once-winsorized scores/CAR, and percentage-point outcome.
- `M3_call_diagnostics.csv.gz`: residuals, leverage and Cook's diagnostic. The two
  unit-leverage singleton calls have undefined Cook's distance, retained missing.
- `manifest.json`: hashes of these references, published results, regression code,
  and the original baseline manifest.

CIKs and call IDs are strings. `included_M1_M2_M3` identifies the identical 11,950
calls; `included_R1` removes 355 adjudicated fiscal-2010 calls. Zeros remain zero.
No supplier-dependence variable or fractional membership rows are included.

[Results and limitations](../../docs/hardware_regression_v1/REPORT.md) ·
[Offline rerun](../../analysis/hardware_regression_v1/README.md)
