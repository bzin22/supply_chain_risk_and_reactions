"""Portable hardware baseline contracts; no provider access or raw inputs."""
import json
from pathlib import Path
from urllib.parse import urlsplit, parse_qsl
import numpy as np
import pandas as pd
import pytest
from analysis import hardware_reproduction as hw


@pytest.fixture(scope='module')
def loaded():
    return hw.load_package()


def test_roster_is_distinct_from_screen_and_analysis_representation(loaded):
    data,sample,config=loaded
    assert len(data)==12832 and len(sample)==12744
    roster=pd.read_csv(hw.PACKAGE/'roster_379.csv',dtype=str,keep_default_na=False)
    screen=pd.read_csv(hw.PACKAGE/'screened_universe_400.csv',dtype=str,keep_default_na=False)
    assert len(roster)==379 and len(screen)==400
    assert set(roster.portfolio_cik)==set(sample.portfolio_cik)
    assert set(roster.portfolio_cik)<set(screen.portfolio_cik)
    for field in ['portfolio_cik','historical_cik','aliases','hardware_classification','physical_products','product_evidence_url','headquarters_source_url','company_screen_asof','study_first_quarter','study_last_quarter']:
        assert roster[field].ne('').all(),field
    assert roster.portfolio_cik.str.fullmatch(r'\d{10}').all()


def test_export_contains_no_raw_text_prices_or_credentials(loaded):
    data,_,_=loaded
    forbidden={'transcript_text','content','text','date_evidence_snippet','call_date_evidence','confirmed_call_date_evidence','raw_path','price_source_path','stock_return','adjusted_close'}
    assert not forbidden.intersection(data.columns)
    for col in [c for c in data if c.endswith('_url')]:
        for url in set(data[col]):
            assert not urlsplit(url).username
            assert not {k.lower() for k,v in parse_qsl(urlsplit(url).query)}.intersection({'apikey','api_key','token','access_token'})
    schema=json.loads((hw.PACKAGE/'schema.json').read_text())
    assert list(data)==schema['columns']
    raw=json.loads((hw.PACKAGE/'private_inputs.json').read_text())
    assert all(not r['redistributed'] and not Path(r['path']).is_absolute() for r in raw)
    assert not (hw.ROOT/'data/final/earnings_call_transcripts_validated_2010_2019_v1.csv').exists()


def test_score_scaling_and_release_policy(loaded):
    data,_,_=loaded
    assert data.call_date.eq(data.earnings_call_date).all()
    assert data.event_date_policy.eq('release').all()
    for metric in ['SCRisk','Resolution']:
        raw=data[metric+'_raw'].to_numpy(float)
        sd=np.std(raw,ddof=0)
        np.testing.assert_allclose(data[metric].to_numpy(float),raw/sd,rtol=1e-13,atol=1e-13)
    assert data.scrisk_zero.sum()==3553
    assert data.resolution_zero.sum()==10710


def test_pair_coverage_and_year_tables_reconcile(loaded):
    data,sample,_=loaded
    pair=pd.read_csv(hw.PACKAGE/'pair_coverage.csv.gz',dtype=str,keep_default_na=False)
    assert len(pair)==16000 and not pair.duplicated(['portfolio_cik','quarter_label']).any()
    assert pair.call_id.isin(data.call_id).sum()==12832
    years=pd.read_csv(hw.REFERENCE/'coverage_by_year.csv',dtype={'fiscal_year':str})
    for row in years.itertuples():
        valid=data[data.quarter_label.str.startswith(row.fiscal_year)]
        retained=sample[sample.quarter_label.str.startswith(row.fiscal_year)]
        assert len(valid)==row.valid_calls and len(retained)==row.retained_calls
        assert retained.portfolio_cik.nunique()==row.retained_firms
    assert (len(data)-len(sample))==88


def test_tampered_reference_table_fails(tmp_path):
    a=tmp_path/'actual.csv';b=tmp_path/'reference.csv'
    a.write_text('portfolio,mean\nQ1,0.01\n');b.write_text('portfolio,mean\nQ1,0.02\n')
    with pytest.raises(AssertionError):hw.compare_table(a,b)


def test_no_overwrite(tmp_path):
    with pytest.raises(FileExistsError):hw.reproduce(hw.PACKAGE,tmp_path)
