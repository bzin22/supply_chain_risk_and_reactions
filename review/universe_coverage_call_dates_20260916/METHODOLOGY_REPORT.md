# Bounded methodology handoff

## Completed scope

The primary study window is 2010Q1-2019Q4. The versioned public-source universe contains 151,073 resolved US-domiciled, US-listed operating-company firm-quarters. Membership and ticker intervals use 40 quarter-end Alpha Vantage listing snapshots; SEC CIK metadata supplies permanent issuer identity, domicile evidence, and current SIC. Preferred shares, foreign or unverified-domicile issuers, and other non-common securities are excluded. Unresolved identities remain in review tables and are not request inputs.

The corrected representative pilot contains 800 firm-quarters. It produced 323 valid transcripts, including 41 reused responses and 282 new responses. Repeated provider unavailability accounts for 477 rows. There were 0 confirmed identity/quarter mismatches and 0 exact-duplicate groups. No post-2019 active observations remain.

The call-date map covers 11,880 valid transcripts, of which 11,392 have resolved CIKs. It assigns 1,930 high-confidence dates and retains 431 medium candidates plus 9,519 unresolved rows. A date is high confidence only when an issuer-filed SEC document explicitly states a call/webcast date and explicitly matches the fiscal quarter. Explicit transcript-opening dates are recorded separately and conflicts remain unresolved. Filing dates, report dates, period ends, and quarter labels are never used as event dates.

## Planning implications

The pilot-weighted valid rate is 40.2%. Excluding the documented DNS-outage session, the planning estimate is 226,800 live requests, 126.0 hours at 30 requests per minute, 2.28 GB of raw storage, and about 60,715 valid transcripts. These are estimates, not stopping quotas.

## Remaining differences from Theile et al. (2026)

- Public listing snapshots plus SEC identity metadata are not a CRSP/Compustat-style historical security master; historical SIC changes are not reconstructed.
- The provider's observed transcript availability is materially below the paper's planning benchmarks in this representative pilot.
- SEC-filed evidence is an independent and auditable call-date source, but rows without explicit evidence remain excluded; investor-relations corroboration is not complete.
- The paper's complete risk, resolution, and supply-chain dictionary artifacts are not yet frozen and versioned. No expanded-corpus scoring was performed.
- Prices, factors, CARs, quintiles, and regressions were not constructed in this bounded stage.
