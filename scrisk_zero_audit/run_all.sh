#!/usr/bin/env bash
# Rebuild every SCRisk-zero audit output. Run from the repository root.
# Reads only the scored transcripts, the event returns and terms.jsonl.
# Writes only to the output directory.
#
# Four environment variables select which scoring run is audited.  With none
# set, this reproduces the original audit of ppmi_svd_full_20260910:
#
#   SCRISK_AUDIT_RUN         run directory holding the scored CSV and event returns
#   SCRISK_AUDIT_OUT         output directory
#   SCRISK_AUDIT_LIBRARY     terms.jsonl the run was scored with
#   SCRISK_AUDIT_VOCABULARY  v1_library_only or v2_seeds_inflections
set -euo pipefail
cd "$(dirname "$0")/.."
R="conda run -n dap-env python"
echo "auditing run: ${SCRISK_AUDIT_RUN:-artifacts/earnings_call_supply_chain/ppmi_svd_full_20260910}"
echo "vocabulary:   ${SCRISK_AUDIT_VOCABULARY:-v1_library_only}"
echo "output:       ${SCRISK_AUDIT_OUT:-outputs/scrisk_zero_audit}"
$R scrisk_zero_audit/dictionary_checks.py
$R scrisk_zero_audit/scan.py
$R scrisk_zero_audit/probe_detail.py
$R scrisk_zero_audit/probe_inflection.py
$R scrisk_zero_audit/content_integrity.py
$R scrisk_zero_audit/aggregate.py
$R scrisk_zero_audit/build_samples.py
$R scrisk_zero_audit/attribution.py
$R scrisk_zero_audit/seed_split.py
conda run -n dap-env python -m pytest scrisk_zero_audit -q
