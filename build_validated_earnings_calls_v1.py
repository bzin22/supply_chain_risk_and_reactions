"""Build the validated 2010Q1--2019Q4 earnings-call corpus and report-date map.

This workflow does not collect transcripts, score text, estimate returns, or
download SEC/IR documents.  Canonical ``earnings_call_date`` values are reported
earnings dates mapped to transcript fiscal quarters, with Alpha Vantage
``reportedDate`` as the preferred source.  Only compact date evidence is
retained; full date-source responses are hashed in memory and discarded.
"""

from __future__ import annotations

import argparse
import calendar
import csv
import hashlib
import io
import json
import os
import re
import time
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path
from types import TracebackType
from typing import Any, Self

import requests

from validate_date_map_pilot import (
    LEGACY_AUDIT,
    LEGACY_RAW_ROOT,
    RAW_ROOT,
    ROOT,
    SOURCE_MANIFEST,
    TICKER_HISTORY,
    UNIVERSE,
    fiscal_period_end,
    infer_fiscal_year_end_month,
    initial_classification,
    normalize_text,
    quarter_index,
    read_csv,
    web_user_agent,
)

OUTPUT = ROOT / "data/validated_earnings_calls/v1"
FINAL_DIR = ROOT / "data/final"
REPORT_DIR = ROOT / "review/validated_earnings_calls_v1"
PILOT_DIR = ROOT / "data/validated_earnings_calls/pilot_50_v20260918"
API_URL = "https://www.alphavantage.co/query"
DATE_SOURCE_URL = "https://www.alphavantage.co/documentation/#earnings"
DATE_SOURCE_TITLE = "Alpha Vantage EARNINGS quarterly earnings"
SEC_METADATA_ROOT = (
    ROOT / "artifacts/historical_universe_sources_v20260916/sec/company_metadata"
)

VALIDATION_RANK = {
    "valid": 0,
    "quarantine": 1,
    "identity_mismatch": 2,
    "invalid_content": 3,
    "duplicate": 4,
    "no_transcript": 5,
    "technical_failure": 6,
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def configure_csv_limit() -> None:
    limit = 1024 * 1024
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


class AtomicCsvWriter:
    def __init__(self, path: Path, fields: list[str]) -> None:
        self.path = path
        self.temporary = path.with_suffix(path.suffix + ".tmp")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.temporary.open("w", newline="", encoding="utf-8")
        self.writer = csv.DictWriter(
            self.handle, fieldnames=fields, extrasaction="ignore"
        )
        self.writer.writeheader()

    def writerow(self, row: dict[str, Any]) -> None:
        self.writer.writerow(row)

    def close(self) -> None:
        self.handle.flush()
        os.fsync(self.handle.fileno())
        self.handle.close()
        self.temporary.replace(self.path)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_type is None:
            self.close()
        else:
            self.handle.close()
            self.temporary.unlink(missing_ok=True)


def repo_relative(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def source_key(row: dict[str, str]) -> tuple[str, str, str]:
    return row["company_id"], row["provider_ticker"], row["quarter_label"]


def adapt_legacy_source(
    legacy: dict[str, str], eligible: dict[str, str]
) -> dict[str, str]:
    return {
        "session_id": "legacy_cache_20260904",
        "company_id": eligible["company_id"],
        "cik": eligible["cik"],
        "company_name": eligible["company_name"],
        "provider_ticker": legacy["ticker"].upper(),
        "quarter_label": legacy["quarter_label"],
        "attempt_number": "0",
        "requested_at_utc": legacy["fetched_at_utc"],
        "completed_at_utc": legacy["fetched_at_utc"],
        "http_status": legacy["http_status"],
        "provider_status": legacy["provider_status"],
        "raw_path": legacy["raw_file_path"],
        "raw_size_bytes": legacy["raw_file_size_bytes"],
        "raw_sha256": legacy["raw_file_sha256"],
        "classification": {
            "valid full transcript": "valid",
            "no transcript": "no_transcript",
            "provider information/rate-limit response": "provider_or_http_failure",
        }.get(legacy["response_classification"], "quarantine"),
        "validation_reason": legacy["classification_reasons"],
        "terminal_status": "legacy_alternate",
        "retry_status": legacy["recommended_action"],
        "segment_count": legacy["segment_count"],
        "token_count": legacy["token_count"],
        "normalized_transcript_sha256": legacy[
            "normalized_transcript_sha256"
        ],
        "api_message": legacy["provider_message"],
    }


def legacy_candidate(
    legacy: dict[str, str], candidates: list[dict[str, str]]
) -> dict[str, str] | None:
    if len(candidates) == 1:
        return candidates[0]
    legacy_name = set(normalize_text(legacy.get("company_name", "")).split())
    scored = []
    for row in candidates:
        tokens = set(normalize_text(row["company_name"]).split())
        meaningful = {
            token
            for token in tokens
            if len(token) >= 5
            and token
            not in {"corporation", "company", "incorporated", "holdings", "limited"}
        }
        scored.append((len(meaningful & legacy_name), row))
    scored.sort(key=lambda item: (-item[0], item[1]["company_id"]))
    if scored and scored[0][0] > 0 and (
        len(scored) == 1 or scored[0][0] > scored[1][0]
    ):
        return scored[0][1]
    return None


def deleted_pilot_paths() -> set[str]:
    path = PILOT_DIR / "payload_deletion_manifest.csv"
    if not path.exists():
        return set()
    return {row["raw_path"] for row in read_csv(path)}


def classify_attempt(
    source: dict[str, str],
    eligible: dict[str, str],
    ticker_rows: list[dict[str, str]],
    known_deleted: set[str],
) -> dict[str, Any]:
    raw_path = ROOT / source["raw_path"]
    if not raw_path.is_file() and source["raw_path"] in known_deleted:
        status = (
            "no_transcript"
            if source["classification"] == "no_transcript"
            else "technical_failure"
        )
        return {
            **source,
            "eligible_cik": eligible["cik"],
            "eligible_company_name": eligible["company_name"],
            "eligible_security_id": eligible["security_id"],
            "raw_exists": "false",
            "raw_sha256_verified": "previously_verified_before_deletion",
            "provider_body_sha256": "",
            "canonical_transcript_sha256": "",
            "normalized_transcript_sha256_recomputed": "",
            "payload_symbol": "",
            "payload_quarter": "",
            "payload_symbol_match": "",
            "payload_quarter_match": "",
            "cik_manifest_match": str(source["cik"] == eligible["cik"]).lower(),
            "issuer_name_match": "",
            "ticker_reuse_conflicting_ciks": "",
            "validation_flags": "payload_previously_deleted_after_pilot_freeze",
            "recomputed_segment_count": source["segment_count"],
            "recomputed_token_count": source["token_count"],
            "validation_status": status,
            "validation_reason_final": "routine non-retained payload was verified and deleted after pilot manifest freeze",
            "duplicate_canonical_request": "",
            "storage_disposition": "already_deleted_after_manifest_freeze",
            "error_code": source["api_message"] or source["http_status"]
            if status == "technical_failure"
            else "",
            "transcript_text": "",
        }
    return initial_classification(source, eligible, ticker_rows)


def manifest_fields() -> list[str]:
    return [
        "session_id", "company_id", "cik", "company_name", "provider_ticker",
        "quarter_label", "attempt_number", "requested_at_utc", "completed_at_utc",
        "http_status", "provider_status", "raw_path", "raw_size_bytes", "raw_sha256",
        "classification", "validation_reason", "terminal_status", "retry_status",
        "segment_count", "token_count", "normalized_transcript_sha256", "api_message",
        "eligible_cik", "eligible_company_name", "eligible_security_id", "raw_exists",
        "raw_sha256_verified", "provider_body_sha256", "canonical_transcript_sha256",
        "normalized_transcript_sha256_recomputed", "payload_symbol", "payload_quarter",
        "payload_symbol_match", "payload_quarter_match", "cik_manifest_match",
        "issuer_name_match", "ticker_reuse_conflicting_ciks", "validation_flags",
        "recomputed_segment_count", "recomputed_token_count", "validation_status",
        "validation_reason_final", "duplicate_canonical_request", "storage_disposition",
        "error_code", "retry_history",
    ]


WORKING_FIELDS = [
    "call_id", "company_id", "security_id", "cik", "company_name",
    "historical_ticker", "quarter_label", "transcript_text", "validation_status",
    "validation_reason", "validation_flags", "raw_path", "raw_sha256",
    "canonical_transcript_sha256", "normalized_transcript_sha256", "segment_count",
    "token_count", "payload_symbol_match", "payload_quarter_match", "cik_manifest_match",
    "issuer_name_match", "ticker_reuse_conflicting_ciks",
]


def working_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "call_id": "|".join(
            (row["company_id"], row["provider_ticker"], row["quarter_label"])
        ),
        "company_id": row["company_id"],
        "security_id": row["eligible_security_id"],
        "cik": row["cik"],
        "company_name": row["company_name"],
        "historical_ticker": row["provider_ticker"],
        "quarter_label": row["quarter_label"],
        "transcript_text": row["transcript_text"],
        "validation_status": row["validation_status"],
        "validation_reason": row["validation_reason_final"],
        "validation_flags": row["validation_flags"],
        "raw_path": row["raw_path"],
        "raw_sha256": row["raw_sha256"],
        "canonical_transcript_sha256": row["canonical_transcript_sha256"],
        "normalized_transcript_sha256": row[
            "normalized_transcript_sha256_recomputed"
        ],
        "segment_count": row["recomputed_segment_count"],
        "token_count": row["recomputed_token_count"],
        "payload_symbol_match": row["payload_symbol_match"],
        "payload_quarter_match": row["payload_quarter_match"],
        "cik_manifest_match": row["cik_manifest_match"],
        "issuer_name_match": row["issuer_name_match"],
        "ticker_reuse_conflicting_ciks": row["ticker_reuse_conflicting_ciks"],
    }


def validate_corpus(output: Path) -> dict[str, Any]:
    started = time.monotonic()
    universe = read_csv(UNIVERSE)
    universe.sort(
        key=lambda row: (
            row["company_id"], quarter_index(row["quarter_label"]), row["provider_ticker"]
        )
    )
    eligible_index = {source_key(row): row for row in universe}
    by_ticker_quarter: defaultdict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in universe:
        by_ticker_quarter[(row["provider_ticker"], row["quarter_label"])].append(row)

    sources: defaultdict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in read_csv(SOURCE_MANIFEST):
        key = source_key(row)
        if key in eligible_index:
            sources[key].append(row)

    unmapped_legacy = []
    for legacy in read_csv(LEGACY_AUDIT):
        candidates = by_ticker_quarter[
            (legacy["ticker"].upper(), legacy["quarter_label"])
        ]
        candidate = legacy_candidate(legacy, candidates)
        if candidate is None:
            unmapped_legacy.append(
                {
                    "ticker": legacy["ticker"],
                    "quarter_label": legacy["quarter_label"],
                    "company_name": legacy["company_name"],
                    "raw_path": legacy["raw_file_path"],
                    "raw_sha256": legacy["raw_file_sha256"],
                    "reason": "no unique historical issuer mapping",
                    "storage_disposition": "retain_as_quarantine",
                }
            )
            continue
        sources[source_key(candidate)].append(adapt_legacy_source(legacy, candidate))

    ticker_rows_by_symbol: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
    for ticker_row in read_csv(TICKER_HISTORY):
        ticker_rows_by_symbol[ticker_row["ticker"].upper()].append(ticker_row)
    known_deleted = deleted_pilot_paths()
    seen_hashes: dict[str, str] = {}
    status_counts: Counter[str] = Counter()
    terminal_counts: Counter[str] = Counter()
    attempt_count = 0
    missing_requests = []
    terminal_fields = manifest_fields()
    with (
        AtomicCsvWriter(output / "request_manifest.csv", manifest_fields()) as manifest,
        AtomicCsvWriter(output / "terminal_validation.csv", terminal_fields) as terminal_writer,
        AtomicCsvWriter(output / "validated_calls_working.csv", WORKING_FIELDS) as working,
    ):
        for position, eligible in enumerate(universe, start=1):
            key = source_key(eligible)
            source_rows = sources.get(key, [])
            if not source_rows:
                missing_requests.append(
                    {
                        "company_id": key[0],
                        "provider_ticker": key[1],
                        "quarter_label": key[2],
                    }
                )
                continue
            attempts = [
                classify_attempt(
                    source,
                    eligible,
                    ticker_rows_by_symbol[eligible["provider_ticker"].upper()],
                    known_deleted,
                )
                for source in source_rows
            ]
            attempts.sort(
                key=lambda row: (
                    int(row["attempt_number"]), row["completed_at_utc"], row["raw_path"]
                )
            )
            history = ";".join(
                f"{row['attempt_number']}:{row['validation_status']}:{row['completed_at_utc']}"
                for row in attempts
            )
            for row in attempts:
                row["retry_history"] = history
                digest = row["canonical_transcript_sha256"]
                if row["validation_status"] == "valid" and digest:
                    canonical = seen_hashes.get(digest)
                    request_name = "|".join(
                        (row["company_id"], row["provider_ticker"], row["quarter_label"], row["attempt_number"])
                    )
                    if canonical:
                        row["validation_status"] = "duplicate"
                        row["validation_reason_final"] = "exact canonical transcript hash duplicates named request"
                        row["duplicate_canonical_request"] = canonical
                        row["storage_disposition"] = "delete_after_manifest_freeze"
                    else:
                        seen_hashes[digest] = request_name
                status_counts[row["validation_status"]] += 1
                attempt_count += 1
                manifest.writerow(row)
            chosen = min(
                attempts,
                key=lambda row: (
                    VALIDATION_RANK[row["validation_status"]],
                    -int(row["attempt_number"]),
                    row["completed_at_utc"],
                ),
            )
            terminal_counts[chosen["validation_status"]] += 1
            terminal_writer.writerow(chosen)
            if chosen["validation_status"] == "valid":
                working.writerow(working_row(chosen))
            if position % 5000 == 0:
                print(
                    f"validated {position:,}/{len(universe):,} eligible firm-quarters; valid={terminal_counts['valid']:,}",
                    flush=True,
                )

    if unmapped_legacy:
        fields = list(unmapped_legacy[0])
        with AtomicCsvWriter(output / "unmapped_legacy_quarantine.csv", fields) as writer:
            for row in unmapped_legacy:
                writer.writerow(row)
    if missing_requests:
        with AtomicCsvWriter(
            output / "eligible_without_request.csv", list(missing_requests[0])
        ) as writer:
            for row in missing_requests:
                writer.writerow(row)

    summary = {
        "generated_at_utc": utc_now(),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "eligible_firm_quarters": len(universe),
        "attempts_classified": attempt_count,
        "attempt_status_counts": dict(sorted(status_counts.items())),
        "terminal_status_counts": dict(sorted(terminal_counts.items())),
        "valid_calls": terminal_counts["valid"],
        "eligible_without_request": len(missing_requests),
        "unmapped_legacy_quarantine": len(unmapped_legacy),
        "date_policy": "earnings_call_date equals Alpha Vantage EARNINGS reportedDate mapped by fiscal quarter",
    }
    write_json(output / "validation_summary.json", summary)
    return summary


def subtract_months(value: date, months: int) -> date:
    ordinal = value.year * 12 + value.month - 1 - months
    year, month0 = divmod(ordinal, 12)
    month = month0 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def map_fiscal_rows(payload: dict[str, Any]) -> list[dict[str, str]]:
    annual_dates = []
    for row in payload.get("annualEarnings", []):
        try:
            annual_dates.append(date.fromisoformat(str(row["fiscalDateEnding"])))
        except (KeyError, TypeError, ValueError):
            continue
    annual_dates = sorted(set(annual_dates))
    mapped = []
    for row in payload.get("quarterlyEarnings", []):
        try:
            fiscal_end = date.fromisoformat(str(row["fiscalDateEnding"]))
            reported = date.fromisoformat(str(row["reportedDate"]))
        except (KeyError, TypeError, ValueError):
            continue
        matches = []
        for annual_end in annual_dates:
            for q, months in ((4, 0), (3, 3), (2, 6), (1, 9)):
                expected = subtract_months(annual_end, months)
                distance = abs((fiscal_end - expected).days)
                if distance <= 35:
                    matches.append((distance, annual_end, q))
        if not matches:
            continue
        matches.sort(key=lambda item: (item[0], item[1], item[2]))
        distance, annual_end, q = matches[0]
        mapped.append(
            {
                "quarter_label": f"{annual_end.year}Q{q}",
                "fiscal_date_ending": fiscal_end.isoformat(),
                "reported_date": reported.isoformat(),
                "report_time": str(row.get("reportTime") or ""),
                "fiscal_mapping_distance_days": str(distance),
                "fiscal_year_end": annual_end.isoformat(),
            }
        )
    return mapped


DATE_REQUEST_FIELDS = [
    "historical_ticker", "requested_at_utc", "completed_at_utc", "http_status",
    "status", "retry_history", "error_code", "response_sha256", "mapped_row_count",
    "source_url", "source_title",
]
DELETION_MANIFEST_FIELDS = [
    "raw_path", "raw_sha256", "validation_status", "deleted_at_utc", "deletion_status",
]
DATE_ROW_FIELDS = [
    "historical_ticker", "quarter_label", "fiscal_date_ending", "reported_date",
    "report_time", "fiscal_mapping_distance_days", "fiscal_year_end", "source_url",
    "source_title", "evidence_snippet", "retrieval_timestamp_utc", "match_method",
    "confidence", "status", "response_sha256",
]
YFINANCE_REQUEST_FIELDS = [
    "historical_ticker", "requested_at_utc", "completed_at_utc", "status",
    "retry_history", "error_code", "compact_response_sha256", "earnings_date_count",
    "mapped_row_count", "source_url", "source_title",
]
TARGETED_REQUEST_FIELDS = [
    "historical_ticker", "requested_at_utc", "completed_at_utc", "http_status",
    "status", "error_code", "response_sha256", "source_row_count",
    "mapped_row_count", "source_url", "source_title",
]


def valid_call_keys(path: Path) -> tuple[set[tuple[str, str]], set[str]]:
    keys = set()
    tickers = set()
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            ticker = row["historical_ticker"]
            keys.add((ticker, row["quarter_label"]))
            tickers.add(ticker)
    return keys, tickers


def existing_completed_tickers(
    path: Path, completed_statuses: set[str] | None = None
) -> set[str]:
    if not path.exists():
        return set()
    statuses = completed_statuses or {"success"}
    with path.open(newline="", encoding="utf-8") as handle:
        return {
            row["historical_ticker"]
            for row in csv.DictReader(handle)
            if row["status"] in statuses
        }


def append_csv(path: Path, fields: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists() and path.stat().st_size > 0
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())


def collect_reported_dates(
    output: Path, interval: float, timeout: float, tickers_arg: str | None
) -> dict[str, Any]:
    api_key = os.environ.get("ALPHAVANTAGE_API_KEY")
    if not api_key:
        raise RuntimeError("ALPHAVANTAGE_API_KEY is not present")
    call_keys, all_tickers = valid_call_keys(output / "validated_calls_working.csv")
    selected = sorted(all_tickers)
    if tickers_arg:
        requested = {value.strip().upper() for value in tickers_arg.split(",") if value.strip()}
        selected = [ticker for ticker in selected if ticker in requested]
    completed = existing_completed_tickers(
        output / "reported_date_request_manifest.csv", {"success", "no_history"}
    )
    selected = [ticker for ticker in selected if ticker not in completed]
    session = requests.Session()
    status_counts: Counter[str] = Counter()
    started = time.monotonic()
    for position, ticker in enumerate(selected, start=1):
        request_started = utc_now()
        attempt_notes = []
        payload: dict[str, Any] | None = None
        no_history = False
        body = b""
        http_status = ""
        error_code = ""
        for attempt in range(1, 4):
            try:
                response = session.get(
                    API_URL,
                    params={"function": "EARNINGS", "symbol": ticker, "apikey": api_key},
                    timeout=timeout,
                )
                http_status = str(response.status_code)
                body = response.content
                candidate = response.json()
                message = ""
                if isinstance(candidate, dict):
                    message = str(
                        candidate.get("Information")
                        or candidate.get("Note")
                        or candidate.get("Error Message")
                        or ""
                    )
                if response.status_code == 200 and isinstance(candidate, dict) and isinstance(candidate.get("quarterlyEarnings"), list):
                    payload = candidate
                    attempt_notes.append(f"{attempt}:success")
                    break
                if response.status_code == 200 and candidate == {}:
                    no_history = True
                    error_code = "no_earnings_history_for_symbol"
                    attempt_notes.append(f"{attempt}:no_history")
                    break
                error_code = (
                    message
                    or "empty_or_unexpected_payload"
                    if response.status_code == 200
                    else f"http_{response.status_code}"
                )
                attempt_notes.append(f"{attempt}:provider_error:{error_code[:120]}")
            except (requests.RequestException, ValueError) as exc:
                error_code = type(exc).__name__
                attempt_notes.append(f"{attempt}:technical_failure:{error_code}")
            if attempt < 3:
                time.sleep(max(interval, attempt * 2.0))
        completed_at = utc_now()
        digest = sha256_bytes(body) if body else ""
        mapped = map_fiscal_rows(payload) if payload else []
        relevant = [
            row for row in mapped if (ticker, row["quarter_label"]) in call_keys
        ]
        if payload is not None:
            status = "success"
            date_rows = []
            for row in relevant:
                evidence = (
                    f"{ticker} fiscal period ended {row['fiscal_date_ending']}; "
                    f"reportedDate {row['reported_date']}; mapped to {row['quarter_label']} "
                    f"using fiscal year end {row['fiscal_year_end']}"
                )
                date_rows.append(
                    {
                        "historical_ticker": ticker,
                        **row,
                        "source_url": DATE_SOURCE_URL,
                        "source_title": DATE_SOURCE_TITLE,
                        "evidence_snippet": evidence,
                        "retrieval_timestamp_utc": completed_at,
                        "match_method": "alpha_vantage_fiscalDateEnding_plus_annual_fiscal_year_end",
                        "confidence": "high" if row["fiscal_mapping_distance_days"] == "0" else "medium",
                        "status": "reported_date_mapped",
                        "response_sha256": digest,
                    }
                )
            append_csv(output / "reported_date_rows.csv", DATE_ROW_FIELDS, date_rows)
        elif no_history:
            status = "no_history"
        else:
            status = "technical_failure" if error_code.endswith(("Error", "Timeout")) else "provider_failure"
        append_csv(
            output / "reported_date_request_manifest.csv",
            DATE_REQUEST_FIELDS,
            [
                {
                    "historical_ticker": ticker,
                    "requested_at_utc": request_started,
                    "completed_at_utc": completed_at,
                    "http_status": http_status,
                    "status": status,
                    "retry_history": ";".join(attempt_notes),
                    "error_code": error_code,
                    "response_sha256": digest,
                    "mapped_row_count": len(relevant),
                    "source_url": DATE_SOURCE_URL,
                    "source_title": DATE_SOURCE_TITLE,
                }
            ],
        )
        status_counts[status] += 1
        print(
            f"earnings dates {position:,}/{len(selected):,} {ticker}: {status}, mapped={len(relevant)}",
            flush=True,
        )
        time.sleep(interval)
    summary = {
        "completed_at_utc": utc_now(),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "eligible_ticker_count": len(all_tickers),
        "tickers_requested_this_run": len(selected),
        "status_counts_this_run": dict(status_counts),
        "full_payloads_stored": False,
    }
    write_json(output / "reported_date_collection_summary.json", summary)
    return summary


def collect_yfinance_dates(
    output: Path,
    interval: float,
    tickers_arg: str | None,
    workers: int,
    only_unresolved: bool,
    refresh: bool,
) -> dict[str, Any]:
    import yfinance as yf

    call_keys, all_tickers = valid_call_keys(output / "validated_calls_working.csv")
    quarters_by_ticker: defaultdict[str, set[str]] = defaultdict(set)
    ciks_by_ticker: defaultdict[str, set[str]] = defaultdict(set)
    with (output / "validated_calls_working.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        for call in csv.DictReader(handle):
            ciks_by_ticker[call["historical_ticker"]].add(call["cik"])
    for ticker, quarter in call_keys:
        quarters_by_ticker[ticker].add(quarter)
    selected = sorted(all_tickers)
    if only_unresolved:
        current_map = load_date_map(output)
        selected = sorted(
            {
                ticker
                for ticker, quarter in call_keys
                if (ticker, quarter) not in current_map
            }
        )
    if tickers_arg:
        requested = {value.strip().upper() for value in tickers_arg.split(",") if value.strip()}
        selected = [ticker for ticker in selected if ticker in requested]
    if not refresh:
        completed = existing_completed_tickers(
            output / "yfinance_date_request_manifest.csv"
        )
        selected = [ticker for ticker in selected if ticker not in completed]
    status_counts: Counter[str] = Counter()
    started = time.monotonic()

    def retrieve(ticker: str) -> tuple[str, str, str, list[str], str, list[date], dict[str, Any]]:
        requested_at = utc_now()
        error_code = ""
        notes: list[str] = []
        dates: list[date] = []
        info: dict[str, Any] = {}
        for attempt in range(1, 3):
            try:
                instrument = yf.Ticker(ticker)
                frame = instrument.get_earnings_dates(limit=100)
                if frame is not None:
                    dates = sorted({value.date() for value in frame.index.to_pydatetime()})
                try:
                    info = instrument.info or {}
                except Exception:  # noqa: BLE001 - third-party backend errors vary
                    info = {}
                notes.append(f"{attempt}:success")
                break
            except Exception as exc:  # noqa: BLE001 - compact third-party failure ledger
                error_code = type(exc).__name__
                notes.append(f"{attempt}:technical_failure:{error_code}")
                if attempt < 2:
                    time.sleep(max(1.0, interval))
        time.sleep(interval)
        return ticker, requested_at, utc_now(), notes, error_code, dates, info

    with ThreadPoolExecutor(max_workers=workers) as executor:
        retrieved = executor.map(retrieve, selected)
        for position, result in enumerate(retrieved, start=1):
            ticker, requested_at, completed_at, notes, error_code, dates, info = result
            fiscal_month = infer_fiscal_year_end_month(info)
            fiscal_anchor_source = "yfinance_lastFiscalYearEnd"
            if fiscal_month is None and len(ciks_by_ticker[ticker]) == 1:
                cik = next(iter(ciks_by_ticker[ticker]))
                metadata_path = SEC_METADATA_ROOT / f"CIK{int(cik):010d}.json"
                if metadata_path.exists():
                    try:
                        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                        fiscal_year_end = str(metadata.get("fiscalYearEnd") or "")
                        month = int(fiscal_year_end[:2])
                        if 1 <= month <= 12:
                            fiscal_month = month
                            fiscal_anchor_source = "existing_sec_company_metadata_fiscalYearEnd"
                    except (OSError, ValueError, json.JSONDecodeError):
                        pass
            compact = json.dumps(
                {
                    "dates": [value.isoformat() for value in dates],
                    "lastFiscalYearEndMonth": fiscal_month,
                    "fiscalAnchorSource": fiscal_anchor_source,
                },
                sort_keys=True,
            ).encode()
            mapped_rows = []
            if dates and fiscal_month:
                for quarter in sorted(quarters_by_ticker[ticker], key=quarter_index):
                    year, q = int(quarter[:4]), int(quarter[-1])
                    period_end = fiscal_period_end(year, q, fiscal_month)
                    choices = [
                        value
                        for value in dates
                        if 1 <= (value - period_end).days <= 120
                    ]
                    if not choices:
                        continue
                    candidate = min(
                        choices, key=lambda value: (value - period_end).days
                    )
                    distance = (candidate - period_end).days
                    source_url = f"https://finance.yahoo.com/quote/{ticker}/analysis/"
                    mapped_rows.append(
                        {
                            "historical_ticker": ticker,
                            "quarter_label": quarter,
                            "fiscal_date_ending": period_end.isoformat(),
                            "reported_date": candidate.isoformat(),
                            "report_time": "",
                            "fiscal_mapping_distance_days": str(distance),
                            "fiscal_year_end": "",
                            "source_url": source_url,
                            "source_title": f"Yahoo Finance earnings dates for {ticker}",
                            "evidence_snippet": (
                                f"Yahoo Finance earnings-date row for {ticker} on "
                                f"{candidate.isoformat()}; uniquely selected {distance} days "
                                f"after computed fiscal period end {period_end.isoformat()} for {quarter}; "
                                f"fiscal anchor: {fiscal_anchor_source}"
                            ),
                            "retrieval_timestamp_utc": completed_at,
                            "match_method": (
                                "yfinance_earnings_date_fiscal_period_window_"
                                + fiscal_anchor_source
                            ),
                            "confidence": "high" if len(choices) == 1 else "medium",
                            "status": "reported_date_mapped",
                            "response_sha256": sha256_bytes(compact),
                        }
                    )
                append_csv(
                    output / "yfinance_reported_date_rows.csv",
                    DATE_ROW_FIELDS,
                    mapped_rows,
                )
            status = (
                "success"
                if dates
                else ("technical_failure" if error_code else "no_history")
            )
            append_csv(
                output / "yfinance_date_request_manifest.csv",
                YFINANCE_REQUEST_FIELDS,
                [
                    {
                        "historical_ticker": ticker,
                        "requested_at_utc": requested_at,
                        "completed_at_utc": completed_at,
                        "status": status,
                        "retry_history": ";".join(notes),
                        "error_code": error_code,
                        "compact_response_sha256": sha256_bytes(compact),
                        "earnings_date_count": len(dates),
                        "mapped_row_count": len(mapped_rows),
                        "source_url": f"https://finance.yahoo.com/quote/{ticker}/analysis/",
                        "source_title": f"Yahoo Finance earnings dates for {ticker}",
                    }
                ],
            )
            status_counts[status] += 1
            print(
                f"yfinance dates {position:,}/{len(selected):,} {ticker}: {status}, mapped={len(mapped_rows)}",
                flush=True,
            )
    summary = {
        "completed_at_utc": utc_now(),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "eligible_ticker_count": len(all_tickers),
        "tickers_requested_this_run": len(selected),
        "status_counts_this_run": dict(status_counts),
        "full_payloads_stored": False,
    }
    write_json(output / "yfinance_date_collection_summary.json", summary)
    return summary


def collect_targeted_dates(
    output: Path, interval: float, timeout: float
) -> dict[str, Any]:
    current_map = load_date_map(output)
    call_keys, _ = valid_call_keys(output / "validated_calls_working.csv")
    ciks_by_ticker: defaultdict[str, set[str]] = defaultdict(set)
    with (output / "validated_calls_working.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        for call in csv.DictReader(handle):
            key = (call["historical_ticker"], call["quarter_label"])
            if key not in current_map:
                ciks_by_ticker[call["historical_ticker"]].add(call["cik"])
    tickers = sorted(ciks_by_ticker)
    session = requests.Session()
    status_counts: Counter[str] = Counter()
    started = time.monotonic()
    for position, ticker in enumerate(tickers, start=1):
        requested_at = utc_now()
        source_url = f"https://quant500.com/earnings-date/{ticker}"
        endpoint = (
            "https://quant500.com/api/descarga/resultados.csv"
            f"?ticker={ticker}&lang=en"
        )
        body = b""
        http_status = ""
        error_code = ""
        source_rows: list[dict[str, str]] = []
        try:
            response = session.get(
                endpoint, timeout=timeout, headers={"User-Agent": web_user_agent()}
            )
            http_status = str(response.status_code)
            body = response.content
            text = body.decode("utf-8-sig", errors="replace")
            csv_text = "\n".join(
                line for line in text.splitlines() if not line.startswith("#")
            )
            if response.status_code == 200 and csv_text.strip():
                source_rows = list(csv.DictReader(io.StringIO(csv_text)))
            elif response.status_code != 200:
                error_code = f"http_{response.status_code}"
        except requests.RequestException as exc:
            error_code = type(exc).__name__
        completed_at = utc_now()
        digest = sha256_bytes(body) if body else ""
        expected_ciks = {str(int(value)) for value in ciks_by_ticker[ticker]}
        clean = [
            row
            for row in source_rows
            if row.get("paired_with_report") == "yes"
            and row.get("announcement_date")
            and row.get("quarter_end")
            and str(int(row.get("cik") or "0")) in expected_ciks
        ]
        annual = [
            {"fiscalDateEnding": row["quarter_end"]}
            for row in clean
            if row.get("report_form") == "10-K"
        ]
        quarterly = [
            {
                "fiscalDateEnding": row["quarter_end"],
                "reportedDate": row["announcement_date"],
                "reportTime": row.get("time_ny") or "",
            }
            for row in clean
        ]
        mapped = map_fiscal_rows(
            {"annualEarnings": annual, "quarterlyEarnings": quarterly}
        )
        relevant = [
            row for row in mapped if (ticker, row["quarter_label"]) in call_keys
        ]
        date_rows = []
        for row in relevant:
            date_rows.append(
                {
                    "historical_ticker": ticker,
                    **row,
                    "source_url": source_url,
                    "source_title": f"Quant500 {ticker} earnings announcement dates",
                    "evidence_snippet": (
                        f"{ticker} CIK-matched earnings announcement on {row['reported_date']} "
                        f"paired to report quarter ended {row['fiscal_date_ending']} and "
                        f"mapped to {row['quarter_label']}"
                    ),
                    "retrieval_timestamp_utc": completed_at,
                    "match_method": "quant500_cik_paired_8k_report_fiscal_mapping",
                    "confidence": "high",
                    "status": "reported_date_mapped",
                    "response_sha256": digest,
                }
            )
        append_csv(
            output / "targeted_reported_date_rows.csv", DATE_ROW_FIELDS, date_rows
        )
        if error_code:
            status = "technical_failure"
        elif not clean:
            status = "no_history"
        elif not relevant:
            status = "no_matching_fiscal_rows"
        else:
            status = "success"
        append_csv(
            output / "targeted_date_request_manifest.csv",
            TARGETED_REQUEST_FIELDS,
            [
                {
                    "historical_ticker": ticker,
                    "requested_at_utc": requested_at,
                    "completed_at_utc": completed_at,
                    "http_status": http_status,
                    "status": status,
                    "error_code": error_code,
                    "response_sha256": digest,
                    "source_row_count": len(clean),
                    "mapped_row_count": len(relevant),
                    "source_url": source_url,
                    "source_title": f"Quant500 {ticker} earnings announcement dates",
                }
            ],
        )
        status_counts[status] += 1
        print(
            f"targeted dates {position:,}/{len(tickers):,} {ticker}: {status}, mapped={len(relevant)}",
            flush=True,
        )
        time.sleep(interval)
    summary = {
        "completed_at_utc": utc_now(),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "tickers_requested": len(tickers),
        "status_counts": dict(status_counts),
        "full_payloads_stored": False,
    }
    write_json(output / "targeted_date_collection_summary.json", summary)
    return summary


def parse_explicit_history_rows(body: bytes) -> list[dict[str, str]]:
    text = body.decode("utf-8", errors="replace")
    pattern = re.compile(
        r"Q([1-4])\s+(20\d{2})</td>\s*<td[^>]*>"
        r"(\d{1,2})/(\d{1,2})/(20\d{2})</td>",
        re.IGNORECASE,
    )
    rows = {}
    for q, fiscal_year, month, day, report_year in pattern.findall(text):
        try:
            reported = date(int(report_year), int(month), int(day)).isoformat()
        except ValueError:
            continue
        rows[(fiscal_year, q, reported)] = {
            "quarter_label": f"{fiscal_year}Q{q}",
            "reported_date": reported,
        }
    return list(rows.values())


def collect_history_web_dates(
    output: Path, interval: float, timeout: float
) -> dict[str, Any]:
    current_map = load_date_map(output)
    call_keys, _ = valid_call_keys(output / "validated_calls_working.csv")
    names_by_ticker: defaultdict[str, set[str]] = defaultdict(set)
    with (output / "validated_calls_working.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        for call in csv.DictReader(handle):
            key = (call["historical_ticker"], call["quarter_label"])
            if key not in current_map:
                names_by_ticker[call["historical_ticker"]].add(call["company_name"])
    sources = (
        (
            "Next Earnings Date",
            "https://www.nextearningsdate.com/{ticker}-earnings-history.html",
        ),
        (
            "Historical Earnings",
            "https://www.historicalearnings.com/{ticker}-historical-earnings.html",
        ),
    )
    session = requests.Session()
    status_counts: Counter[str] = Counter()
    request_rows = 0
    started = time.monotonic()
    for position, ticker in enumerate(sorted(names_by_ticker), start=1):
        for source_title, template in sources:
            url = template.format(ticker=ticker.lower())
            requested_at = utc_now()
            body = b""
            http_status = ""
            error_code = ""
            try:
                response = session.get(
                    url, timeout=timeout, headers={"User-Agent": web_user_agent()}
                )
                body = response.content
                http_status = str(response.status_code)
                if response.status_code != 200:
                    error_code = f"http_{response.status_code}"
            except requests.RequestException as exc:
                error_code = type(exc).__name__
            completed_at = utc_now()
            digest = sha256_bytes(body) if body else ""
            parsed = parse_explicit_history_rows(body) if not error_code else []
            page_text = normalize_text(body.decode("utf-8", errors="replace"))
            identity_tokens = {
                token
                for name in names_by_ticker[ticker]
                for token in normalize_text(name).split()
                if len(token) >= 3
                and token
                not in {
                    "the",
                    "inc",
                    "incorporated",
                    "corp",
                    "corporation",
                    "company",
                    "holdings",
                    "limited",
                    "group",
                }
            }
            identity_match = any(
                token in page_text
                for token in identity_tokens
            )
            relevant = [
                row
                for row in parsed
                if (ticker, row["quarter_label"]) in call_keys
                and "2010Q1" <= row["quarter_label"] <= "2019Q4"
            ]
            date_rows = []
            if identity_match:
                for row in relevant:
                    date_rows.append(
                        {
                            "historical_ticker": ticker,
                            "quarter_label": row["quarter_label"],
                            "fiscal_date_ending": "",
                            "reported_date": row["reported_date"],
                            "report_time": "",
                            "fiscal_mapping_distance_days": "",
                            "fiscal_year_end": "",
                            "source_url": url,
                            "source_title": f"{source_title}: {ticker} earnings history",
                            "evidence_snippet": (
                                f"{ticker} {row['quarter_label']} earnings date "
                                f"{row['reported_date']} in explicit period/date table"
                            ),
                            "retrieval_timestamp_utc": completed_at,
                            "match_method": "explicit_fiscal_quarter_earnings_date_table",
                            "confidence": "high_two_source_candidate",
                            "status": "reported_date_mapped",
                            "response_sha256": digest,
                        }
                    )
                append_csv(
                    output / "history_web_reported_date_rows.csv",
                    DATE_ROW_FIELDS,
                    date_rows,
                )
            if error_code:
                status = "technical_failure"
            elif not parsed:
                status = "no_history"
            elif not identity_match:
                status = "identity_mismatch"
            elif not relevant:
                status = "no_matching_fiscal_rows"
            else:
                status = "success"
            append_csv(
                output / "history_web_date_request_manifest.csv",
                TARGETED_REQUEST_FIELDS,
                [
                    {
                        "historical_ticker": ticker,
                        "requested_at_utc": requested_at,
                        "completed_at_utc": completed_at,
                        "http_status": http_status,
                        "status": status,
                        "error_code": error_code,
                        "response_sha256": digest,
                        "source_row_count": len(parsed),
                        "mapped_row_count": len(date_rows),
                        "source_url": url,
                        "source_title": f"{source_title}: {ticker} earnings history",
                    }
                ],
            )
            request_rows += 1
            status_counts[status] += 1
            time.sleep(interval)
        print(
            f"history web {position:,}/{len(names_by_ticker):,} {ticker}",
            flush=True,
        )
    summary = {
        "completed_at_utc": utc_now(),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "tickers_requested": len(names_by_ticker),
        "source_requests": request_rows,
        "status_counts": dict(status_counts),
        "full_payloads_stored": False,
    }
    write_json(output / "history_web_date_collection_summary.json", summary)
    return summary


FINAL_DATE_FIELDS = [
    "earnings_call_date", "date_status", "date_source_url", "date_source_title",
    "date_evidence_snippet", "date_retrieved_at_utc", "date_match_method",
    "date_confidence", "date_fiscal_date_ending", "date_report_time",
    "date_response_sha256", "date_source_agreement",
]


def load_date_evidence(
    output: Path,
) -> tuple[dict[tuple[str, str], dict[str, str]], dict[tuple[str, str], list[str]]]:
    by_key: defaultdict[tuple[str, str], list[tuple[str, dict[str, str]]]] = defaultdict(list)
    for source_name, path in (
        ("alpha_vantage", output / "reported_date_rows.csv"),
        ("targeted_web", output / "targeted_reported_date_rows.csv"),
        ("history_web", output / "history_web_reported_date_rows.csv"),
        ("yfinance", output / "yfinance_reported_date_rows.csv"),
    ):
        if path.exists():
            for row in read_csv(path):
                by_key[(row["historical_ticker"], row["quarter_label"])].append((source_name, row))
    result: dict[tuple[str, str], dict[str, str]] = {}
    conflicting_dates: dict[tuple[str, str], list[str]] = {}
    for key, sourced_rows in by_key.items():
        alpha = [row for source, row in sourced_rows if source == "alpha_vantage"]
        targeted = [row for source, row in sourced_rows if source == "targeted_web"]
        history = [row for source, row in sourced_rows if source == "history_web"]
        yahoo = [row for source, row in sourced_rows if source == "yfinance"]
        # Alpha Vantage gives an explicit fiscalDateEnding/reportedDate pair.
        # Yahoo is the bulk fallback, followed by the two targeted web sources.
        preferred = alpha or yahoo or history or targeted
        by_pair: defaultdict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
        for row in preferred:
            by_pair[(row["reported_date"], row["fiscal_date_ending"])].append(row)
        if len(by_pair) == 1:
            rows = next(iter(by_pair.values()))
            rows.sort(key=lambda row: row["retrieval_timestamp_utc"])
            selected = dict(rows[-1])
            other_dates = {
                row["reported_date"]
                for row in alpha + targeted + history + yahoo
                if row not in preferred
            }
            if not other_dates:
                selected["source_agreement"] = "single_source"
            elif other_dates == {selected["reported_date"]}:
                selected["source_agreement"] = "agree"
            else:
                selected["source_agreement"] = "conflict"
            result[key] = selected
        else:
            conflicting_dates[key] = sorted(
                {reported_date for reported_date, _ in by_pair}
            )
    return result, conflicting_dates


def load_date_map(output: Path) -> dict[tuple[str, str], dict[str, str]]:
    return load_date_evidence(output)[0]


def finalize(output: Path, final_dir: Path, report_dir: Path) -> dict[str, Any]:
    started = time.monotonic()
    date_map, preferred_source_conflicts = load_date_evidence(output)
    working_path = output / "validated_calls_working.csv"
    final_path = final_dir / "earnings_call_transcripts_validated_2010_2019_v1.csv"
    sha_path = final_path.with_suffix(final_path.suffix + ".sha256")
    manifest_path = final_path.with_suffix(".manifest.json")
    for immutable_path in (final_path, sha_path, manifest_path):
        if immutable_path.exists():
            raise RuntimeError(
                f"refusing to overwrite immutable v1 artifact: {immutable_path}"
            )
    validation_summary = json.loads((output / "validation_summary.json").read_text())
    source_manifests = {
        path.name: sha256_file(path) if path.exists() else "absent"
        for path in (
            output / "request_manifest.csv",
            output / "payload_deletion_manifest.csv",
            output / "reported_date_request_manifest.csv",
            output / "yfinance_date_request_manifest.csv",
            output / "targeted_date_request_manifest.csv",
            output / "history_web_date_request_manifest.csv",
        )
    }
    final_fields = WORKING_FIELDS + FINAL_DATE_FIELDS
    date_counts: Counter[str] = Counter()
    selected_sources: Counter[str] = Counter()
    exclusions = []
    seen_calls = set()
    included_calls = set()
    with working_path.open(newline="", encoding="utf-8") as handle, AtomicCsvWriter(
        final_path, final_fields
    ) as writer:
        for row in csv.DictReader(handle):
            if row["call_id"] in seen_calls:
                raise RuntimeError(f"duplicate valid call_id: {row['call_id']}")
            seen_calls.add(row["call_id"])
            date_key = (row["historical_ticker"], row["quarter_label"])
            evidence = date_map.get(date_key)
            if not evidence:
                conflicting_dates = preferred_source_conflicts.get(date_key)
                if conflicting_dates:
                    date_status = "preferred_source_reported_date_conflict"
                    exclusion_reason = (
                        "preferred date source reported conflicting dates for this "
                        f"fiscal quarter: {', '.join(conflicting_dates)}"
                    )
                    date_counts["excluded_preferred_source_conflict"] += 1
                else:
                    date_status = "no_reported_date_found"
                    exclusion_reason = (
                        "no exact reported-date row for the historical ticker and fiscal quarter"
                    )
                    date_counts["excluded_no_reported_date"] += 1
                exclusions.append(
                    {
                        "call_id": row["call_id"],
                        "company_id": row["company_id"],
                        "cik": row["cik"],
                        "company_name": row["company_name"],
                        "historical_ticker": row["historical_ticker"],
                        "quarter_label": row["quarter_label"],
                        "validation_status": row["validation_status"],
                        "date_status": date_status,
                        "exclusion_reason": exclusion_reason,
                    }
                )
                continue
            if row["ticker_reuse_conflicting_ciks"]:
                exclusions.append(
                    {
                        "call_id": row["call_id"],
                        "company_id": row["company_id"],
                        "cik": row["cik"],
                        "company_name": row["company_name"],
                        "historical_ticker": row["historical_ticker"],
                        "quarter_label": row["quarter_label"],
                        "validation_status": "quarantine",
                        "date_status": "reported_date_mapped_ticker_reuse_quarantine",
                        "exclusion_reason": "historical ticker overlaps another CIK; excluded from canonical regression corpus",
                    }
                )
                date_counts["excluded_ticker_reuse_quarantine"] += 1
                continue

            agreement = evidence["source_agreement"]
            if agreement == "conflict":
                    date_status = "reported_date_mapped_conflicting_sources"
            elif agreement == "agree":
                date_status = "reported_date_mapped_sources_agree"
            else:
                date_status = "reported_date_mapped_single_source"
            row.update(
                {
                    "earnings_call_date": evidence["reported_date"],
                    "date_status": date_status,
                    "date_source_url": evidence["source_url"],
                    "date_source_title": evidence["source_title"],
                    "date_evidence_snippet": evidence["evidence_snippet"],
                    "date_retrieved_at_utc": evidence["retrieval_timestamp_utc"],
                    "date_match_method": evidence["match_method"],
                    "date_confidence": evidence["confidence"],
                    "date_fiscal_date_ending": evidence["fiscal_date_ending"],
                    "date_report_time": evidence["report_time"],
                    "date_response_sha256": evidence["response_sha256"],
                    "date_source_agreement": agreement,
                }
            )
            if sha256_bytes(row["transcript_text"].encode()) != row[
                "canonical_transcript_sha256"
            ]:
                raise RuntimeError(f"transcript hash mismatch: {row['call_id']}")
            date_counts[row["date_status"]] += 1
            selected_sources[row["date_source_title"]] += 1
            included_calls.add(row["call_id"])
            writer.writerow(row)

    if exclusions:
        with AtomicCsvWriter(
            report_dir / "canonical_exclusions.csv", list(exclusions[0])
        ) as writer:
            for row in exclusions:
                writer.writerow(row)
    digest = sha256_file(final_path)
    summary = {
        "version": "v1",
        "created_at_utc": utc_now(),
        "immutable_canonical_file": repo_relative(final_path),
        "sha256": digest,
        "row_count": len(included_calls),
        "input_valid_calls": len(seen_calls),
        "validation_status": "valid, dated, and without unresolved ticker reuse",
        "date_policy": "earnings_call_date is the reported earnings date; Alpha Vantage reportedDate is preferred, followed by Yahoo Finance and targeted history sources",
        "date_status_counts": dict(sorted(date_counts.items())),
        "selected_source_title_counts": dict(sorted(selected_sources.items())),
        "excluded_call_count": len(exclusions),
        "exclusion_report": repo_relative(report_dir / "canonical_exclusions.csv"),
        "source_manifest_sha256": source_manifests,
        "validation_summary": validation_summary,
        "elapsed_seconds_finalize": round(time.monotonic() - started, 3),
        "correction_policy": "Do not overwrite v1; corrections create v2.",
    }
    sha_path.write_text(f"{digest}  {final_path.name}\n", encoding="ascii")
    write_json(manifest_path, summary)
    report_dir.mkdir(parents=True, exist_ok=True)
    report = (
        "# Validated earnings-call corpus v1\n\n"
        f"- Canonical dated calls: {len(included_calls):,}\n"
        f"- Valid calls before date and ticker-reuse exclusions: {len(seen_calls):,}\n"
        f"- Excluded without a reported date: {date_counts['excluded_no_reported_date']:,}\n"
        f"- Excluded for conflicting preferred-source reported dates: {date_counts['excluded_preferred_source_conflict']:,}\n"
        f"- Excluded for unresolved ticker reuse: {date_counts['excluded_ticker_reuse_quarantine']:,}\n"
        f"- SHA-256: `{digest}`\n"
        "- `earnings_call_date` is the reported earnings date. Alpha Vantage `reportedDate` is preferred.\n"
        "- Source disagreements remain visible in `date_status` and `date_source_agreement`; the preferred source supplies the canonical date.\n"
        "- Full date-source payloads were not stored.\n"
    )
    (report_dir / "FINAL_REPORT.md").write_text(report, encoding="utf-8")
    for immutable_path in (final_path, sha_path, manifest_path):
        immutable_path.chmod(0o444)
    return summary


def deletion_candidates(output: Path) -> Iterator[dict[str, str]]:
    retained = {"valid", "quarantine"}
    manifest_rows = read_csv(output / "request_manifest.csv")
    retained_paths = {
        row["raw_path"]
        for row in manifest_rows
        if row["validation_status"] in retained and row["raw_path"]
    }
    seen = set()
    for row in manifest_rows:
        path_text = row["raw_path"]
        if (
            row["validation_status"] in retained
            or not path_text
            or path_text in seen
            or path_text in retained_paths
        ):
            continue
        seen.add(path_text)
        path = ROOT / path_text
        yield {
            "raw_path": path_text,
            "raw_sha256": row["raw_sha256"],
            "validation_status": row["validation_status"],
            "deleted_at_utc": "",
            "deletion_status": "already_absent" if not path.exists() else "pending",
        }


def delete_nonretained(output: Path) -> dict[str, Any]:
    rows = list(deletion_candidates(output))
    deletion_path = output / "payload_deletion_manifest.csv"
    with AtomicCsvWriter(deletion_path, DELETION_MANIFEST_FIELDS) as writer:
        for row in rows:
            writer.writerow(row)
    manifest_digest = sha256_file(deletion_path)
    deleted = 0
    bytes_deleted = 0
    for row in rows:
        path = (ROOT / row["raw_path"]).resolve()
        allowed = (RAW_ROOT.resolve(), LEGACY_RAW_ROOT.resolve())
        if not any(path.is_relative_to(root) for root in allowed):
            raise RuntimeError(f"refusing to delete outside transcript raw roots: {path}")
        if not path.exists():
            continue
        actual = sha256_file(path)
        if row["raw_sha256"] and actual != row["raw_sha256"]:
            raise RuntimeError(f"hash changed before deletion: {path}")
        bytes_deleted += path.stat().st_size
        path.unlink()
        deleted += 1
    summary = {
        "completed_at_utc": utc_now(),
        "frozen_request_manifest_sha256": sha256_file(
            output / "request_manifest.csv"
        ),
        "frozen_deletion_manifest_sha256": manifest_digest,
        "candidate_payloads": len(rows),
        "payloads_deleted_this_run": deleted,
        "bytes_deleted_this_run": bytes_deleted,
        "retention_rule": "retain full payloads only for valid and quarantine records",
    }
    write_json(output / "payload_deletion_summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=(
            "validate",
            "dates",
            "dates-yfinance",
            "dates-targeted",
            "dates-history-web",
            "finalize",
            "delete-nonretained",
        ),
    )
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--final-dir", type=Path, default=FINAL_DIR)
    parser.add_argument("--report-dir", type=Path, default=REPORT_DIR)
    parser.add_argument("--interval", type=float, default=1.1)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--only-unresolved", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--tickers", help="comma-separated bounded date-source validation")
    args = parser.parse_args()
    configure_csv_limit()
    if args.command == "validate":
        result = validate_corpus(args.output)
    elif args.command == "dates":
        result = collect_reported_dates(args.output, args.interval, args.timeout, args.tickers)
    elif args.command == "dates-yfinance":
        result = collect_yfinance_dates(
            args.output,
            args.interval,
            args.tickers,
            args.workers,
            args.only_unresolved,
            args.refresh,
        )
    elif args.command == "dates-targeted":
        result = collect_targeted_dates(args.output, args.interval, args.timeout)
    elif args.command == "dates-history-web":
        result = collect_history_web_dates(args.output, args.interval, args.timeout)
    elif args.command == "finalize":
        result = finalize(args.output, args.final_dir, args.report_dir)
    else:
        result = delete_nonretained(args.output)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
