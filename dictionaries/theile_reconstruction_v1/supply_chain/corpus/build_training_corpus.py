"""Stage 5: assemble the shared training corpus, in two candidate spaces.

Why two. The paper takes 16 x 100 = 1,600 candidates down to 208 unique keywords
by removing duplicates AND multiword n-grams. That ~87% attrition only happens if
the model proposes multiword phrases as candidates in the first place, which is
what metaHeuristica did. A unigram-only model proposes none, so its top-100 lists
survive almost intact: the earlier run in this repo produced 1,093 terms, five
times the paper's 208. Reproducing the paper's funnel therefore needs a
phrase-augmented candidate space, with the multiword candidates dropped after
ranking rather than never generated.

Both corpora come from the identical document set and identical cleaning, so the
only difference between them is phrase joining.

Phrase detection is the gensim "original" score, computed here so that all three
methods share one deterministic preprocessing step:
    score(a,b) = (count(ab) - min_count) * N / (count(a) * count(b))
"""
from __future__ import annotations

import argparse
import collections
import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from seeds import MULTIWORD_SEEDS

# A bigram starting or ending on a function word is a grammatical accident, not a
# term: 'our_customers', 'warehousing_and', 'to_distribute'. In the subset run these
# consumed 82 of the 1,600 candidate slots, including one that displaced the Table 2
# term 'endcustomers' with 'our_endcustomers'.
FUNCTION_WORDS = set(
    "a an the and or but nor so yet of to in for with on at by from as is are was were "
    "be been being has have had do does did will would shall should may might must can "
    "could this that these those it its their our your his her they we you i he she "
    "not no than then if when while although however whereas which who whom whose what "
    "there here all any both each few more most other some such only own same very "
    "into through during before after above below up down out off over under again "
    "further once about against between because until upon per also".split())


def prune(counter: collections.Counter, floor: int) -> int:
    for k in [k for k, v in counter.items() if v <= floor]:
        del counter[k]
    return floor + 1


def usable_documents(manifest: Path, sample: Path):
    selected = {json.loads(l)["accession"] for l in sample.open()}
    rows: dict[str, dict] = {}
    for line in manifest.open():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r["accession"] in selected:
            rows[r["accession"]] = r
    ok = [r for r in rows.values() if r.get("parser_status") == "ok"]

    # Exclude exact content duplicates and repeat CIK/report-period pairs, keeping
    # the earliest filing of each so the choice does not depend on dict ordering.
    ok.sort(key=lambda r: (r["filed"], r["accession"]))
    seen_hash, seen_period, kept, excluded = set(), set(), [], []
    for r in ok:
        h = r["sha256_primary_document"]
        pk = (r["cik"], r.get("conformed_period"))
        if h in seen_hash:
            excluded.append({**r, "exclusion": "duplicate_content_hash"}); continue
        if r.get("conformed_period") and pk in seen_period:
            excluded.append({**r, "exclusion": "duplicate_cik_report_period"}); continue
        seen_hash.add(h)
        if r.get("conformed_period"):
            seen_period.add(pk)
        kept.append(r)
    return kept, excluded


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--sample", type=Path, required=True)
    p.add_argument("--text-dir", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--report-dir", type=Path, required=True)
    p.add_argument("--phrase-min-count", type=int, default=50)
    p.add_argument("--phrase-threshold", type=float, default=12.0)
    p.add_argument("--max-vocab", type=int, default=25_000_000)
    a = p.parse_args()

    a.output_dir.mkdir(parents=True, exist_ok=True)
    kept, excluded = usable_documents(a.manifest, a.sample)
    print(f"documents kept={len(kept):,} excluded_as_duplicate={len(excluded):,}", flush=True)

    def doc_tokens(r):
        p = a.text_dir / r["cik"] / f"{r['accession']}.txt.gz"
        with gzip.open(p, "rb") as fh:
            return fh.read().decode().split()

    # Pass 1: unigram and bigram counts, with pruning to bound memory.
    uni: collections.Counter = collections.Counter()
    bi: collections.Counter = collections.Counter()
    total = 0
    floor_u = floor_b = 0
    for i, r in enumerate(kept, 1):
        t = doc_tokens(r)
        total += len(t)
        uni.update(t)
        bi.update(zip(t, t[1:]))
        if len(bi) > a.max_vocab:
            floor_b = prune(bi, floor_b)
        if len(uni) > a.max_vocab // 4:
            floor_u = prune(uni, floor_u)
        if i % 5000 == 0:
            print(f"  counted {i:,}/{len(kept):,} docs  {total/1e6:.0f}M tokens  "
                  f"uni={len(uni):,} bi={len(bi):,}", flush=True)

    N = total
    phrases: dict[tuple[str, str], float] = {}
    for (x, y), c in bi.items():
        if c < a.phrase_min_count:
            continue
        if x in FUNCTION_WORDS or y in FUNCTION_WORDS:
            continue
        cx, cy = uni.get(x, 0), uni.get(y, 0)
        if not cx or not cy:
            continue
        score = (c - a.phrase_min_count) * N / (cx * cy)
        if score > a.phrase_threshold:
            phrases[(x, y)] = score
    # The three multiword seeds must be joinable regardless of score.
    forced = []
    for s in MULTIWORD_SEEDS:
        w = tuple(s.split())
        if w not in phrases:
            phrases[w] = float("nan")
            forced.append(s)
    print(f"phrases detected={len(phrases):,} forced_seed_phrases={forced}", flush=True)

    # Pass 2: write both corpora.
    uni_path = a.output_dir / "corpus_unigram.txt.gz"
    phr_path = a.output_dir / "corpus_phrased.txt.gz"
    joined = 0
    with gzip.open(uni_path, "wt", compresslevel=4) as fu, \
         gzip.open(phr_path, "wt", compresslevel=4) as fp:
        for i, r in enumerate(kept, 1):
            t = doc_tokens(r)
            fu.write(" ".join(t) + "\n")
            out, k = [], 0
            while k < len(t):
                if k + 1 < len(t) and (t[k], t[k + 1]) in phrases:
                    out.append(t[k] + "_" + t[k + 1]); k += 2; joined += 1
                else:
                    out.append(t[k]); k += 1
            fp.write(" ".join(out) + "\n")
            if i % 5000 == 0:
                print(f"  wrote {i:,}/{len(kept):,}", flush=True)

    report = {
        "documents_used": len(kept),
        "documents_excluded_duplicate": len(excluded),
        "exclusion_breakdown": dict(collections.Counter(e["exclusion"] for e in excluded)),
        "total_tokens": N,
        "unigram_types_after_pruning": len(uni),
        "bigram_types_after_pruning": len(bi),
        "prune_floor_unigram": floor_u,
        "prune_floor_bigram": floor_b,
        "phrases_detected": len(phrases),
        "function_word_anchored_bigrams_rejected": True,
        "phrase_min_count": a.phrase_min_count,
        "phrase_threshold": a.phrase_threshold,
        "phrase_score": "gensim original: (count(ab)-min_count)*N/(count(a)*count(b))",
        "forced_seed_phrases": forced,
        "phrase_joins_applied": joined,
        "corpus_unigram": str(uni_path),
        "corpus_phrased": str(phr_path),
    }
    a.report_dir.mkdir(parents=True, exist_ok=True)
    (a.report_dir / "training_corpus_report.json").write_text(json.dumps(report, indent=2))
    with (a.report_dir / "excluded_duplicates.jsonl").open("w") as fh:
        for e in excluded:
            fh.write(json.dumps({k: e[k] for k in
                     ("accession", "cik", "filed", "form", "conformed_period", "exclusion")}) + "\n")
    top = sorted(phrases.items(), key=lambda kv: -uni.get(kv[0][0], 0))[:1]
    print(json.dumps({k: v for k, v in report.items() if k != "corpus_unigram"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
