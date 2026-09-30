"""Read-only inventory of local Alpha Vantage earnings and adjusted prices."""
import json
from .inventory import ART, read, source_path
from analysis.primary_event_study import core


def build():
    companies = read(ART / 'company_manifest.csv')
    symbols = {s for r in companies for s in r['aliases'].split(';')}
    records = []
    for root in [core.ROOT, core.ROOT.parent / 'data_analysis_pipeline']:
        for p in root.rglob('*.json'):
            if p.stem not in symbols and not p.name.startswith(('EARNINGS_', 'TIME_SERIES_DAILY_ADJUSTED_')):
                continue
            d = json.loads(p.read_text())
            if not isinstance(d, dict):
                continue
            payload = d.get('payload', d)
            if not isinstance(payload, dict):
                continue
            if payload.get('quarterlyEarnings'):
                symbol = payload.get('symbol')
                params = {'function': 'EARNINGS', 'symbol': symbol}
            elif payload.get('Time Series (Daily)'):
                symbol = payload.get('Meta Data', {}).get('2. Symbol')
                params = {'function': 'TIME_SERIES_DAILY_ADJUSTED', 'symbol': symbol, 'outputsize': 'full'}
            else:
                continue
            if symbol in symbols:
                records.append(dict(params=params, status='ok', raw_path=source_path(p),
                                    raw_sha256=core.sha256(p), fetched_at_utc=d.get('fetched_at_utc',''),
                                    provenance='preexisting local supporting cache; no download'))
    core.write_json(ART / 'supporting_cache_inventory.json', records)
    print('Reconciled supporting cache files:', len(records), flush=True)


if __name__ == '__main__':
    build()
