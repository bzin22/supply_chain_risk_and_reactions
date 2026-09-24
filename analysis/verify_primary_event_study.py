"""Independent reconciliation of a completed primary event-study artifact set."""
from __future__ import annotations

import argparse
import hashlib
import json
import gzip
from pathlib import Path

import numpy as np
import pandas as pd


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(2**20),b''): h.update(block)
    return h.hexdigest()


def verify(output):
    output=Path(output)
    manifest=json.loads((output/'manifest.json').read_text())
    checks=[]
    def check(name,condition):
        if not bool(condition): raise AssertionError(name)
        checks.append(name)
    d=pd.read_csv(output/'call_level_scored_car.csv',dtype={'cik':str,'sic_4digit':str,'sic_2digit':str},low_memory=False)
    source_meta=pd.read_csv('artifacts/primary_event_study_2010_2019_v1/metadata.csv',dtype={'cik':str})
    check('all 58,305 v1 call IDs retained exactly once',len(d)==58305 and d.call_id.is_unique and set(d.call_id)==set(source_meta.call_id))
    check('CIK and fiscal quarter keys unique',not d.duplicated(['cik','quarter_label']).any())
    check('all validated calls have defined scores',d.SCRisk.notna().all() and d.Resolution.notna().all())
    for label,zero in [('SCRisk','scrisk_zero'),('Resolution','resolution_zero')]:
        raw=d[label+'_weight_sum']/d.transcript_word_count
        check(label+' length adjustment',np.allclose(raw,d[label+'_raw'],rtol=1e-11,atol=1e-15))
        sd=np.std(d[label+'_raw'],ddof=0)
        check(label+' full population SD',np.allclose(sd,d[label+'_sd'],rtol=1e-11,atol=1e-15))
        check(label+' scaled without centering',np.allclose(d[label+'_raw']/sd,d[label],rtol=1e-11,atol=1e-12))
        check(label+' raw zero indicator',(d[zero]==d[label+'_weight_sum'].eq(0)).all())
    if manifest.get('score_reuse'):
        score_columns=['SCRisk','Resolution','SCRisk_raw','Resolution_raw','SCRisk_sd','Resolution_sd',
                       'SCRisk_weight_sum','Resolution_weight_sum','transcript_word_count',
                       'supply_chain_risk_pairs','supply_chain_resolution_pairs','scrisk_zero','resolution_zero']
        prior_dir=Path(manifest['score_reuse']['directory'])
        prior=pd.read_csv(prior_dir/'call_level_scored_car.csv',usecols=['call_id']+score_columns)
        compared=d.merge(prior,on='call_id',suffixes=('_current','_prior'),validate='one_to_one')
        for col in score_columns:
            check('raw or standardized score preserved '+col,np.allclose(compared[col+'_current'],compared[col+'_prior'],rtol=1e-12,atol=1e-15))
    check('Resolution remains subset of SCRisk',(d.Resolution_weight_sum<=d.SCRisk_weight_sum+1e-12).all())
    fitted=d[d.car_model_status=='ok']
    check('all fitted models use exactly 200 observations',fitted.estimation_observations.eq(200).all())
    check('all fitted models have rank 5',fitted.estimation_rank.eq(5).all())
    calendar=pd.read_csv(output/'daily_factors.csv').date.tolist()
    positions={v:i for i,v in enumerate(calendar)}
    check('every fitted estimation window is -209 through -10',all(positions[r.estimation_start]==positions[r.event_trading_date]-209 and positions[r.estimation_end]==positions[r.event_trading_date]-10 for r in fitted.itertuples()))
    check('day zero is first factor-calendar day on/after selected event date',all(r.event_trading_date>=r.call_date and calendar[positions[r.event_trading_date]-1]<r.call_date for r in fitted.itertuples()))
    if manifest.get('date_policy_key')=='release':
        check('all release dates used as instructed',d.call_date.eq(d.earnings_call_date).all())
        check('release date provenance retained',d.event_date_source_field.eq('earnings_call_date').all())
        check('event-date source URL follows release date',d.call_date_source_url.fillna('').eq(d.date_source_url.fillna('')).all())
        check('event-date evidence follows release date',d.call_date_evidence.fillna('').eq(d.date_evidence_snippet.fillna('')).all())
        check('selected source hash identifies unchanged v1',d.call_date_source_sha256.eq(manifest['source']['sha256_before']).all())
        source_join=d.merge(source_meta,on='call_id',suffixes=('_output','_source'),validate='one_to_one')
        for field in ['earnings_call_date','date_source_agreement','date_source_url','date_response_sha256']:
            check('v1 date evidence unchanged '+field,source_join[field+'_output'].fillna('').eq(source_join[field+'_source'].fillna('')).all())
    for window,n in [('0_1',2),('2_60',59)]:
        ok=d[d['car_'+window+'_status']=='ok']
        check('CAR '+window+' complete event window',ok['car_'+window+'_observations'].eq(n).all() and np.isfinite(ok['CAR_'+window]).all())
        excluded=d[~d['car_'+window+'_eligible']]
        check('CAR '+window+' every exclusion has a reason',excluded['car_'+window+'_exclusion_reasons'].notna().all())
    classified=d[d.sic_match_status=='matched_point_in_time']
    check('SIC has four digits and two-digit prefix',classified.sic_4digit.str.fullmatch(r'\d{4}').all() and (classified.sic_4digit.str[:2]==classified.sic_2digit).all())
    check('no SIC filing is after its information cutoff',(classified.sic_filing_date<=classified.sic_asof_date).all())
    missing=pd.read_csv(output/'sic_missing_or_unassigned.csv')
    check('all unassigned SIC calls reported',len(missing)==len(d)-len(classified))
    p=d[d.portfolio_eligible].copy()
    check('portfolio sample requires both CARs and SIC',p.car_joint_eligible.all() and p.sic_match_status.eq('matched_point_in_time').all())
    check('all portfolio rows have both quintiles',p[['SCRisk_quintile','Resolution_quintile']].notna().all().all())
    for label in ['SCRisk','Resolution','CAR_0_1','CAR_2_60']:
        lo,hi=np.quantile(p[label],[.01,.99],method='linear')
        check(label+' winsorization independently reproduced',np.allclose(p[label].clip(lo,hi),p[label+'_winsor'],rtol=1e-11,atol=1e-12))
    for variable,groups in [('SCRisk_quintile',['sic_division']),('Resolution_quintile',['sic_division','SCRisk_quintile'])]:
        for _,group in p.groupby(groups):
            counts=group[variable].value_counts().reindex(range(1,6),fill_value=0)
            check(variable+' group balance '+str(group.index[0]),counts.max()-counts.min()<=1)
    for name,q,car in [('01_car_0_1_by_scrisk','SCRisk_quintile','CAR_0_1'),('02_car_0_1_by_resolution','Resolution_quintile','CAR_0_1'),('04_car_2_60_by_scrisk','SCRisk_quintile','CAR_2_60')]:
        table=pd.read_csv(output/(name+'.csv'))
        check(name+' counts reconcile',table.n.sum()==len(p))
        for row in table.to_dict('records'):
            subset=p[p[q]==row[q]]
            check(name+' mean '+str(row[q]),np.isclose(subset[car+'_winsor'].mean(),row['mean'],atol=1e-12))
    for name in ['03_car_0_1_heatmap','05_car_2_60_heatmap']:
        table=pd.read_csv(output/(name+'.csv'))
        check(name+' has 25 cells and reconciles',len(table)==25 and table.n.sum()==len(p))
        car='CAR_0_1_winsor' if name.startswith('03') else 'CAR_2_60_winsor'
        for row in table.to_dict('records'):
            group=p[(p.SCRisk_quintile==row['SCRisk_quintile'])&(p.Resolution_quintile==row['Resolution_quintile'])]
            check(name+' mean '+str((row['SCRisk_quintile'],row['Resolution_quintile'])),np.isclose(group[car].mean(),row['mean'],atol=1e-12,equal_nan=True))
    audit_ids=set()
    lookup=d.set_index('call_id').to_dict('index')
    audit_ok=True
    for line in gzip.open(output/'match_audit.jsonl.gz','rt'):
        audit=json.loads(line); row=lookup[audit['call_id']]
        audit_ok &= audit['call_id'] not in audit_ids
        audit_ids.add(audit['call_id'])
        pairs=audit['pairs']
        audit_ok &= len(pairs)==row['supply_chain_risk_pairs']
        audit_ok &= sum(bool(x['resolution']) for x in pairs)==row['supply_chain_resolution_pairs']
        audit_ok &= np.isclose(sum(x['weight'] for x in pairs),row['SCRisk_weight_sum'],atol=1e-12)
        audit_ok &= np.isclose(sum(x['weight'] for x in pairs if x['resolution']),row['Resolution_weight_sum'],atol=1e-12)
        for pair in pairs:
            a,b=pair['supply_span'],pair['risk_span']
            audit_ok &= max(a[0]-b[1],b[0]-a[1],0)<=10
            for resolution in pair['resolution']:
                b=resolution['span']
                audit_ok &= max(a[0]-b[1],b[0]-a[1],0)<=10
    check('all match audits reproduce counts weights and proximity',audit_ok and audit_ids==set(d.call_id))
    for filename,expected in manifest['output_sha256'].items():
        check('output hash '+filename,digest(output/filename)==expected)
    for kind,record in manifest['dictionaries'].items():
        check(kind+' dictionary hash',digest(record['path'])==record['sha256'])
        check(kind+' dictionary hash recorded on every row',d[kind+'_dictionary_sha256'].eq(record['sha256']).all())
    pilot_dir=Path(manifest['pilot_path']) if manifest.get('pilot_path') else output.parent/'pilot_03'
    pilot=pd.read_csv(pilot_dir/'call_level_scored_car.csv')
    joined=d.merge(pilot,on='call_id',suffixes=('_full','_pilot'),validate='one_to_one')
    for col in ['SCRisk_raw','Resolution_raw','SCRisk_weight_sum','Resolution_weight_sum']:
        check('pilot/full agreement '+col,np.allclose(joined[col+'_full'],joined[col+'_pilot'],rtol=1e-11,atol=1e-14))
    check('immutable v1 source hash',digest(manifest['source']['path'])==manifest['source']['sha256_before'])
    result={'passed':True,'checks_passed':len(checks),'checks':checks,'rows':len(d),'portfolio_rows':len(p),
            'dataset_sha256':digest(output/'call_level_scored_car.csv'),'verifier_sha256':digest(__file__)}
    (output/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='checks'},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('output',type=Path)
    verify(parser.parse_args().output)
