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
"$ENV_DIR/bin/python" -m pytest -q analysis/test_fractional_reproduction.py analysis/test_modified_portfolio_chart_pdfs.py analysis/primary_event_study/test_primary.py test_calculate_supply_chain_transcript_scores.py
"$ENV_DIR/bin/python" -m analysis.fractional_reproduction --output "${1:-outputs/fractional_reproduction_v1}"
