#!/usr/bin/env python3
"""Attribute each zero-score call to one dominant cause."""
import json
import os
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]  # repository root
OUT = Path(os.environ.get('SCRISK_AUDIT_OUT', str(ROOT / 'outputs/scrisk_zero_audit')))

z = pd.read_csv(OUT / 'zero_audit_per_call.csv')
z['key'] = z.ticker + '|' + z.quarter_label
infl = pd.read_csv(OUT / 'probe_inflection_per_call.csv')
infl = infl[infl.probe == 'lib_seeds_and_risk_inflected']
z = z.merge(infl[['ticker_quarter', 'supply_chain_term', 'risk_term']],
            left_on='key', right_on='ticker_quarter', how='left')
z['vocab_flip'] = z.ticker_quarter.notna()
z['vocab_flip_self_pair'] = z.vocab_flip & (z.supply_chain_term == z.risk_term)

ci = pd.read_csv(OUT / 'transcript_content_integrity.csv')
ci['key'] = ci.ticker + '|' + ci.quarter_label
# The scorer's own verdict, so the audit cannot disagree with the filter.
flagged = set(ci[(ci.group == 'zero')
                 & (ci.pipeline_integrity_status == 'content_absent')].key)
z['content_absent'] = z.key.isin(flagged)


def cause(r):
    if r.content_absent:
        return '1_transcript_content_absent'
    if r.vocab_flip:
        return ('2b_vocabulary_gap_shortage_self_pair' if r.vocab_flip_self_pair
                else '2a_vocabulary_coverage_gap')
    if r.probe_window_25_becomes_nonzero == 1:
        return '3_window_near_miss_11_to_25_tokens'
    if r.probe_window_50_becomes_nonzero == 1:
        return '4_window_miss_26_to_50_tokens'
    return '5_no_colocated_language_at_any_plausible_window'


z['dominant_cause'] = z.apply(cause, axis=1)
tab = z.dominant_cause.value_counts().sort_index()
out = {c: {'calls': int(n), 'percent_of_zeros': round(100 * n / len(z), 2)}
       for c, n in tab.items()}
out['_total'] = {'calls': int(len(z)), 'percent_of_zeros': 100.0}
out['_recoverable_by_vocabulary_fix_alone'] = {
    'calls': int(z.vocab_flip.sum()),
    'percent_of_zeros': round(100 * float(z.vocab_flip.mean()), 2)}
out['_recoverable_by_vocabulary_or_window_25'] = {
    'calls': int((z.vocab_flip | (z.probe_window_25_becomes_nonzero == 1)).sum()),
    'percent_of_zeros': round(100 * float(
        (z.vocab_flip | (z.probe_window_25_becomes_nonzero == 1)).mean()), 2)}
(OUT / 'zero_cause_attribution.json').write_text(json.dumps(out, indent=2))
z[['ticker', 'quarter_label', 'company_name', 'sector', 'year', 'bucket',
   'recomputed_word_count', 'supply_chain_occurrences_recomputed',
   'risk_occurrences_recomputed', 'min_supply_chain_risk_token_distance',
   'dominant_cause']].to_csv(OUT / 'zero_cause_attribution.csv', index=False)
print(json.dumps(out, indent=2))
print('\nby sector (% of that sector\'s zeros):')
print((100 * pd.crosstab(z.sector, z.dominant_cause, normalize='index')).round(1).to_string())
print('\nvocabulary-gap share of zeros by year:')
g = z.groupby('year').vocab_flip.agg(['size', 'sum'])
g['percent'] = (100 * g['sum'] / g['size']).round(1)
print(g.to_string())
