#!/usr/bin/env python3
"""Derive a per-call audit of SCRisk == 0 earnings calls.

Read-only with respect to every existing input and output.  The scoring
pipeline is imported, never modified: base classification uses
``calculate_supply_chain_transcript_scores.tokenize``,
``find_indexed_occurrences`` and the same window rule.  Each probe is a
separate derived column, not a change to the pipeline.
"""

from __future__ import annotations

import csv
import hashlib
import json
import multiprocessing as mp
import os
import re
import sys
from bisect import bisect_left
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # repository root
sys.path.insert(0, str(ROOT))
from scoring import calculate_supply_chain_transcript_scores as S  # noqa: E402

# Every path and the vocabulary version come from the environment so the same
# audit can be pointed at a different scoring run.  The defaults are the
# original ppmi_svd_full_20260910 run and the original library-only
# vocabulary, so running this with no environment set reproduces the first
# audit exactly.
RUN = Path(
    os.environ.get(
        "SCRISK_AUDIT_RUN",
        str(ROOT / "artifacts/earnings_call_supply_chain/ppmi_svd_full_20260910"),
    )
)
SCORED = RUN / "earnings_call_transcripts_scored.csv"
EVENTS = RUN / "earnings_call_event_returns.csv"
LIBRARY = Path(
    os.environ.get(
        "SCRISK_AUDIT_LIBRARY",
        str(ROOT / "artifacts/sec_10k_supply_chain/experiments/ppmi_svd_full_20260910/terms.jsonl"),
    )
)
OUT = Path(os.environ.get("SCRISK_AUDIT_OUT", str(ROOT / "outputs/scrisk_zero_audit")))
VOCABULARY_VERSION = os.environ.get("SCRISK_AUDIT_VOCABULARY", "v1_library_only")

SAMPLE_SIZE = 50
SAMPLE_SEED = 20260915
WORD_ONLY_RE = re.compile(r"[A-Za-z]+")
NONASCII_ALPHA_RE = re.compile(r"[^\x00-\x7F]")

_CTX: dict[str, object] = {}


def stem(token: str) -> str:
    """Crude suffix stripper used only as a diagnostic probe."""
    t = token
    if len(t) > 5 and t.endswith("ing"):
        t = t[:-3]
    elif len(t) > 4 and t.endswith("ed"):
        t = t[:-2]
    if len(t) > 4 and t.endswith("ies"):
        t = t[:-3] + "y"
    elif len(t) > 4 and t.endswith("sses"):
        t = t[:-2]
    elif len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
        t = t[:-1]
    return t


def stem_terms(terms) -> list[str]:
    return [" ".join(stem(w) for w in term.split()) for term in terms]


def min_span_distance(left, right) -> int | None:
    """Minimum token gap between any span in ``left`` and any in ``right``."""
    if not left or not right:
        return None
    right = sorted(right, key=lambda o: o.start)
    starts = [o.start for o in right]
    best = None
    for a in left:
        i = bisect_left(starts, a.start)
        for j in range(max(0, i - 3), min(len(right), i + 4)):
            b = right[j]
            if a.end < b.start:
                d = b.start - a.end
            elif b.end < a.start:
                d = a.start - b.end
            else:
                d = 0
            if best is None or d < best:
                best = d
                if best == 0:
                    return 0
    return best


def base_vocabularies() -> tuple[dict[str, float], list[str]]:
    """Return the supply-chain and risk vocabularies the audited run scored with."""
    library = S.load_supply_chain_library(LIBRARY)
    weights = S.build_supply_chain_vocabulary(library, VOCABULARY_VERSION)
    risk = S.build_risk_vocabulary(S.load_primary_risk_dictionary())
    return weights, risk


def init_worker() -> None:
    weights, risk = base_vocabularies()
    seed_terms = [" ".join(S.normalize_term(s)) for s in S.SUPPLY_CHAIN_SEEDS]
    res = [" ".join(S.normalize_term(t)) for t in S.load_primary_resolution_dictionary()]
    _CTX.update(
        sc=S.build_phrase_index(weights),
        sc_seeded=S.build_phrase_index(list(weights) + seed_terms),
        sc_stem=S.build_phrase_index(stem_terms(weights)),
        sc_seeded_stem=S.build_phrase_index(stem_terms(list(weights) + seed_terms)),
        risk=S.build_phrase_index(risk),
        risk_stem=S.build_phrase_index(stem_terms(risk)),
        res=S.build_phrase_index(res),
    )


def analyse(job: tuple[dict, str]) -> dict:
    meta, text = job
    find = S.find_indexed_occurrences
    tokens = S.tokenize(text)
    sc = find(tokens, _CTX["sc"])
    risk = find(tokens, _CTX["risk"])
    res = find(tokens, _CTX["res"])
    d_base = min_span_distance(sc, risk)

    if not tokens:
        bucket = "empty_transcript"
    elif not sc and not risk:
        bucket = "no_supply_chain_and_no_risk_vocab"
    elif not sc:
        bucket = "no_supply_chain_vocab"
    elif not risk:
        bucket = "supply_chain_but_no_risk_vocab"
    elif d_base is not None and d_base > S.WINDOW:
        bucket = "both_present_never_within_window"
    else:
        bucket = "UNEXPECTED_pair_within_window"

    # Probe 1: the 16 seed phrases added to the supply-chain vocabulary.
    sc_seeded = find(tokens, _CTX["sc_seeded"])
    d_seeded = min_span_distance(sc_seeded, risk)

    # Probe 2: hyphen / apostrophe / period splitting.
    tokens_h = [m.group(0).lower() for m in WORD_ONLY_RE.finditer(text)]
    same_tokens = tokens_h == tokens
    if same_tokens:
        sc_h, risk_h, d_h = sc, risk, d_base
    else:
        sc_h = find(tokens_h, _CTX["sc"])
        risk_h = find(tokens_h, _CTX["risk"])
        d_h = min_span_distance(sc_h, risk_h)

    # Probe 3: stemmed tokens and stemmed dictionaries.
    tokens_s = [stem(t) for t in tokens]
    sc_s = find(tokens_s, _CTX["sc_stem"])
    risk_s = find(tokens_s, _CTX["risk_stem"])
    d_s = min_span_distance(sc_s, risk_s)

    # Probe 6: everything at once (seeds + hyphen split + stemming).
    tokens_c = [stem(t) for t in tokens_h]
    sc_c = find(tokens_c, _CTX["sc_seeded_stem"])
    risk_c = find(tokens_c, _CTX["risk_stem"])
    d_c = min_span_distance(sc_c, risk_c)

    stripped = text.strip()
    row = dict(meta)
    row.update(
        recomputed_word_count=len(tokens),
        supply_chain_occurrences_recomputed=len(sc),
        risk_occurrences_recomputed=len(risk),
        resolution_occurrences_recomputed=len(res),
        distinct_supply_chain_terms=len({o.term for o in sc}),
        distinct_risk_terms=len({o.term for o in risk}),
        min_supply_chain_risk_token_distance="" if d_base is None else d_base,
        bucket=bucket,
        probe_seeds_becomes_nonzero=int(d_seeded is not None and d_seeded <= S.WINDOW),
        probe_seeds_supply_chain_occurrences=len(sc_seeded),
        probe_seeds_min_distance="" if d_seeded is None else d_seeded,
        probe_hyphen_split_becomes_nonzero=int(d_h is not None and d_h <= S.WINDOW),
        probe_hyphen_split_changed_tokens=int(not same_tokens),
        probe_hyphen_split_min_distance="" if d_h is None else d_h,
        probe_stemming_becomes_nonzero=int(d_s is not None and d_s <= S.WINDOW),
        probe_stemming_supply_chain_occurrences=len(sc_s),
        probe_stemming_risk_occurrences=len(risk_s),
        probe_stemming_min_distance="" if d_s is None else d_s,
        probe_window_25_becomes_nonzero=int(d_base is not None and d_base <= 25),
        probe_window_50_becomes_nonzero=int(d_base is not None and d_base <= 50),
        probe_combined_becomes_nonzero=int(d_c is not None and d_c <= S.WINDOW),
        probe_combined_min_distance="" if d_c is None else d_c,
        text_character_length=len(text),
        text_is_blank=int(not stripped),
        ends_with_terminal_punctuation=int(bool(stripped) and stripped[-1] in ".?!\"'’”"),
        non_ascii_character_count=len(NONASCII_ALPHA_RE.findall(text)),
        distinct_token_ratio=round(len(set(tokens)) / len(tokens), 4) if tokens else "",
        text_sha1=hashlib.sha1(text.encode("utf-8")).hexdigest(),
        top_supply_chain_terms=";".join(
            t for t, _ in _top({o.term for o in sc}, sc)
        ),
        top_risk_terms=";".join(t for t, _ in _top({o.term for o in risk}, risk)),
    )
    return row


def _top(_unused, occurrences, limit: int = 5):
    counts: dict[str, int] = {}
    for o in occurrences:
        counts[o.term] = counts.get(o.term, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]


def load_populations() -> tuple[dict, dict]:
    zero, positive = {}, {}
    with EVENTS.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["event_status"] != "ok":
                continue
            key = (row["ticker"], row["quarter_label"])
            target = zero if float(row["SCRisk"] or 0) == 0.0 else positive
            target[key] = row
    return zero, positive


META_DROP = {"transcript_text"}


def main() -> None:
    S.configure_csv_field_size_limit()
    OUT.mkdir(parents=True, exist_ok=True)
    zero, positive = load_populations()
    print(f"zero-score analysable calls: {len(zero):,}; positive-score: {len(positive):,}", flush=True)

    import random

    sample_keys = set(random.Random(SAMPLE_SEED).sample(sorted(zero), SAMPLE_SIZE))
    (OUT / "sampled_zero_call_keys.json").write_text(
        json.dumps({"seed": SAMPLE_SEED, "keys": sorted("|".join(k) for k in sample_keys)}, indent=2)
    )

    meta_path = OUT / "all_calls_metadata.csv"
    per_call_rows: list[dict] = []
    sampled_texts: dict[tuple[str, str], str] = {}

    def jobs():
        with SCORED.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            fields = [f for f in reader.fieldnames if f not in META_DROP]
            with meta_path.open("w", newline="", encoding="utf-8") as meta_handle:
                writer = csv.DictWriter(meta_handle, fieldnames=fields, extrasaction="ignore")
                writer.writeheader()
                for row in reader:
                    writer.writerow(row)
                    key = (row["ticker"], row["quarter_label"])
                    if key not in zero:
                        continue
                    text = row.get("transcript_text") or ""
                    if key in sample_keys:
                        sampled_texts[key] = text
                    yield (
                        {
                            "ticker": row["ticker"],
                            "quarter_label": row["quarter_label"],
                            "company_name": row["company_name"],
                            "sector": row["sector"],
                            "industry": row["industry"],
                            "year": row["year"],
                            "quarter": row["quarter"],
                            "call_date": row["call_date"],
                            "status": row["status"],
                            "segment_word_count": row["word_count"],
                            "score_word_count": row["score_word_count"],
                            "supply_chain_occurrences_csv": row["supply_chain_occurrences"],
                            "risk_occurrences_csv": row["risk_occurrences"],
                            "supply_chain_risk_pairs_csv": row["supply_chain_risk_pairs"],
                            "SCRisk_weight_sum_csv": row["SCRisk_weight_sum"],
                        },
                        text,
                    )

    workers = max(1, min(8, mp.cpu_count() - 1))
    with mp.Pool(workers, initializer=init_worker) as pool:
        for i, out_row in enumerate(pool.imap_unordered(analyse, jobs(), chunksize=8), start=1):
            per_call_rows.append(out_row)
            if i % 1000 == 0:
                print(f"  analysed {i:,}", flush=True)

    per_call_rows.sort(key=lambda r: (r["ticker"], r["quarter_label"]))
    per_call_path = OUT / "zero_audit_per_call.csv"
    with per_call_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(per_call_rows[0].keys()))
        writer.writeheader()
        writer.writerows(per_call_rows)
    print(f"wrote {per_call_path} ({len(per_call_rows):,} rows)")

    with (OUT / "sampled_zero_transcript_texts.json").open("w", encoding="utf-8") as handle:
        json.dump({"|".join(k): v for k, v in sampled_texts.items()}, handle)
    print(f"cached {len(sampled_texts)} sampled transcripts")


if __name__ == "__main__":
    main()
