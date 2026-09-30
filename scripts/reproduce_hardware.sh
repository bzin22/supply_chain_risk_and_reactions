#!/bin/sh
# Offline analysis after installing pinned dependencies into an isolated venv.
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
"$PYTHON" -c 'import sys; assert sys.version_info[:3] == (3,14,7), "Use Python 3.14.7 (set PYTHON to its executable)"'
ENV_DIR="${HARDWARE_VENV:-.venv-hardware}"
"$PYTHON" -m venv "$ENV_DIR"
ENV_DIR="$(CDPATH= cd -- "$ENV_DIR" && pwd)"
"$ENV_DIR/bin/python" -m pip install --disable-pip-version-check -r requirements-hardware.lock
export MPLBACKEND=Agg
export MPLCONFIGDIR="${MPLCONFIGDIR:-$ENV_DIR/matplotlib}"
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-$ENV_DIR/cache}"
"$ENV_DIR/bin/python" -m pytest -q tests/test_hardware_reproduction.py tests/test_hardware_release_dates.py tests/test_primary.py tests/test_fractional_charts.py tests/test_scoring.py
"$ENV_DIR/bin/python" -m analysis.hardware_reproduction --output "${1:-outputs/hardware_baseline_reproduction_v1}"
