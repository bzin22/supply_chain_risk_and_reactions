#!/usr/bin/env python3
"""Second read-only pass: record which term pair drives each probe flip."""
from __future__ import annotations
import csv, json, multiprocessing as mp, re, sys
from bisect import bisect_left
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # repository root
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from scoring import calculate_supply_chain_transcript_scores as S
import scan as A

OUT = A.OUT
WORD_ONLY_RE = re.compile(r"[A-Za-z]+")
NONASCII_LETTER_RE = re.compile(r"[^\x00-\x7F]")
_C: dict = {}


def nearest_pair(left, right, window):
    """Closest (left_term, right_term, distance) pair, or None past the window."""
    if not left or not right:
        return None
    right = sorted(right, key=lambda o: o.start)
    starts = [o.start for o in right]
    best = None
    for a in left:
        i = bisect_left(starts, a.start)
        for j in range(max(0, i - 3), min(len(right), i + 4)):
            b = right[j]
            d = 0 if not (a.end < b.start or b.end < a.start) else (
                b.start - a.end if a.end < b.start else a.start - b.end)
            if best is None or d < best[2]:
                best = (a.term, b.term, d)
    if best is None or best[2] > window:
        return None
    return best


def init():
    A.init_worker()
    _C.update(A._CTX)
    _C["stem_to_library"] = {}
    weights, risk = A.base_vocabularies()
    for t in weights:
        _C["stem_to_library"].setdefault(" ".join(A.stem(w) for w in t.split()), []).append(t)
    _C["stem_to_risk"] = {}
    for t in risk:
        _C["stem_to_risk"].setdefault(" ".join(A.stem(w) for w in t.split()), []).append(t)


def analyse(job):
    key, text = job
    find = S.find_indexed_occurrences
    tokens = S.tokenize(text)
    tokens_h = [m.group(0).lower() for m in WORD_ONLY_RE.finditer(text)]
    tokens_s = [A.stem(t) for t in tokens]
    risk = find(tokens, _C["risk"])
    out = {"key": key}
    out["seeds"] = nearest_pair(find(tokens, _C["sc_seeded"]), risk, S.WINDOW)
    out["hyphen"] = nearest_pair(find(tokens_h, _C["sc"]), find(tokens_h, _C["risk"]), S.WINDOW)
    out["stem"] = nearest_pair(find(tokens_s, _C["sc_stem"]), find(tokens_s, _C["risk_stem"]), S.WINDOW)
    out["window25"] = nearest_pair(find(tokens, _C["sc"]), risk, 25)
    # a conservative stemming probe: only plural/inflection folding that cannot
    # collide with a general business word already outside the library
    out["nonascii_letters"] = sum(1 for ch in NONASCII_LETTER_RE.findall(text) if ch.isalpha())
    out["digit_token_count"] = len(re.findall(r"\d", text))
    return out


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
    print(f"detail rows: {len(rows):,}")

    detail_path = OUT / "probe_flip_detail.csv"
    with detail_path.open("w", newline="", encoding="utf-8") as h:
        w = csv.writer(h)
        w.writerow(["ticker_quarter", "probe", "supply_chain_term", "risk_term", "token_distance"])
        for r in rows:
            for probe in ("seeds", "hyphen", "stem", "window25"):
                p = r[probe]
                if p:
                    w.writerow([r["key"], probe, p[0], p[1], p[2]])
    print("wrote", detail_path)

    agg = {}
    for probe in ("seeds", "hyphen", "stem", "window25"):
        sc_c, rk_c, pair_c = Counter(), Counter(), Counter()
        for r in rows:
            p = r[probe]
            if p:
                sc_c[p[0]] += 1; rk_c[p[1]] += 1; pair_c[f"{p[0]} + {p[1]}"] += 1
        agg[probe] = {"calls_flipped": sum(1 for r in rows if r[probe]),
                      "top_supply_chain_terms": sc_c.most_common(15),
                      "top_risk_terms": rk_c.most_common(15),
                      "top_pairs": pair_c.most_common(15)}
    # which library terms the stemmer broadened, and into what
    lib, _ = A.base_vocabularies()
    broadened = {t: " ".join(A.stem(w) for w in t.split()) for t in lib
                 if " ".join(A.stem(w) for w in t.split()) != t}
    agg["stemmer_broadened_library_terms"] = broadened
    agg["nonascii_letter_calls"] = sum(1 for r in rows if r["nonascii_letters"] > 0)
    agg["nonascii_letter_total"] = sum(r["nonascii_letters"] for r in rows)
    agg["calls_containing_digits"] = sum(1 for r in rows if r["digit_token_count"] > 0)
    (OUT / "probe_flip_drivers.json").write_text(json.dumps(agg, indent=2))
    print(json.dumps({k: (v if not isinstance(v, dict) else
                          {kk: vv for kk, vv in v.items() if kk != "top_pairs"})
                      for k, v in agg.items() if k != "stemmer_broadened_library_terms"}, indent=2))


if __name__ == "__main__":
    main()
