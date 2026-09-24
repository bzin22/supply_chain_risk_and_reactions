"""Reconcile and report the representative 2010-2019 coverage pilot."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from collection.extract_earnings_call_transcript_data import response_segments
from collection.study_period import validate_study_quarter

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SAMPLE = ROOT / "data" / "pilot" / "representative_coverage_pilot_v20260916" / "eligible_firm_quarters.csv"
DEFAULT_ARTIFACTS = ROOT / "artifacts" / "representative_coverage_pilot_v20260916"
DEFAULT_REPORT = ROOT / "review" / "representative_coverage_pilot_20260916"
AUDIT = ROOT / "review" / "alpha_vantage_transcript_audit_20260916" / "response_manifest.csv"
CALL_DATES = ROOT / "data" / "call_dates" / "call_dates_v20260916" / "call_date_mapping.csv"
FULL_UNIVERSE = ROOT / "data" / "universe" / "us_operating_companies_v20260916" / "eligible_firm_quarters.csv"

GENERIC_NAME_TOKENS = {
    "inc", "incorporated", "corp", "corporation", "company", "co", "holdings",
    "holding", "group", "limited", "ltd", "plc", "the", "american", "international",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def raw_text(path: Path) -> str:
    wrapper = json.loads(path.read_text(encoding="utf-8"))
    payload = wrapper.get("payload")
    return "\n\n".join(str(row.get("content") or "") for row in response_segments(payload))


def identity_status(company_name: str, text: str) -> tuple[str, str]:
    tokens = [
        token for token in re.findall(r"[a-z0-9]+", company_name.lower())
        if len(token) >= 5 and token not in GENERIC_NAME_TOKENS
    ]
    opening = text[:15000].lower()
    if tokens and any(token in opening for token in tokens):
        return "supported", "distinctive company-name token found in opening transcript text"
    return "manual_review", "no distinctive company-name token found in opening transcript text"


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACTS)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    sample = read_csv(args.sample)
    legacy = {
        (row["ticker"].upper(), row["quarter_label"]): row
        for row in read_csv(AUDIT) if int(row["year"]) <= 2019
    }
    manifest_path = args.artifact_dir / "request_manifest.csv"
    all_attempts = read_csv(manifest_path) if manifest_path.exists() else []
    active_live_keys = {
        (row["company_id"], row["provider_ticker"], row["quarter_label"])
        for row in sample
    }
    attempts = [
        row for row in all_attempts
        if (row["company_id"], row["provider_ticker"], row["quarter_label"]) in active_live_keys
    ]
    superseded_attempts = [row for row in all_attempts if row not in attempts]
    if superseded_attempts:
        write_csv(args.report_dir / "superseded_sample_attempt_manifest.csv", list(superseded_attempts[0]), superseded_attempts)
    live: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in attempts:
        live[(row["company_id"], row["provider_ticker"], row["quarter_label"])].append(row)
    call_dates = {}
    if CALL_DATES.exists():
        call_dates = {
            (row["ticker"], row["quarter_label"]): row for row in read_csv(CALL_DATES)
        }

    terminal: list[dict[str, object]] = []
    hash_failures: list[str] = []
    incomplete: list[str] = []
    for eligible in sample:
        validate_study_quarter(eligible["quarter_label"])
        key = (eligible["company_id"], eligible["provider_ticker"], eligible["quarter_label"])
        prior = legacy.get((eligible["provider_ticker"], eligible["quarter_label"]))
        live_rows = live.get(key, [])
        if live_rows and live_rows[-1]["terminal_status"] in {
            "valid", "terminal_provider_unavailability", "terminal_provider_failure", "quarantine"
        }:
            last = live_rows[-1]
            state = last["terminal_status"]
            source = "pilot_live"
            raw_path = last["raw_path"]
            raw_sha = last["raw_sha256"]
            classification = last["classification"]
            reason = last["validation_reason"]
            normalized_sha = last["normalized_transcript_sha256"]
        elif prior and prior["response_classification"] == "valid full transcript":
            state = "valid"
            source = "legacy_reuse"
            raw_path = prior["raw_file_path"]
            raw_sha = prior["raw_file_sha256"]
            classification = prior["response_classification"]
            reason = prior["classification_reasons"]
            normalized_sha = prior["normalized_transcript_sha256"]
        else:
            incomplete.append("|".join(key))
            continue
        path = ROOT / raw_path
        if hashlib.sha256(path.read_bytes()).hexdigest() != raw_sha:
            hash_failures.append(raw_path)
        identity, identity_reason = ("not_applicable", "")
        if state == "valid":
            identity, identity_reason = identity_status(eligible["company_name"], raw_text(path))
        date_row = call_dates.get((eligible["provider_ticker"], eligible["quarter_label"]), {})
        terminal.append({
            **eligible,
            "terminal_state": state, "response_source": source,
            "attempt_count": len(live_rows) + (1 if prior else 0),
            "raw_path": raw_path, "raw_sha256": raw_sha,
            "classification": classification, "validation_reason": reason,
            "identity_validation": identity, "identity_validation_reason": identity_reason,
            "normalized_transcript_sha256": normalized_sha,
            "duplicate_group_size": "", "duplicate_canonical_key": "",
            "call_date": date_row.get("earnings_call_date", ""),
            "call_date_confidence": date_row.get("confidence", "unresolved"),
            "call_date_source": date_row.get("call_date_source_url", ""),
        })
    if incomplete:
        raise RuntimeError(f"pilot has {len(incomplete)} nonterminal firm-quarters; first: {incomplete[:3]}")

    duplicate_groups = 0
    duplicate_noncanonical = 0
    hashes: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in terminal:
        if row["terminal_state"] == "valid" and row["normalized_transcript_sha256"]:
            hashes[str(row["normalized_transcript_sha256"])].append(row)
    for group in hashes.values():
        if len(group) < 2:
            continue
        duplicate_groups += 1
        group.sort(key=lambda row: (str(row["provider_ticker"]), str(row["quarter_label"])))
        canonical = f"{group[0]['provider_ticker']}|{group[0]['quarter_label']}"
        for index, row in enumerate(group):
            row["duplicate_group_size"] = len(group)
            row["duplicate_canonical_key"] = canonical
            duplicate_noncanonical += int(index > 0)

    args.report_dir.mkdir(parents=True, exist_ok=True)
    terminal_fields = list(terminal[0])
    write_csv(args.report_dir / "terminal_state_manifest.csv", terminal_fields, terminal)
    retry_rows = [row for row in attempts if row["terminal_status"] == "nonterminal_failure"]
    attempt_fields = list(attempts[0]) if attempts else ["session_id", "terminal_status"]
    write_csv(args.report_dir / "retry_manifest.csv", attempt_fields, retry_rows)
    terminal_failures = [
        row for row in terminal
        if row["terminal_state"] in {"terminal_provider_unavailability", "terminal_provider_failure"}
    ]
    write_csv(args.report_dir / "terminal_failure_manifest.csv", terminal_fields, terminal_failures)
    quarantines = [row for row in terminal if row["terminal_state"] == "quarantine"]
    write_csv(args.report_dir / "quarantine_manifest.csv", terminal_fields, quarantines)
    dimensions = {
        "year": lambda row: str(row["quarter_label"])[:4],
        "exchange": lambda row: str(row["exchange"]),
        "sic_division": lambda row: str(row["sic_division"]),
        "response_status": lambda row: str(row["terminal_state"]),
    }
    states = sorted({str(row["terminal_state"]) for row in terminal})
    for dimension, key_function in dimensions.items():
        values = sorted({key_function(row) for row in terminal})
        rows_out = []
        for value in values:
            subset = [row for row in terminal if key_function(row) == value]
            total_weight = sum(float(row["design_weight"]) for row in subset)
            out: dict[str, object] = {
                dimension: value, "sample_firm_quarters": len(subset),
                "weighted_population_estimate": f"{total_weight:.4f}",
            }
            for state in states:
                state_rows = [row for row in subset if row["terminal_state"] == state]
                out[f"{state}_count"] = len(state_rows)
                out[f"{state}_weighted"] = f"{sum(float(row['design_weight']) for row in state_rows):.4f}"
            rows_out.append(out)
        write_csv(args.report_dir / f"coverage_by_{dimension}.csv", list(rows_out[0]), rows_out)

    state_counts = Counter(str(row["terminal_state"]) for row in terminal)
    total_weight = sum(float(row["design_weight"]) for row in terminal)
    weighted_rates = {
        state: sum(float(row["design_weight"]) for row in terminal if row["terminal_state"] == state) / total_weight
        for state in state_counts
    }
    live_bytes = sum(int(row["raw_size_bytes"]) for row in attempts)
    unresolved_initial = len(terminal) - sum(row["response_source"] == "legacy_reuse" for row in terminal)
    attempt_multiplier = len(attempts) / unresolved_initial if unresolved_initial else 0.0
    full_universe = read_csv(FULL_UNIVERSE)
    full_keys = {(row["company_id"], row["quarter_label"]) for row in full_universe}
    reusable_keys = {
        (row["company_id"], row["quarter_label"])
        for row in call_dates.values() if row.get("company_id") and row.get("cik")
    }
    reusable_full = len(full_keys & reusable_keys)
    missing_full = len(full_keys) - reusable_full
    non_transport_attempts = [row for row in attempts if row["classification"] != "transport_error"]
    initial_live = len(terminal) - sum(row["response_source"] == "legacy_reuse" for row in terminal)
    normal_attempt_multiplier = len(non_transport_attempts) / initial_live if initial_live else 0.0
    estimated_full_requests = round(missing_full * normal_attempt_multiplier)
    average_non_transport_bytes = (
        sum(int(row["raw_size_bytes"]) for row in non_transport_attempts) / len(non_transport_attempts)
        if non_transport_attempts else 0.0
    )
    summary = {
        "eligible_firm_quarters": len(terminal),
        "unique_companies": len({str(row["company_id"]) for row in terminal}),
        "existing_valid_reused": sum(row["response_source"] == "legacy_reuse" for row in terminal),
        "new_valid_transcripts": sum(row["response_source"] == "pilot_live" and row["terminal_state"] == "valid" for row in terminal),
        "terminal_state_counts": dict(state_counts),
        "weighted_terminal_state_rates": weighted_rates,
        "live_requests": len(attempts), "live_bytes": live_bytes,
        "superseded_sample_attempts_excluded": len(superseded_attempts),
        "attempt_multiplier_on_initially_unresolved": attempt_multiplier,
        "rate_limit_api_transport_failures": sum(
            row["classification"] in {"provider_or_http_failure", "transport_error"} for row in attempts
        ),
        "rate_limit_failures": sum(row["provider_status"] == "rate_limited" for row in attempts),
        "provider_or_http_failures": sum(row["classification"] == "provider_or_http_failure" for row in attempts),
        "transport_failures": sum(row["classification"] == "transport_error" for row in attempts),
        "identity_manual_review": sum(row["identity_validation"] == "manual_review" for row in terminal),
        "identity_or_quarter_mismatches": sum(
            row["terminal_state"] == "quarantine"
            and ("identity" in row["validation_reason"].lower() or "quarter" in row["validation_reason"].lower())
            for row in terminal
        ),
        "exact_duplicate_groups": duplicate_groups,
        "duplicate_noncanonical_observations": duplicate_noncanonical,
        "high_confidence_call_dates": sum(row["call_date_confidence"] == "high" for row in terminal),
        "raw_hash_failures": hash_failures,
        "post_2019_observations": 0,
        "full_universe_firm_quarters": len(full_universe),
        "full_universe_existing_valid_reusable": reusable_full,
        "estimated_full_live_requests_excluding_transport_outage": estimated_full_requests,
        "estimated_duration_hours_at_30_requests_per_minute": estimated_full_requests / 30 / 60,
        "estimated_raw_storage_bytes": round(estimated_full_requests * average_non_transport_bytes),
        "estimated_final_valid_transcripts": round(len(full_universe) * weighted_rates.get("valid", 0.0)),
    }
    (args.report_dir / "pilot_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    report = [
        "# Representative transcript-coverage pilot",
        "",
        f"Eligible sampled firm-quarters: {len(terminal):,}",
        f"Unique companies: {summary['unique_companies']:,}",
        f"Existing valid responses reused: {summary['existing_valid_reused']:,}",
        f"New valid transcripts: {summary['new_valid_transcripts']:,}",
        f"Live requests: {len(attempts):,}",
        f"Terminal states: {dict(state_counts)}",
        f"Rate-limit failures: {summary['rate_limit_failures']:,}",
        f"Provider/API failures: {summary['provider_or_http_failures']:,}",
        f"Transport failures: {summary['transport_failures']:,} (one environment-wide DNS outage session)",
        f"Identity rows requiring manual review: {summary['identity_manual_review']:,}",
        f"Confirmed identity or quarter mismatches: {summary['identity_or_quarter_mismatches']:,}",
        f"Exact duplicate groups: {duplicate_groups:,}",
        f"High-confidence independent call dates: {summary['high_confidence_call_dates']:,}",
        f"Estimated full live requests (excluding the transport outage): {summary['estimated_full_live_requests_excluding_transport_outage']:,}",
        f"Estimated duration at 30 requests/minute: {summary['estimated_duration_hours_at_30_requests_per_minute']:.1f} hours",
        f"Estimated raw storage: {summary['estimated_raw_storage_bytes'] / 1_000_000_000:.2f} GB",
        f"Estimated final valid transcripts: {summary['estimated_final_valid_transcripts']:,}",
        "Post-2019 active observations: 0",
        "",
        "The sample was proportionally allocated across year, exchange, and SIC division. "
        "Weighted response rates are stored in `pilot_summary.json`; detailed coverage tables "
        "are stored beside this report.",
    ]
    (args.report_dir / "PILOT_REPORT.md").write_text("\n".join(report) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
