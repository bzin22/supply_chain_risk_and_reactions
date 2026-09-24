#!/bin/sh
# From a checkout: sh scripts/reproduce_fractional.sh [new-output-directory]
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
"$PYTHON" -c 'import sys; assert sys.version_info[:3] == (3,14,7), "Use Python 3.14.7 (set PYTHON to its executable)"'
ENV_DIR="${FRACTIONAL_VENV:-.venv-fractional}"
"$PYTHON" -m venv "$ENV_DIR"
ENV_DIR="$(CDPATH= cd -- "$ENV_DIR" && pwd)"
"$ENV_DIR/bin/python" -m pip install --disable-pip-version-check -r requirements-fractional.lock
export MPLBACKEND=Agg
export MPLCONFIGDIR="${MPLCONFIGDIR:-$ENV_DIR/matplotlib}"
"$ENV_DIR/bin/python" -m pytest -q tests/test_fractional_reproduction.py tests/test_fractional_charts.py tests/test_primary.py tests/test_scoring.py
"$ENV_DIR/bin/python" -m analysis.fractional_reproduction --output "${1:-outputs/fractional_reproduction_v1}"
