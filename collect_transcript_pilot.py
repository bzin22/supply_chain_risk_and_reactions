"""Run the bounded, immutable 2010-2019 transcript recovery pilot."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from extract_earnings_call_transcript_data import (
    URL,
    api_message,
    classify_response,
    response_segments,
)
from study_period import validate_study_quarter

ROOT = Path(__file__).resolve().parent
DEFAULT_UNIVERSE = ROOT / "data" / "pilot" / "pilot_universe_v20260916" / "eligible_firm_quarters.csv"
DEFAULT_OUTPUT = ROOT / "artifacts" / "transcript_pilot_20260916"
LEGACY_RAW = ROOT / "artifacts" / "earnings_call_responses"
PRIOR_AUDIT = ROOT / "review" / "alpha_vantage_transcript_audit_20260916" / "response_manifest.csv"
MAX_REQUESTS_PER_MINUTE = 75.0

MANIFEST_FIELDS = [
    "session_id", "company_id", "cik", "company_name", "provider_ticker",
    "quarter_label", "attempt_number", "requested_at_utc", "completed_at_utc",
    "http_status", "provider_status", "raw_path", "raw_size_bytes", "raw_sha256",
    "classification", "validation_reason", "terminal_status", "retry_status",
    "segment_count", "token_count", "normalized_transcript_sha256", "api_message",
]

IDENTITY_MARKERS = {
    "CIK0000320193": ("apple",),
    "CIK0000008177": ("atlantic american",),
    "CIK0000037996": ("ford motor", "ford"),
    "CIK0000945436": ("sunedison", "sun edison", "memc"),
    "CIK0000031791": ("perkinelmer", "perkin elmer"),
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_text(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def text_from_payload(payload: Any) -> str:
    return "\n\n".join(str(row.get("content") or "") for row in response_segments(payload))


def validate_success(
    payload: Any, *, company_id: str, quarter: str
) -> tuple[str, str, int, int, str]:
    segments = response_segments(payload)
    text = text_from_payload(payload)
    normalized = normalize_text(text)
    tokens = normalized.split()
    digest = sha256_bytes(normalized.encode("utf-8")) if normalized else ""
    if not segments or not normalized:
        return "quarantine", "success status without usable transcript content", len(segments), len(tokens), digest
    lowered = text.lower()
    if "transcript has been redacted" in lowered or "content unavailable" in lowered:
        return "quarantine", "redacted or unavailable marker", len(segments), len(tokens), digest
    if len(tokens) < 150:
        return "quarantine", "suspiciously short transcript under 150 lexical tokens", len(segments), len(tokens), digest
    requested_year = int(quarter[:4])
    opening_years = {int(value) for value in re.findall(r"\b20\d{2}\b", text[:5000])}
    if opening_years and all(abs(year - requested_year) > 1 for year in opening_years):
        return "quarantine", f"opening years {sorted(opening_years)} conflict with requested year {requested_year}", len(segments), len(tokens), digest
    if company_id == "CIK0000945436" and "sunation" in lowered[:10000]:
        return "quarantine", "ticker-reuse identity mismatch: Sunation response for SunEdison", len(segments), len(tokens), digest
    markers = IDENTITY_MARKERS.get(company_id, ())
    identity_reason = ""
    if markers and not any(marker in lowered[:15000] for marker in markers):
        identity_reason = "company identity marker not found in opening text; manual identity review required"
    return (
        "manual_review" if identity_reason else "valid",
        identity_reason or "usable transcript passed structural, year, and identity checks",
        len(segments), len(tokens), digest,
    )


def load_universe(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    required = {"company_id", "cik", "company_name", "provider_ticker", "quarter_label"}
    if not rows or required - set(rows[0]):
        raise ValueError(f"{path} lacks required pilot-universe columns")
    seen = set()
    for row in rows:
        row["provider_ticker"] = row["provider_ticker"].strip().upper()
        row["quarter_label"] = validate_study_quarter(row["quarter_label"])
        key = (row["company_id"], row["provider_ticker"], row["quarter_label"])
        if key in seen:
            raise ValueError(f"duplicate eligible pilot key: {key}")
        seen.add(key)
    return rows


def load_prior_audit() -> dict[tuple[str, str], dict[str, str]]:
    if not PRIOR_AUDIT.exists():
        return {}
    with PRIOR_AUDIT.open(newline="", encoding="utf-8") as handle:
        return {
            (row["ticker"].strip().upper(), row["quarter_label"].strip().upper()): row
            for row in csv.DictReader(handle)
            if int(row["year"]) <= 2019
        }


def load_manifest(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def append_manifest(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        writer.writerow(row)
        handle.flush()
        os.fsync(handle.fileno())


def index_manifest_rows(
    rows: list[dict[str, str]],
) -> dict[tuple[str, str, str], list[dict[str, str]]]:
    indexed: defaultdict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for item in rows:
        indexed[(
            item["company_id"], item["provider_ticker"], item["quarter_label"]
        )].append(item)
    return dict(indexed)


def immutable_raw_path(
    output_dir: Path, row: dict[str, str], attempt_number: int, requested_at: str
) -> Path:
    stamp = re.sub(r"[^0-9]", "", requested_at)[:20]
    return (
        output_dir / "raw" / row["company_id"] / row["provider_ticker"] /
        row["quarter_label"] / f"attempt_{attempt_number:02d}_{stamp}.json"
    )


def write_exclusive_json(path: Path, value: dict[str, Any]) -> tuple[int, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, ensure_ascii=False) + "\n").encode("utf-8")
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    return len(data), sha256_bytes(data)


def prior_state(
    row: dict[str, str], audit: dict[tuple[str, str], dict[str, str]],
    history_index: dict[tuple[str, str, str], list[dict[str, str]]],
) -> tuple[str, int, bool]:
    ticker = row["provider_ticker"]
    quarter = row["quarter_label"]
    key = (ticker, quarter)
    legacy = audit.get(key)
    history_key = (row["company_id"], ticker, quarter)
    relevant = history_index.get(history_key, [])
    # Protocol amendment 2026-09-18: a provider no-transcript response is a
    # terminal availability outcome and is not retried automatically.
    if any(item["provider_status"] == "no_transcript" for item in relevant):
        return "terminal_provider_unavailability", len(relevant), True
    if any(item["provider_status"] == "api_error" for item in relevant):
        return "terminal_provider_failure", len(relevant), False
    if legacy and legacy["response_classification"] == "no transcript":
        return "terminal_provider_unavailability", 1, True
    if relevant and relevant[-1]["terminal_status"] in {
        "valid", "terminal_provider_unavailability", "terminal_provider_failure", "quarantine"
    }:
        return relevant[-1]["terminal_status"], int(relevant[-1]["attempt_number"]), True
    if legacy and legacy["response_classification"] == "valid full transcript":
        return "legacy_valid", 1, True
    prior_attempts = (1 if legacy else 0) + len(relevant)
    return "unresolved", prior_attempts, False


def request_once(
    session: requests.Session, api_key: str, row: dict[str, str], timeout: float
) -> tuple[requests.Response | None, Any, str, str]:
    try:
        response = session.get(
            URL,
            params={
                "function": "EARNINGS_CALL_TRANSCRIPT",
                "symbol": row["provider_ticker"],
                "quarter": row["quarter_label"],
                "apikey": api_key,
            },
            timeout=timeout,
        )
        try:
            payload: Any = response.json()
            response_text = ""
        except ValueError:
            payload = None
            response_text = response.text
        return response, payload, response_text, classify_response(response, payload)
    except requests.RequestException as exc:
        # requests may include the complete query URL (and therefore the API
        # key) in an exception string. Persist only the exception class.
        return None, None, "", f"request_error_{type(exc).__name__}"


def validate_requests_per_minute(value: float) -> None:
    if value <= 0 or value > MAX_REQUESTS_PER_MINUTE:
        raise ValueError(
            f"--requests-per-minute must be in (0, {MAX_REQUESTS_PER_MINUTE:g}]"
        )


def run_pilot(args: argparse.Namespace) -> dict[str, Any]:
    args.universe = args.universe.resolve()
    args.output_dir = args.output_dir.resolve()
    api_key = os.environ.get("ALPHAVANTAGE_API_KEY")
    if not api_key:
        raise RuntimeError("ALPHAVANTAGE_API_KEY is not present in this process")
    validate_requests_per_minute(args.requests_per_minute)
    universe = load_universe(args.universe)
    audit = load_prior_audit()
    manifest_path = args.output_dir / "request_manifest.csv"
    live_rows = load_manifest(manifest_path)
    prior_manifest_rows: list[dict[str, str]] = []
    prior_manifest_paths: list[str] = []
    for prior_path in args.prior_request_manifest:
        resolved = prior_path.resolve()
        if not resolved.exists():
            raise ValueError(f"prior request manifest does not exist: {resolved}")
        prior_manifest_rows.extend(load_manifest(resolved))
        prior_manifest_paths.append(resolved.relative_to(ROOT).as_posix())
    history_rows = prior_manifest_rows + live_rows
    history_index = index_manifest_rows(history_rows)
    session_id = datetime.now(UTC).strftime("pilot_%Y%m%dT%H%M%SZ")
    pending = []
    reused = 0
    for row in universe:
        state, prior_attempts, prior_no_transcript = prior_state(row, audit, history_index)
        if state == "legacy_valid":
            reused += 1
        elif state not in {"valid", "terminal_provider_unavailability", "terminal_provider_failure", "quarantine"}:
            pending.append((row, prior_attempts, prior_no_transcript))
    if args.limit is not None:
        pending = pending[: args.limit]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    start_record = {
        "session_id": session_id,
        "started_at_utc": utc_now(),
        "study_period": "2010Q1-2019Q4",
        "universe_path": args.universe.relative_to(ROOT).as_posix(),
        "universe_sha256": sha256_bytes(args.universe.read_bytes()),
        "eligible_firm_quarters": len(universe),
        "pending_at_session_start": len(pending),
        "legacy_valid_reused": reused,
        "prior_request_manifests": prior_manifest_paths,
        "prior_request_manifest_sha256": {
            path: sha256_bytes((ROOT / path).read_bytes()) for path in prior_manifest_paths
        },
        "prior_request_rows_loaded": len(prior_manifest_rows),
        "requests_per_minute": args.requests_per_minute,
        "max_total_attempts": args.max_total_attempts,
        "credential_source": "ALPHAVANTAGE_API_KEY environment variable",
        "credential_value_recorded": False,
    }
    start_path = args.output_dir / f"{session_id}_start.json"
    with start_path.open("x", encoding="utf-8") as handle:
        json.dump(start_record, handle, indent=2)
        handle.write("\n")

    interval = 60.0 / args.requests_per_minute
    counts: Counter[str] = Counter()
    stop_reason = "completed_bounded_pending_set"
    with requests.Session() as session:
        for index, (row, prior_attempts, prior_no_transcript) in enumerate(pending, start=1):
            started = time.monotonic()
            requested_at = utc_now()
            attempt_number = prior_attempts + 1
            response, payload, response_text, provider_status = request_once(
                session, api_key, row, args.timeout
            )
            if provider_status.startswith("request_error_"):
                classification = "transport_error"
                reason = provider_status
                exhausted = attempt_number >= args.max_total_attempts
                terminal_status = "terminal_provider_failure" if exhausted else "nonterminal_failure"
                retry_status = "terminal_after_bounded_attempts" if exhausted else "retryable_bounded"
                segment_count = token_count = 0
                transcript_digest = ""
                message = provider_status
            elif provider_status == "success":
                classification, reason, segment_count, token_count, transcript_digest = validate_success(
                    payload, company_id=row["company_id"], quarter=row["quarter_label"]
                )
                terminal_status = "valid" if classification == "valid" else "quarantine"
                retry_status = "terminal" if classification == "valid" else "manual_review"
                message = api_message(payload)
            elif provider_status == "no_transcript":
                classification = "no_transcript"
                reason = "provider returned no usable transcript segments"
                segment_count = token_count = 0
                transcript_digest = ""
                terminal_status = "terminal_provider_unavailability"
                retry_status = "not_retried_by_protocol"
                message = api_message(payload)
            else:
                classification = "provider_or_http_failure"
                reason = f"non-success provider status {provider_status}"
                segment_count = token_count = 0
                transcript_digest = ""
                deterministic_api_error = provider_status == "api_error"
                exhausted = deterministic_api_error or attempt_number >= args.max_total_attempts
                terminal_status = "terminal_provider_failure" if exhausted else "nonterminal_failure"
                retry_status = (
                    "not_retried_invalid_api"
                    if deterministic_api_error
                    else "terminal_after_bounded_attempts" if exhausted
                    else "retryable_bounded"
                )
                message = api_message(payload)

            envelope = {
                "session_id": session_id,
                "company_id": row["company_id"], "cik": row["cik"],
                "company_name": row["company_name"], "provider_ticker": row["provider_ticker"],
                "quarter_label": row["quarter_label"], "attempt_number": attempt_number,
                "requested_at_utc": requested_at, "completed_at_utc": utc_now(),
                "http_status": response.status_code if response is not None else None,
                "provider_status": provider_status, "api_message": message,
                "payload": payload, "response_text": response_text,
            }
            raw_path = immutable_raw_path(args.output_dir, row, attempt_number, requested_at)
            size, digest = write_exclusive_json(raw_path, envelope)
            manifest_row = {
                **envelope,
                "raw_path": raw_path.relative_to(ROOT).as_posix(),
                "raw_size_bytes": size, "raw_sha256": digest,
                "classification": classification, "validation_reason": reason,
                "terminal_status": terminal_status, "retry_status": retry_status,
                "segment_count": segment_count, "token_count": token_count,
                "normalized_transcript_sha256": transcript_digest,
            }
            append_manifest(manifest_path, manifest_row)
            live_rows.append({key: str(manifest_row.get(key, "")) for key in MANIFEST_FIELDS})
            indexed_row = {key: str(manifest_row.get(key, "")) for key in MANIFEST_FIELDS}
            history_rows.append(indexed_row)
            history_key = (
                indexed_row["company_id"], indexed_row["provider_ticker"],
                indexed_row["quarter_label"],
            )
            history_index.setdefault(history_key, []).append(indexed_row)
            counts[classification] += 1
            print(
                f"[{index}/{len(pending)}] {row['provider_ticker']} {row['quarter_label']}: "
                f"{provider_status} -> {classification}"
            )
            if provider_status in {"information", "rate_limited"}:
                stop_reason = f"stopped_on_{provider_status}"
                break
            elapsed = time.monotonic() - started
            time.sleep(max(0.0, interval - elapsed))

    summary = {
        "session_id": session_id,
        "study_period": "2010Q1-2019Q4",
        "eligible_firm_quarters": len(universe),
        "existing_valid_reused": reused,
        "pending_before_limit": len(pending),
        "live_requests_this_session": sum(counts.values()),
        "classification_counts": dict(counts),
        "stop_reason": stop_reason,
        "request_manifest": manifest_path.relative_to(ROOT).as_posix(),
        "prior_request_manifests": prior_manifest_paths,
        "prior_request_rows_loaded": len(prior_manifest_rows),
        "start_record": start_path.relative_to(ROOT).as_posix(),
    }
    summary_path = args.output_dir / f"{session_id}_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--requests-per-minute",
        type=float,
        default=MAX_REQUESTS_PER_MINUTE,
        help=f"provider request ceiling; maximum {MAX_REQUESTS_PER_MINUTE:g}",
    )
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--max-total-attempts", type=int, default=5)
    parser.add_argument(
        "--prior-request-manifest", action="append", type=Path, default=[],
        help="append-only earlier request manifest whose matching terminal states may be reused",
    )
    parser.add_argument("--limit", type=int, help="bounded number of unresolved firm-quarters")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.universe = args.universe.resolve()
    args.output_dir = args.output_dir.resolve()
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be positive")
    if args.max_total_attempts < 2:
        raise SystemExit("--max-total-attempts must be at least 2")
    try:
        run_pilot(args)
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
