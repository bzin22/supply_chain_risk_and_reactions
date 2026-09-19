# Point-in-time universe sources

Version: v20260916

- Alpha Vantage `LISTING_STATUS`: immutable active and delisted snapshots at each of the 40 quarter ends from 2010Q1 through 2019Q4. Listing intervals and historical provider tickers come from these snapshots. https://www.alphavantage.co/documentation/
- SEC exact Form 10-K discovery manifest: reused local quarterly-index discovery for issuer-name-to-CIK matching; no 10-K population redownload.
- SEC company ticker/exchange JSON: current-only identity corroboration, never used as historical membership evidence. https://www.sec.gov/files/company_tickers_exchange.json
- SEC submissions/company metadata: CIK, current name, former-name and SIC metadata, captured per resolved issuer. https://data.sec.gov/submissions/
- SIC limitation: the active build uses complete current SEC issuer metadata; the incomplete historical-header experiment is not an active input.

## Inclusion and exclusion

The request universe contains resolved SEC issuers with US-listed common-stock candidate securities whose listing interval overlaps the calendar quarter. ETFs, funds, warrants, rights, units, preferred shares, test/non-common issues, blank-check companies, and SEC investment-company SICs are excluded. Unresolved identities remain in `identity_review.csv` and are not transcript request inputs. Multiple security candidates are preserved, while `eligible_firm_quarters.csv` selects one effective provider ticker per issuer-quarter using quarter-end activity, exchange, and plain common-stock-symbol evidence.

All raw sources are checksummed in `source_manifest.csv`.
