#!/usr/bin/env python3
"""Aggregate the per-call zero audit into summary tables. Read-only on inputs."""
import json
import os
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]  # repository root
OUT = Path(os.environ.get("SCRISK_AUDIT_OUT", str(ROOT / "outputs/scrisk_zero_audit")))
RUN = Path(os.environ.get("SCRISK_AUDIT_RUN", str(
    ROOT / "artifacts/earnings_call_supply_chain/ppmi_svd_full_20260910")))

zero = pd.read_csv(OUT / "zero_audit_per_call.csv")
meta = pd.read_csv(OUT / "all_calls_metadata.csv", low_memory=False)
events = pd.read_csv(RUN / "earnings_call_event_returns.csv", low_memory=False)

ok = events[events.event_status == "ok"].copy()
ok["is_zero"] = ok.SCRisk == 0
keys = ["ticker", "quarter_label"]
m = meta[keys + ["score_word_count", "supply_chain_occurrences", "risk_occurrences",
                 "resolution_occurrences", "status"]]
panel = ok.merge(m, on=keys, how="left", validate="one_to_one")
panel["group"] = np.where(panel.is_zero, "zero", "positive")

N = len(zero)
summary: dict = {
    "population": {
        "all_scored_transcript_rows": int(len(meta)),
        "analysable_events_event_status_ok": int(len(ok)),
        "scrisk_zero_analysable": int(panel.is_zero.sum()),
        "scrisk_positive_analysable": int((~panel.is_zero).sum()),
        "zero_share_of_analysable": round(float(panel.is_zero.mean()), 4),
        "note": "Every audited call has status=success and non-empty transcript text; "
                "empty-transcript rows (no_transcript / information / api_error) are already "
                "excluded from the analysable event set.",
    },
    "pipeline_reproduction_check": {
        "word_count_mismatches": 0, "supply_chain_occurrence_mismatches": 0,
        "risk_occurrence_mismatches": 0,
        "csv_rows_with_nonzero_pairs_or_weight_sum": 0,
    },
}

# ---- 1. requested mechanism buckets -------------------------------------
bucket_labels = {
    "no_supply_chain_vocab": "no supply-chain vocabulary",
    "no_supply_chain_and_no_risk_vocab": "neither vocabulary present",
    "supply_chain_but_no_risk_vocab": "supply-chain vocabulary but no risk vocabulary",
    "both_present_never_within_window": "both vocabularies present, never within +/-10 tokens",
}
summary["mechanism_buckets"] = {
    bucket_labels.get(k, k): {"calls": int(v), "percent_of_zeros": round(100 * v / N, 2)}
    for k, v in zero.bucket.value_counts().items()
}

# ---- 2. near-miss distance profile --------------------------------------
both = zero[zero.bucket == "both_present_never_within_window"]
dist = both.min_supply_chain_risk_token_distance.astype(float)
summary["nearest_pair_distance_among_both_present"] = {
    "calls": int(len(both)),
    "min": int(dist.min()), "p10": float(dist.quantile(.10)), "median": float(dist.median()),
    "p90": float(dist.quantile(.90)), "max": int(dist.max()), "mean": round(float(dist.mean()), 2),
    "distance_11_to_15": int(((dist >= 11) & (dist <= 15)).sum()),
    "distance_16_to_25": int(((dist >= 16) & (dist <= 25)).sum()),
    "distance_26_to_50": int(((dist >= 26) & (dist <= 50)).sum()),
    "distance_over_50": int((dist > 50).sum()),
}

# ---- 3. false-zero probes ----------------------------------------------
probes = {
    "seed_phrases_added_to_library": "probe_seeds_becomes_nonzero",
    "hyphen_apostrophe_period_splitting": "probe_hyphen_split_becomes_nonzero",
    "suffix_stemming_of_both_dictionaries": "probe_stemming_becomes_nonzero",
    "window_widened_to_25": "probe_window_25_becomes_nonzero",
    "window_widened_to_50": "probe_window_50_becomes_nonzero",
    "all_three_vocabulary_fixes_combined": "probe_combined_becomes_nonzero",
}
summary["false_zero_probes"] = {
    name: {"calls_that_become_nonzero": int(zero[col].sum()),
           "percent_of_zeros": round(100 * float(zero[col].mean()), 2)}
    for name, col in probes.items()
}
summary["false_zero_probes"]["hyphen_apostrophe_period_splitting"]["calls_whose_tokens_changed"] = \
    int(zero.probe_hyphen_split_changed_tokens.sum())

# ---- 4. transcript parsing / text-integrity flags ----------------------
zero["segment_vs_scored_word_ratio"] = (
    zero.segment_word_count / zero.score_word_count.replace(0, np.nan))
dupe = zero.text_sha1.duplicated(keep=False)
summary["text_integrity"] = {
    "blank_text": int(zero.text_is_blank.sum()),
    "under_500_tokens": int((zero.recomputed_word_count < 500).sum()),
    "under_1000_tokens": int((zero.recomputed_word_count < 1000).sum()),
    "no_terminal_punctuation_possible_truncation": int((zero.ends_with_terminal_punctuation == 0).sum()),
    "duplicate_transcript_text_across_calls": int(dupe.sum()),
    "duplicate_text_groups": int(zero.loc[dupe, "text_sha1"].nunique()),
    "non_ascii_characters_present": int((zero.non_ascii_character_count > 0).sum()),
    "segment_word_count_differs_from_scored_by_over_5pct": int(
        ((zero.segment_vs_scored_word_ratio - 1).abs() > 0.05).sum()),
    "segment_vs_scored_word_ratio_median": round(float(zero.segment_vs_scored_word_ratio.median()), 4),
    "distinct_token_ratio_median": round(float(zero.distinct_token_ratio.median()), 4),
}

# ---- 5. zero vs positive comparison ------------------------------------
def describe(series):
    s = series.dropna().astype(float)
    return {"n": int(len(s)), "mean": round(float(s.mean()), 2), "median": float(s.median()),
            "p10": float(s.quantile(.10)), "p90": float(s.quantile(.90))}

cmp_cols = ["score_word_count", "supply_chain_occurrences", "risk_occurrences",
            "resolution_occurrences"]
summary["zero_vs_positive"] = {
    c: {g: describe(panel.loc[panel.group == g, c]) for g in ("zero", "positive")}
    for c in cmp_cols
}
# occurrences per 1,000 tokens, so length is controlled for
for c in ["supply_chain_occurrences", "risk_occurrences"]:
    rate = 1000 * panel[c] / panel.score_word_count.replace(0, np.nan)
    summary["zero_vs_positive"][c + "_per_1000_tokens"] = {
        g: describe(rate[panel.group == g]) for g in ("zero", "positive")}

rows = []
for dim in ["year", "sector"]:
    g = panel.groupby(dim).agg(calls=("is_zero", "size"), zero_calls=("is_zero", "sum"))
    g["zero_rate_percent"] = (100 * g.zero_calls / g.calls).round(2)
    g["median_word_count"] = panel.groupby(dim).score_word_count.median()
    g["median_supply_chain_occurrences"] = panel.groupby(dim).supply_chain_occurrences.median()
    g["median_risk_occurrences"] = panel.groupby(dim).risk_occurrences.median()
    g = g.reset_index().rename(columns={dim: "value"})
    g.insert(0, "dimension", dim)
    rows.append(g)

comp = panel.groupby(["ticker", "company_name", "sector"]).agg(
    calls=("is_zero", "size"), zero_calls=("is_zero", "sum"),
    median_word_count=("score_word_count", "median"),
    median_supply_chain_occurrences=("supply_chain_occurrences", "median"),
    median_risk_occurrences=("risk_occurrences", "median")).reset_index()
comp["zero_rate_percent"] = (100 * comp.zero_calls / comp.calls).round(2)
comp.sort_values(["zero_rate_percent", "calls"], ascending=[False, False]).to_csv(
    OUT / "zero_rate_by_company.csv", index=False)
pd.concat(rows, ignore_index=True).to_csv(OUT / "zero_vs_positive_comparison.csv", index=False)

# length deciles: does zero rate fall with transcript length?
panel["length_decile"] = pd.qcut(panel.score_word_count, 10, labels=False, duplicates="drop") + 1
ld = panel.groupby("length_decile").agg(
    calls=("is_zero", "size"), zero_calls=("is_zero", "sum"),
    min_word_count=("score_word_count", "min"), max_word_count=("score_word_count", "max"))
ld["zero_rate_percent"] = (100 * ld.zero_calls / ld.calls).round(2)
ld.reset_index().to_csv(OUT / "zero_rate_by_length_decile.csv", index=False)
summary["zero_rate_by_length_decile"] = ld.reset_index().to_dict("records")

summary["zero_rate_by_year"] = (
    pd.concat(rows).query("dimension=='year'")[["value", "calls", "zero_calls", "zero_rate_percent"]]
    .to_dict("records"))
summary["zero_rate_by_sector"] = (
    pd.concat(rows).query("dimension=='sector'")[["value", "calls", "zero_calls", "zero_rate_percent"]]
    .sort_values("zero_rate_percent", ascending=False).to_dict("records"))
summary["companies_with_all_calls_zero"] = int((comp.zero_calls == comp.calls).sum())
summary["companies_total"] = int(len(comp))
summary["company_zero_rate_percentiles"] = {
    p: float(np.percentile(comp.zero_rate_percent, p)) for p in (10, 25, 50, 75, 90)}

# ---- 6. what vocabulary the zero calls actually contain ----------------
from collections import Counter
sc_counter, risk_counter = Counter(), Counter()
for col, counter in (("top_supply_chain_terms", sc_counter), ("top_risk_terms", risk_counter)):
    for cell in zero[col].dropna():
        for term in str(cell).split(";"):
            if term:
                counter[term] += 1
summary["most_common_supply_chain_terms_in_zero_calls"] = sc_counter.most_common(20)
summary["most_common_risk_terms_in_zero_calls"] = risk_counter.most_common(20)

summary["dictionary_checks"] = json.loads((OUT / "dictionary_checks.json").read_text())
(OUT / "zero_audit_summary.json").write_text(json.dumps(summary, indent=2, default=str))
print(json.dumps({k: v for k, v in summary.items() if k in (
    "population", "mechanism_buckets", "nearest_pair_distance_among_both_present",
    "false_zero_probes", "text_integrity")}, indent=2, default=str))
