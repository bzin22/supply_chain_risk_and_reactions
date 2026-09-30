"""Bounded missing-history requests for evidenced Hubbell Class B aliases."""
from analysis.hardware_us400.data import Client

if __name__ == '__main__':
    client = Client()
    for symbol in ['HUB-B', 'HUB.B']:
        for function in ['EARNINGS', 'TIME_SERIES_DAILY_ADJUSTED']:
            params = {'function': function, 'symbol': symbol}
            if function == 'TIME_SERIES_DAILY_ADJUSTED':
                params['outputsize'] = 'full'
            client.fetch(params)
