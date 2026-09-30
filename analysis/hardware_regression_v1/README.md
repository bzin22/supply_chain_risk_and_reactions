# Hardware regression extension

This planned analysis follows descriptive exploration; it is not preregistered.
[PLAN.md](PLAN.md) and the [initial specification lock](initial_specification_lock.json)
record the specifications before the first coefficient estimation. The outcome is
100 times once-winsorized CAR(0,1); the common sample is 11,950 calls from 378 firms.

- M1: intercept and continuous SCRisk.
- M2: M1 plus continuous Resolution.
- M3, primary: SCRisk and Resolution plus firm and event-calendar quarter effects.
- R1: M3 excluding adjudicated issuer fiscal year 2010, retaining original scaling
  and clipping thresholds.

[Results and limitations](../../docs/hardware_regression_v1/REPORT.md) ·
[Paper-ready PDF](../../docs/hardware_regression_v1/regression_table.pdf) ·
[Full-precision CSV](../../docs/hardware_regression_v1/regression_results.csv) ·
[Call-level audit files](../../reproduction/hardware_regression_v1/README.md)

## Run offline

Install the pinned regression dependencies once in a separate environment
(original run: Python 3.12.13):

```sh
python3.12 -m venv .venv-hardware-regression
.venv-hardware-regression/bin/python -m pip install -r analysis/hardware_regression_v1/requirements.lock
```

Then use this single rerun command from the repository root:

```sh
PYTHON=.venv-hardware-regression/bin/python sh scripts/run_hardware_regression.sh outputs/hardware_regression_v1
```

Choose a new output directory for subsequent runs. The command refuses to
overwrite an existing directory and makes no network requests. Dependency
installation requires package access, but no transcript, price or SEC collection
occurs. No transcript scoring, CAR estimation or fractional chart generation runs.

The unchanged audited hardware loader verifies the baseline manifest, method
equivalence, dictionaries, date adjudications and unique call IDs. The extension
copies its exact public dependencies into a local output snapshot before loading,
then saves call IDs, transformed values, covariance matrices and fingerprints.
The snapshot is generated locally, not duplicated in Git. A clean checkout
contains every required manifest-matching source. If working-tree sources differ,
an optional second script argument supplies a preserved audited checkout; only
exact expected hashes are accepted, and baseline data mismatches always fail.
No private transcript or price file is read or copied.

`estimate.py` uses alternating projection/FWL and CR1 and independently verifies
each model using statsmodels OLS with explicit dummies. `inputs.py` handles source
verification and the one-time baseline transformation. `run.py` preserves the
initial specification lock and writes sample IDs before fitting. `report.py`
generates the tables without editing the paper.

## Check the extension

```sh
.venv-hardware-regression/bin/python -m pytest -q tests/test_hardware_regression.py
```

Reference-data tests run without generated outputs; the completed-run integration
test additionally runs when the default output directory exists. Tests cover
score units, zeros, one-time winsorization, calendar/fiscal distinctions,
unbalanced fixed effects, the independent covariance calculation, singleton
handling and baseline preservation. Published compact references are checked by
their manifest. The existing corrected baseline, dictionaries and fractional
figures are unchanged by this extension.
