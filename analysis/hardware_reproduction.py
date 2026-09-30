"""Offline reproduction of the reviewed hardware baseline from derived call data.

This starts after transcript scoring and daily-price regression. The committed
raw-stage driver and hashed private-input inventory document those stages;
private transcripts and provider price histories are never fetched here.
"""
from __future__ import annotations
import argparse
import ast
import json
from pathlib import Path
import numpy as np
import pandas as pd
from analysis.primary_event_study import core
from analysis.hardware_us400.run import render

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'reproduction/hardware_baseline_v1'
REFERENCE = ROOT / 'docs/hardware_baseline'


def verify_equivalence(package):
    for record in json.loads((package/'method_equivalence.json').read_text()):
        trees=[]
        for field, digest in [('original_snapshot','original_sha256'),('active_module','active_sha256')]:
            path=ROOT/record[field]
            if core.sha256(path)!=record[digest]:
                raise ValueError(f'Method source hash mismatch: {path}')
            trees.append({n.name:ast.dump(n,include_attributes=False) for n in ast.parse(path.read_text()).body
                          if isinstance(n,(ast.FunctionDef,ast.ClassDef))})
        for name in record['identical_definitions']:
            if trees[0][name]!=trees[1][name]:
                raise ValueError(f'Approved method definition changed: {name}')


def load_package(package=PACKAGE):
    manifest=json.loads((package/'manifest.json').read_text())
    for path,digest in manifest['files'].items():
        p=ROOT/path
        if not p.is_file() or core.sha256(p)!=digest:
            raise ValueError(f'Missing file or SHA-256 mismatch: {path}')
    verify_equivalence(package)
    config=json.loads((package/'config.json').read_text())
    schema=json.loads((package/'schema.json').read_text())
    data=pd.read_csv(package/'calls.csv.gz',dtype={c:str for c in schema['string_columns']},
                     keep_default_na=False,float_precision='round_trip',low_memory=False)
    if data.columns.tolist()!=schema['columns'] or not data.call_id.is_unique:
        raise ValueError('Unexpected call schema or duplicate stable identifiers')
    if len(data)!=config['counts']['input_calls'] or data.cik.nunique()!=config['counts']['input_firms']:
        raise ValueError('Call/firm coverage changed')
    if data.duplicated(['portfolio_cik','quarter_label']).any() or not data.quarter_label.str.fullmatch(r'201[0-9]Q[1-4]').all():
        raise ValueError('Duplicate issuer-quarter or quarter outside the study')
    from analysis.hardware_us400.release_dates import validate_decisions, ACCEPTED
    audit=pd.read_csv(package/'date_audit.csv.gz',dtype=str,keep_default_na=False)
    decisions=validate_decisions(data.to_dict('records'),audit.to_dict('records'))
    for r in data.to_dict('records'):
        d=decisions[r['call_id']]
        if r['date_audit_status']!=d['status'] or r['call_date']!=d['release_date'] or r['date_fiscal_date_ending']!=d['fiscal_period_end']:
            raise ValueError('Canonical data differs from date adjudication')
        if d['status'] not in ACCEPTED and (r['portfolio_eligible'] or r['call_date']):
            raise ValueError('Unresolved mapping entered CAR analysis')
        if d['transcript_status'] in {'invalid_issuer_or_period','unresolved_period'} and r['score_valid']:
            raise ValueError('Invalid issuer-period included in score population')
    for col in schema['boolean_columns']:
        # Legacy disagreement flags can be absent for new supplemental calls.
        if col in ['reported_date_source_disagreement','release_date_differs_from_confirmed_call']:
            if not data[col].isin([True,False,'True','False','']).all():raise ValueError(col)
        elif data[col].dtype!=bool:
            raise ValueError(f'Nonboolean eligibility/score flag: {col}')
    if not data.event_date_policy.eq('release').all() or not data.call_date.eq(data.earnings_call_date).all():
        raise ValueError('Release-event policy changed')
    if config['scaling']!={'ddof':0,'centered':False,'population':'all valid calls before CAR gates'}:
        raise ValueError('Unsupported scaling configuration')
    if config['winsorization']!={'quantiles':[0.01,0.99],'method':'linear','population':'common eligible sample'}:
        raise ValueError('Unsupported winsorization configuration')
    if config['allocation']['method']!='fractional_ties_within_SIC_division_then_nested_Resolution':
        raise ValueError('Unsupported portfolio allocation')
    # Shared helpers implement these choices; reject drift rather than ignoring it.
    expected=json.loads((package/'method_contract.json').read_text())
    for key in ['event_policy','carhart','industry','allocation','scoring']:
        if config[key]!=expected[key]:raise ValueError(f'Unsupported method configuration: {key}')
    _,_,_,dictionaries=core.load_dictionaries()
    if dictionaries!=config['dictionaries']:raise ValueError('Canonical dictionaries changed')
    for name in ['SCRisk','Resolution']:
        raw=pd.to_numeric(data[name+'_raw'],errors='raise').to_numpy(float)
        sd=float(np.std(raw[data.score_valid.to_numpy()],ddof=0))
        np.testing.assert_allclose(sd,config['expected_scaling_sd'][name],atol=1e-18,rtol=1e-13)
        np.testing.assert_allclose(pd.to_numeric(data[name+'_sd']),sd,atol=1e-18,rtol=1e-13)
        np.testing.assert_allclose(pd.to_numeric(data[name]),raw/sd,atol=1e-13,rtol=1e-13)
        # Recompute rather than trusting archived standardized fields.
        data[name]=raw/sd
    base=(data.score_valid & data.call_date.ne('') & data.market_data_status.eq('ok') &
          data.price_identity_status.eq('matched_historical_ticker_cik_security'))
    for window in ['0_1','2_60']:
        derived=base & data['car_'+window+'_status'].eq('ok')
        if not derived.equals(data['car_'+window+'_eligible']):raise ValueError('CAR eligibility mismatch')
    joint=data.car_0_1_eligible & data.car_2_60_eligible
    eligible=joint & data.sic_match_status.eq('matched_point_in_time')
    if not joint.equals(data.car_joint_eligible) or not eligible.equals(data.portfolio_eligible):
        raise ValueError('Common eligibility differs from documented gates')
    roster=pd.read_csv(package/'roster_379.csv',dtype=str,keep_default_na=False)
    if len(roster)!=379 or roster.portfolio_cik.nunique()!=379:
        raise ValueError('Canonical reporting roster changed')
    sample=data.loc[eligible].copy().reset_index(drop=True)
    if len(sample)!=config['counts']['eligible_calls'] or sample.portfolio_cik.nunique()!=config['counts']['eligible_firms'] or not set(sample.portfolio_cik).issubset(set(roster.portfolio_cik)):
        raise ValueError('Analysis representation differs from canonical roster')
    for name in ['SCRisk','Resolution','CAR_0_1','CAR_2_60']:
        sample[name]=pd.to_numeric(sample[name],errors='raise')
    if not np.isfinite(sample[['SCRisk','Resolution','CAR_0_1','CAR_2_60']].to_numpy()).all():raise ValueError('Nonfinite eligible input')
    return data,sample,config


def compare_table(actual, expected):
    a=pd.read_csv(actual,float_precision='round_trip',keep_default_na=False)
    b=pd.read_csv(expected,float_precision='round_trip',keep_default_na=False)
    if a.columns.tolist()!=b.columns.tolist() or a.shape!=b.shape:
        raise ValueError(f'Reference table schema/shape differs: {expected.name}')
    for c in a:
        if pd.api.types.is_numeric_dtype(a[c]) and pd.api.types.is_numeric_dtype(b[c]):
            np.testing.assert_allclose(a[c],b[c],rtol=1e-12,atol=1e-13,err_msg=f'{expected.name}:{c}')
        elif not a[c].equals(b[c]):raise ValueError(f'Reference labels differ: {expected.name}:{c}')


def reproduce(package,output):
    if output.exists():raise FileExistsError(f'Refusing to overwrite {output}')
    data,sample,config=load_package(package)
    output.mkdir(parents=True)
    result=render(output,sample)
    expected=list(REFERENCE.glob('[0-9][0-9]_*.csv'))+[REFERENCE/'portfolio_comparisons.csv',REFERENCE/'winsorization_thresholds.csv',REFERENCE/'zero_tie_audit.csv']
    for p in expected:compare_table(output/p.name,p)
    summary={'input_calls':len(data),'input_firms':int(data.portfolio_cik.nunique()),'score_valid_calls':int(data.score_valid.sum()),'date_audit_verified':True,
             'canonical_roster_firms':379,'screened_universe_firms':400,**result,
             'reference_tables_verified':len(expected),'five_panels_verified':5,
             'scaling_recomputed':True,'common_eligibility_recomputed':True,
             'winsorization_and_fractional_allocation_recomputed':True,
             'portfolio_comparisons_recomputed':True,
             'raw_scoring_and_CAR_refit':False,'network_access_required':False}
    core.write_json(output/'verification.json',summary)
    print(json.dumps(summary,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--package',type=Path,default=PACKAGE)
    p.add_argument('--output',type=Path,default=ROOT/'outputs/hardware_baseline_reproduction_v1')
    a=p.parse_args();reproduce(a.package.resolve(),a.output.resolve())
