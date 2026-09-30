"""Add explicit primary-source dates without changing release-event policy."""
import argparse,re
from pathlib import Path
from bs4 import BeautifulSoup
from analysis.hardware_us400.inventory import ART,FINAL,read
from analysis.hardware_us400.sic import history,assign
from analysis.primary_event_study import core
from analysis.primary_event_study.run import apply_date_policy


def enrich(source,output):
    assert not output.exists(), 'Choose a new prepared-input version'
    dates=read(ART/'ir_dates/resolved_release_dates.csv')
    archive=ART/'ir_dates/hubbell_archive.html'
    corroboration=ART/'ir_dates/04-21-11.html'
    body=re.sub(r'\s+',' ',BeautifulSoup(corroboration.read_text(),'html.parser').get_text(' ',strip=True))
    assert 'Three Months Ended March 31 2011 2010' in body
    announcement=re.sub(r'\s+',' ',BeautifulSoup(archive.read_text(),'html.parser').get_text(' ',strip=True))
    assert 'first quarter 2010 financial results prior to the opening of the market on April 22, 2010' in announcement
    dates.append(dict(ticker='HUBB',cik='0000048898',quarter_label='2010Q1',fiscal_date_ending='2010-03-31',reported_date='2010-04-22',source_url='https://hubbell.gcs-web.com/news-releases',source_path=core.relative(archive),source_sha256=core.sha256(archive),match_method='company_IR_release_archive_and_call_announcement; fiscal_end_corroborated_by_explicit_2010_comparative_income_statement',confirmed_call_date='2010-04-22',fiscal_corrob_path=core.relative(corroboration),fiscal_corrob_sha256=core.sha256(corroboration)))
    by={(d['cik'],d['quarter_label']):d for d in dates}
    h=history();rows=read(source);audit=[]
    for r in rows:
        d=by.get((r['cik'],r['quarter_label']))
        if not d or r.get('call_date'):continue
        assert r['transcript_origin']!='frozen_v1'
        assert core.sha256(core.ROOT/d['source_path'])==d['source_sha256']
        r.update(earnings_call_date=d['reported_date'],date_fiscal_date_ending=d['fiscal_date_ending'],date_status='reported_date_mapped_primary_company_IR',date_source_url=d['source_url'],date_evidence_path=d['source_path'],date_evidence_sha256=d['source_sha256'],date_response_sha256=d['source_sha256'],date_match_method=d['match_method'],date_source_title='Hubbell official quarterly results release',date_report_time='pre-market' if d['quarter_label']=='2010Q1' else '',date_source_agreement='company_IR_explicit_period_and_release')
        if d.get('fiscal_corrob_path'):
            r.update(fiscal_period_corroboration_path=d['fiscal_corrob_path'],fiscal_period_corroboration_sha256=d['fiscal_corrob_sha256'])
        if d.get('confirmed_call_date'):
            r.update(confirmed_call_date=d['confirmed_call_date'],call_date_confirmation_status='independently_confirmed_company_IR_call_schedule',confirmed_call_date_source_path=d['source_path'],confirmed_call_date_source_sha256=d['source_sha256'],confirmed_call_date_source_url=d['source_url'],confirmed_call_date_evidence='Company announcement explicitly schedules the first-quarter 2010 results call at 10 AM ET on April 22, 2010.')
        apply_date_policy(r,'release')
        r.update(call_date_source_path=d['source_path'],call_date_source_sha256=d['source_sha256'])
        r.update(assign(r,h));audit.append({'call_id':r['call_id'],**d})
    core.write_csv(output,rows)
    core.write_csv(ART/(output.stem+'_IR_enrichment.csv'),audit)
    print('Primary-source release dates added:',len(audit),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',type=Path,default=FINAL/'prepared_calls.csv');p.add_argument('--output',type=Path,default=FINAL/'prepared_enriched_calls.csv');a=p.parse_args();enrich(a.input,a.output)
