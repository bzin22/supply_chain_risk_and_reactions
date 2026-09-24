"""Build separate, reproducible call-level scoring and event-study outputs."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import platform
import shutil
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import core
from .core import ROOT, SOURCE, SOURCE_HASH, ARCHIVE, DICTIONARIES, sha256, relative, write_csv, write_json
from .prepare import CACHE

PRICE_CACHE = ROOT/'artifacts/primary_event_study_release_dates_v1/prices'
DATE_POLICIES = {
    'confirmed': 'explicit SEC conference-call evidence; reported earnings dates alone do not qualify',
    'release': 'v1 earnings_call_date (reported earnings-release date) treated as call date by explicit user instruction; separate confirmed dates retained for audit only',
}


def price_path(ticker):
    original=ARCHIVE/'alpha_vantage_daily_adjusted_raw'/f'{ticker}.json'
    if original.is_file(): return original,original
    original=PRICE_CACHE/f'{ticker}.json'
    retry=PRICE_CACHE/f'{ticker}.retry01.json'
    if retry.is_file():
        response=json.loads(retry.read_text())
        if response.get('classification')=='ok' and response.get('payload',{}).get('Time Series (Daily)'):
            return retry,original
    return original,original


def apply_date_policy(row, policy):
    # Preserve the original confirmation evidence before assigning provenance
    # to the selected event date. Never label SEC call evidence as the source
    # of a different, user-selected earnings-release date.
    for suffix in ['source_url','source_path','source_sha256','evidence']:
        row.setdefault('confirmed_call_date_'+suffix,row.get('call_date_'+suffix,''))
    row['confirmed_call_date_status']=row.get('call_date_confirmation_status','')
    row['reported_earnings_date'] = row['earnings_call_date']
    row['call_date'] = row['earnings_call_date'] if policy == 'release' else row['confirmed_call_date']
    row['event_date_policy'] = policy
    row['event_date_source_field'] = 'earnings_call_date' if policy == 'release' else 'confirmed_call_date'
    row['event_date_assumption'] = DATE_POLICIES[policy]
    if policy == 'release':
        row['call_date_source_url']=row.get('date_source_url','')
        row['call_date_source_path']=relative(SOURCE)
        row['call_date_source_sha256']=SOURCE_HASH
        row['call_date_evidence']=row.get('date_evidence_snippet','')
        row['call_date_provider_response_sha256']=row.get('date_response_sha256','')
        row['call_date_source_title']=row.get('date_source_title','')
        row['call_date_retrieved_at_utc']=row.get('date_retrieved_at_utc','')
        row['call_date_match_method']=row.get('date_match_method','')
    row['release_date_differs_from_confirmed_call'] = bool(row.get('confirmed_call_date')) and row['earnings_call_date'] != row['confirmed_call_date']
    return row


def code_hashes():
    paths = sorted(Path(__file__).parent.glob('*.py')) + [ROOT/'calculate_supply_chain_transcript_scores.py',ROOT/'calculate_carhart_event_returns.py']
    return {relative(p):sha256(p) for p in paths}


def metadata(date_policy='confirmed'):
    dates={r['call_id']:r for r in csv.DictReader((CACHE/'confirmed_dates.csv').open())}
    history=defaultdict(list)
    for r in csv.DictReader((CACHE/'sic_history.csv').open()): history[r['cik']].append(r)
    rows=[]
    for r in csv.DictReader((CACHE/'metadata.csv').open()):
        r.update(dates[r['call_id']])
        apply_date_policy(r, date_policy)
        r.update(core.assign_sic(r,history))
        rows.append(r)
    return rows


def pilot_selection(rows):
    selected={}
    buckets=defaultdict(list)
    for r in rows:
        key=(r['quarter_label'][:4], bool(r['confirmed_call_date']))
        buckets[key].append(r)
        buckets[('division',r['sic_division'] or 'missing')].append(r)
    for key,group in buckets.items():
        for r in sorted(group,key=lambda x:hashlib.sha256(('pilot-v1|'+x['call_id']).encode()).hexdigest())[:3]:
            selected[r['call_id']]=str(key)
    return selected


class Prices:
    def __init__(self):
        self.cache={}
        self.records={}
        self.mapping_hash=sha256(CACHE/'ticker_history.csv')
        self.links=defaultdict(list)
        for row in csv.DictReader((CACHE/'ticker_history.csv').open()):
            if row['cik']:
                self.links[row['ticker']].append(row)

    def for_call(self,row):
        ticker=row['historical_ticker']
        if ticker not in self.cache:
            path,initial=price_path(ticker)
            values={}
            rec={'ticker':ticker,'market_data_status':'not_in_price_cache','price_source_path':'',
                 'price_source_sha256':'','price_retrieved_at_utc':'','price_first_date':'','price_last_date':'',
                 'price_provider':'Alpha Vantage TIME_SERIES_DAILY_ADJUSTED',
                 'price_source_url':'https://www.alphavantage.co/documentation/#dailyadj',
                 'price_adjustment':'provider split and dividend adjusted close'}
            rec['price_initial_response_path']=relative(initial) if path!=initial else ''
            rec['price_initial_response_sha256']=sha256(initial) if path!=initial else ''
            if path.is_file():
                data=json.loads(path.read_text())
                payload=data.get('payload',data)
                symbol=payload.get('Meta Data',{}).get('2. Symbol','')
                rec.update(price_source_path=relative(path),price_source_sha256=sha256(path),
                           price_retrieved_at_utc=data.get('fetched_at_utc',''))
                if data.get('classification') and 'Time Series (Daily)' not in payload:
                    rec['market_data_status']=data['classification']
                elif symbol.upper()!=ticker.upper():
                    rec['market_data_status']='provider_symbol_mismatch_or_unavailable'
                else:
                    for d,r in payload.get('Time Series (Daily)',{}).items():
                        value=float(r['5. adjusted close'])
                        if '2008-01-01'<=d<='2021-01-01' and np.isfinite(value) and value>0:
                            values[date.fromisoformat(d)]=value
                    rec['market_data_status']='ok' if values else 'no_prices_in_study_period'
                    if values:
                        rec.update(price_first_date=min(values).isoformat(),price_last_date=max(values).isoformat())
            self.records[ticker]=rec
            self.cache[ticker]=values
        record=dict(self.records[ticker])
        links=self.links.get(ticker,[])
        exact=[x for x in links if x['cik']==row['cik'] and x['security_id']==row['security_id']]
        if len({x['cik'] for x in links})>1:
            status='ticker_reuse_requires_price_identity_review'
        elif not exact:
            status='missing_cik_security_link'
        else:
            status='matched_historical_ticker_cik_security'
        record['price_identity_status']=status
        record['price_mapping_method']='exact historical ticker + CIK + security_id in frozen ticker history'
        record['price_mapping_sha256']=self.mapping_hash
        return self.cache[ticker],record


def run(output,mode,pilot=None,date_policy='confirmed',reuse_scores=None):
    csv.field_size_limit(100_000_000)
    if output.exists():
        raise ValueError(f'Refusing to overwrite an existing run: {output}')
    assert sha256(SOURCE)==SOURCE_HASH,'Frozen source hash changed'
    weights,risk,resolution,dict_meta=core.load_dictionaries()
    hashes=code_hashes()
    aux={relative(p):sha256(p) for p in [CACHE/'metadata.csv',CACHE/'confirmed_dates.csv',CACHE/'call_date_evidence_decisions.csv',CACHE/'sic_history.csv',CACHE/'ticker_history.csv',core.DATE_MAP,ROOT/'data/call_dates/call_dates_v20260916/source_evidence.csv']}
    aux.update({relative(p):sha256(p) for p in sorted(PRICE_CACHE.glob('*.retry01.json'))})
    if mode=='full':
        if pilot is None: raise ValueError('A passed, inspected pilot is required')
        pilot_meta=json.loads((pilot/'manifest.json').read_text())
        assert pilot_meta['pilot_validation']['passed']
        assert pilot_meta['code_hashes']==hashes,'Code changed since pilot'
        assert pilot_meta['auxiliary_input_hashes']==aux,'Auxiliary inputs changed since pilot'
        assert pilot_meta['dictionaries']==dict_meta,'Dictionaries changed since pilot'
        assert pilot_meta['date_policy']==DATE_POLICIES[date_policy], 'Date policy changed since pilot'
        assert (pilot/'INSPECTED.md').is_file(),'Inspect pilot and record review before full run'
    rows=metadata(date_policy)
    selected=pilot_selection(rows) if mode=='pilot' else {r['call_id']:'full' for r in rows}
    by_id={r['call_id']:r for r in rows if r['call_id'] in selected}
    output.mkdir(parents=True)
    write_csv(output/'selection.csv',[{'call_id':key,'selection_stratum':value} for key,value in sorted(selected.items())])
    indexes=[core.scorer.build_phrase_index(x) for x in (weights,risk,resolution)]
    scores=[]
    validations=[]
    audit_path=output/'match_audit.jsonl.gz'
    reuse_meta=None
    if reuse_scores is not None:
        prior=json.loads((reuse_scores/'manifest.json').read_text())
        verification=json.loads((reuse_scores/'verification.json').read_text())
        assert verification['passed']
        assert prior['source']['sha256_after']==SOURCE_HASH
        assert prior['dictionaries']==dict_meta
        for path in [Path(core.__file__),ROOT/'calculate_supply_chain_transcript_scores.py']:
            assert prior['code_hashes'][relative(path)]==sha256(path),'Scoring implementation changed since reusable scores'
        assert sha256(reuse_scores/'call_level_scored_car.csv')==verification['dataset_sha256']
        assert sha256(reuse_scores/'match_audit.jsonl.gz')==prior['output_sha256']['match_audit.jsonl.gz']
        reuse_meta={'directory':relative(reuse_scores),'manifest_sha256':sha256(reuse_scores/'manifest.json'),
                    'dataset_sha256':verification['dataset_sha256'],'audit_sha256':sha256(reuse_scores/'match_audit.jsonl.gz'),
                    'method':'reuse verified raw transcript scores only; recompute SD, all event returns, eligibility and portfolios'}
        if mode=='full':
            example,_=core.score_text('',weights,indexes,audit=False)
            columns=list(example)+['source_row_ordinal','source_csv_sha256','score_specification']
            columns += [f'{kind}_dictionary_{k}' for kind in dict_meta for k in ['path','sha256','version','term_count']]
            old=pd.read_csv(reuse_scores/'call_level_scored_car.csv',usecols=['call_id']+columns,keep_default_na=False,float_precision='round_trip')
            assert old.call_id.is_unique and set(old.call_id)==set(selected)
            for oldrow in old.to_dict('records'):
                r=by_id[oldrow.pop('call_id')]; r.update(oldrow); scores.append(r)
            shutil.copyfile(reuse_scores/'match_audit.jsonl.gz',audit_path)
            print('Reused verified raw scores',len(scores),flush=True)
    if not scores:
      with audit_path.open('wb') as raw, gzip.GzipFile(filename='',fileobj=raw,mode='wb',mtime=0) as zipped:
        with io.TextIOWrapper(zipped,encoding='utf-8') as audits, SOURCE.open() as source:
            for ordinal,row in enumerate(csv.DictReader(source),1):
                if row['call_id'] not in selected: continue
                assert hashlib.sha256(row['transcript_text'].encode()).hexdigest()==row['canonical_transcript_sha256'],row['call_id']
                score,matches=core.score_text(row['transcript_text'],weights,indexes,audit=True)
                if mode=='pilot':
                    reference=core.scorer.calculate_raw_scores(row['transcript_text'],weights,risk,resolution,
                                                               supply_chain_index=indexes[0],risk_index=indexes[1],resolution_index=indexes[2])
                    for key,expected in [('SCRisk_weight_sum',reference.scrisk_weight_sum),
                                         ('Resolution_weight_sum',reference.resolution_weight_sum),
                                         ('supply_chain_risk_pairs',reference.risk_pairs),
                                         ('supply_chain_resolution_pairs',reference.resolution_pairs),
                                         ('transcript_word_count',reference.word_count)]:
                        assert math.isclose(score[key],expected,rel_tol=1e-13,abs_tol=1e-13),(row['call_id'],key)
                    validations.append({'call_id':row['call_id'],'reference_scoring_agrees':True,
                                        'pair_weight_sum_recomputed':math.isclose(sum(m['weight'] for m in matches),score['SCRisk_weight_sum'])})
                r=by_id[row['call_id']]
                r.update(score,source_row_ordinal=ordinal,source_csv_sha256=SOURCE_HASH)
                for kind,details in dict_meta.items():
                    for k in ['path','sha256','version','term_count']:
                        r[f'{kind}_dictionary_{k}']=details[k]
                r['score_specification']='exact_canonical_libraries_pair_sum_distance_le_10_population_sd_no_centering_v1'
                scores.append(r)
                audits.write(json.dumps({'call_id':r['call_id'],'transcript_sha256':row['canonical_transcript_sha256'],
                                         'word_count':score['transcript_word_count'],'pairs':matches},separators=(',',':'))+'\n')
                if len(scores)%1000==0: print('Scored',len(scores),flush=True)
    assert len(scores)==len(selected)
    # v1 is already adjudicated. Older scorer heuristics remain diagnostics;
    # short valid calls are not reclassified merely because they have <1000 words.
    population=[r['validation_status']=='valid' and r['transcript_word_count']>0 for r in scores]
    for r,valid in zip(scores,population): r['score_valid']=valid
    sds={}
    for label in ['SCRisk','Resolution']:
        scaled,sd=core.scorer.normalize_raw_scores([r[label+'_raw'] for r in scores],population)
        sds[label]=sd
        for r,value in zip(scores,scaled):
            r[label]=value
            r[label+'_sd']=sd
            r['score_standardization_population']=mode+'_all_integrity_passing_source_calls'
    calendar,factors,factor_meta=core.load_factors()
    prices=Prices()
    daily=[]
    for i,r in enumerate(scores):
        p,price_meta=prices.for_call(r)
        r.update(price_meta)
        car,audit=core.carhart(r['call_date'],p,calendar,factors,audit=mode=='pilot')
        r.update(car)
        for d in audit: daily.append({'call_id':r['call_id'],**d})
        reasons=[]
        if not r['call_date']: reasons.append('missing_event_date_under_'+date_policy+'_policy')
        if not r['score_valid']: reasons.append('invalid_or_empty_source_transcript')
        if r['market_data_status']!='ok': reasons.append(r['market_data_status'])
        if r['price_identity_status']!='matched_historical_ticker_cik_security': reasons.append(r['price_identity_status'])
        base_ok=not reasons
        for window in ['0_1','2_60']:
            r[f'car_{window}_eligible']=base_ok and r[f'car_{window}_status']=='ok'
            r[f'car_{window}_exclusion_reasons']=';'.join(reasons+([] if r[f'car_{window}_status']=='ok' else [r['car_model_status'] if r['car_model_status']!='ok' else r[f'car_{window}_status']]))
        r['car_joint_eligible']=r['car_0_1_eligible'] and r['car_2_60_eligible']
        r['portfolio_eligible']=r['car_joint_eligible'] and r['sic_match_status']=='matched_point_in_time'
        all_reasons=list(dict.fromkeys(reasons+[r[f'car_{w}_status'] for w in ['0_1','2_60'] if r[f'car_{w}_status']!='ok']))
        if r['sic_match_status']!='matched_point_in_time': all_reasons.append(r['sic_match_status'])
        r['portfolio_exclusion_reasons']=';'.join(all_reasons)
        if i and i%5000==0: print('CAR gates',i,flush=True)
    frame=pd.DataFrame(scores)
    from .portfolios import build_portfolios
    frame,portfolio_manifest=build_portfolios(frame,output,make_charts=mode=='full',sample_label='Release-date event sample' if date_policy=='release' else 'Confirmed-call sample')
    frame.to_csv(output/'call_level_scored_car.csv',index=False,float_format='%.17g')
    sic_cols=['call_id','cik','quarter_label','date_fiscal_date_ending']+[c for c in frame if c.startswith('sic_')]
    frame[sic_cols].to_csv(output/'sic_point_in_time_map.csv',index=False)
    frame.loc[frame.sic_match_status!='matched_point_in_time',sic_cols].to_csv(output/'sic_missing_or_unassigned.csv',index=False)
    frame.loc[~frame.portfolio_eligible].drop(columns=[c for c in frame if c.startswith(('supply_chain_dictionary','risk_dictionary','resolution_dictionary'))]).to_csv(output/'excluded_calls.csv',index=False,float_format='%.17g')
    write_csv(output/'market_data_sources.csv',list(prices.records.values()))
    factor_frame=pd.DataFrame(factors,columns=['Mkt_RF','SMB','HML','Mom','RF'])
    factor_frame.insert(0,'date',calendar)
    factor_frame.to_csv(output/'daily_factors.csv',index=False,float_format='%.17g')
    if mode=='pilot':
        write_csv(output/'scoring_crosscheck.csv',validations)
        write_csv(output/'event_day_audit.csv',daily)
        assert sum(frame.car_joint_eligible)>=5,'Pilot needs at least five successful CAR models'
        assert (frame.loc[frame.car_model_status=='ok','estimation_observations']==200).all()
        assert (frame.loc[frame.car_0_1_status=='ok','car_0_1_observations']==2).all()
        assert (frame.loc[frame.car_2_60_status=='ok','car_2_60_observations']==59).all()
        assert (frame.loc[frame.sic_match_status=='matched_point_in_time','sic_filing_date']<=frame.loc[frame.sic_match_status=='matched_point_in_time','sic_asof_date']).all()
    gate_counts={'source_calls':len(frame),'score_integrity_pass':sum(population),
                 'confirmed_call_dates':int(frame.confirmed_call_date.ne('').sum()),
                 'event_dates_available':int(frame.call_date.ne('').sum()),
                 'point_in_time_sic_assigned':int(frame.sic_match_status.eq('matched_point_in_time').sum()),
                 'price_cache_available':int(frame.market_data_status.eq('ok').sum()),
                 'car_0_1_eligible':int(frame.car_0_1_eligible.sum()),'car_2_60_eligible':int(frame.car_2_60_eligible.sum()),
                 'car_joint_eligible':int(frame.car_joint_eligible.sum()),'portfolio_eligible':int(frame.portfolio_eligible.sum())}
    sequential=[]
    mask=pd.Series(True,index=frame.index)
    for name,condition in [('source',mask.copy()),('valid_transcript_score',frame.score_valid),
                           ('event_date_under_'+date_policy+'_policy',frame.call_date.ne('')),('price_identity',frame.price_identity_status.eq('matched_historical_ticker_cik_security')),
                           ('adjusted_prices',frame.market_data_status.eq('ok')),('car_both_windows',frame.car_joint_eligible),
                           ('historical_sic_division',frame.sic_match_status.eq('matched_point_in_time'))]:
        before=int(mask.sum()); mask &= condition
        sequential.append({'gate':name,'retained':int(mask.sum()),'excluded_at_gate':before-int(mask.sum())})
    write_csv(output/'gate_counts.csv',sequential)
    source_after=sha256(SOURCE)
    assert source_after==SOURCE_HASH
    manifest={'mode':mode,'created_at_utc':datetime.now(timezone.utc).isoformat(),
              'source':{'path':relative(SOURCE),'sha256_before':SOURCE_HASH,'sha256_after':source_after,'unchanged':True},
              'code_hashes':hashes,'auxiliary_input_hashes':aux,'dictionaries':dict_meta,'factors':factor_meta,
              'environment':{'python':platform.python_version(),'numpy':np.__version__,'pandas':pd.__version__},
              'standardization':{'method':'population SD, no centering','population':sum(population),'sd':sds},
              'score_method':{'window':10,'distance':'closest inclusive token positions <= 10','pair_sum':True,
                              'resolution':'same supply-risk pair with resolution within 10 tokens of supply span',
                              'identical_span_pairs':'included and audited','token_regex':core.scorer.WORD_RE.pattern,
                              'supply_chain_vocabulary':'canonical library only; no extra seeds or inflections',
                              'integrity':'honor v1 validation; legacy heuristic flags diagnostic only; no length-only exclusions'},
              'date_policy':DATE_POLICIES[date_policy], 'date_policy_key':date_policy,'score_reuse':reuse_meta,
              'sic_policy':'latest dated filing SIC known by actual fiscal period end; keyed by CIK+quarter_label',
              'car_method':{'estimation_offsets':[-209,-10],'observations_required':200,'intercept':True,
                            'day_0':'first Fama-French trading date on/after call_date under documented policy; no after-hours shift',
                            'windows':[[0,1],[2,60]],'car':'sum of daily stock return minus RF and fitted excess return'},
              'gate_counts':gate_counts,'sequential_gate_counts':sequential,
              'status_counts':{c:dict(Counter(str(x) for x in frame[c])) for c in ['call_date_confirmation_status','sic_match_status','car_model_status','car_0_1_status','car_2_60_status','transcript_integrity_status']},
              'portfolios':portfolio_manifest,'pilot_validation':{'passed':True,'reference_scoring_crosschecks':len(validations), 'full_run_approved_by_inspected_pilot':mode=='full'},
              'pilot_path':relative(pilot) if pilot else None,
              'pilot_manifest_sha256':sha256(pilot/'manifest.json') if pilot else None,
              'limitations':['Reconstructed dictionaries, not the authors unpublished library.',
                            DATE_POLICIES[date_policy],
                            'Historical SIC source coverage and adjusted-price coverage are incomplete.',
                            'Provider ticker histories are not a CRSP permanent security identifier.',
                            'Intervals are descriptive firm-clustered uncertainty, not controlled regressions.']}
    manifest['output_sha256']={p.name:sha256(p) for p in sorted(output.iterdir()) if p.is_file()}
    write_json(output/'manifest.json',manifest)
    print(json.dumps({'output':str(output),'gates':gate_counts},indent=2),flush=True)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('mode',choices=['pilot','full'])
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--pilot',type=Path)
    p.add_argument('--date-policy',choices=DATE_POLICIES,default='confirmed')
    p.add_argument('--reuse-scores',type=Path)
    a=p.parse_args()
    run(a.output.resolve(),a.mode,a.pilot.resolve() if a.pilot else None,a.date_policy,a.reuse_scores.resolve() if a.reuse_scores else None)


if __name__=='__main__': main()
