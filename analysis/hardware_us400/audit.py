"""Read-only all-call fiscal/date diagnostics; flags never establish a new date.

Use --calls for the dataset being audited. Private JSON transcripts and SEC
SUB indexes are read locally. No SEC/IR or provider requests are made. Decisions
remain in date_audit.csv.gz and require evidence/adjudication separately.
"""
import argparse
from collections import defaultdict
from datetime import date
import json
from pathlib import Path
import re
import pandas as pd
from dateutil.parser import parse
from .rebuild_audited import PRIVATE

QUARTERS={'first':'1','second':'2','third':'3','fourth':'4','1st':'1','2nd':'2','3rd':'3','4th':'4','1':'1','2':'2','3':'3','4':'4'}
QUARTER=re.compile(r'(?:(first|second|third|fourth|[1-4](?:st|nd|rd|th)?)\s+(?:fiscal\s+)?quarter(?:\s+of)?(?:\s+(?:the\s+)?(?:fiscal\s+)?(?:year\s+)?)?\s*(20\d\d)|(?:fiscal\s+)?(20\d\d)\s+(?:fiscal\s+)?(first|second|third|fourth|[1-4](?:st|nd|rd|th)?)\s+quarter|Q([1-4])(?:\s+of)?\s+(?:fiscal\s+)?(20\d\d))',re.I)


def diagnostics(calls,private_root):
    refs=pd.read_csv(private_root/PRIVATE/'refit_inputs.csv.gz',dtype=str,keep_default_na=False).set_index('call_id')
    by_end=defaultdict(list);by_label=defaultdict(list)
    for path in sorted((private_root/'artifacts/primary_event_study_2010_2019_v1/sec_sub').glob('*/sub.txt')):
        sub=pd.read_csv(path,sep='\t',dtype=str,keep_default_na=False)
        sub=sub[sub.cik.str.zfill(10).isin(set(calls.cik))]
        for r in sub.to_dict('records'):
            if r['form'] not in ['10-K','10-Q','10-K/A','10-Q/A'] or r['fp'] not in ['FY','Q1','Q2','Q3'] or len(r['period'])!=8:continue
            end=f"{r['period'][:4]}-{r['period'][4:6]}-{r['period'][6:]}";cik=r['cik'].zfill(10)
            by_end[cik,end].append(r);by_label[cik,r['fy']+('Q4' if r['fp']=='FY' else r['fp'])].append(r)
    duplicated=set(calls[calls.call_date.ne('')].loc[lambda x:x.duplicated(['cik','call_date'],keep=False),'call_id'])
    duplicate_text=set(calls.loc[calls.duplicated('canonical_transcript_sha256',keep=False),'call_id'])
    output=[]
    for r in calls.to_dict('records'):
        flags=[];support=[];key=r['call_id'];quarter=r.get('provider_quarter_label') or r['quarter_label']
        recs=by_end[r['cik'],r['date_fiscal_date_ending']];fp='FY' if quarter.endswith('4') else quarter[-2:]
        if recs:
            if any(t['fp']==fp for t in recs):support.append('cached_SEC_same_period_and_quarter')
            else:flags.append('historical_fiscal_quarter_conflict')
        elif by_label[r['cik'],quarter]:flags.append('historical_period_end_conflict')
        else:flags.append('no_independent_historical_period_match')
        if key in duplicated:flags.append('duplicate_issuer_release')
        if key in duplicate_text:flags.append('duplicate_transcript_content')
        if not r['call_date']:flags.append('missing_release')
        else:
            day=date.fromisoformat(r['call_date'])
            if day.weekday()>=5:flags.append('weekend_release_requires_evidence')
            if r['date_fiscal_date_ending'] and not 7<=(day-date.fromisoformat(r['date_fiscal_date_ending'])).days<=120:flags.append('release_lag_requires_evidence')
        raw=json.loads((private_root/refs.loc[key,'raw_path']).read_text());payload=raw.get('payload',raw)
        text=' '.join(str(s.get('content','')) for s in payload.get('transcript',[]))
        labels=[]
        for m in QUARTER.finditer(text[:5000]):
            g=m.groups();q=g[0] or g[3] or g[4];y=g[1] or g[2] or g[5];label=y+'Q'+QUARTERS[q.lower()]
            if m.start()<1500 and re.search('welcome|conference|results for|discuss|review',text[max(0,m.start()-70):m.end()+100],re.I):labels.append(label)
        if labels and labels[0]!=quarter:flags.append('transcript_opening_quarter_conflict')
        for m in re.finditer(r'(?:today(?:\s+is|\s+being|\s+on|,)?|statements.{0,40}as of)\s+([A-Z][a-z]+\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+20\d\d))',text[:10000]):
            if r['call_date'] and abs((parse(m[1]).date()-date.fromisoformat(r['call_date'])).days)>7:flags.append('transcript_current_date_conflict');break
        if 'yfinance' in r['date_match_method']:flags.append('broad_window_mapping')
        if str(r['reported_date_source_disagreement'])=='True':flags.append('provider_release_source_disagreement')
        output.append(dict(call_id=key,cik=r['cik'],provider_quarter_label=quarter,fiscal_period_end=r['date_fiscal_date_ending'],release_date=r['call_date'],flags=';'.join(sorted(set(flags))),calendar_support=';'.join(support),first_opening_quarter=labels[0] if labels else ''))
    result=pd.DataFrame(output)
    for cik,g in result[result.release_date.ne('')].groupby('cik'):
        g=g.sort_values('provider_quarter_label')
        for a,b in zip(g.to_dict('records'),g.to_dict('records')[1:]):
            if a['release_date']>b['release_date']:
                result.loc[result.call_id.isin([a['call_id'],b['call_id']]),'flags']+=';nonmonotonic_quarter_events'
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--calls',type=Path,required=True);p.add_argument('--private-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError(a.output)
    calls=pd.read_csv(a.calls,dtype=str,keep_default_na=False)
    result=diagnostics(calls,a.private_root);result.to_csv(a.output,index=False)
    print('Audited',len(result),'calls;',int(result['flags'].ne('').sum()),'flagged for adjudication')
