#!/usr/bin/env python3
"""List every term that pairs with its own occurrence, and count those pairs.

A supply-chain occurrence and a risk occurrence that share the same token span
are the same tokens, so the term can only be one that sits in both
vocabularies.  The complete list is therefore the intersection of the two,
which the scoring manifest already records as
``terms_in_both_supply_chain_and_risk``.  This counts the pairs directly
instead of trusting that argument, and writes the result next to the
before-and-after report.
"""
import csv, json, multiprocessing as mp, sys
from collections import Counter
from pathlib import Path
ROOT = Path('/Users/bzin/stock_market_reactions_recreation_study')
sys.path.insert(0, str(ROOT))
import calculate_supply_chain_transcript_scores as S

RUN = ROOT / 'artifacts/earnings_call_supply_chain/ppmi_svd_full_20260910_vocab_v2'
LIB = ROOT / 'artifacts/sec_10k_supply_chain/experiments/ppmi_svd_full_20260910/terms.jsonl'
_C = {}

def init():
    lib = S.load_supply_chain_library(LIB)
    for v in ('v1_library_only', 'v2_seeds_inflections'):
        sc = S.build_supply_chain_vocabulary(lib, v)
        rk = S.build_risk_vocabulary(S.STARTER_RISK_WORDS, v)
        _C[v] = (S.build_phrase_index(sc), S.build_phrase_index(rk))

def analyse(job):
    text = job
    tokens = S.tokenize(text)
    out = {}
    for v, (sci, rki) in _C.items():
        sc = S.find_indexed_occurrences(tokens, sci)
        rk = S.find_indexed_occurrences(tokens, rki)
        rk_spans = {(o.start, o.end): o.term for o in rk}
        c = Counter()
        for o in sc:
            if rk_spans.get((o.start, o.end)) is not None:
                # identical span on both sides: a self-pair
                c[(o.term, rk_spans[(o.start, o.end)])] += 1
        out[v] = c
    return out

def main():
    S.configure_csv_field_size_limit()
    keys = set()
    with (RUN / 'earnings_call_event_returns.csv').open(newline='', encoding='utf-8') as h:
        for r in csv.DictReader(h):
            if r['event_status'] == 'ok' and r['CAR_0_1'] and r['SCRisk']:
                keys.add((r['ticker'], r['quarter_label']))

    def jobs():
        with (RUN / 'earnings_call_transcripts_scored.csv').open(newline='', encoding='utf-8') as h:
            for r in csv.DictReader(h):
                if (r['ticker'], r['quarter_label']) in keys:
                    yield r.get('transcript_text') or ''

    totals = {'v1_library_only': Counter(), 'v2_seeds_inflections': Counter()}
    with mp.Pool(max(1, min(8, mp.cpu_count() - 1)), initializer=init) as pool:
        for res in pool.imap_unordered(analyse, jobs(), chunksize=16):
            for v, c in res.items():
                totals[v].update(c)
    out = ROOT / 'outputs/scrisk_vocabulary_fix'
    out.mkdir(parents=True, exist_ok=True)
    report = {'analysable_calls': len(keys)}
    with (out / 'self_pair_terms.csv').open('w', newline='', encoding='utf-8') as h:
        w = csv.writer(h)
        w.writerow(['vocabulary_version', 'supply_chain_term', 'risk_term',
                    'identical_span_pairs', 'weight_each', 'weight_contributed'])
        lib = S.load_supply_chain_library(LIB)
        for v, c in totals.items():
            weights = S.build_supply_chain_vocabulary(lib, v)
            report[v] = {'identical_span_pairs': sum(c.values()),
                         'terms': sorted({a for a, _ in c})}
            print(f'== {v}: {sum(c.values()):,} identical-span pairs')
            for (a, b), n in c.most_common():
                w.writerow([v, a, b, n, weights[a], round(n * weights[a], 6)])
                print(f'   supply-chain "{a}"  +  risk "{b}"   {n:,} pairs')
    (out / 'self_pair_terms.json').write_text(json.dumps(report, indent=2))
    print(f'wrote {out}/self_pair_terms.csv and .json')

if __name__ == '__main__':
    main()
