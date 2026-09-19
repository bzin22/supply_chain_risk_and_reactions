"""Write the bounded universe, pilot, call-date, and attrition handoff."""

from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
UNIVERSE = ROOT / "data/universe/us_operating_companies_v20260916"
PILOT = ROOT / "review/representative_coverage_pilot_20260916"
DATES = ROOT / "data/call_dates/call_dates_v20260916"
OUT = ROOT / "review/universe_coverage_call_dates_20260916"


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    universe = json.loads((UNIVERSE / "manifest.json").read_text())
    pilot = json.loads((PILOT / "pilot_summary.json").read_text())
    dates = json.loads((DATES / "coverage_report.json").read_text())
    attrition = [
        {"scope": "full_corpus", "stage": "eligible_resolved_firm_quarters", "count": universe["eligible_resolved_firm_quarters"], "status": "observed", "note": "versioned US-domiciled, US-listed operating-company universe"},
        {"scope": "full_corpus", "stage": "valid_transcripts_current", "count": dates["valid_transcript_rows"], "status": "observed_partial_collection", "note": "legacy valid corpus plus active representative-pilot additions"},
        {"scope": "full_corpus", "stage": "resolved_transcript_identities", "count": dates["resolved_identity_rows"], "status": "observed_partial_collection", "note": "point-in-time CIK resolved"},
        {"scope": "full_corpus", "stage": "high_confidence_call_dates", "count": dates["high_confidence_call_dates"], "status": "observed_partial_collection", "note": "explicit independent SEC evidence"},
        {"scope": "full_corpus", "stage": "frozen_scored_sample", "count": 0, "status": "not_started", "note": "dictionary and expanded corpus freeze required first"},
        {"scope": "full_corpus", "stage": "final_regression_observations", "count": 0, "status": "not_started", "note": "CAR construction was not authorized"},
        {"scope": "representative_pilot", "stage": "eligible_sampled_firm_quarters", "count": pilot["eligible_firm_quarters"], "status": "observed", "note": "proportional year-exchange-SIC sample"},
        {"scope": "representative_pilot", "stage": "valid_transcripts", "count": pilot["terminal_state_counts"].get("valid", 0), "status": "observed", "note": "reused plus newly collected"},
        {"scope": "representative_pilot", "stage": "high_confidence_call_dates", "count": pilot["high_confidence_call_dates"], "status": "observed", "note": "eligible for a future primary CAR input only after freeze"},
    ]
    write_csv(OUT / "ATTRITION_TABLE.csv", attrition)
    report = f"""# Bounded methodology handoff

## Completed scope

The primary study window is 2010Q1-2019Q4. The versioned public-source universe contains {universe['eligible_resolved_firm_quarters']:,} resolved US-domiciled, US-listed operating-company firm-quarters. Membership and ticker intervals use 40 quarter-end Alpha Vantage listing snapshots; SEC CIK metadata supplies permanent issuer identity, domicile evidence, and current SIC. Preferred shares, foreign or unverified-domicile issuers, and other non-common securities are excluded. Unresolved identities remain in review tables and are not request inputs.

The corrected representative pilot contains {pilot['eligible_firm_quarters']:,} firm-quarters. It produced {pilot['terminal_state_counts'].get('valid', 0):,} valid transcripts, including {pilot['existing_valid_reused']:,} reused responses and {pilot['new_valid_transcripts']:,} new responses. Repeated provider unavailability accounts for {pilot['terminal_state_counts'].get('terminal_provider_unavailability', 0):,} rows. There were {pilot['identity_or_quarter_mismatches']:,} confirmed identity/quarter mismatches and {pilot['exact_duplicate_groups']:,} exact-duplicate groups. No post-2019 active observations remain.

The call-date map covers {dates['valid_transcript_rows']:,} valid transcripts, of which {dates['resolved_identity_rows']:,} have resolved CIKs. It assigns {dates['high_confidence_call_dates']:,} high-confidence dates and retains {dates['medium_confidence_candidates']:,} medium candidates plus {dates['unresolved']:,} unresolved rows. A date is high confidence only when an issuer-filed SEC document explicitly states a call/webcast date and explicitly matches the fiscal quarter. Explicit transcript-opening dates are recorded separately and conflicts remain unresolved. Filing dates, report dates, period ends, and quarter labels are never used as event dates.

## Planning implications

The pilot-weighted valid rate is {pilot['weighted_terminal_state_rates'].get('valid', 0):.1%}. Excluding the documented DNS-outage session, the planning estimate is {pilot['estimated_full_live_requests_excluding_transport_outage']:,} live requests, {pilot['estimated_duration_hours_at_30_requests_per_minute']:.1f} hours at 30 requests per minute, {pilot['estimated_raw_storage_bytes']/1_000_000_000:.2f} GB of raw storage, and about {pilot['estimated_final_valid_transcripts']:,} valid transcripts. These are estimates, not stopping quotas.

## Remaining differences from Theile et al. (2026)

- Public listing snapshots plus SEC identity metadata are not a CRSP/Compustat-style historical security master; historical SIC changes are not reconstructed.
- The provider's observed transcript availability is materially below the paper's planning benchmarks in this representative pilot.
- SEC-filed evidence is an independent and auditable call-date source, but rows without explicit evidence remain excluded; investor-relations corroboration is not complete.
- The paper's complete risk, resolution, and supply-chain dictionary artifacts are not yet frozen and versioned. No expanded-corpus scoring was performed.
- Prices, factors, CARs, quintiles, and regressions were not constructed in this bounded stage.
"""
    (OUT / "METHODOLOGY_REPORT.md").write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
