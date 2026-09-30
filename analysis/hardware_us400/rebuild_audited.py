"""Refit the audited hardware baseline using local, hashed private inputs only.

No collection and no date inference occur here. The public decision ledger is
required for every call. Unresolved issuer-period events are blank and excluded.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
from datetime import date
import gzip
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from analysis.primary_event_study import core
from .release_dates import apply_decision, validate_decisions, ACCEPTED
from .inventory import payload_text
from .sic import AVGO_EVIDENCE
from .run import render

PACKAGE=Path(__file__).resolve().parents[2]/'reproduction/hardware_baseline_v1'
PRIVATE='artifacts/hardware_fiscal_date_audit_20260930'


def read(path):
    return pd.read_csv(path,dtype=str,keep_default_na=False).to_dict('records')


def sic_history(root):
    h=defaultdict(list)
    for path in ['artifacts/primary_event_study_2010_2019_v1/sic_history.csv',
                 'artifacts/hardware_portfolio_us400_2010_2019_v1/supplemental_sic_history.csv']:
        for row in read(root/path):h[row['cik']].append(row)
    chain=[]
    for cik,lo,hi in [('0001441634','0000-01-01','2016-01-31'),('0001649338','2016-02-01','2018-04-03'),('0001730168','2018-04-04','9999-12-31')]:
        chain.extend(r for r in h[cik] if lo<=r['filing_date']<=hi)
    h['0001730168']=chain
    return h


def load_prices(root,row,cache):
    key=row.get('price_source_path','')
    if not key:return {}
    if key not in cache:
        path=root/key
        if core.sha256(path)!=row['price_source_sha256']:raise ValueError('Private price hash mismatch')
        wrapped=json.loads(path.read_text());payload=wrapped.get('payload',wrapped)
        values={date.fromisoformat(d):float(v['5. adjusted close']) for d,v in payload.get('Time Series (Daily)',{}).items()
                if '2008-01-01'<=d<='2021-01-01' and np.isfinite(float(v['5. adjusted close'])) and float(v['5. adjusted close'])>0}
        cache[key]=values
    return cache[key]


def rebuild(root,output,pilot=False,rescore=False):
    if output.exists():raise FileExistsError(output)
    source=root/PRIVATE/'refit_inputs.csv.gz'
    expected=json.loads((PACKAGE/'audit_input_contract.json').read_text())
    for relative,digest in expected['private_files'].items():
        if core.sha256(root/relative)!=digest:raise ValueError('Input hash mismatch: '+relative)
    rows=read(source)
    decisions=read(PACKAGE/'date_audit.csv.gz')
    lookup=validate_decisions(rows,decisions)
    schema=json.loads((PACKAGE/'schema.json').read_text())
    if pilot:
        # Bounded outcome-blind pilot: all Mercury, other calendar corrections,
        # collision members, and first 20 unaffected records.
        ids={d['call_id'] for d in decisions if d['status']=='verified_correction' or d['collision_adjudication']}
        ids.update(d['call_id'] for d in decisions if d['current_ticker']=='MRCY')
        ids.update(r['call_id'] for r in rows[:20])
        rows=[r for r in rows if r['call_id'] in ids]
    weights,risk,res,dicts=core.load_dictionaries()
    indexes=[core.scorer.build_phrase_index(v) for v in [weights,risk,res]]
    for i,row in enumerate(rows):
        d=lookup[row['call_id']]
        rows[i]=row=apply_decision(row,d)
        for col in schema['boolean_columns']:row[col]=str(row.get(col,''))=='True'
        row['score_valid']=row['score_valid'] and d['transcript_status'] not in {'invalid_issuer_or_period','unresolved_period'}
        row['validation_status']='valid' if row['score_valid'] else d['transcript_status']
        if rescore:
            p=root/row['raw_path'];wrapped=json.loads(p.read_text());text=payload_text(wrapped.get('payload',wrapped))
            if hashlib.sha256(text.encode()).hexdigest()!=row['canonical_transcript_sha256']:raise ValueError('Transcript hash mismatch')
            scores,_=core.score_text(text,weights,indexes)
            for metric in ['SCRisk_raw','Resolution_raw']:
                np.testing.assert_allclose(scores[metric],float(row[metric]),rtol=1e-12,atol=1e-15)
            row.update(scores)
        for name in ['SCRisk','Resolution']:row[name+'_raw']=float(row[name+'_raw'])
    for metric in ['SCRisk','Resolution']:
        sd=float(np.std([r[metric+'_raw'] for r in rows if r['score_valid']],ddof=0))
        for r in rows:r[metric]=r[metric+'_raw']/sd;r[metric+'_sd']=sd
    archive=root/'.archive/post_2019_removed_20260916/artifacts/earnings_call_supply_chain/ppmi_svd_full_20260910/event_study_inputs/fama_french'
    ff=core.parse_factor_rows(archive/'fama_french_daily.zip','percent',4)
    mom=core.parse_factor_rows(archive/'momentum_daily.zip','percent',1)
    cal=sorted(d for d in ff if date(2008,1,1)<=d<=date(2021,1,1))
    factors=np.array([[*ff[d][:3],mom.get(d,[np.nan])[0],ff[d][3]] for d in cal])
    h=sic_history(root);cache={};changes=[]
    output.mkdir(parents=True)
    for row in rows:
        d=lookup[row['call_id']]
        # Clear all stale model diagnostics before a missing event can return early.
        for k in list(row):
            if k.startswith(('estimation_','beta_','car_','CAR_')) or k in ['alpha','event_trading_date','day_0_calendar_lag']:
                row[k]=''
        row.update(core.assign_sic(row,h))
        prices=load_prices(root,row,cache)
        if not prices:row['market_data_status']='no_valid_cached_prices'
        result,_=core.carhart(row['call_date'],prices,cal,factors)
        row.update(result)
        if d['status'] not in ACCEPTED:
            row.update(car_model_status='unresolved_release_mapping',car_0_1_status='unresolved_release_mapping',car_2_60_status='unresolved_release_mapping')
        base=[]
        if not row['call_date']:base.append('unresolved_release_mapping')
        if not row['score_valid']:base.append(row['validation_status'])
        if row['market_data_status']!='ok':base.append(row['market_data_status'])
        if row['price_identity_status']!='matched_historical_ticker_cik_security':base.append(row['price_identity_status'])
        for w in ['0_1','2_60']:row['car_'+w+'_eligible']=not base and row['car_'+w+'_status']=='ok'
        row['car_joint_eligible']=row['car_0_1_eligible'] and row['car_2_60_eligible']
        row['portfolio_eligible']=row['car_joint_eligible'] and row['sic_match_status']=='matched_point_in_time'
        row['portfolio_exclusion_reasons']=';'.join(dict.fromkeys(base+[row['car_'+w+'_status'] for w in ['0_1','2_60'] if row['car_'+w+'_status']!='ok']+([] if row['sic_match_status']=='matched_point_in_time' else [row['sic_match_status']])))
    frame=pd.DataFrame(rows)
    frame.to_csv(output/'private_refit_results.csv.gz',index=False,float_format='%.17g',compression={'method':'gzip','mtime':0})
    # Strict public allowlist; no raw transcript, price observations or private paths.
    public=frame.reindex(columns=schema['columns'])
    public.to_csv(output/'calls.csv.gz',index=False,float_format='%.17g',compression={'method':'gzip','mtime':0})
    sample=frame.loc[frame.portfolio_eligible].copy()
    result=render(output,sample)
    summary={'input_calls':len(frame),'score_valid_calls':int(frame.score_valid.sum()),'input_firms':int(frame.cik.nunique()),**result,'rescore_verified':rescore,'CAR_refit':True,'SIC_reassigned':True,'network_requests':0,'scaling_sd':{m:float(frame[m+'_sd'].iloc[0]) for m in ['SCRisk','Resolution']},'dictionaries':dicts,'decision_sha256':core.sha256(PACKAGE/'date_audit.csv.gz'),'input_sha256':core.sha256(source)}
    core.write_json(output/'audit_rebuild_verification.json',summary)
    print(json.dumps(summary,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--private-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--pilot',action='store_true');p.add_argument('--rescore',action='store_true');a=p.parse_args()
    rebuild(a.private_root.resolve(),a.output.resolve(),a.pilot,a.rescore)
