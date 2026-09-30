"""Resolve missing Hubbell release dates from explicit company IR fiscal periods."""
import concurrent.futures, json, re
from datetime import datetime, timezone
import requests
from bs4 import BeautifulSoup
from analysis.hardware_us400.inventory import ART
from analysis.primary_event_study import core

D=ART/'ir_dates'
def fetch(item):
    name=item['text'][:8].replace('/','-')
    p=D/(name+'.html')
    if not p.exists():
        res=requests.get(item['url'],timeout=40);res.raise_for_status();p.write_text(res.text)
    soup=BeautifulSoup(p.read_text(),'html.parser')
    body=re.sub(r'\s+',' ',soup.get_text(' ',strip=True))
    match=re.search(r'for the (first|second|third|fourth) quarter ended (\w+\s+\d{1,2},?\s+20\d{2})',body,re.I)
    if not match:return {'unresolved_url':item['url'],'excerpt':body[:2500]}
    end=datetime.strptime(match[2].replace(',',''),'%B %d %Y').date()
    q={'first':1,'second':2,'third':3,'fourth':4}[match[1].lower()]
    return dict(ticker='HUBB',cik='0000048898',quarter_label=f'{end.year}Q{q}',fiscal_date_ending=end.isoformat(),reported_date=datetime.strptime(item['text'][:8],'%m/%d/%y').date().isoformat(),source_url=item['url'],source_path=core.relative(p),source_sha256=core.sha256(p),retrieved_at_utc=datetime.now(timezone.utc).isoformat(),match_method='company_IR_release_archive_date_and_explicit_quarter_ended_in_release_body',matched_fiscal_text=match[0])

if __name__=='__main__':
    items=json.loads((D/'archive_candidates.json').read_text())
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:rows=list(pool.map(fetch,items))
    good=[r for r in rows if r.get('quarter_label','')>='2010Q1']
    core.write_csv(D/'resolved_release_dates.csv',good)
    core.write_json(D/'unresolved.json',[r for r in rows if 'quarter_label' not in r])
    print('Resolved',len(good),'unresolved',len([r for r in rows if 'quarter_label' not in r]))
    for r in rows:print(r.get('quarter_label'),r.get('fiscal_date_ending'),r.get('reported_date'),r.get('unresolved_url',''))
