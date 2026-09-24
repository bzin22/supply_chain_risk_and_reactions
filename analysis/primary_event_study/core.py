"""Auditable scoring, historical classification, and Carhart calculations."""
from __future__ import annotations

import bisect
import csv
import hashlib
import json
import math
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

import calculate_supply_chain_transcript_scores as scorer
from calculate_carhart_event_returns import parse_factor_rows

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'data/final/earnings_call_transcripts_validated_2010_2019_v1.csv'
SOURCE_HASH = '06d4620290b4b8a66f18a8762d5042968d4b436d4aef7009f6004d9d331eece3'
DICT_ROOT = ROOT / 'dictionaries/theile_reconstruction_v1'
DICTIONARIES = {
    'supply_chain': DICT_ROOT / 'supply_chain/supply_chain_terms.jsonl',
    'risk': DICT_ROOT / 'risk/risk_terms_reconstructed_full.txt',
    'resolution': DICT_ROOT / 'resolution/resolution_terms_conservative_baseline.txt',
}
ARCHIVE = ROOT / '.archive/post_2019_removed_20260916/artifacts/earnings_call_supply_chain/ppmi_svd_full_20260910/event_study_inputs'
DATE_MAP = ROOT / 'data/call_dates/call_dates_v20260916/call_date_mapping.csv'
DIVISIONS = [
    (1, 9, 'Agriculture/forestry/fishing'), (10, 14, 'Mining'),
    (15, 17, 'Construction'), (20, 39, 'Manufacturing'),
    (40, 49, 'Transportation/communications/utilities'), (50, 51, 'Wholesale'),
    (52, 59, 'Retail'), (60, 67, 'Finance/insurance/real estate'),
    (70, 89, 'Services'), (91, 99, 'Public administration'),
]


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(2**20), b''):
            h.update(block)
    return h.hexdigest()


def relative(path):
    return str(Path(path).resolve().relative_to(ROOT))


def write_json(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, indent=2, sort_keys=True, allow_nan=False) + '\n')


def write_csv(path, rows, fields=None):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    fields = fields or list(dict.fromkeys(k for row in rows for k in row))
    with Path(path).open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def load_dictionaries():
    weights = scorer.load_supply_chain_library(DICTIONARIES['supply_chain'])
    risk = scorer.load_dictionary(DICTIONARIES['risk'])
    resolution = scorer.load_dictionary(DICTIONARIES['resolution'])
    expected = {'supply_chain': 254, 'risk': 161, 'resolution': 55}
    manifest = {}
    for kind, words in [('supply_chain', weights), ('risk', risk), ('resolution', resolution)]:
        assert len(words) == expected[kind], (kind, len(words))
        raw = DICTIONARIES[kind].read_text().splitlines()
        assert len([x for x in raw if x.strip()]) == len(words), 'Duplicate dictionary terms'
        manifest[kind] = {'path': relative(DICTIONARIES[kind]), 'sha256': sha256(DICTIONARIES[kind]),
                          'term_count': len(words), 'version': 'theile_reconstruction_v1',
                          'matching': 'exact library terms; no generated inflections'}
    assert all(0 < w <= 1 for w in weights.values())
    return weights, risk, resolution, manifest


def score_text(text, weights, indexes, audit=False):
    """Same pair sum as approved scorer, using sorted positions for proximity."""
    tokens = scorer.tokenize(text)
    sc, risk, res = [scorer.find_indexed_occurrences(tokens, x) for x in indexes]
    starts = [r.start for r in risk]
    res_starts = [r.start for r in res]
    max_risk = max((r.end-r.start+1 for r in risk), default=1)
    max_res = max((r.end-r.start+1 for r in res), default=1)
    pairs = resolved = same = 0
    weight_sum = res_sum = same_sum = 0.0
    matches = []
    for s in sc:
        near_res = [r for r in res[bisect.bisect_left(res_starts, s.start-10-max_res+1):
                                  bisect.bisect_right(res_starts, s.end+10)]
                    if scorer.spans_within(s, r, 10)]
        for r in risk[bisect.bisect_left(starts, s.start-10-max_risk+1):
                      bisect.bisect_right(starts, s.end+10)]:
            if not scorer.spans_within(s, r, 10):
                continue
            w = weights[s.term]
            pairs += 1
            weight_sum += w
            identical = (s.start, s.end) == (r.start, r.end)
            same += identical
            same_sum += w if identical else 0
            if near_res:
                resolved += 1
                res_sum += w
            if audit:
                matches.append({'supply_term': s.term, 'supply_span': [s.start, s.end],
                                'risk_term': r.term, 'risk_span': [r.start, r.end], 'weight': w,
                                'resolution': [{'term': z.term, 'span': [z.start, z.end]} for z in near_res],
                                'identical_span': identical,
                                'context': ' '.join(tokens[max(0, min(s.start,r.start)-12):max(s.end,r.end)+13])})
    n = len(tokens)
    status, flags = scorer.assess_transcript_integrity(text)
    result = {'transcript_word_count': n, 'supply_chain_occurrences': len(sc),
              'risk_occurrences': len(risk), 'resolution_occurrences': len(res),
              'supply_chain_risk_pairs': pairs, 'supply_chain_resolution_pairs': resolved,
              'SCRisk_weight_sum': weight_sum, 'Resolution_weight_sum': res_sum,
              'SCRisk_raw': weight_sum/n if n else 0, 'Resolution_raw': res_sum/n if n else 0,
              'scrisk_identical_span_pairs': same, 'scrisk_identical_span_weight_sum': same_sum,
              'scrisk_zero': pairs == 0, 'resolution_zero': resolved == 0,
              'zero_reason': ('nonzero' if pairs else 'no_supply_chain_terms' if not sc else
                              'no_risk_terms' if not risk else 'no_pairs_within_10_tokens'),
              'transcript_integrity_status': status, 'transcript_integrity_flags': ';'.join(flags)}
    assert 0 <= res_sum <= weight_sum + 1e-12
    return result, matches


def sic_division(value):
    text = str(value).strip()
    if not re.fullmatch(r'\d{1,4}', text) or int(text) == 0:
        return '', '', '', 'missing_or_invalid_sic'
    sic = text.zfill(4)
    two = int(sic[:2])
    for lo, hi, name in DIVISIONS:
        if lo <= two <= hi:
            return sic, sic[:2], name, 'assigned'
    return sic, sic[:2], '', 'unassigned_sic_division'


def assign_sic(row, history):
    # Fiscal labels are issuer-specific. Use the observed fiscal period end,
    # never convert YYYYQn mechanically into a calendar quarter.
    cutoff = row.get('date_fiscal_date_ending', '')
    result = {'sic_asof_date': cutoff, 'sic_asof_rule': 'latest filing on or before fiscal period end',
              'sic_4digit': '', 'sic_2digit': '', 'sic_division': '',
              'sic_match_status': 'missing_historical_sic', 'sic_source_path': '',
              'sic_source_sha256': '', 'sic_source_url': '', 'sic_filing_date': '', 'sic_accession': ''}
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', cutoff):
        result['sic_match_status'] = 'missing_fiscal_period_end'
        return result
    candidates = [r for r in history.get(row['cik'], []) if r['filing_date'] <= cutoff]
    if not candidates:
        return result
    latest = max(r['filing_date'] for r in candidates)
    candidates = [r for r in candidates if r['filing_date'] == latest]
    if len({r['sic'].zfill(4) for r in candidates}) > 1:
        result['sic_match_status'] = 'conflicting_historical_sic'
        return result
    chosen = sorted(candidates, key=lambda r: (r['accession'], r['source_path']))[-1]
    sic, two, div, status = sic_division(chosen['sic'])
    result.update(sic_4digit=sic, sic_2digit=two, sic_division=div,
                  sic_match_status='matched_point_in_time' if status == 'assigned' else status,
                  sic_source_path=chosen['source_path'], sic_source_sha256=chosen['source_sha256'],
                  sic_source_url=chosen['source_url'], sic_filing_date=latest,
                  sic_accession=chosen['accession'])
    return result


def load_factors():
    ff_path = ARCHIVE / 'fama_french/fama_french_daily.zip'
    mom_path = ARCHIVE / 'fama_french/momentum_daily.zip'
    ff = parse_factor_rows(ff_path, 'percent', 4)
    mom = parse_factor_rows(mom_path, 'percent', 1)
    # Keep the FF calendar intact. Missing momentum cannot compress event time.
    dates = sorted(d for d in ff if date(2008,1,1) <= d <= date(2021,1,1))
    factors = np.array([[ff[d][0], ff[d][1], ff[d][2], mom.get(d, [np.nan])[0], ff[d][3]] for d in dates])
    return dates, factors, {'fama_french': {'path': relative(ff_path), 'sha256': sha256(ff_path)},
                           'momentum': {'path': relative(mom_path), 'sha256': sha256(mom_path)},
                           'units_input': 'percent', 'units_used': 'decimal',
                           'calendar': 'Fama-French daily dates, without removing missing momentum',
                           'missing_momentum': int(np.isnan(factors[:,3]).sum()),
                           'vintage': 'retrieved 2026-09-15; CIZ-era French files'}


def carhart(call_date, prices, calendar, factors, audit=False):
    out = {'car_model_status': '', 'car_0_1_status': '', 'car_2_60_status': '',
           'CAR_0_1': None, 'CAR_2_60': None, 'estimation_observations': 0}
    if not call_date:
        out.update(car_model_status='unconfirmed_call_date', car_0_1_status='unconfirmed_call_date',
                   car_2_60_status='unconfirmed_call_date')
        return out, []
    d = date.fromisoformat(call_date)
    i = bisect.bisect_left(calendar, d)
    if i >= len(calendar) or i < 210:
        out.update(car_model_status='insufficient_factor_calendar', car_0_1_status='model_unavailable',
                   car_2_60_status='model_unavailable')
        return out, []
    out.update(event_trading_date=calendar[i].isoformat(), day_0_calendar_lag=(calendar[i]-d).days,
               estimation_start=calendar[i-209].isoformat(), estimation_end=calendar[i-10].isoformat())
    x = np.column_stack([np.ones(200), factors[i-209:i-9,:4]])
    def stock_return(j):
        p, prev = prices.get(calendar[j]), prices.get(calendar[j-1])
        return p/prev-1 if p and prev and p>0 and prev>0 and np.isfinite(p+prev) else np.nan
    actual_est = np.array([stock_return(j) for j in range(i-209, i-9)])
    y = actual_est - factors[i-209:i-9,4]
    good = np.isfinite(y) & np.isfinite(x).all(axis=1)
    out['estimation_observations'] = int(good.sum())
    out['estimation_missing_price_count'] = int((~np.isfinite(actual_est)).sum())
    out['estimation_missing_factor_count'] = int((~np.isfinite(factors[i-209:i-9]).all(axis=1)).sum())
    if not good.all():
        out.update(car_model_status='missing_estimation_prices_or_factors',
                   car_0_1_status='model_unavailable', car_2_60_status='model_unavailable',
                   missing_estimation_dates=';'.join(calendar[j].isoformat() for j in range(i-209,i-9) if not good[j-(i-209)]))
        return out, []
    beta, _, rank, singular = np.linalg.lstsq(x, y, rcond=None)
    out.update(estimation_rank=int(rank), estimation_condition_number=float(singular[0]/singular[-1]))
    if rank != 5:
        out.update(car_model_status='rank_deficient', car_0_1_status='model_unavailable', car_2_60_status='model_unavailable')
        return out, []
    residual = y-x@beta
    sse = float(residual@residual)
    sst = float(np.sum((y-y.mean())**2))
    out.update(car_model_status='ok', estimation_rmse=math.sqrt(sse/195),
               estimation_r_squared=1-sse/sst if sst else None,
               **dict(zip(['alpha','beta_market_minus_rf','beta_smb','beta_hml','beta_momentum'], map(float,beta))))
    daily = []
    for start, stop, name in [(0,1,'0_1'), (2,60,'2_60')]:
        ars, missing = [], []
        for offset in range(start, stop+1):
            j = i+offset
            if j >= len(calendar):
                missing.append(f'day_{offset}_outside_factor_calendar')
                continue
            actual = stock_return(j)
            expected = factors[j,4] + np.r_[1., factors[j,:4]]@beta
            abnormal = actual-expected
            if not np.isfinite(abnormal):
                missing.append(calendar[j].isoformat())
            else:
                ars.append(float(abnormal))
            if audit:
                daily.append({'event_day':offset, 'date':calendar[j].isoformat(),
                              'stock_return':float(actual) if np.isfinite(actual) else None,
                              'expected_return':float(expected) if np.isfinite(expected) else None,
                              'abnormal_return':float(abnormal) if np.isfinite(abnormal) else None})
        out[f'car_{name}_status'] = 'missing_event_prices_or_factors' if missing else 'ok'
        out[f'CAR_{name}'] = None if missing else sum(ars)
        out[f'car_{name}_observations'] = len(ars)
        out[f'car_{name}_missing_dates'] = ';'.join(missing)
    return out, daily


def equal_count_quintiles(frame, value, groups):
    """Ties split by an outcome-blind hash of call_id; counts differ by <=1."""
    result = pd.Series(pd.NA, index=frame.index, dtype='Int64')
    for _, group in frame.groupby(groups, sort=True, dropna=False):
        ordered = group.sort_values([value, 'portfolio_tie_key', 'call_id'])
        result.loc[ordered.index] = np.arange(len(ordered))*5//len(ordered)+1
    return result
