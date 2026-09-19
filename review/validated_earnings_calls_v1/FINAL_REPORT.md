# Validated earnings-call corpus v1

## Canonical result

- Canonical dated calls: 58,305 across 2,200 companies
- Valid calls before final exclusions: 58,980
- Excluded without a reported date: 467 (0.79% of valid calls)
- Quarantined for unresolved ticker reuse: 208 (0.35%)
- Canonical retention from pre-exclusion valid calls: 98.86%
- SHA-256: `06d4620290b4b8a66f18a8762d5042968d4b436d4aef7009f6004d9d331eece3`

The SHA companion passes `shasum -a 256 -c`. The canonical CSV has 58,305
unique call IDs, no blank transcript or date fields, no transcript-hash
mismatches, no out-of-period quarter labels, and no unresolved ticker-reuse
flags.

## Validation

The full universe contains 151,073 eligible firm-quarters. Validation produced
58,980 valid calls, 90,760 terminal `no_transcript` outcomes, 300 quarantines,
61 duplicates, 33 technical failures, and 14 invalid-content outcomes. Another
925 eligible firm-quarters had no request. Validation took 161.3 seconds.

The 50-company pilot covered 2,000 eligible firm-quarters and produced 1,490
valid calls, a 74.5% validation yield. All 1,490 pilot valid calls remain in the
canonical corpus. The pilot took 49.8 minutes. Its original strict actual-call-
date rule was later replaced by the reported-date policy used for v1.

## Reported-date mapping

`earnings_call_date` is the reported earnings date. Alpha Vantage
`reportedDate` is preferred, followed by Yahoo Finance and targeted
earnings-history sources. The selected sources are:

- Alpha Vantage: 55,862 calls (95.81%)
- Yahoo Finance: 1,474 (2.53%)
- Explicit earnings-history pages: 949 (1.63%)
- Quant500: 20 (0.03%)

Two or more sources agree for 26,685 calls. A single usable source supports
29,949 calls. Another 1,671 calls retain a preferred-source date while a
secondary source differs; these rows are explicitly marked
`reported_date_mapped_conflicting_sources` for robustness checks.

The 467 undated exclusions consist of 214 calls where a fallback page matched a
different issuer, 60 where both Alpha Vantage and Yahoo returned no history,
153 where Alpha Vantage returned partial history without the requested fiscal
quarter, and 40 with the corresponding Yahoo partial-history gap.

The recorded full date-mapping window ran from approximately 22:01 to 23:46 UTC
on 2026-09-18. Final CSV construction and hashing took 35.1 seconds. Full date
source payloads were processed in memory and discarded; compact evidence and
request manifests were retained.

## Retention and provenance

All 59,282 payloads classified as valid or quarantine remain present. All
95,987 non-retained payload paths are absent after manifest freeze; 94,867 were
deleted in the full-run deletion step and 1,120 had already been removed during
the pilot. The canonical exclusions are recorded in
`canonical_exclusions.csv`. Corrections must create v2 rather than overwrite
v1.
