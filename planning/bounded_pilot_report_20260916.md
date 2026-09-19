# Bounded pilot preflight report — 2026-09-16

> Superseded by the completed live pilot report at
> `review/transcript_pilot_20260916/PILOT_REPORT.md`.

## Status

This is a bounded cache/preflight pilot, not the required live recovery pilot.
No provider requests were made: `ALPHAVANTAGE_API_KEY` is not available to this
process, and the point-in-time universe needed to determine eligible quarters
has not yet been built. Treating the convenience grid as eligibility would
invalidate the pilot.

## Deliberately mixed identity cases

The preflight examined 2010-2019 cache entries for AAPL and F (large active),
AAME and MGPI (smaller active), SUNE (delisted/ticker-reuse risk), and CP
(renamed issuer and non-US negative control). These labels are pilot-selection
flags, not a completed historical-universe classification.

The convenience cache contains 40 requested quarters for each ticker, or 240
grid requests. The true eligible firm-quarter count is unresolved until
effective-dated security histories are available.

| Cached response classification | Count |
| --- | ---: |
| Valid full transcript reusable | 77 |
| Provider information/rate-limit | 39 |
| First-attempt `no_transcript` | 122 |
| Uncertain/manual review | 1 |
| Placeholder/redacted | 1 |
| Total | 240 |

Additional preflight results:

- Newly recovered transcripts: 0; no live retry was attempted.
- Repeated `no_transcript`: 0 documented; the legacy cache preserves only one
  attempt per ticker-quarter, so the 122 cases require a later-session retry.
- Identity/quarter mismatch: 1 high-confidence opening-year conflict (F).
- Exact duplicates: 0 in the repository-wide normalized-text audit.
- Defensible call-date coverage: 0; the cached provider payloads do not contain
  validated earnings-call dates.
- Post-2019 active observations: 0 after the removal gate.

## What the preflight proves

The pilot mix exposes the central design risks: current tickers can represent
different historical companies; a listed ticker can fail US-company rules;
and blanket 40-quarter requests are not point-in-time eligibility. It also
shows that useful valid responses can be reused while retry work is targeted.

## Approval needed for the next pilot stage

Approve building the versioned historical universe and immutable retry
collector, followed by a bounded live pilot of only unresolved eligible
firm-quarters. The complete collection remains prohibited until that pilot's
results are reviewed.
