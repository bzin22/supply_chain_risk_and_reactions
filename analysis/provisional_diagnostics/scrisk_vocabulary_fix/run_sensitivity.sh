#!/usr/bin/env bash
# Score the four SCRisk sensitivity variants and their event returns.
# Runnable from anywhere.  Writes only under the v2 run directory.
#
# Provisional diagnostic.  The variants measure how much of this pipeline's
# SCRisk score rests on two arguable vocabulary properties.  They are not
# paper-comparable: the dictionaries, universe and period all differ.
#
# Each variant changes exactly one thing against the corrected default
# (v2_seeds_inflections, window 10, integrity filter on).  Nothing here is a
# methodology change; these exist so the two arguable vocabulary properties
# can be measured instead of assumed.
set -euo pipefail
cd "$(dirname "$0")/../../.."   # repository root
R="conda run -n dap-env python"
VOCAB=analysis/provisional_diagnostics/scrisk_vocabulary_fix
R1=artifacts/earnings_call_supply_chain/ppmi_svd_full_20260910
R2=artifacts/earnings_call_supply_chain/ppmi_svd_full_20260910_vocab_v2
LIB=artifacts/sec_10k_supply_chain/experiments/ppmi_svd_full_20260910/terms.jsonl
TMP="${CLAUDE_JOB_DIR:-/tmp}/tmp"
mkdir -p "$TMP"

run_variant () {
  local name="$1"; shift
  local out="$R2/sensitivity/$name"
  mkdir -p "$out"
  echo "=== $name: $* ==="
  $R calculate_supply_chain_transcript_scores.py \
    --input earnings_call_transcripts.csv --library "$LIB" \
    --vocabulary-version v2_seeds_inflections \
    --output "$TMP/$name.csv" "$@"
  $R "$VOCAB/compact_scores.py" "$TMP/$name.csv" "$out/transcript_scores.csv"
  cp "$TMP/$name.csv.scoring_manifest.json" "$out/scoring_manifest.json"
  $R calculate_carhart_event_returns.py \
    --segments "$R1/earnings_call_transcript_segments_scored_with_event_dates.csv" \
    --event-date-column event_date \
    --supply-chain-scores "$TMP/$name.csv" \
    --prices "$R1/event_study_inputs/adjusted_close_prices.csv" \
    --factors "$R1/event_study_inputs/fama_french/fama_french_daily.zip" \
    --momentum "$R1/event_study_inputs/fama_french/momentum_daily.zip" \
    --output "$out/event_returns.csv"
  rm -f "$TMP/$name.csv" "$TMP/$name.csv.scoring_manifest.json"
}

# shortage/shortages sit in both vocabularies, so one word pairs with itself.
run_variant no_self_pairs --forbid-identical-span-pairs
run_variant no_shortage_family --exclude-supply-chain-terms shortage,shortages
# customers is the weakest of the 16 seeds and the most common word in either.
run_variant no_customer_family --exclude-supply-chain-terms customer,customers
run_variant no_shortage_no_customer \
  --exclude-supply-chain-terms shortage,shortages,customer,customers
echo "All four sensitivity variants written under $R2/sensitivity"
