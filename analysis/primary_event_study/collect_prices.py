"""Resumable adjusted-close collection, restricted to tickers present in frozen v1."""
import argparse
import csv
import json
import os
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from collect_earnings_event_inputs import AlphaVantageClient, payload_message, provider_enforced_rate_limit
from .core import ARCHIVE, ROOT, relative, sha256, write_json, write_csv
from .prepare import CACHE
from .run import PRICE_CACHE


def collect(limit=None):
    rows=list(csv.DictReader((CACHE/'metadata.csv').open()))
    tickers=sorted({r['historical_ticker'] for r in rows})
    pending=[t for t in tickers if not (ARCHIVE/'alpha_vantage_daily_adjusted_raw'/f'{t}.json').exists() and not (PRICE_CACHE/f'{t}.json').exists()]
    if limit is not None: pending=pending[:limit]
    PRICE_CACHE.mkdir(parents=True,exist_ok=True)
    lock=threading.Lock()
    stop=threading.Event()
    last=[0.0]
    def fetch_one(ticker):
        assert '/' not in ticker and '\\' not in ticker
        params={'function':'TIME_SERIES_DAILY_ADJUSTED','symbol':ticker,'outputsize':'full'}
        with lock:
            if stop.is_set(): return None
            time.sleep(max(0,1.1-(time.monotonic()-last[0])))
            last[0]=time.monotonic()
        client=AlphaVantageClient(os.environ['ALPHAVANTAGE_API_KEY'],0)
        try:
            payload,fetched=client.fetch(params)
            message=payload_message(payload)
            status='ok' if payload.get('Time Series (Daily)') else 'provider_unavailable'
            if provider_enforced_rate_limit(message): status='provider_rate_limit'
            if 'premium' in message.lower(): status='provider_entitlement_required'
            record={'fetched_at_utc':fetched,'params':params,'payload':payload,'classification':status}
        except RuntimeError as exc:
            # Client redacts the API URL; do not print or store credentials.
            record={'params':params,'classification':'provider_transport_error','message':str(exc)}
            status=record['classification']
        path=PRICE_CACHE/f'{ticker}.json'
        write_json(path,record)
        if status in {'provider_rate_limit','provider_entitlement_required'}:
            stop.set()
        return ticker,status
    with ThreadPoolExecutor(max_workers=4) as executor:
        completed=0
        for future in as_completed([executor.submit(fetch_one,t) for t in pending]):
            result=future.result()
            if result is None: continue
            completed+=1
            ticker,status=result
            print(json.dumps({'completed':completed,'requested':len(pending),'ticker':ticker,'status':status}),flush=True)
    if stop.is_set(): print('Provider limit or entitlement response preserved; stopped new requests.',flush=True)
    records=[]
    for ticker in tickers:
        path=ARCHIVE/'alpha_vantage_daily_adjusted_raw'/f'{ticker}.json'
        if not path.exists(): path=PRICE_CACHE/f'{ticker}.json'
        if path.exists():
            r=json.loads(path.read_text()); payload=r.get('payload',r)
            status=r.get('classification','ok' if payload.get('Time Series (Daily)') else 'provider_unavailable')
            records.append({'ticker':ticker,'status':status,'path':relative(path),'sha256':sha256(path),
                            'fetched_at_utc':r.get('fetched_at_utc',''),'price_rows':len(payload.get('Time Series (Daily)',{}))})
        else: records.append({'ticker':ticker,'status':'not_requested','path':'','sha256':'','fetched_at_utc':'','price_rows':0})
    write_csv(PRICE_CACHE.parent/'collection_inventory.csv',records)
    write_json(PRICE_CACHE.parent/'collection_manifest.json',{'source_metadata_sha256':sha256(CACHE/'metadata.csv'),
               'ticker_count':len(tickers),'status_counts':dict(Counter(r['status'] for r in records)),
               'collector_sha256':sha256(Path(__file__)),'request_interval_seconds':1.1,
               'max_in_flight_requests':4,
               'provider_url':'https://www.alphavantage.co/query','function':'TIME_SERIES_DAILY_ADJUSTED',
               'cache_policy':'preserve all original and new responses; no implicit symbol substitutions',
               'inventory_sha256':sha256(PRICE_CACHE.parent/'collection_inventory.csv')})
    print(json.dumps(dict(Counter(r['status'] for r in records))),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--limit',type=int)
    collect(parser.parse_args().limit)
