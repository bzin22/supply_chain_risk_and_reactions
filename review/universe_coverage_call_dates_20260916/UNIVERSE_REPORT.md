# Point-in-time US operating-company universe

Version: v20260916

Study period: 2010Q1-2019Q4

## Result

- 151,073 unique eligible firm-quarters.
- 4,671 resolved SEC-confirmed US issuers.
- 9,636 candidate common-stock security histories before issuer resolution.
- 7,435 security histories resolved to SEC CIKs before domicile and operating-security exclusions.
- 189,667 eligible resolved security-quarter candidates before selecting one provider
  ticker per issuer-quarter.
- 32,793 firm-quarters had multiple security candidates; every candidate and
  the deterministic primary-security ranking are preserved.
- 2,201 unresolved security identities remain in review tables and are excluded
  from transcript request inputs.
- 9,322 unique non-common, non-operating, foreign, or unverified-domicile
  security records were excluded.

## Eligible firm-quarters by year

| Year | Firm-quarters | Unique companies |
| --- | ---: | ---: |
| 2010 | 11,891 | 3,033 |
| 2011 | 12,427 | 3,146 |
| 2012 | 12,994 | 3,311 |
| 2013 | 13,702 | 3,511 |
| 2014 | 14,658 | 3,757 |
| 2015 | 15,474 | 3,944 |
| 2016 | 16,514 | 4,188 |
| 2017 | 17,159 | 4,368 |
| 2018 | 17,876 | 4,522 |
| 2019 | 18,378 | 4,640 |

## Construction

Historical membership, ticker, exchange, IPO date, and delisting date come
from immutable active and delisted Alpha Vantage listing snapshots at every
quarter end. SEC exact-10-K names, current ticker/exchange data, and per-issuer
submissions metadata resolve CIK and corroborate issuer identity. One effective
provider ticker is selected per CIK-quarter; all alternative securities and
selection ranks remain in `primary_security_selection.csv`.

ETFs, funds, warrants, rights, units, preferred shares, when-issued securities,
blank-check companies, and SEC investment-company classifications are excluded.
SEC state-of-incorporation metadata must also confirm US domicile; foreign and
unverified-domicile issuers remain in provenance but not request inputs.
Uncertain matches are not forced.

## Limitations

- Public SEC metadata is filer-centric rather than a historical security
  master. Historical membership comes from the provider snapshots, with SEC
  evidence used for identity corroboration.
- The active SIC classification is complete current SEC issuer metadata.
  Historical SIC changes are not reconstructed. The incomplete historical
  filing-header experiment is preserved outside the active inputs and is not
  used in these counts.
- Eligibility means that the documented security listing interval overlaps the
  calendar quarter. The provider's fiscal-quarter transcript label remains a
  separate field.
- Unresolved identities are retained for review but are not eligible for API
  requests or downstream analysis.

Raw source locations, retrieval timestamps, sizes, and SHA-256 checksums are
recorded in the versioned universe `source_manifest.csv`.
