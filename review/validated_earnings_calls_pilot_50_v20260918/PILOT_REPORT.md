# 50-company validation and date-mapping pilot

- Companies: 50
- Eligible firm-quarters: 2,000
- Valid calls: 1,490 (74.5%)
- Validation outcomes: {'valid': 1490, 'no_transcript': 506, 'technical_failure': 4}
- Confirmed call dates: 0 (0.0% of valid calls)
- Other date outcomes: {'ambiguous': 1389, 'no_source_found': 101}
- Source rows: {'yfinance': 1389, 'yahoo_finance_web_search': 119, 'targeted_web_backup': 119}
- Comparable-source agreement: {'not_comparable': 1490}
- Unresolved reasons: {'yfinance_candidate_lacks_explicit_fiscal-period evidence': 1389, 'no qualifying yfinance or web source': 101}
- Source quality: {'yfinance|medium_candidate_only|ambiguous': 1371, 'yfinance|low_candidate_only|ambiguous': 18, 'yahoo_finance_web_search|none|no_source_found': 119, 'targeted_web_backup|none|no_source_found': 119}
- Issuer-size tiers: {'mega': 5, 'large': 14, 'unavailable': 7, 'mid': 12, 'small': 12}
- Runtime: 49.8 minutes
- Projected full-universe firm-quarters: 151,073
- Projected remaining companies: 4,621
- Projected valid calls at pilot yield: 112,549
- Remaining universe: not launched; explicit review and approval required.

Unresolved date rows are in `unresolved_dates.csv`. Canonical dates remain blank unless the source explicitly states issuer, fiscal quarter, and call date.
