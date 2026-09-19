"""Fail if an active transcript, segment, or analysis CSV exceeds 2019Q4."""

from __future__ import annotations

import json
from pathlib import Path

from study_period import (
    validate_csv_event_dates_in_study_period,
    validate_csv_in_study_period,
    validate_study_quarter,
)

ROOT = Path(__file__).resolve().parent
ACTIVE_CSVS = [
    ROOT / "earnings_call_transcripts.csv",
    ROOT / "earnings_call_transcript_segments.csv",
    ROOT / "data" / "universe" / "us_operating_companies_v20260916" / "eligible_firm_quarters.csv",
    ROOT / "data" / "universe" / "us_operating_companies_v20260916" / "eligible_security_quarters.csv",
    ROOT / "data" / "universe" / "us_operating_companies_v20260916" / "primary_security_selection.csv",
    ROOT / "data" / "pilot" / "representative_coverage_pilot_v20260916" / "eligible_firm_quarters.csv",
    ROOT / "data" / "call_dates" / "call_dates_v20260916" / "call_date_mapping.csv",
    ROOT / "data" / "call_dates" / "call_dates_v20260916" / "identity_review.csv",
    ROOT / "data" / "call_dates" / "call_dates_v20260916" / "transcript_8k_candidate_links.csv",
    ROOT / "data" / "call_dates" / "call_dates_v20260916" / "source_evidence.csv",
    ROOT / "data" / "call_dates" / "call_dates_v20260916" / "unresolved.csv",
]
DATE_ONLY_CSVS = [
    ROOT / "data" / "call_dates" / "call_dates_v20260916" / "sec_8k_candidates.csv",
]
RAW_DIR = ROOT / "artifacts" / "earnings_call_responses"
PILOT_RAW_DIR = ROOT / "artifacts" / "representative_coverage_pilot_v20260916" / "raw"
ANALYSIS_DIR = ROOT / "artifacts" / "earnings_call_supply_chain"
PILOT_REPORT_DIR = ROOT / "review" / "representative_coverage_pilot_20260916"


def verify_active_data() -> dict[str, int]:
    csvs = [path for path in ACTIVE_CSVS if path.exists()]
    if ANALYSIS_DIR.exists():
        csvs.extend(sorted(ANALYSIS_DIR.rglob("*.csv")))
    if PILOT_REPORT_DIR.exists():
        csvs.extend(
            path for path in sorted(PILOT_REPORT_DIR.glob("*.csv"))
            if path.name in {
                "terminal_state_manifest.csv", "retry_manifest.csv",
                "terminal_failure_manifest.csv", "quarantine_manifest.csv",
            }
        )
    for path in csvs:
        validate_csv_in_study_period(path, context="active study data")
        validate_csv_event_dates_in_study_period(path, context="active study event dates")
    date_only = [path for path in DATE_ONLY_CSVS if path.exists()]
    for path in date_only:
        validate_csv_event_dates_in_study_period(path, context="active study event dates")

    raw_count = 0
    for path in sorted(RAW_DIR.glob("*.json")) if RAW_DIR.exists() else []:
        payload = json.loads(path.read_text(encoding="utf-8"))
        validate_study_quarter(str(payload.get("quarter_label") or ""))
        raw_count += 1
    for path in sorted(PILOT_RAW_DIR.rglob("*.json")) if PILOT_RAW_DIR.exists() else []:
        payload = json.loads(path.read_text(encoding="utf-8"))
        validate_study_quarter(str(payload.get("quarter_label") or ""))
        raw_count += 1
    return {"csv_files_checked": len(csvs) + len(date_only), "raw_files_checked": raw_count}


if __name__ == "__main__":
    result = verify_active_data()
    print(
        f"PASS: {result['csv_files_checked']} active CSVs and "
        f"{result['raw_files_checked']} raw responses end at 2019Q4"
    )
