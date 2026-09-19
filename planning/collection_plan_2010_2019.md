# 2010-2019 transcript collection and validation record

## Decision gate

The 50-company pilot was reviewed, the complete collection was approved, and
the full 2010-2019 validation and reported-date mapping are complete. Every
eligible firm-quarter has a documented terminal state. Scoring and regression
remain separate downstream stages.

## 1. Freeze a point-in-time company universe

Build a versioned security-quarter table rather than a current-ticker list.
The primary source should provide historical security names, permanent company
and security identifiers, listing/delisting dates, exchange, share/security
type, and SIC. CRSP/Compustat is the preferred source if licensed access is
available because the paper uses Compustat and WRDS. SEC CIK/submission history
and historical exchange records can corroborate identity, but a current
listing download alone is not a defensible historical universe.

Required outputs:

- `universe_vYYYYMMDD/companies.csv`: permanent company identifier, CIK where
  available, issuer domicile/operating-company status, and provenance.
- `universe_vYYYYMMDD/securities.csv`: permanent security identifier, security
  type, exchange, listing/delisting dates, exclusion reason, and provenance.
- `universe_vYYYYMMDD/ticker_history.csv`: effective-dated ticker-to-security
  mappings; ticker reuse must create separate identities.
- `universe_vYYYYMMDD/eligible_firm_quarters.csv`: only quarters during which
  an eligible US operating-company common equity was listed.
- Annual coverage by exchange and two-digit SIC, plus source retrieval dates
  and raw-source checksums.

Exclude ETFs, funds, warrants, preferred shares, test issues, non-operating
securities, and non-US issuers. Do not sector-balance.

## 2. Replace the collector before retrying

The current collector is suitable only as a legacy cache reader. Before a live
pilot, replace its one-file-per-pair overwrite behavior with append-only,
attempt-numbered raw files and a request manifest containing permanent IDs,
ticker effective dates, attempt number, timestamp, HTTP/provider status,
SHA-256, classification, validation reason, and retry/terminal status.

Use conservative shared rate control, exponential backoff with jitter,
bounded attempts, atomic manifest checkpoints, and session IDs. Information,
rate-limit, API, HTTP, and transport errors remain retryable. A
`no_transcript` result must be retried in a later session before becoming
terminal provider unavailability. Exact duplicates keep one canonical body
and preserve all attempt provenance. Quarantine malformed, redacted,
truncated, boilerplate, suspiciously short, and identity/quarter-mismatched
responses. Never generate missing text.

## 3. Bounded live pilot

Use a frozen subset containing active large firms, active small firms,
delisted firms, renamed firms, acquired firms, and ticker-reuse cases. Include
negative controls that should be excluded by domicile/security type. Request
only eligible quarters. Reuse valid cached responses without contacting the
provider; retry only unresolved states. Run at most one bounded session, then
a later-session retry for `no_transcript` cases.

The approval report must include eligible requests, valid cache reuse, new
recoveries, retryable failures, repeated `no_transcript`, mismatches,
duplicates, defensible call-date coverage, and extrapolated duration/storage.

## 4. Earnings-call dates

The permanent canonical-corpus rule is to set `earnings_call_date` to the
reported earnings date. Alpha Vantage EARNINGS
`quarterlyEarnings.reportedDate` is preferred, followed by Yahoo Finance and
targeted earnings-history sources. Match transcript fiscal quarters using
fiscal-period evidence; never match by the calendar quarter containing the
reported date. Store only the date, compact evidence, provenance, retrieval
timestamp, match method, confidence, status, and response hash. Full date-source
responses are not stored. These dates are not described as independently
verified conference-call dates.

## 5. Full collection and curation

After approval, collect/resume until every eligible firm-quarter is valid,
terminal unavailable, or quarantined with a documented reason. Produce annual,
exchange, SIC, and response-status coverage; duplicate and quarantine
manifests; the immutable raw cache; curated call and segment datasets; date
mapping; and attrition from eligible firm-quarters to regression observations.

At the current active-cache mean of 30.7 KB per raw response, 126,000 responses
would occupy about 3.9 GB before attempt history and derived files. At a
conservative 30 requests/minute, 126,000 network requests alone require about
70 hours; retries and validation add time. These are planning estimates, not
stopping rules.

## 6. Freeze and analysis gate

The curated corpus is frozen as
`data/final/earnings_call_transcripts_validated_2010_2019_v1.csv`, accompanied
by a SHA-256 file and provenance manifest. Corrections create v2. Every analysis
entry point must pass the 2010Q1-2019Q4 validator. The methodology must explain
that this is a deliberate 2010-2019 comparison while the paper used Capital
IQ's available US transcripts from 2008-2019 and Compustat/WRDS inputs.
