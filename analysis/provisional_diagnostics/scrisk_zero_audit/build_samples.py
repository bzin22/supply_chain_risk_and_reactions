#!/usr/bin/env python3
"""Render +/-40-token raw-text windows for the 50 sampled zero calls."""
from __future__ import annotations
import json, re, sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]  # repository root
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import calculate_supply_chain_transcript_scores as S
import scan as A
OUT = A.OUT
CTX = 40

texts = json.loads((OUT / "sampled_zero_transcript_texts.json").read_text())
per_call = pd.read_csv(OUT / "zero_audit_per_call.csv")
per_call["key"] = per_call.ticker + "|" + per_call.quarter_label
per_call = per_call.set_index("key")

weights = S.load_supply_chain_library(A.LIBRARY)
sc_index = S.build_phrase_index(weights)
seeds = [" ".join(S.normalize_term(s)) for s in S.SUPPLY_CHAIN_SEEDS]
sc_seeded_index = S.build_phrase_index(list(weights) + seeds)
risk_index = S.build_phrase_index(S.build_risk_vocabulary(S.load_primary_risk_dictionary()))


def excerpt(text, spans, lo, hi):
    a = spans[max(0, lo)][0]
    b = spans[min(len(spans) - 1, hi)][1]
    return re.sub(r"\s+", " ", text[a:b]).strip()


lines = ["# 50 randomly sampled SCRisk = 0 earnings calls",
         "",
         f"Seed `{A.SAMPLE_SEED}`, drawn from the calls with `SCRisk == 0` and "
         f"`event_status == 'ok'` under vocabulary `{A.VOCABULARY_VERSION}`. For each call: "
         "the closest supply-chain/risk term pair found under that vocabulary, and the same "
         "pair once the 16 seed phrases are restored. Excerpts are raw transcript text, "
         "+/-40 tokens around the nearer term.",
         ""]

verdicts = []
for key in sorted(texts):
    text = texts[key]
    row = per_call.loc[key]
    spans = [(m.start(), m.end()) for m in S.WORD_RE.finditer(text)]
    tokens = [text[a:b].lower() for a, b in spans]
    sc = S.find_indexed_occurrences(tokens, sc_index)
    scs = S.find_indexed_occurrences(tokens, sc_seeded_index)
    rk = S.find_indexed_occurrences(tokens, risk_index)

    def closest(left, right):
        best = None
        for a in left:
            for b in right:
                d = 0 if not (a.end < b.start or b.end < a.start) else (
                    b.start - a.end if a.end < b.start else a.start - b.end)
                if best is None or d < best[0]:
                    best = (d, a, b)
        return best

    base = closest(sc, rk)
    seeded = closest(scs, rk)
    lines += [f"## {key} — {row.company_name} ({row.sector}, {row.year}Q{row.quarter})",
              "",
              f"- tokens: {row.recomputed_word_count:,} | supply-chain hits: "
              f"{row.supply_chain_occurrences_recomputed} | risk hits: "
              f"{row.risk_occurrences_recomputed} | bucket: `{row.bucket}`"]
    if base:
        d, a, b = base
        lines.append(f"- current library nearest pair: `{a.term}` + `{b.term}`, **{d} tokens apart** "
                     f"(window is {S.WINDOW})")
        lo, hi = min(a.start, b.start) - CTX, max(a.end, b.end) + CTX
        lines += ["", f"  > ...{excerpt(text, spans, lo, hi)}...", ""]
    else:
        lines += ["- current library nearest pair: none (one or both vocabularies absent)", ""]
    if seeded and (not base or seeded[0] < base[0]):
        d, a, b = seeded
        flag = "**FALSE ZERO**" if d <= S.WINDOW else "closer but still outside the window"
        lines.append(f"- with the 16 seeds restored: `{a.term}` + `{b.term}`, **{d} tokens apart** — {flag}")
        lo, hi = min(a.start, b.start) - CTX, max(a.end, b.end) + CTX
        lines += ["", f"  > ...{excerpt(text, spans, lo, hi)}...", ""]
        verdict = "false_zero_dropped_seed_vocabulary" if d <= S.WINDOW else "near_miss"
    elif base and base[0] <= 25:
        verdict = "near_miss"
    else:
        verdict = "true_zero_no_colocated_language"
    lines.append(f"- **verdict: `{verdict}`**")
    lines.append("")
    verdicts.append({"key": key, "company": row.company_name, "sector": row.sector,
                     "year": int(row.year), "tokens": int(row.recomputed_word_count),
                     "bucket": row.bucket,
                     "current_nearest_distance": base[0] if base else None,
                     "seeded_nearest_distance": seeded[0] if seeded else None,
                     "verdict": verdict})

(OUT / "sampled_zero_transcripts.md").write_text("\n".join(lines))
pd.DataFrame(verdicts).to_csv(OUT / "sampled_zero_verdicts.csv", index=False)
print(pd.DataFrame(verdicts).verdict.value_counts().to_string())
print()
print(pd.DataFrame(verdicts)[["key","tokens","current_nearest_distance","seeded_nearest_distance","verdict"]].to_string(index=False))
