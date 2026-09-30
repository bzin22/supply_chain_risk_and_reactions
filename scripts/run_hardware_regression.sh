#!/bin/sh
# Offline regressions only; install analysis/hardware_regression_v1/requirements.lock separately.
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
export MPLBACKEND=Agg
export MPLCONFIGDIR="${MPLCONFIGDIR:-${TMPDIR:-/tmp}/hardware-regression-mpl}"
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1
"$PYTHON" -m analysis.hardware_regression_v1.run \
  --output "${1:-outputs/hardware_regression_v1}" \
  --audited-source "${2:-.}"
