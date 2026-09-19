# Cached Alpha Vantage transcript audit

> Historical pre-removal audit. The 2020-2024 material described below was
> moved out of active scan paths on 2026-09-16. See
> `provenance/post_2019_removal_20260916/REMOVAL_REPORT.md`.

Audit date: 2026-09-16

## Scope and preservation

The cache contains exactly 27,000 JSON files for 450 tickers and 60 quarters from 2010Q1 through 2024Q4. The requested grid has no missing or unexpected ticker-quarter pairs. The audit streamed the existing files and wrote only to this review directory. No raw file under `artifacts/` was deleted, overwritten, or moved.

The manifest records the raw path, raw SHA-256, provider status, HTTP status, provider message, segment count, lexical token count, distinct-token ratio, detected markers, normalized-transcript SHA-256, duplicate-group fields, classification, reasons, and recommended action. Transcript text is not copied into the manifest. Only flagged beginning and ending excerpts are retained.

## Results

| Classification | Count |
|---|---:|
| Valid full transcript | 18,158 |
| No transcript | 5,401 |
| Provider information/rate-limit response | 3,414 |
| Uncertain/manual review | 16 |
| API error | 8 |
| Placeholder/redacted | 1 |
| Copyright/boilerplate | 1 |
| Probably truncated | 1 |
| Malformed | 0 |
| Duplicate | 0 |

The 3,414 provider-information responses all report request throttling or plan information and are not transcript successes. The eight API errors report invalid API calls. All 5,401 `no_transcript` results lack independently verified evidence that a transcript truly did not exist, so they appear in the optional unverifiable retry list.

Thirteen provider-success responses contain fewer than 1,000 lexical tokens. Length alone did not cause rejection. Eleven remain manual-review cases, one is explicitly redacted, and one is probably truncated. The short/flagged excerpt file permits review without producing a large derived transcript corpus.

Eight responses contain a high-confidence opening call year that conflicts by more than one year with the requested quarter: CP 2024Q1, F 2012Q2, KIM 2024Q1, MGPI 2024Q1, MRSH 2018Q2, OHI 2021Q3, PPC 2023Q2, and WRB 2010Q3. They require identity verification. OHI 2021Q3 is also a 23-token one-segment stub and is classified as probably truncated.

Exact normalized-text hashing found no duplicate transcript groups. Empty responses were not hashed as transcripts.

## Study-period coverage

The paper covers 2008-2019. This cache begins in 2010, so it cannot cover 2008-2009.

| Period | Requested | Provider status `success` | Valid full transcript |
|---|---:|---:|---:|
| Paper period represented in cache, 2010-2019 | 18,000 | 11,611 | 11,598 |
| Current extension, 2020-2024 | 9,000 | 6,566 | 6,560 |

Detailed coverage appears in separate CSV files by year, ticker, current sector, response classification, and period. Sector labels are the current labels in `data/provisional/convenience_sample_450_companies_9_sectors.csv`; they are not historical sector classifications.

## Date limitation

This task recollects transcript responses. It does not collect or validate earnings-call dates. No cached payload contains a usable `reportedDate` or equivalent date field. Even if Alpha Vantage `reportedDate` were present, it would be provider metadata and not a verified earnings-call date. Event studies need a separate date source, mapping, and validation process.

## Classification method

Classification precedence is: malformed wrapper; provider Information/Note; API or transport error; copyright marker; explicit redaction/unavailable marker; provider `no_transcript`; missing usable segments; degenerate repeated boilerplate; high-confidence opening-year conflict; short-content structural checks; otherwise valid full transcript.

Token counts use lexical tokens matched as words or numbers. Distinct-token ratio is lowercase distinct tokens divided by total tokens. A normalized transcript hash is SHA-256 over lowercase lexical tokens joined by single spaces. `duplicate` applies only to a noncanonical response whose normalized body exactly matches another otherwise-valid transcript.

`probably truncated` requires more than short length: either fewer than 150 tokens with at most three segments, or fewer than 1,000 tokens plus a one-segment or abrupt-ending signal. Other short responses remain manual review. The classifier is intentionally conservative and does not prove semantic completeness.

## Dictionary replication status

No final dictionary was constructed during this audit.

The article reports a 208-term weighted supply-chain library but publishes only the 16 seeds and the top 30 terms. The complete weighted file is not available in the article or workspace. The workspace's 118-term PPMI/SVD library is a different corpus-derived construction and therefore an approximation, not an exact replication.

Table 3 publishes 144 risk terms observed in the sample and states that another 17 terms in the risk library did not occur. Those 17 terms are not named, so the complete 161-term risk dictionary cannot be recovered from the article alone. The local starter risk list is provisional.

The resolution library is defined as `mitigate`, `resolve`, and Oxford synonyms, but the article publishes only a top-frequency table. The Oxford product, edition, senses, morphology rules, and complete term list are not specified. A reconstruction from a current dictionary page must be labeled an approximation unless the original author file and source/version metadata are obtained.

The accompanying checklist specifies the missing files, completeness tests, and mandatory per-term provenance fields. Exact-replication status remains blocked for all three dictionaries.

## Sources

- Theile, K., Hofer, C., Singhal, V. R., and Hoberg, K. (2026), “Supply Chain Risk and Resolution: An Empirical Study of Stock Market Reactions,” DOI: https://doi.org/10.1177/10591478261420550
- Local cached responses under `artifacts/earnings_call_responses/`, read 2026-09-16
- Current ticker metadata: `data/provisional/convenience_sample_450_companies_9_sectors.csv`
