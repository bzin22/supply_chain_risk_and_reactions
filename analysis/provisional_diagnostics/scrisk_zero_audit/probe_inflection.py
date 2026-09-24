#!/usr/bin/env python3
"""Probe 7: complete the vocabulary's regular inflections, no stem truncation."""
from __future__ import annotations
import csv, json, multiprocessing as mp, sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # repository root
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from scoring import calculate_supply_chain_transcript_scores as S
import scan as A
from probe_detail import nearest_pair

OUT = A.OUT
_C: dict = {}


def inflect(word: str) -> set[str]:
    """Regular singular/plural variants only. Never truncates a stem."""
    out = {word}
    if word.endswith("ies") and len(word) > 4:
        out.add(word[:-3] + "y")
    elif word.endswith(("ses", "xes", "zes", "ches", "shes")):
        out.add(word[:-2])
    elif word.endswith("s") and not word.endswith("ss"):
        out.add(word[:-1])
    else:
        out.add(word + "s")
        if word.endswith("y") and len(word) > 2 and word[-2] not in "aeiou":
            out.add(word[:-1] + "ies")
        if word.endswith(("s", "x", "z", "ch", "sh")):
            out.add(word + "es")
    return out


def expand(terms):
    seen = set()
    for term in terms:
        words = term.split()
        # inflect the head word (last token) only, as English does
        for variant in inflect(words[-1]):
            seen.add(" ".join(words[:-1] + [variant]))
    return sorted(seen)


def init():
    A.init_worker()
    weights = S.load_supply_chain_library(A.LIBRARY)
    seeds = [" ".join(S.normalize_term(s)) for s in S.SUPPLY_CHAIN_SEEDS]
    risk = S.build_risk_vocabulary(S.load_primary_risk_dictionary())
    _C["sc_lib_inflected"] = S.build_phrase_index(expand(weights))
    _C["sc_lib_seeds_inflected"] = S.build_phrase_index(expand(list(weights) + seeds))
    _C["risk"] = A._CTX["risk"]
    _C["risk_inflected"] = S.build_phrase_index(expand(risk))


def analyse(job):
    key, text = job
    find = S.find_indexed_occurrences
    tokens = S.tokenize(text)
    risk = find(tokens, _C["risk"])
    risk_i = find(tokens, _C["risk_inflected"])
    return {
        "key": key,
        "lib_inflected": nearest_pair(find(tokens, _C["sc_lib_inflected"]), risk, S.WINDOW),
        "lib_seeds_inflected": nearest_pair(find(tokens, _C["sc_lib_seeds_inflected"]), risk, S.WINDOW),
        "lib_seeds_and_risk_inflected": nearest_pair(
            find(tokens, _C["sc_lib_seeds_inflected"]), risk_i, S.WINDOW),
    }


def main():
    S.configure_csv_field_size_limit()
    zero, _ = A.load_populations()

    def jobs():
        with A.SCORED.open(newline="", encoding="utf-8") as h:
            for row in csv.DictReader(h):
                k = (row["ticker"], row["quarter_label"])
                if k in zero:
                    yield ("|".join(k), row.get("transcript_text") or "")

    rows = []
    with mp.Pool(max(1, min(8, mp.cpu_count() - 1)), initializer=init) as pool:
        for r in pool.imap_unordered(analyse, jobs(), chunksize=8):
            rows.append(r)

    res, n = {}, len(rows)
    for probe in ("lib_inflected", "lib_seeds_inflected", "lib_seeds_and_risk_inflected"):
        flipped = [r for r in rows if r[probe]]
        sc_c, rk_c, pair_c = Counter(), Counter(), Counter()
        for r in flipped:
            a, b, _ = r[probe]
            sc_c[a] += 1; rk_c[b] += 1; pair_c[f"{a} + {b}"] += 1
        res[probe] = {"calls_flipped": len(flipped),
                      "percent_of_zeros": round(100 * len(flipped) / n, 2),
                      "top_supply_chain_terms": sc_c.most_common(15),
                      "top_risk_terms": rk_c.most_common(12),
                      "top_pairs": pair_c.most_common(20)}
    with (OUT / "probe_inflection_per_call.csv").open("w", newline="", encoding="utf-8") as h:
        w = csv.writer(h)
        w.writerow(["ticker_quarter", "probe", "supply_chain_term", "risk_term", "token_distance"])
        for r in rows:
            for probe in ("lib_inflected", "lib_seeds_inflected", "lib_seeds_and_risk_inflected"):
                if r[probe]:
                    w.writerow([r["key"], probe, *r[probe]])
    (OUT / "probe_inflection_drivers.json").write_text(json.dumps(res, indent=2))
    for p, v in res.items():
        print(f"== {p}: {v['calls_flipped']:,} ({v['percent_of_zeros']}%)")
        print("   sc:", v["top_supply_chain_terms"][:8])
        print("   pairs:", v["top_pairs"][:8])


if __name__ == "__main__":
    main()
