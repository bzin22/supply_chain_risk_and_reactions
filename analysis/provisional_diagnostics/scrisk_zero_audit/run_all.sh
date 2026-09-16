#!/usr/bin/env bash
# Rebuild every SCRisk-zero audit output. Runnable from anywhere.
# Reads only the scored transcripts, the event returns and terms.jsonl.
# Writes only to the output directory, which is not committed.
#
# Provisional diagnostic. It explains why this pipeline's SCRisk scores come
# out zero so often; it produces no paper-comparable result.
#
# Four environment variables select which scoring run is audited.  With none
# set, this reproduces the original audit of ppmi_svd_full_20260910:
#
#   SCRISK_AUDIT_RUN         run directory holding the scored CSV and event returns
#   SCRISK_AUDIT_OUT         output directory
#   SCRISK_AUDIT_LIBRARY     terms.jsonl the run was scored with
#   SCRISK_AUDIT_VOCABULARY  v1_library_only or v2_seeds_inflections
set -euo pipefail
cd "$(dirname "$0")/../../.."   # repository root
R="conda run -n dap-env python"
AUDIT=analysis/provisional_diagnostics/scrisk_zero_audit
echo "auditing run: ${SCRISK_AUDIT_RUN:-artifacts/earnings_call_supply_chain/ppmi_svd_full_20260910}"
echo "vocabulary:   ${SCRISK_AUDIT_VOCABULARY:-v1_library_only}"
echo "output:       ${SCRISK_AUDIT_OUT:-outputs/scrisk_zero_audit}"
$R "$AUDIT/dictionary_checks.py"
$R "$AUDIT/scan.py"
$R "$AUDIT/probe_detail.py"
$R "$AUDIT/probe_inflection.py"
$R "$AUDIT/content_integrity.py"
$R "$AUDIT/aggregate.py"
$R "$AUDIT/build_samples.py"
$R "$AUDIT/attribution.py"
$R "$AUDIT/seed_split.py"
conda run -n dap-env python -m pytest "$AUDIT" -q
