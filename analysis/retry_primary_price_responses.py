"""One evidence-preserving retry for the two initial invalid API responses."""
import os

from collect_earnings_event_inputs import AlphaVantageClient, atomic_write_json
from analysis.primary_event_study.run import PRICE_CACHE


if __name__=='__main__':
    client=AlphaVantageClient(os.environ['ALPHAVANTAGE_API_KEY'],1.1)
    for ticker in ['ANY','PLD']:
        path=PRICE_CACHE/f'{ticker}.retry01.json'
        if path.exists(): raise RuntimeError('Refusing to replace retry evidence')
        params={'function':'TIME_SERIES_DAILY_ADJUSTED','symbol':ticker,'outputsize':'full'}
        payload,retrieved=client.fetch(params)
        status='ok' if payload.get('Time Series (Daily)') else 'provider_unavailable'
        atomic_write_json(path,{'params':params,'fetched_at_utc':retrieved,'payload':payload,'classification':status,
                                'retry_of':str(PRICE_CACHE/f'{ticker}.json')})
        print(ticker,status,flush=True)
