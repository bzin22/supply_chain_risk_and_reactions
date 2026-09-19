# Bounded transcript recovery pilot

Pilot completed: 2026-09-16

## Outcome

The bounded pilot reached a documented terminal state for all 186 eligible
firm-quarters. It reused 64 valid legacy responses and recovered 14 additional
valid transcripts. No rate-limit, API, HTTP, or transport failure occurred in
the successful pilot sessions.

| Terminal state | Firm-quarters |
| --- | ---: |
| Valid transcript | 78 |
| Terminal provider unavailability after later-session retry | 106 |
| Quarantine | 2 |
| Total eligible | 186 |

The 175 live requests were spread across four collector session IDs. The
initial session was intentionally interrupted after checkpointing; its pending
work resumed without overwriting or repeating completed terminal responses.
First-time `no_transcript` results were retried under a later session ID before
being classified as terminal provider unavailability.

## Pilot composition

| Identity case | Eligible | Valid | Terminal unavailable | Quarantine |
| --- | ---: | ---: | ---: | ---: |
| Apple (`AAPL`), active large | 40 | 40 | 0 | 0 |
| Atlantic American (`AAME`), active small | 40 | 0 | 40 | 0 |
| Ford (`F`), active large | 40 | 38 | 0 | 2 |
| SunEdison (`SUNE`), delisted/ticker-reuse risk | 26 | 0 | 26 | 0 |
| PerkinElmer (`PKI`), renamed to Revvity after the study | 40 | 0 | 40 | 0 |

This is deliberately not a representative sample. Its purpose was to expose
identity, historical-ticker, delisting, small-firm, and response-validation
failure modes before scaling.

## Validation findings

- Exact normalized-text duplicate groups: 0.
- Identity/quarter mismatches: Ford 2012Q2 returned a transcript whose opening
  referenced 2023; it is quarantined.
- Suspiciously short responses: Ford 2012Q4 returned fewer than 150 lexical
  tokens; it is quarantined.
- Explicit earnings-call dates in provider headings/openings: 0 of 78 valid
  transcripts. Generic dates elsewhere in the calls were deliberately not
  treated as call dates.
- Independently validated call dates: 0. Therefore, none of these pilot calls
  is yet eligible for the primary CAR analysis.
- Raw integrity failures: 0. Every pilot raw-file SHA-256 matches its manifest.
- Exact API-key occurrences in pilot artifacts: 0.
- Active post-2019 observations: 0, confirmed by the repository boundary gate.

The historical `PKI` test is informative: using current ticker `RVTY` would
have assigned the wrong effective-dated symbol to 2010-2019, while the correct
historical symbol produced repeated provider unavailability. This is a
provider-coverage result, not permission to substitute the current ticker.

## Runtime and scale estimate

The pilot wrote 786,054 bytes across 175 immutable attempt records. The
attempt files averaged only 4.5 KB because most were empty provider responses;
that average is not suitable for forecasting a transcript-rich full corpus.
The existing active cache averages 30.7 KB per response, implying roughly
3.9 GB for 126,000 single-attempt raw responses before retries, manifests,
quarantine copies, and derived datasets.

For a benchmark scenario with 126,000 eligible requests and 11,598 existing
valid responses reused, applying the pilot's 1.434 live-attempt multiplier to
the remaining 114,402 pairs gives about 164,100 provider requests. At the
pilot's conservative 30 requests/minute, that is approximately 91 hours of
request time. This is a planning scenario, not a stopping rule.

The pilot valid rate was 41.9% (78/186), which would naïvely imply about 52,800
valid responses from 126,000 eligible firm-quarters. That extrapolation is not
defensible because the pilot intentionally overweights delisted, renamed,
small, and unavailable firms. The earlier 108,000 usable-observation figure
remains only a planning benchmark until the historical universe and a
representative coverage sample exist.

## Sources and limitations

The versioned pilot universe is under
`data/pilot/pilot_universe_v20260916/`. SEC filings establish CIK, historical
ticker, exchange, operating-company identity, and the SunEdison bankruptcy;
the source URLs and retrieval date are preserved in `SOURCES.md` and every
universe row. Public SEC evidence remains filer-centric rather than a complete
historical security master, so this pilot universe must not be promoted to the
full study universe.

## Gate decision

The collector passed the bounded operational pilot: append-only responses,
resumability, later-session `no_transcript` retries, conservative rate control,
identity checks, quarantine, and checksummed provenance all worked.

The complete collection should not begin yet. The next reviewable stage is to
construct the full public-source point-in-time US operating-company universe,
then run a representative universe-coverage pilot and build an independent
earnings-call-date source. Dictionaries and scoring remain frozen.
