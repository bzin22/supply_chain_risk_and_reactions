"""Evidence gates for fiscal calendars, release dates and shared events."""
import pandas as pd
import pytest
from analysis.hardware_us400.data import map_fiscal_rows
from analysis.hardware_us400.release_dates import validate_decisions,apply_decision
from analysis.hardware_us400.rebuild_audited import PACKAGE


def decision(key='a',quarter='2014Q3'):
    return dict(call_id=key,cik='0001049521',provider_quarter_label=quarter,
                fiscal_period_label=quarter,fiscal_period_end='2014-03-31',release_date='2014-04-29',
                status='verified_correction',source_url='https://www.sec.gov/Archives/edgar/data/1049521/000104952114000007/a8-kxq32014earningsrelease.htm',
                evidence='Mercury issuer 8-K identifies fiscal Q3, March 31 end and April 29 release.',
                audit_flags='',transcript_status='matched_issuer_period')


def test_mercury_q3_cannot_reuse_august_q4():
    row=dict(call_id='a',cik='0001049521',quarter_label='2014Q3',call_date='2014-08-05')
    d=decision();validate_decisions([row],[d]);fixed=apply_decision(row,d)
    assert fixed['call_date']=='2014-04-29'
    assert fixed['date_fiscal_date_ending']=='2014-03-31'
    assert fixed['event_date_policy']=='release'


def test_no_quarter_proximity_or_annual_calendar_inference():
    payload={'annualEarnings':[{'fiscalDateEnding':'2014-06-30'}],
             'quarterlyEarnings':[{'fiscalDateEnding':'2014-06-30','reportedDate':'2014-08-05'}]}
    assert map_fiscal_rows(payload)==[]
    p=dict(quarter_label='2014Q3',fiscal_period_end='2014-03-31',source_url='https://issuer.example/release',evidence='Historical issuer quarter end')
    assert map_fiscal_rows(payload,[p])==[]


def test_historical_calendar_shift_uses_each_evidenced_period():
    periods=[dict(quarter_label=q,fiscal_period_end=end,source_url='https://issuer.example/history',evidence='Issuer historical calendar') for q,end in [('2013Q4','2013-12-31'),('2015Q3','2014-12-31')]]
    payload={'annualEarnings':[{'fiscalDateEnding':'2014-03-31'}],
             'quarterlyEarnings':[{'fiscalDateEnding':'2013-12-31','reportedDate':'2014-02-27'},{'fiscalDateEnding':'2014-12-31','reportedDate':'2015-01-29'}]}
    result=map_fiscal_rows(payload,periods)
    assert [(r['quarter_label'],r['reported_date']) for r in result]==[('2013Q4','2014-02-27'),('2015Q3','2015-01-29')]


def test_ambiguous_exact_provider_dates_stay_unresolved():
    payload={'quarterlyEarnings':[{'fiscalDateEnding':'2014-03-31','reportedDate':d} for d in ['2014-04-29','2014-08-05']]}
    p=dict(quarter_label='2014Q3',fiscal_period_end='2014-03-31',source_url='https://issuer.example',evidence='Fiscal quarter identified')
    assert map_fiscal_rows(payload,[p])==[]


def test_distinct_transcripts_same_event_require_adjudication():
    ds=[decision('a'),decision('b','2014Q4')]
    rows=[dict(call_id=d['call_id'],cik=d['cik'],quarter_label=d['provider_quarter_label']) for d in ds]
    with pytest.raises(ValueError,match='Shared issuer/event'):validate_decisions(rows,ds)
    for d in ds:d.update(collision_adjudication='Issuer confirms two separately identified releases on the same date.',collision_adjudication_url='https://issuer.example/adjudication')
    assert len(validate_decisions(rows,ds))==2


def test_correcting_collision_does_not_remove_adjudication_requirement():
    d=decision();d['audit_flags']='duplicate_issuer_release'
    with pytest.raises(ValueError,match='Original date collision'):validate_decisions([dict(call_id='a',cik=d['cik'],quarter_label='2014Q3')],[d])


def test_unresolved_and_wrong_issuer_never_acquire_dates():
    d=decision();d['transcript_status']='invalid_issuer_or_period'
    row=dict(call_id='a',cik=d['cik'],quarter_label='2014Q3')
    with pytest.raises(ValueError,match='transcript identity'):validate_decisions([row],[d])
    d.update(status='unresolved',release_date='',fiscal_period_end='',fiscal_period_label='')
    validate_decisions([row],[d]);assert apply_decision(row,d)['call_date']==''
    d['cik']='0000002488'
    with pytest.raises(ValueError,match='different issuer'):validate_decisions([row],[d])


def test_every_input_has_a_decision_and_known_fixes_are_evidenced():
    data=pd.read_csv(PACKAGE/'date_audit.csv.gz',dtype=str,keep_default_na=False)
    assert len(data)==12832 and data.call_id.is_unique
    m=data[(data.current_ticker=='MRCY') & (data.provider_quarter_label=='2014Q3')].iloc[0]
    assert m.release_date=='2014-04-29' and m.fiscal_period_end=='2014-03-31'
    v=data[(data.current_ticker=='VFC') & (data.provider_quarter_label=='2018Q1')].iloc[0]
    assert v.fiscal_period_label=='2018T' and v.release_date=='2018-05-04'
    assert data[data.status=='unresolved'].release_date.eq('').all()
    assert data[data.audit_flags.str.contains('duplicate_issuer_release')].collision_adjudication.ne('').all()
    amd=data[data.current_ticker=='AMD']
    assert len(amd)==36 and amd.transcript_status.eq('invalid_issuer_or_period').all()


def test_release_order_is_checked_after_adjudication():
    ds=[decision('a'),decision('b','2014Q4')]
    ds[1].update(fiscal_period_end='2014-04-01',release_date='2014-04-15')
    rows=[dict(call_id=d['call_id'],cik=d['cik'],quarter_label=d['provider_quarter_label']) for d in ds]
    with pytest.raises(ValueError,match='ordering'):validate_decisions(rows,ds)


def test_different_fiscal_end_window_candidates_are_adjudicated():
    p=pd.read_csv(PACKAGE/'provider_conflict_adjudications.csv',dtype=str,keep_default_na=False)
    assert len(p)==194
    assert p.observed_fiscal_end.ne(p.discarded_candidate_fiscal_ends).all()
    assert p.call_id.str.contains('DE\\|2014Q3').any()
