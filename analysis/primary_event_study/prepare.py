"""Prepare auxiliary inputs without changing any transcript source."""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import subprocess
import time
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

from .core import ROOT, SOURCE, SOURCE_HASH, DATE_MAP, sha256, relative, write_csv, write_json

CACHE = ROOT / 'artifacts/primary_event_study_2010_2019_v1'


class RangeFile(io.RawIOBase):
    """Read a public ZIP by HTTP ranges; retain all received bytes for provenance."""
    def __init__(self, url, directory):
        self.url, self.directory, self.pos = url, directory, 0
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': os.environ['SEC_USER_AGENT'], 'Accept-Encoding':'identity'})
        self.parts = []
        tail = self.request('bytes=-66000')
        self.tail_start = self.size-len(tail)
        self.tail = tail

    def request(self, byte_range):
        time.sleep(.2)
        r = self.session.get(self.url, headers={'Range':byte_range}, timeout=60)
        r.raise_for_status()
        if r.status_code != 206:
            raise ValueError(f'SEC server did not honor range: {r.status_code}')
        match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', r.headers.get('Content-Range',''))
        if not match:
            raise ValueError('Missing Content-Range')
        lo, hi, self.size = map(int, match.groups())
        assert len(r.content) == hi-lo+1
        if byte_range != 'bytes=-66000':
            expected = tuple(map(int, byte_range.removeprefix('bytes=').split('-')))
            assert (lo,hi) == expected, 'Wrong range returned'
        path = self.directory / f'range_{lo}_{hi}.bin'
        path.write_bytes(r.content)
        self.parts.append({'path':relative(path),'sha256':sha256(path),'range':r.headers['Content-Range']})
        return r.content

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        self.pos = offset if whence == 0 else self.pos+offset if whence == 1 else self.size+offset
        return self.pos

    def read(self, size=-1):
        end = self.size if size < 0 else min(self.size,self.pos+size)
        if end <= self.pos:
            return b''
        if self.pos >= self.tail_start:
            content = self.tail[self.pos-self.tail_start:end-self.tail_start]
        else:
            content = self.request(f'bytes={self.pos}-{end-1}')
        self.pos = end
        return content


def download_sic(quarters):
    for quarter in quarters:
        directory = CACHE / 'sec_sub' / quarter
        directory.mkdir(parents=True, exist_ok=True)
        meta_path = directory / 'source.json'
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            if meta.get('status') == 'ok' and sha256(directory/'sub.txt') == meta['sub_sha256']:
                print(quarter, 'cached', flush=True)
                continue
        url = f'https://www.sec.gov/files/dera/data/financial-statement-data-sets/{quarter}.zip'
        meta = {'url':url,'retrieved_at_utc':datetime.now(timezone.utc).isoformat(),
                'method':'HTTP range extraction of ZIP sub.txt; CRC checked by zipfile; raw ranges retained'}
        try:
            remote = RangeFile(url,directory)
            with zipfile.ZipFile(remote) as archive:
                name = next(n for n in archive.namelist() if n.lower().split('/')[-1] == 'sub.txt')
                raw = archive.read(name)
            (directory/'sub.txt').write_bytes(raw)
            meta.update(status='ok',sub_sha256=sha256(directory/'sub.txt'),ranges=remote.parts,
                        archive_size=remote.size,sub_bytes=len(raw))
        except Exception as e:
            meta.update(status='error',error=f'{type(e).__name__}: {e}')
        write_json(meta_path,meta)
        print(quarter,meta['status'],meta.get('sub_bytes',meta.get('error')),flush=True)
        if meta['status'] != 'ok':
            raise RuntimeError('SIC retrieval failed; retained source.json for resumption')


def prepare_metadata():
    csv.field_size_limit(100_000_000)
    assert sha256(SOURCE) == SOURCE_HASH, 'Frozen v1 hash mismatch'
    CACHE.mkdir(parents=True,exist_ok=True)
    rows = []
    with SOURCE.open() as f:
        for row in csv.DictReader(f):
            row.pop('transcript_text')
            rows.append(row)
    assert len(rows) == 58305 and len({r['call_id'] for r in rows}) == len(rows)
    assert len({(r['cik'],r['quarter_label']) for r in rows}) == len(rows)
    write_csv(CACHE/'metadata.csv',rows)
    # Freeze the committed ticker/CIK linkage as an auxiliary input. This file
    # contains no transcript text and does not expand the transcript universe.
    commit = 'ae9526a'
    file = 'data/universe/us_operating_companies_v20260916/ticker_history.csv'
    content = subprocess.check_output(['git','show',f'{commit}:{file}'],cwd=ROOT)
    (CACHE/'ticker_history.csv').write_bytes(content)
    write_json(CACHE/'source.json',{'path':relative(SOURCE),'sha256':SOURCE_HASH,'rows':len(rows),
                                  'ticker_history_git_commit':commit,'ticker_history_git_path':file,
                                  'ticker_history_sha256':sha256(CACHE/'ticker_history.csv')})
    print('Prepared metadata',len(rows),flush=True)


def build_sic_history():
    history = {}
    for sub in sorted((CACHE/'sec_sub').glob('*/sub.txt')):
        meta = json.loads(sub.with_name('source.json').read_text())
        assert meta['status']=='ok' and sha256(sub)==meta['sub_sha256']
        with sub.open(errors='strict') as f:
            for r in csv.DictReader(f,delimiter='\t'):
                if not r.get('sic') or not re.fullmatch(r'\d{8}',r.get('filed','')):
                    continue
                filing = f"{r['filed'][:4]}-{r['filed'][4:6]}-{r['filed'][6:]}"
                record = {'cik':r['cik'].zfill(10),'sic':r['sic'].zfill(4),'filing_date':filing,
                          'accession':r['adsh'],'source_path':relative(sub),
                          'source_sha256':meta['sub_sha256'],'source_url':meta['url']}
                history[(record['cik'],record['accession'])] = record
    # Historical full filing headers supplement the early XBRL coverage gap.
    base = ROOT/'artifacts/call_date_sources_v20260916/sec_filing_documents'
    for path in sorted(base.glob('*/*/*.txt')):
        with path.open(errors='replace') as f:
            head = f.read(50000).split('</SEC-HEADER>')[0]
        cik = re.search(r'CENTRAL INDEX KEY:\s*(\d+)',head)
        sic = re.search(r'STANDARD INDUSTRIAL CLASSIFICATION:[^\n]*\[(\d{4})\]',head)
        filed = re.search(r'FILED AS OF DATE:\s*(\d{8})',head)
        if not (cik and sic and filed) or cik[1].zfill(10) != path.parents[1].name:
            continue
        d=filed[1]
        record={'cik':cik[1].zfill(10),'sic':sic[1],'filing_date':f'{d[:4]}-{d[4:6]}-{d[6:]}',
                'accession':path.parent.name,'source_path':relative(path),'source_sha256':sha256(path),
                'source_url':f'https://www.sec.gov/Archives/edgar/data/{int(cik[1])}/{path.parent.name.replace("-", "")}/{path.name}'}
        history.setdefault((record['cik'],record['accession']),record)
    write_csv(CACHE/'sic_history.csv',sorted(history.values(),key=lambda r:(r['cik'],r['filing_date'],r['accession'])))
    print('Historical SIC observations',len(history),flush=True)


def reconcile_dates():
    csv.field_size_limit(100_000_000)
    from .dates import confirm_live_call
    candidates = defaultdict(list)
    evidence=ROOT/'data/call_dates/call_dates_v20260916/source_evidence.csv'
    for r in csv.DictReader(evidence.open()):
        if r['fiscal_period_match'].lower()=='true' and r['explicit_call_date']:
            candidates[(r['cik'].zfill(10),r['quarter_label'],r['ticker'])].append({
                'earnings_call_date':r['explicit_call_date'],'call_date_source_raw_path':r['source_raw_path'],
                'call_date_source_url':r['source_url'],'call_date_source_sha256':r['source_sha256'],
                'evidence_excerpt':r['evidence_excerpt']})
    rows=[]
    hash_cache={}
    decisions=[]
    from datetime import date
    for r in csv.DictReader((CACHE/'metadata.csv').open()):
        choices=candidates.get((r['cik'],r['quarter_label'],r['historical_ticker']),[])
        out={'call_id':r['call_id'],'confirmed_call_date':'','call_date_confirmation_status':'no_explicit_call_date_evidence',
             'call_date_confirmation_method':'',
             'call_date_source_url':'','call_date_source_path':'','call_date_source_sha256':'','call_date_evidence':'',
             'call_vs_reported_date_disagreement':False,'call_vs_reported_date_days':'',
             'reported_date_source_disagreement':r['date_source_agreement']=='conflict'}
        accepted=[]
        for c in choices:
            delta=(date.fromisoformat(c['earnings_call_date'])-date.fromisoformat(r['earnings_call_date'])).days
            if not -1 <= delta <= 7:
                continue
            positive,reason=confirm_live_call(c['earnings_call_date'],c['evidence_excerpt'])
            decisions.append({'call_id':r['call_id'],'candidate_date':c['earnings_call_date'],
                              'live_schedule_check':positive,'reason':reason,
                              'source_path':c['call_date_source_raw_path'],'source_sha256':c['call_date_source_sha256'],
                              'evidence_excerpt':c['evidence_excerpt']})
            if positive: accepted.append(c)
        unique_dates={c['earnings_call_date'] for c in accepted}
        if len(unique_dates)>1:
            out['call_date_confirmation_status']='ambiguous_live_call_schedule_dates'
        elif accepted:
            c=sorted(accepted,key=lambda c:(c['call_date_source_raw_path'],c['evidence_excerpt']))[0]
            path=ROOT/c['call_date_source_raw_path']
            if path not in hash_cache:
                hash_cache[path]=sha256(path) if path.is_file() else ''
            delta=(date.fromisoformat(c['earnings_call_date'])-date.fromisoformat(r['earnings_call_date'])).days
            out.update(call_vs_reported_date_disagreement=delta!=0,call_vs_reported_date_days=delta,
                       call_date_source_url=c['call_date_source_url'],call_date_source_path=c['call_date_source_raw_path'],
                       call_date_source_sha256=c['call_date_source_sha256'],call_date_evidence=c['evidence_excerpt'])
            if hash_cache[path]!=c['call_date_source_sha256']:
                out['call_date_confirmation_status']='call_date_evidence_hash_failure'
            else:
                out.update(confirmed_call_date=c['earnings_call_date'],call_date_confirmation_status='confirmed_explicit_sec_call_date',
                           call_date_confirmation_method=confirm_live_call(c['earnings_call_date'],c['evidence_excerpt'])[1])
        elif choices:
            out['call_date_confirmation_status']='cached_evidence_does_not_confirm_live_call_for_this_fiscal_event'
        rows.append(out)
    write_csv(CACHE/'confirmed_dates.csv',rows)
    write_csv(CACHE/'call_date_evidence_decisions.csv',decisions)
    from collections import Counter
    print('Call-date gates',dict(Counter(r['call_date_confirmation_status'] for r in rows)),flush=True)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('stage',choices=['metadata','sic-download','sic-history','dates'])
    p.add_argument('--quarters',nargs='+')
    a=p.parse_args()
    if a.stage=='metadata': prepare_metadata()
    elif a.stage=='sic-download':
        download_sic(a.quarters or [f'{y}q{q}' for y in range(2009,2021) for q in range(1,5) if y<2020 or q==1])
    elif a.stage=='sic-history': build_sic_history()
    else: reconcile_dates()


if __name__=='__main__': main()
