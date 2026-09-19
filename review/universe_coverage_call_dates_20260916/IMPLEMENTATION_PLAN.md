# Point-in-time universe, representative coverage pilot, and call-date mapping

Prepared: 2026-09-16

## Boundaries

- Study period: 2010Q1 through 2019Q4 only.
- No full earnings-call transcript collection in this stage.
- No price collection, factor collection, CAR construction, scoring, quintiles, or regressions.
- Existing dictionaries are out of scope and will not be modified.
- Original provider and SEC responses remain immutable; derived files are versioned separately.

## Audited starting point

- The local SEC discovery manifest contains 76,596 exact Form 10-K filings from
  14,130 CIKs filed during 2010-2019. This is a candidate issuer backbone, not a
  historical security master.
- The active transcript audit identifies 11,598 valid full transcripts from
  2010-2019. None has a provider-reported call date.
- The existing 450-company file is a current, sector-balanced convenience
  sample and will not be used as the study universe.
- `ALPHAVANTAGE_API_KEY` is available. `SEC_USER_AGENT` is not currently set.

## 1. Point-in-time operating-company universe

### Source capture

1. Save immutable Alpha Vantage `LISTING_STATUS` CSV responses for `active`
   and `delisted` securities at each of the 40 quarter ends from 2010Q1 through
   2019Q4 (80 bounded requests, no transcript requests).
2. Reuse the local exact-10-K discovery manifest rather than downloading the
   same 10-K index population again.
3. Download the SEC bulk submissions archive once and the 40 SEC quarterly
   master indexes once. Use them for CIK/former-name history, filing history,
   Forms 8-A/10 registration evidence, Forms 25/25-NSE delisting evidence, SIC,
   and accession-level provenance.
4. Fetch individual filing cover pages only when needed to resolve a security,
   ticker, exchange, or operating-company ambiguity. SEC access will use a
   contact-bearing user agent and a limiter below the SEC's 10 requests/second
   ceiling.

### Eligibility rules

- Include a US-listed common-equity security when its documented listing
  interval overlaps the calendar quarter and the issuer is an operating
  company.
- Include later-delisted, acquired, renamed, and ticker-changed issuers.
- Exclude ETFs, mutual/closed-end funds, investment companies, warrants,
  rights, units, preferred shares, test issues, and other non-operating or
  non-common-equity securities.
- Use CIK as the public-source permanent issuer identifier. Assign a separate
  versioned security identifier so multiple securities and ticker reuse do not
  collapse into one company.
- Treat unmatched or conflicting identities as unresolved; do not force a name
  match. Unresolved rows stay in a review table and are excluded from request
  inputs until resolved.
- Effective dates come from listing/delisting evidence. Quarter labels and
  filing dates are never substituted for an unknown event date.

### Versioned outputs

`data/universe/us_operating_companies_v20260916/` will contain:

- `companies.csv`
- `securities.csv`
- `ticker_history.csv`
- `eligible_firm_quarters.csv`
- `exclusions.csv`
- `identity_review.csv`
- `coverage_by_year_exchange_sic.csv`
- `source_manifest.csv`
- `SOURCES.md` and `manifest.json`

Raw downloaded source files will be checksummed under a gitignored artifact
directory. Tests will enforce unique identifiers, non-overlapping ticker
intervals, 2010Q1-2019Q4 bounds, allowed security classes, and complete source
provenance.

## 2. Representative coverage pilot

- Draw 800 eligible firm-quarters with fixed seed `20260916`.
- Allocate the sample proportionally across year, exchange, and one-digit SIC
  division. This estimates population coverage rather than deliberately
  overweighting edge cases.
- Preserve design weights and report weighted and unweighted response rates.
- Reuse existing valid responses first. Query Alpha Vantage only for sampled
  unresolved firm-quarters, at the established conservative 30 requests/minute.
- Retry nonterminal failures and first-time `no_transcript` results in a later
  session under the existing bounded-attempt rules.
- Report sampling composition, reused valid calls, new valid calls, terminal
  unavailability, provider/API failures, mismatches, duplicates, quarantine,
  call-date coverage, duration, storage, and revised full-run estimates.

This pilot is capped at 800 firm-quarters. It cannot expand into the full
collection without a separate approval.

## 3. Independent call-date mapping

- Create one mapping row for every one of the 11,598 currently valid
  transcripts, including unresolved rows.
- Resolve each historical ticker to CIK through the new universe mapping.
- Search SEC filing metadata for candidate Forms 8-K/8-K-A and their exhibits.
  Candidate windows are retrieval aids only; dates are assigned only when an
  issuer document explicitly states the earnings-call date and identifies the
  relevant fiscal period.
- Use archived issuer investor-relations releases/webcast notices when SEC
  exhibits do not contain explicit evidence. Preserve URL, retrieval timestamp,
  raw-file SHA-256, evidence type, and a short evidence excerpt.
- Keep `fiscal_quarter`, `earnings_announcement_date`, and `call_date` separate.
  The 8-K filing date, fiscal-period end, and quarter label are never used as
  inferred call dates.
- Confidence levels:
  - `high`: explicit call date plus matching issuer/fiscal-period evidence;
  - `medium`: explicit call date and issuer match, but weaker fiscal-period
    evidence;
  - `unresolved`: no defensible explicit date or conflicting evidence.
- Only `high` mappings will eventually be eligible for the primary CAR input;
  CAR construction is not part of this stage.

Outputs will be versioned under `data/call_dates/call_dates_v20260916/`:

- `call_date_mapping.csv`
- `source_evidence.csv`
- `unresolved.csv`
- `source_manifest.csv`
- `COVERAGE_REPORT.md` and `manifest.json`

## Approval gate

Execution begins only after approval of this plan and after a contact-bearing
`SEC_USER_AGENT` is exported. The first checkpoint will be the completed
universe and its audit tables. The 800-observation transcript pilot and the
full 11,598-row call-date evidence pass follow as separate bounded steps. No
full transcript collection or CAR work is authorized by this plan.
