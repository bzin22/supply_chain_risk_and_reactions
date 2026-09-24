"""Independently reproduce pilot returns using pandas returns and SciPy OLS."""
import argparse
import bisect
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.linalg import lstsq

from analysis.primary_event_study.core import ROOT, sha256, write_json


def inspect(output):
    d=pd.read_csv(output/'call_level_scored_car.csv',keep_default_na=False,dtype={'cik':str})
    factor=pd.read_csv(output/'daily_factors.csv').set_index('date')
    assert d.call_date.eq(d.earnings_call_date).all()
    assert d.event_date_policy.eq('release').all()
    assert d.call_id.is_unique and len(d)==72
    reference=pd.read_csv(output/'scoring_crosscheck.csv')
    assert reference.reference_scoring_agrees.all() and reference.pair_weight_sum_recomputed.all()
    old=pd.read_csv(ROOT/'outputs/primary_event_study_2010_2019_v1/full/call_level_scored_car.csv',
                    usecols=['call_id','SCRisk_raw','Resolution_raw','sic_4digit','sic_match_status'],
                    dtype={'sic_4digit':str},keep_default_na=False)
    joined=d.merge(old,on='call_id',suffixes=('_new','_old'),validate='one_to_one')
    for col in ['SCRisk_raw','Resolution_raw']:
        assert np.allclose(joined[col+'_new'],joined[col+'_old'],rtol=1e-12,atol=1e-15)
    assert joined.sic_match_status_new.eq(joined.sic_match_status_old).all()
    calendar=factor.index.tolist()
    errors=[]; successful=0
    for row in d.to_dict('records'):
        if row['car_model_status']!='ok': continue
        i=bisect.bisect_left(calendar,row['earnings_call_date'])
        assert calendar[i]==row['event_trading_date']
        envelope=json.loads((ROOT/row['price_source_path']).read_text())
        assert sha256(ROOT/row['price_source_path'])==row['price_source_sha256']
        price=pd.Series({day:float(values['5. adjusted close']) for day,values in envelope['payload']['Time Series (Daily)'].items()})
        returns=price.reindex(calendar).pct_change(fill_method=None)
        excess=returns-factor.RF
        x=np.c_[np.ones(len(factor)),factor[['Mkt_RF','SMB','HML','Mom']].to_numpy()]
        a=x[i-209:i-9]; y=excess.iloc[i-209:i-9].to_numpy()
        assert len(y)==200 and np.isfinite(y).all() and np.isfinite(a).all()
        beta,_,rank,_=lstsq(a,y,lapack_driver='gelsy')
        assert rank==5 and row['estimation_observations']==200
        abnormal=excess.iloc[i:i+61].to_numpy()-x[i:i+61]@beta
        for name,interval in [('CAR_0_1',slice(0,2)),('CAR_2_60',slice(2,61))]:
            if row['car_'+name[4:]+'_status']=='ok':
                value=float(abnormal[interval].sum())
                errors.append(abs(value-float(row[name])))
                assert np.isclose(value,float(row[name]),rtol=1e-10,atol=1e-11)
        successful+=1
    assert successful>=5
    result={'passed':True,'pilot_rows':len(d),'score_reference_comparisons':len(reference),
            'independent_models':successful,'CAR_comparisons':len(errors),'maximum_absolute_CAR_error':max(errors),
            'all_release_dates_used':True,'SIC_statuses_unchanged':True,
            'source_disagreement_counts':d.date_source_agreement.value_counts().to_dict(),
            'CAR_status_counts':d.car_model_status.value_counts().to_dict(),
            'checker_sha256':sha256(Path(__file__))}
    write_json(output/'independent_review.json',result)
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('output',type=Path)
    inspect(p.parse_args().output)
