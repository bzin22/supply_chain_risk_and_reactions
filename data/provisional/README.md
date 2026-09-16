# data/provisional/

Inputs that are not the paper's. Each is here because it was convenient, not
because it matches Theile et al. (2026). Nothing in this directory should be
described as the study universe.

## `convenience_sample_450_companies_9_sectors.csv`

450 tickers with `symbol,name,sector,industry`, 50 per sector across 9
sectors.

This is a convenience sample, not the paper's historical US-company universe.
Three specific problems:

- Membership is current, not historical. A company that was listed during the
  sample period but has since delisted or been acquired is absent, so the
  sample is survivorship-biased.
- `sector` and `industry` are yfinance labels, not SIC codes. The paper groups
  by SIC. The two do not map onto each other.
- The 50-per-sector balance is by construction. The real economy is not
  balanced that way, so sector-level averages out of this sample do not
  represent the market.

Pass it explicitly if you want it:

```
conda run -n dap-env python extract_earnings_call_transcript_data.py \
  --input data/provisional/convenience_sample_450_companies_9_sectors.csv
```

`--input` has no default, so this file can never be picked up silently.

## `companies_traded_15_years.csv`

2,387 rows of `symbol,name,exchange,assetType,ipoDate,delistingDate,status`.
Shape matches an Alpha Vantage `LISTING_STATUS` response filtered to companies
with at least 15 years of trading history, but the exact query and the date it
was pulled are not recorded. Treat the provenance as unverified.

This is the input the 450-company sample was drawn from. It is retained for
that reason, not because the pipeline reads it. No core pipeline script does.

## `select_convenience_sample_by_sector.py`

The script that produced the 450-company sample from the listing above, using
yfinance sector and industry labels.

It cannot reproduce the committed sample. yfinance labels change over time, the
script stops as soon as every sector bucket is full so the result depends on
input row order, and the configuration in the file targets 50 per sector across
10 sectors while the committed file has 450 across 9. What closed that gap is
not recorded.

Regenerating a fresh sample:

```
conda run -n dap-env python data/provisional/select_convenience_sample_by_sector.py
```

That writes `convenience_sample_regenerated.csv` next to the script. Expect a
different sample from the committed one, and do not overwrite the committed
file with it.
