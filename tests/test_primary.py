from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from analysis.primary_event_study import core
from analysis.primary_event_study.portfolios import summarize
from analysis.primary_event_study.dates import confirm_live_call
from analysis.primary_event_study.run import apply_date_policy


def test_release_date_policy_preserves_conflict_evidence():
    row={'earnings_call_date':'2012-01-26','confirmed_call_date':'2012-01-27',
         'date_source_agreement':'conflicting','call_date_confirmation_status':'confirmed',
         'call_date_source_url':'sec-call-url','date_source_url':'release-url',
         'call_date_evidence':'Call on January 27','date_evidence_snippet':'Release on January 26'}
    apply_date_policy(row,'release')
    assert row['call_date']=='2012-01-26'
    assert row['confirmed_call_date']=='2012-01-27'
    assert row['release_date_differs_from_confirmed_call']
    assert row['date_source_agreement']=='conflicting'
    assert row['call_date_source_url']=='release-url'
    assert row['confirmed_call_date_source_url']=='sec-call-url'
    assert row['call_date_evidence']=='Release on January 26'
    assert row['confirmed_call_date_evidence']=='Call on January 27'
    row['confirmed_call_date']=''
    apply_date_policy(row,'release')
    assert row['call_date']=='2012-01-26'
    assert row['confirmed_call_date_source_url']=='sec-call-url'


def test_successful_price_retry_preserves_original(tmp_path,monkeypatch):
    import json
    from analysis.primary_event_study import run
    monkeypatch.setattr(run,'PRICE_CACHE',tmp_path)
    monkeypatch.setattr(run,'ARCHIVE',tmp_path/'archive')
    original=tmp_path/'TEST.json'; retry=tmp_path/'TEST.retry01.json'
    original.write_text(json.dumps({'classification':'provider_unavailable'}))
    retry.write_text(json.dumps({'classification':'provider_unavailable'}))
    assert run.price_path('TEST')==(original,original)
    retry.write_text(json.dumps({'classification':'ok','payload':{'Time Series (Daily)':{'2011-01-03':{}}}}))
    assert run.price_path('TEST')==(retry,original)


def test_canonical_libraries():
    weights,risk,res,manifest=core.load_dictionaries()
    assert [len(weights),len(risk),len(res)]==[254,161,55]
    assert 'help' in res and 'address' not in res
    assert 'unresolved' not in res
    assert manifest['resolution']['sha256']=='070b8cdc168a0db96db7f68fef5b0f3e08bde10ec5d7b4161ed882453a57d464'


@pytest.mark.parametrize('day,text,valid',[
    ('2016-08-10','The telephonic replay will be available from 2:00 p.m. on the day of the call through Wednesday, August 10, 2016.',False),
    ('2010-08-05','A replay of the conference call will be available through midnight CDT Thursday, Aug. 5, 2010.',False),
    ('2013-04-17','Badger Meter management will hold a conference call to discuss the company quarterly results on Wednesday, April 17, 2013 at 10:00 AM.',True),
    ('2012-01-26','There will be a conference call on January 26, 2012, at 10:30 a.m. EST during which company executives will review financial results.',True),
    ('2012-01-26','There will be a conference call on January 27, 2012.',False),
    ('2014-05-13','Real-time webcasts in May: the CFO will present at the Global Staples Summit on May 13, 2014.',False),
    ('2012-11-12','The meeting will be available via webcast. The company anticipates publishing an agenda no later than November 12, 2012.',False),
    ('2012-05-08','The company will be webcasting its Analyst Day to be held on May 8, 2012.',False),
])
def test_live_call_date_is_not_replay_expiry(day,text,valid):
    assert confirm_live_call(day,text)[0] is valid


@pytest.mark.parametrize('gap,included',[(9,True),(10,False)])
def test_multiword_proximity_boundary(gap,included):
    text='supply chain '+'filler '*gap+'risk resolved'
    weights={'supply chain':.8}; risk=['risk']; resolution=['resolved']
    indexes=[core.scorer.build_phrase_index(x) for x in (weights,risk,resolution)]
    result,audit=core.score_text(text,weights,indexes,True)
    assert result['supply_chain_risk_pairs']==int(included)
    # For gap=9, risk is distance 10 but resolution distance 11: no Resolution.
    assert result['supply_chain_resolution_pairs']==0
    assert len(audit)==int(included)


def test_pair_multiplicity_resolution_and_self_match():
    w={'supply chain':.8,'risk':.5}; risk=['risk']; res=['resolved']
    text='supply chain risk risk resolved'
    indexes=[core.scorer.build_phrase_index(x) for x in (w,risk,res)]
    result,audit=core.score_text(text,w,indexes,True)
    ref=core.scorer.calculate_raw_scores(text,w,risk,res)
    assert result['SCRisk_weight_sum']==pytest.approx(ref.scrisk_weight_sum)
    assert result['Resolution_weight_sum']==pytest.approx(ref.resolution_weight_sum)
    assert result['supply_chain_risk_pairs']==6
    assert result['scrisk_identical_span_pairs']==2
    assert sum(x['weight'] for x in audit)==pytest.approx(result['SCRisk_weight_sum'])


def test_population_sd_without_centering():
    scaled,sd=core.scorer.normalize_raw_scores([0,1,2,50],[True,True,True,False])
    assert sd==pytest.approx(np.std([0,1,2],ddof=0))
    assert scaled[0]==0 and scaled[3] is None
    assert scaled[2]==pytest.approx(2/sd)


@pytest.mark.parametrize('sic,division',[('0100','Agriculture/forestry/fishing'),('1400','Mining'),
    ('1700','Construction'),('3900','Manufacturing'),('4900','Transportation/communications/utilities'),
    ('5100','Wholesale'),('5900','Retail'),('6700','Finance/insurance/real estate'),('8900','Services'),
    ('9900','Public administration'),('1800',''),('6800',''),('9000',''),('',''),('0000','')])
def test_sic_divisions(sic,division):
    assert core.sic_division(sic)[2]==division


def test_sic_never_looks_forward():
    def obs(d,sic):
        return dict(filing_date=d,sic=sic,accession=d,source_path='p',source_sha256='h',source_url='u')
    history={'0000000001':[obs('2010-02-01','2000'),obs('2010-04-01','6000')]}
    row={'cik':'0000000001','date_fiscal_date_ending':'2010-03-31'}
    result=core.assign_sic(row,history)
    assert result['sic_4digit']=='2000'
    history[row['cik']]=[obs('2010-04-01','6000')]
    assert core.assign_sic(row,history)['sic_match_status']=='missing_historical_sic'


def fixture_market():
    dates=list(pd.bdate_range('2008-01-01',periods=350).date)
    rng=np.random.default_rng(731)
    f=np.c_[rng.normal(0,.008,(350,4)),np.full(350,.0001)]
    beta=np.array([.0003,.9,.2,-.1,.15])
    i=next(j for j in range(220,230) if dates[j].weekday()==0)
    returns=f[:,4]+np.c_[np.ones(350),f[:,:4]]@beta
    returns[i]+=.01; returns[i+1]-=.005; returns[i+2:i+61]+=.0002
    prices=dict(zip(dates,100*np.cumprod(1+returns)))
    return dates,f,beta,i,prices


def test_exact_carhart_windows_and_nontrading_call_day():
    dates,f,beta,i,prices=fixture_market()
    result,daily=core.carhart((dates[i]-timedelta(days=1)).isoformat(),prices,dates,f,True)
    assert result['event_trading_date']==dates[i].isoformat()
    assert result['day_0_calendar_lag']==1
    assert result['estimation_observations']==200
    assert result['estimation_start']==dates[i-209].isoformat()
    assert result['estimation_end']==dates[i-10].isoformat()
    assert result['CAR_0_1']==pytest.approx(.005,abs=1e-12)
    assert result['CAR_2_60']==pytest.approx(59*.0002,abs=1e-12)
    assert len(daily)==61 and result['car_2_60_observations']==59
    assert result['alpha']==pytest.approx(beta[0],abs=1e-12)


def test_missing_estimation_does_not_shorten_window():
    dates,f,_,i,prices=fixture_market()
    prices.pop(dates[i-100])
    result,_=core.carhart(dates[i].isoformat(),prices,dates,f)
    assert result['car_model_status']=='missing_estimation_prices_or_factors'
    assert result['estimation_observations']==198
    assert result['CAR_0_1'] is None


def test_missing_momentum_does_not_compress_calendar():
    dates,f,_,i,prices=fixture_market()
    f[i+2,3]=np.nan
    result,_=core.carhart(dates[i].isoformat(),prices,dates,f)
    assert result['CAR_0_1']==pytest.approx(.005,abs=1e-12)
    assert result['CAR_2_60'] is None
    assert result['car_2_60_observations']==58
    assert result['car_2_60_missing_dates']==dates[i+2].isoformat()


def test_zero_ties_and_small_groups_keep_every_observation():
    frame=pd.DataFrame({'call_id':[str(x) for x in range(13)],'portfolio_tie_key':[f'{x:04}' for x in range(13)],
                        'value':[0]*13,'division':['A']*11+['B']*2})
    bins=core.equal_count_quintiles(frame,'value',['division'])
    reverse=core.equal_count_quintiles(frame.iloc[::-1],'value',['division'])
    pd.testing.assert_series_equal(bins,reverse.reindex(bins.index))
    assert bins.notna().all()
    counts=bins[:11].value_counts()
    assert counts.max()-counts.min()==1


def test_cluster_interval_matches_cluster_mean_formula():
    g=pd.DataFrame({'CAR':[1.,1.,3.,3.],'cik':['a','a','b','b'],'scrisk_zero':[True]*4,
                    'resolution_zero':[True]*4,'sic_division':['Manufacturing']*4})
    summary=summarize(g,'CAR')
    assert summary['mean']==2
    assert summary['se_firm_clustered']==pytest.approx(1)
