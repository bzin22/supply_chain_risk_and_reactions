"""Validate and date-map a deterministic 50-company earnings-call pilot.

The script never collects transcripts and never downloads or stores SEC/IR
documents.  Network work is limited to yfinance plus search-result/page reads;
only compact source metadata and evidence snippets are persisted.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import subprocess
import time
import urllib.parse
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import requests

from extract_earnings_call_transcript_data import response_segments

ROOT = Path(__file__).resolve().parent
UNIVERSE = (
    ROOT / "data/universe/us_operating_companies_v20260916/eligible_firm_quarters.csv"
)
TICKER_HISTORY = (
    ROOT / "data/universe/us_operating_companies_v20260916/ticker_history.csv"
)
SAMPLE_450 = ROOT / "data/provisional/convenience_sample_450_companies_9_sectors.csv"
SOURCE_MANIFEST = (
    ROOT / "artifacts/full_transcript_collection_v20260917/request_manifest.csv"
)
RAW_ROOT = ROOT / "artifacts/full_transcript_collection_v20260917/raw"
LEGACY_AUDIT = (
    ROOT / "review/alpha_vantage_transcript_audit_20260916/response_manifest.csv"
)
LEGACY_RAW_ROOT = ROOT / "artifacts/earnings_call_responses"
DEFAULT_OUTPUT = ROOT / "data/validated_earnings_calls/pilot_50_v20260918"
DEFAULT_REPORT = ROOT / "review/validated_earnings_calls_pilot_50_v20260918"

STUDY_START = "2010Q1"
STUDY_END = "2019Q4"
SECTOR_RANKS = (0, 12, 24, 36, 49)
SPECIAL_TICKERS = ("ON", "JEF", "RJF", "UVV", "DWSN")
GENERIC_NAME_TOKENS = {
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "company",
    "co",
    "holdings",
    "holding",
    "group",
    "limited",
    "ltd",
    "plc",
    "the",
    "international",
    "technologies",
    "technology",
    "systems",
    "services",
    "industries",
}
PLACEHOLDER_PATTERNS = (
    "transcript has been redacted",
    "content unavailable",
    "access denied",
    "copyright infringement",
    "this transcript is not available",
)
TRUNCATION_PATTERNS = ("[truncated]", "transcript truncated", "content cut off")
WEB_USER_AGENT = "Mozilla/5.0"
MONTHS = {
    name.lower(): number
    for number, name in enumerate(
        (
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ),
        1,
    )
}
MONTHS.update({name[:3]: number for name, number in list(MONTHS.items())})


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def normalize_text(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fields: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def quarter_index(label: str) -> int:
    match = re.fullmatch(r"(20\d{2})Q([1-4])", label)
    if not match or not STUDY_START <= label <= STUDY_END:
        raise ValueError(f"invalid study quarter: {label}")
    return int(match.group(1)) * 4 + int(match.group(2)) - 1


def distinctive_name_tokens(name: str) -> list[str]:
    return [
        token
        for token in normalize_text(name).split()
        if token not in GENERIC_NAME_TOKENS and (len(token) >= 5 or token.isupper())
    ]


def select_pilot(output: Path) -> list[dict[str, str]]:
    sample = read_csv(SAMPLE_450)
    universe = read_csv(UNIVERSE)
    ticker_history = read_csv(TICKER_HISTORY)
    company_by_ticker: defaultdict[str, set[str]] = defaultdict(set)
    tickers_by_company: defaultdict[str, set[str]] = defaultdict(set)
    for row in ticker_history:
        company_by_ticker[row["ticker"].upper()].add(row["company_id"])
        tickers_by_company[row["company_id"]].add(row["ticker"].upper())

    eligible_by_company: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
    for row in universe:
        quarter_index(row["quarter_label"])
        eligible_by_company[row["company_id"]].append(row)

    by_sector: defaultdict[str, list[tuple[int, dict[str, str], str]]] = defaultdict(
        list
    )
    for global_rank, row in enumerate(sample):
        ticker = row["symbol"].upper()
        company_ids = company_by_ticker[ticker]
        if len(company_ids) != 1:
            continue
        company_id = next(iter(company_ids))
        if company_id not in eligible_by_company:
            continue
        sector_rank = sum(
            1 for prior in sample[:global_rank] if prior["sector"] == row["sector"]
        )
        by_sector[row["sector"]].append((sector_rank, row, company_id))

    selected: list[dict[str, str]] = []
    seen: set[str] = set()
    for sector in sorted(by_sector):
        candidates = by_sector[sector]
        for target_rank in SECTOR_RANKS:
            available = [item for item in candidates if item[2] not in seen]
            if not available:
                raise RuntimeError(f"no unused candidate for sector {sector}")
            chosen = min(
                available,
                key=lambda item: (
                    abs(item[0] - target_rank),
                    item[0],
                    item[1]["symbol"],
                ),
            )
            rank, source, company_id = chosen
            representative = min(
                eligible_by_company[company_id], key=lambda row: row["quarter_label"]
            )
            selected.append(
                {
                    "company_id": company_id,
                    "cik": representative["cik"],
                    "company_name": representative["company_name"],
                    "sector": sector,
                    "sample_ticker": source["symbol"].upper(),
                    "selection_role": "sector_size_proxy",
                    "sector_rank_size_proxy": str(rank + 1),
                    "historical_ticker_count": str(len(tickers_by_company[company_id])),
                }
            )
            seen.add(company_id)

    for ticker in SPECIAL_TICKERS:
        company_ids = company_by_ticker[ticker]
        if len(company_ids) != 1:
            raise RuntimeError(f"special ticker is not uniquely mapped: {ticker}")
        company_id = next(iter(company_ids))
        if company_id in seen:
            continue
        representative = min(
            eligible_by_company[company_id], key=lambda row: row["quarter_label"]
        )
        sample_row = next(
            (row for row in sample if row["symbol"].upper() == ticker), None
        )
        selected.append(
            {
                "company_id": company_id,
                "cik": representative["cik"],
                "company_name": representative["company_name"],
                "sector": sample_row["sector"]
                if sample_row
                else representative["sic_division"],
                "sample_ticker": ticker,
                "selection_role": "historical_ticker_change",
                "sector_rank_size_proxy": "",
                "historical_ticker_count": str(len(tickers_by_company[company_id])),
            }
        )
        seen.add(company_id)

    if len(selected) != 50 or len(seen) != 50:
        raise RuntimeError(
            f"pilot selection produced {len(selected)} companies, expected 50"
        )

    selected_ids = {row["company_id"] for row in selected}
    eligible = [row for row in universe if row["company_id"] in selected_ids]
    eligible.sort(
        key=lambda row: (
            row["company_id"],
            quarter_index(row["quarter_label"]),
            row["provider_ticker"],
        )
    )
    by_company_count = Counter(row["company_id"] for row in eligible)
    for row in selected:
        row["eligible_firm_quarters"] = str(by_company_count[row["company_id"]])
        row["selection_seed"] = (
            "sector ranks 1,13,25,37,50 plus fixed ticker-change cases v20260918"
        )

    write_csv(output / "pilot_companies.csv", list(selected[0]), selected)
    write_csv(output / "eligible_firm_quarters.csv", list(eligible[0]), eligible)
    return selected


def transcript_text(payload: Any, include_speakers: bool = False) -> str:
    parts: list[str] = []
    for segment in response_segments(payload):
        content = str(segment.get("content") or "").strip()
        if not content:
            continue
        if include_speakers:
            speaker = str(segment.get("speaker") or "Unknown").strip()
            title = str(segment.get("title") or "").strip()
            prefix = f"[{speaker}{' | ' + title if title else ''}]"
            parts.append(f"{prefix} {content}")
        else:
            parts.append(content)
    return "\n\n".join(parts)


def load_wrapper(path: Path) -> tuple[dict[str, Any] | None, str]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return (value if isinstance(value, dict) else None), ""
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, type(exc).__name__


def overlap_ticker_reuse(
    ticker: str, company_id: str, quarter: str, ticker_rows: list[dict[str, str]]
) -> list[str]:
    year = int(quarter[:4])
    q = int(quarter[-1])
    quarter_end_month = q * 3
    quarter_end = date(year, quarter_end_month, 1)
    if quarter_end_month == 12:
        quarter_end = date(year, 12, 31)
    else:
        quarter_end = date(year, quarter_end_month + 1, 1) - timedelta(days=1)
    conflicts = set()
    for row in ticker_rows:
        if row["ticker"].upper() != ticker.upper() or row["company_id"] == company_id:
            continue
        start = (
            date.fromisoformat(row["effective_start"])
            if row["effective_start"]
            else date.min
        )
        end = (
            date.fromisoformat(row["effective_end"])
            if row["effective_end"]
            else date.max
        )
        if start <= quarter_end <= end:
            conflicts.add(row["company_id"])
    return sorted(conflicts)


def initial_classification(
    source: dict[str, str], eligible: dict[str, str], ticker_rows: list[dict[str, str]]
) -> dict[str, Any]:
    raw_path = ROOT / source["raw_path"]
    raw_exists = raw_path.is_file()
    raw = raw_path.read_bytes() if raw_exists else b""
    wrapper, parse_error = (
        load_wrapper(raw_path) if raw_exists else (None, "FileNotFoundError")
    )
    payload = wrapper.get("payload") if wrapper else None
    plain = transcript_text(payload)
    rendered = transcript_text(payload, include_speakers=True)
    normalized = normalize_text(plain)
    token_count = len(normalized.split())
    segments = response_segments(payload)
    speakers = {
        str(row.get("speaker") or "").strip() for row in segments if row.get("speaker")
    }
    payload_symbol = (
        str(payload.get("symbol") or "").upper() if isinstance(payload, dict) else ""
    )
    payload_quarter = (
        str(payload.get("quarter") or "").upper() if isinstance(payload, dict) else ""
    )
    opening = normalized[:20000]
    name_tokens = distinctive_name_tokens(eligible["company_name"])
    issuer_match = any(
        token in opening.split() or token in opening for token in name_tokens
    )
    ticker_conflicts = overlap_ticker_reuse(
        eligible["provider_ticker"],
        eligible["company_id"],
        eligible["quarter_label"],
        ticker_rows,
    )
    flags: list[str] = []
    if token_count < 1000 and normalized:
        flags.append("short_under_1000_tokens_reviewed")
    if len(speakers) < 2 and normalized:
        flags.append("fewer_than_two_speakers")
    if not issuer_match and normalized:
        flags.append("issuer_name_not_explicit_in_opening")
    if ticker_conflicts:
        flags.append("historical_ticker_reuse_overlap")
    lowered = plain.lower()
    placeholder = next((item for item in PLACEHOLDER_PATTERNS if item in lowered), "")
    truncation = next((item for item in TRUNCATION_PATTERNS if item in lowered), "")

    classification = "valid"
    reason = "structural content and request identity checks passed"
    if not raw_exists or (parse_error and not normalized):
        classification, reason = (
            "technical_failure",
            f"unreadable or missing payload: {parse_error}",
        )
    elif (
        source["classification"] in {"provider_or_http_failure", "transport_error"}
        and not normalized
    ):
        classification, reason = (
            "technical_failure",
            source["validation_reason"] or source["classification"],
        )
    elif not normalized and source["classification"] == "no_transcript":
        classification, reason = (
            "no_transcript",
            "provider returned no substantive transcript",
        )
    elif not normalized:
        classification, reason = (
            "technical_failure",
            "empty payload without a routine no-transcript status",
        )
    elif placeholder:
        classification, reason = (
            "invalid_content",
            f"confirmed non-transcript marker: {placeholder}",
        )
    elif payload_symbol and payload_symbol != eligible["provider_ticker"].upper():
        classification, reason = (
            "identity_mismatch",
            f"payload symbol {payload_symbol} differs from requested ticker",
        )
    elif payload_quarter and payload_quarter != eligible["quarter_label"]:
        classification, reason = (
            "identity_mismatch",
            f"payload quarter {payload_quarter} differs from requested quarter",
        )
    elif truncation or token_count < 150 or len(speakers) < 2:
        classification, reason = (
            "quarantine",
            truncation or "content is too short or structurally incomplete",
        )
    elif ticker_conflicts and not issuer_match:
        classification, reason = (
            "quarantine",
            "ticker reuse overlaps another CIK and issuer text does not resolve it",
        )
    elif not issuer_match:
        # Exact historical ticker/CIK/quarter linkage remains strong, but the
        # missing name is exposed as a flag for pilot review rather than used
        # as a silent rejection.
        reason = "request identity agrees; issuer name is not explicit in opening text"

    return {
        **source,
        "eligible_cik": eligible["cik"],
        "eligible_company_name": eligible["company_name"],
        "eligible_security_id": eligible["security_id"],
        "raw_exists": str(raw_exists).lower(),
        "raw_sha256_verified": str(
            raw_exists and sha256_bytes(raw) == source["raw_sha256"]
        ).lower(),
        "provider_body_sha256": sha256_bytes(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
        )
        if payload is not None
        else "",
        "canonical_transcript_sha256": sha256_bytes(rendered.encode())
        if rendered
        else "",
        "normalized_transcript_sha256_recomputed": sha256_bytes(normalized.encode())
        if normalized
        else "",
        "payload_symbol": payload_symbol,
        "payload_quarter": payload_quarter,
        "payload_symbol_match": str(
            not payload_symbol or payload_symbol == eligible["provider_ticker"].upper()
        ).lower(),
        "payload_quarter_match": str(
            not payload_quarter or payload_quarter == eligible["quarter_label"]
        ).lower(),
        "cik_manifest_match": str(source["cik"] == eligible["cik"]).lower(),
        "issuer_name_match": str(issuer_match).lower(),
        "ticker_reuse_conflicting_ciks": ";".join(ticker_conflicts),
        "validation_flags": ";".join(flags),
        "recomputed_segment_count": str(len(segments)),
        "recomputed_token_count": str(token_count),
        "validation_status": classification,
        "validation_reason_final": reason,
        "duplicate_canonical_request": "",
        "storage_disposition": "retain"
        if classification in {"valid", "quarantine"}
        else "delete_after_manifest_freeze",
        "error_code": source["api_message"] or source["http_status"]
        if classification == "technical_failure"
        else "",
        "transcript_text": rendered,
    }


def validate_pilot(output: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    eligible_rows = read_csv(output / "eligible_firm_quarters.csv")
    eligible_index = {
        (row["company_id"], row["provider_ticker"], row["quarter_label"]): row
        for row in eligible_rows
    }
    ticker_rows = read_csv(TICKER_HISTORY)
    source_rows = [
        row
        for row in read_csv(SOURCE_MANIFEST)
        if (row["company_id"], row["provider_ticker"], row["quarter_label"])
        in eligible_index
    ]
    # The historical 450-company cache contains alternate attempts that the
    # full-universe collector intentionally did not copy.  Include those
    # responses in the pilot ledger without treating them as extra call rows.
    for legacy in read_csv(LEGACY_AUDIT):
        matching = [
            (key, eligible)
            for key, eligible in eligible_index.items()
            if key[1] == legacy["ticker"].upper() and key[2] == legacy["quarter_label"]
        ]
        for key, eligible in matching:
            source_rows.append(
                {
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
            )
    attempts: list[dict[str, Any]] = []
    for source in source_rows:
        key = (source["company_id"], source["provider_ticker"], source["quarter_label"])
        attempts.append(
            initial_classification(source, eligible_index[key], ticker_rows)
        )

    by_hash: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in attempts:
        if row["validation_status"] == "valid" and row["canonical_transcript_sha256"]:
            by_hash[row["canonical_transcript_sha256"]].append(row)
    for group in by_hash.values():
        if len(group) < 2:
            continue
        group.sort(
            key=lambda row: (
                row["company_id"],
                quarter_index(row["quarter_label"]),
                int(row["attempt_number"]),
                row["completed_at_utc"],
            )
        )
        canonical = group[0]
        canonical_key = "|".join(
            (
                canonical["company_id"],
                canonical["provider_ticker"],
                canonical["quarter_label"],
                canonical["attempt_number"],
            )
        )
        for duplicate in group[1:]:
            duplicate["validation_status"] = "duplicate"
            duplicate["validation_reason_final"] = (
                "exact canonical transcript hash duplicates named request"
            )
            duplicate["duplicate_canonical_request"] = canonical_key
            duplicate["storage_disposition"] = "delete_after_manifest_freeze"

    by_request: defaultdict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(
        list
    )
    for row in attempts:
        by_request[
            (row["company_id"], row["provider_ticker"], row["quarter_label"])
        ].append(row)
    for rows in by_request.values():
        history = ";".join(
            f"{row['attempt_number']}:{row['validation_status']}:{row['completed_at_utc']}"
            for row in sorted(
                rows,
                key=lambda item: (
                    int(item["attempt_number"]),
                    item["completed_at_utc"],
                ),
            )
        )
        for row in rows:
            row["retry_history"] = history

    rank = {
        "valid": 0,
        "quarantine": 1,
        "identity_mismatch": 2,
        "invalid_content": 3,
        "duplicate": 4,
        "no_transcript": 5,
        "technical_failure": 6,
    }
    terminal: list[dict[str, Any]] = []
    for key, rows in by_request.items():
        chosen = min(
            rows,
            key=lambda row: (
                rank[row["validation_status"]],
                -int(row["attempt_number"]),
                row["completed_at_utc"],
            ),
        )
        terminal.append(chosen)
    terminal.sort(
        key=lambda row: (
            row["company_id"],
            quarter_index(row["quarter_label"]),
            row["provider_ticker"],
        )
    )

    missing = set(eligible_index) - set(by_request)
    if missing:
        raise RuntimeError(
            f"pilot has {len(missing)} eligible firm-quarters without a collected request; first={sorted(missing)[:3]}"
        )
    if any(row["raw_sha256_verified"] != "true" for row in attempts):
        bad = [
            row["raw_path"] for row in attempts if row["raw_sha256_verified"] != "true"
        ]
        raise RuntimeError(
            f"raw hash verification failed for {len(bad)} pilot payloads; first={bad[:3]}"
        )

    manifest_fields = [field for field in attempts[0] if field != "transcript_text"]
    write_csv(output / "request_manifest.csv", manifest_fields, attempts)
    terminal_fields = [field for field in terminal[0] if field != "transcript_text"]
    write_csv(output / "terminal_validation.csv", terminal_fields, terminal)

    valid_calls = []
    for row in terminal:
        if row["validation_status"] != "valid":
            continue
        valid_calls.append(
            {
                "call_id": "|".join(
                    (row["company_id"], row["provider_ticker"], row["quarter_label"])
                ),
                "company_id": row["company_id"],
                "cik": row["cik"],
                "company_name": row["company_name"],
                "historical_ticker": row["provider_ticker"],
                "quarter_label": row["quarter_label"],
                "transcript_text": row["transcript_text"],
                "validation_status": "valid",
                "validation_flags": row["validation_flags"],
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
                "earnings_call_date": "",
                "date_status": "no_source_found",
                "date_source_url": "",
                "date_source_title": "",
                "date_evidence_snippet": "",
                "date_retrieved_at_utc": "",
                "date_match_method": "",
                "date_confidence": "",
            }
        )
    write_csv(output / "validated_calls_working.csv", list(valid_calls[0]), valid_calls)
    return attempts, valid_calls


def size_tier(market_cap: Any) -> str:
    try:
        value = float(market_cap)
    except (TypeError, ValueError):
        return "unavailable"
    if value >= 200_000_000_000:
        return "mega"
    if value >= 10_000_000_000:
        return "large"
    if value >= 2_000_000_000:
        return "mid"
    return "small"


def infer_fiscal_year_end_month(info: dict[str, Any]) -> int | None:
    value = info.get("lastFiscalYearEnd")
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value, UTC).month
    return None


def fiscal_period_end(year: int, q: int, fiscal_end_month: int) -> date:
    month = ((fiscal_end_month - 3 * (4 - q) - 1) % 12) + 1
    period_year = year if month <= fiscal_end_month else year - 1
    if month == 12:
        return date(period_year, 12, 31)
    return date(period_year, month + 1, 1) - timedelta(days=1)


def parse_date_text(value: str) -> date | None:
    match = re.search(
        r"\b("
        + "|".join(name.title() for name in MONTHS if len(name) > 3)
        + r")\s+(\d{1,2}),\s+(20\d{2})\b",
        value,
        re.IGNORECASE,
    )
    if not match:
        match = re.search(r"\b(20\d{2})-(\d{2})-(\d{2})\b", value)
        if not match:
            return None
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    return date(
        int(match.group(3)), MONTHS[match.group(1).lower()], int(match.group(2))
    )


def yahoo_search(
    query: str, session: requests.Session, timeout: float
) -> list[dict[str, str]]:
    url = "https://www.bing.com/search?format=rss&q=" + urllib.parse.quote_plus(query)
    completed = subprocess.run(
        [
            "curl",
            "-sL",
            "--max-time",
            str(max(1, int(timeout))),
            "-A",
            WEB_USER_AGENT,
            url,
        ],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise requests.RequestException(
            f"search transport failed with curl code {completed.returncode}"
        )
    values: list[dict[str, str]] = []
    try:
        root = ET.fromstring(completed.stdout)
    except ET.ParseError:
        return values
    for item in root.findall("./channel/item")[:8]:
        values.append(
            {
                "url": (item.findtext("link") or "").strip(),
                "title": (item.findtext("title") or "").strip(),
                "snippet": normalize_html_text(item.findtext("description") or ""),
            }
        )
    return values


def normalize_html_text(value: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value)).split())


def page_evidence(
    url: str, session: requests.Session, timeout: float
) -> tuple[str, str, str]:
    completed = subprocess.run(
        [
            "curl",
            "-sL",
            "--max-time",
            str(max(1, int(timeout))),
            "-A",
            WEB_USER_AGENT,
            url,
        ],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise requests.RequestException(
            f"page transport failed with curl code {completed.returncode}"
        )
    body = completed.stdout.decode("utf-8", errors="replace")
    title_match = re.search(
        r"<title[^>]*>(.*?)</title>", body, re.IGNORECASE | re.DOTALL
    )
    title = normalize_html_text(title_match.group(1)) if title_match else ""
    visible = normalize_html_text(
        re.sub(
            r"<(script|style)[^>]*>.*?</\1>", " ", body, flags=re.IGNORECASE | re.DOTALL
        )
    )
    marker = re.search(r"Q[1-4]\s+20\d{2}\s+Earnings\s+Call", visible, re.IGNORECASE)
    window = (
        visible[max(0, marker.start() - 300) : marker.start() + 1200]
        if marker
        else visible[:2500]
    )
    return title, window[:1000], url


def result_looks_relevant(result: dict[str, str], call: dict[str, str]) -> bool:
    combined = normalize_text(" ".join((result["title"], result["snippet"])))
    q = call["quarter_label"][-1]
    year = call["quarter_label"][:4]
    quarter_ok = bool(
        re.search(rf"\bq{q}\s+(?:fy\s*)?{year}\b|\b{year}\s+q{q}\b", combined)
    )
    event_ok = "earnings call" in combined
    ticker_ok = call["historical_ticker"].lower() in combined.split()
    name_ok = any(
        token in combined.split()
        for token in distinctive_name_tokens(call["company_name"])
    )
    return quarter_ok and event_ok and (ticker_ok or name_ok)


def explicit_web_match(
    result: dict[str, str], call: dict[str, str], page_title: str, page_text: str
) -> tuple[date | None, str]:
    q = call["quarter_label"][-1]
    year = call["quarter_label"][:4]
    combined = " ".join((result["title"], result["snippet"], page_title, page_text))
    quarter_ok = bool(
        re.search(
            rf"\bQ{q}\s+(?:FY\s*)?{year}\b|\b{year}\s+Q{q}\b", combined, re.IGNORECASE
        )
    )
    ticker_ok = bool(
        re.search(
            rf"\b{re.escape(call['historical_ticker'])}\b", combined, re.IGNORECASE
        )
    )
    name_ok = any(
        token in normalize_text(combined).split()
        for token in distinctive_name_tokens(call["company_name"])
    )
    earnings_call_ok = bool(
        re.search(r"earnings\s+(?:conference\s+)?call", combined, re.IGNORECASE)
    )
    if not (quarter_ok and earnings_call_ok and (ticker_ok or name_ok)):
        return None, ""
    marker = re.search(
        rf"Q{q}\s+(?:FY\s*)?{year}\s+Earnings\s+Call", combined, re.IGNORECASE
    )
    nearby = combined[marker.start() : marker.start() + 500] if marker else combined
    found = parse_date_text(nearby) or parse_date_text(combined)
    return found, nearby[:500]


def yfinance_dates(ticker: str, limit: int = 100) -> tuple[list[date], dict[str, Any]]:
    import yfinance as yf

    instrument = yf.Ticker(ticker)
    frame = instrument.get_earnings_dates(limit=limit)
    dates: list[date] = []
    if frame is not None:
        dates = sorted({value.date() for value in frame.index.to_pydatetime()})
    try:
        info = instrument.info or {}
    except Exception:  # noqa: BLE001 - yfinance exposes several backend exception types
        info = {}
    return dates, info


def map_dates(
    output: Path, sleep_seconds: float, timeout: float
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    calls = read_csv(output / "validated_calls_working.csv")
    companies = read_csv(output / "pilot_companies.csv")
    calls_by_ticker: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
    for call in calls:
        calls_by_ticker[call["historical_ticker"]].append(call)
    session = requests.Session()
    retrieved = utc_now()
    ticker_cache: dict[str, dict[str, Any]] = {}
    for ticker in sorted(calls_by_ticker):
        started = time.monotonic()
        try:
            dates, info = yfinance_dates(ticker)
            ticker_cache[ticker] = {
                "dates": dates,
                "info": info,
                "error": "",
                "retrieved_at_utc": utc_now(),
            }
        except Exception as exc:  # noqa: BLE001 - record third-party retrieval failures compactly
            ticker_cache[ticker] = {
                "dates": [],
                "info": {},
                "error": type(exc).__name__,
                "retrieved_at_utc": utc_now(),
            }
        time.sleep(max(0.0, sleep_seconds - (time.monotonic() - started)))

    for company in companies:
        cache = ticker_cache.get(company["sample_ticker"], {})
        info = cache.get("info", {})
        market_cap = info.get("marketCap", "") if isinstance(info, dict) else ""
        company["current_market_cap_usd"] = str(market_cap or "")
        company["current_market_cap_tier"] = size_tier(market_cap)
        company["size_source"] = (
            "yfinance Ticker.info marketCap" if market_cap else "unavailable"
        )
        company["size_retrieved_at_utc"] = cache.get("retrieved_at_utc", "")
    write_csv(output / "pilot_companies.csv", list(companies[0]), companies)

    provenance: list[dict[str, Any]] = []
    final_by_call: dict[str, dict[str, Any]] = {}
    for call in calls:
        ticker = call["historical_ticker"]
        cache = ticker_cache[ticker]
        year, q = int(call["quarter_label"][:4]), int(call["quarter_label"][-1])
        fiscal_month = infer_fiscal_year_end_month(cache["info"])
        candidate: date | None = None
        method = ""
        confidence = ""
        if fiscal_month:
            period_end = fiscal_period_end(year, q, fiscal_month)
            choices = [
                value
                for value in cache["dates"]
                if 1 <= (value - period_end).days <= 120
            ]
            if choices:
                candidate = min(choices, key=lambda value: (value - period_end).days)
                method = "yfinance_fiscal_period_window"
                confidence = "medium_candidate_only"
        if candidate is None:
            same_year = [
                value for value in cache["dates"] if value.year in {year - 1, year}
            ]
            if same_year:
                candidate = min(
                    same_year,
                    key=lambda value: abs((value - date(year, q * 3, 15)).days),
                )
                method = "yfinance_nearest_unresolved_fiscal_calendar"
                confidence = "low_candidate_only"
        if candidate:
            provenance.append(
                {
                    "call_id": call["call_id"],
                    "candidate_date": candidate.isoformat(),
                    "source_type": "yfinance",
                    "source_url": f"https://finance.yahoo.com/calendar/earnings?symbol={urllib.parse.quote(ticker)}&day={candidate.isoformat()}",
                    "source_title": f"Yahoo Finance earnings calendar for {ticker}",
                    "evidence_snippet": f"yfinance earnings-date row for {ticker} on {candidate.isoformat()}; fiscal period match is algorithmic, not explicit",
                    "retrieval_timestamp_utc": cache["retrieved_at_utc"],
                    "match_method": method,
                    "confidence": confidence,
                    "status": "ambiguous",
                }
            )

        needs_search = (
            candidate is None
            or cache["error"]
            or confidence.startswith("low")
            or bool(call["ticker_reuse_conflicting_ciks"])
        )
        web_matches: list[dict[str, Any]] = []
        if needs_search:
            queries = [
                (
                    "yahoo_finance_web_search",
                    f"site:finance.yahoo.com/news/ {call['company_name']} {ticker} Q{q} {year} earnings call transcript",
                ),
                (
                    "targeted_web_backup",
                    f"{call['company_name']} {ticker} Q{q} {year} earnings call transcript date -site:sec.gov",
                ),
            ]
            for source_type, query in queries:
                if source_type == "targeted_web_backup" and web_matches:
                    break
                try:
                    results = yahoo_search(query, session, timeout)
                except requests.RequestException:
                    results = []
                for result in results:
                    host = urllib.parse.urlparse(result["url"]).netloc.lower()
                    if (
                        source_type == "yahoo_finance_web_search"
                        and "finance.yahoo.com" not in host
                    ):
                        continue
                    if (
                        "sec.gov" in host
                        or "investor" in host
                        or host.startswith("ir.")
                    ):
                        continue
                    try:
                        page_title, page_text, resolved_url = page_evidence(
                            result["url"], session, timeout
                        )
                    except requests.RequestException:
                        page_title, page_text, resolved_url = (
                            result["title"],
                            result["snippet"],
                            result["url"],
                        )
                    found, snippet = explicit_web_match(
                        result, call, page_title, page_text
                    )
                    if found:
                        web_matches.append(
                            {
                                "call_id": call["call_id"],
                                "candidate_date": found.isoformat(),
                                "source_type": source_type,
                                "source_url": resolved_url,
                                "source_title": page_title or result["title"],
                                "evidence_snippet": snippet or result["snippet"],
                                "retrieval_timestamp_utc": utc_now(),
                                "match_method": "explicit_issuer_quarter_call_date_text",
                                "confidence": "high",
                                "status": "confirmed_call_date",
                            }
                        )
                        break
                time.sleep(sleep_seconds)

        provenance.extend(web_matches)
        explicit_dates = sorted({row["candidate_date"] for row in web_matches})
        if len(explicit_dates) == 1:
            confirmed = explicit_dates[0]
            if candidate and abs((candidate - date.fromisoformat(confirmed)).days) > 1:
                status = "conflicting_sources"
                final_date = ""
                confidence_final = "conflict"
            else:
                status = "confirmed_call_date"
                final_date = confirmed
                confidence_final = "high"
            source_row = web_matches[0]
        elif len(explicit_dates) > 1:
            status, final_date, confidence_final = "conflicting_sources", "", "conflict"
            source_row = web_matches[0]
        elif candidate:
            status, final_date, confidence_final = "ambiguous", "", confidence
            source_row = provenance[-1]
        else:
            status, final_date, confidence_final = "no_source_found", "", "none"
            source_row = {
                "source_url": "",
                "source_title": "",
                "evidence_snippet": "",
                "retrieval_timestamp_utc": retrieved,
                "match_method": "yfinance_then_web_search_no_qualifying_source",
            }
        final_by_call[call["call_id"]] = {
            "earnings_call_date": final_date,
            "date_status": status,
            "date_source_url": source_row["source_url"],
            "date_source_title": source_row["source_title"],
            "date_evidence_snippet": source_row["evidence_snippet"],
            "date_retrieved_at_utc": source_row["retrieval_timestamp_utc"],
            "date_match_method": source_row["match_method"],
            "date_confidence": confidence_final,
        }

    provenance_fields = [
        "call_id",
        "candidate_date",
        "source_type",
        "source_url",
        "source_title",
        "evidence_snippet",
        "retrieval_timestamp_utc",
        "match_method",
        "confidence",
        "status",
    ]
    write_csv(output / "call_date_provenance.csv", provenance_fields, provenance)
    for call in calls:
        call.update(final_by_call[call["call_id"]])
    write_csv(output / "validated_calls_working.csv", list(calls[0]), calls)
    return calls, {
        "ticker_queries": len(ticker_cache),
        "network_retrieved_at_utc": retrieved,
    }


def web_date_fallback(
    output: Path, sleep_seconds: float, timeout: float
) -> dict[str, Any]:
    """Run Yahoo-restricted search outside conda after bulk yfinance mapping."""
    calls = read_csv(output / "validated_calls_working.csv")
    provenance = read_csv(output / "call_date_provenance.csv")
    by_call: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
    for row in provenance:
        by_call[row["call_id"]].append(row)
    session = requests.Session()
    searched = 0
    confirmed = 0
    for call in calls:
        if not (
            call["date_status"] == "no_source_found"
            or call["date_confidence"].startswith("low")
            or call["ticker_reuse_conflicting_ciks"]
        ):
            continue
        searched += 1
        ticker = call["historical_ticker"]
        year, q = call["quarter_label"][:4], call["quarter_label"][-1]
        matches: list[dict[str, Any]] = []
        queries = [
            (
                "yahoo_finance_web_search",
                f"site:finance.yahoo.com/news/ {call['company_name']} {ticker} Q{q} {year} earnings call transcript",
            ),
            (
                "targeted_web_backup",
                f"{call['company_name']} {ticker} Q{q} {year} earnings call transcript date -site:sec.gov",
            ),
        ]
        for source_type, query in queries:
            if source_type == "targeted_web_backup" and matches:
                break
            attempted_at = utc_now()
            try:
                results = yahoo_search(query, session, timeout)
                error = ""
            except requests.RequestException as exc:
                results = []
                error = type(exc).__name__
            for result in results:
                host = urllib.parse.urlparse(result["url"]).netloc.lower()
                if (
                    source_type == "yahoo_finance_web_search"
                    and "finance.yahoo.com" not in host
                ):
                    continue
                if "sec.gov" in host or "investor" in host or host.startswith("ir."):
                    continue
                if not result_looks_relevant(result, call):
                    continue
                try:
                    page_title, page_text, resolved_url = page_evidence(
                        result["url"], session, timeout
                    )
                except requests.RequestException:
                    page_title, page_text, resolved_url = (
                        result["title"],
                        result["snippet"],
                        result["url"],
                    )
                found, snippet = explicit_web_match(result, call, page_title, page_text)
                if not found:
                    continue
                match = {
                    "call_id": call["call_id"],
                    "candidate_date": found.isoformat(),
                    "source_type": source_type,
                    "source_url": resolved_url,
                    "source_title": page_title or result["title"],
                    "evidence_snippet": snippet or result["snippet"],
                    "retrieval_timestamp_utc": utc_now(),
                    "match_method": "explicit_issuer_quarter_call_date_text",
                    "confidence": "high",
                    "status": "confirmed_call_date",
                }
                matches.append(match)
                provenance.append(match)
                break
            if not matches:
                provenance.append(
                    {
                        "call_id": call["call_id"],
                        "candidate_date": "",
                        "source_type": source_type,
                        "source_url": "",
                        "source_title": f"{source_type} attempt",
                        "evidence_snippet": "No qualifying explicit issuer-quarter-call-date result found"
                        + (f" ({error})" if error else ""),
                        "retrieval_timestamp_utc": attempted_at,
                        "match_method": "no_qualifying_search_result",
                        "confidence": "none",
                        "status": "no_source_found",
                    }
                )
            time.sleep(sleep_seconds)

        explicit_dates = sorted({row["candidate_date"] for row in matches})
        yfinance_dates_for_call = {
            row["candidate_date"]
            for row in by_call[call["call_id"]]
            if row["source_type"] == "yfinance" and row["candidate_date"]
        }
        if len(explicit_dates) == 1:
            web_date = explicit_dates[0]
            conflict = yfinance_dates_for_call and all(
                abs((date.fromisoformat(web_date) - date.fromisoformat(ydate)).days) > 1
                for ydate in yfinance_dates_for_call
            )
            source = matches[0]
            if conflict:
                call.update(
                    {
                        "earnings_call_date": "",
                        "date_status": "conflicting_sources",
                        "date_confidence": "conflict",
                        "date_source_url": source["source_url"],
                        "date_source_title": source["source_title"],
                        "date_evidence_snippet": source["evidence_snippet"],
                        "date_retrieved_at_utc": source["retrieval_timestamp_utc"],
                        "date_match_method": "explicit_web_date_conflicts_with_yfinance_candidate",
                    }
                )
            else:
                confirmed += 1
                call.update(
                    {
                        "earnings_call_date": web_date,
                        "date_status": "confirmed_call_date",
                        "date_confidence": "high",
                        "date_source_url": source["source_url"],
                        "date_source_title": source["source_title"],
                        "date_evidence_snippet": source["evidence_snippet"],
                        "date_retrieved_at_utc": source["retrieval_timestamp_utc"],
                        "date_match_method": source["match_method"],
                    }
                )
        elif len(explicit_dates) > 1:
            call.update(
                {
                    "earnings_call_date": "",
                    "date_status": "conflicting_sources",
                    "date_confidence": "conflict",
                }
            )

    write_csv(output / "call_date_provenance.csv", list(provenance[0]), provenance)
    write_csv(output / "validated_calls_working.csv", list(calls[0]), calls)
    return {
        "web_fallback_calls_searched": searched,
        "web_fallback_confirmed": confirmed,
    }


def freeze_and_delete(output: Path, apply_delete: bool) -> dict[str, Any]:
    manifest = read_csv(output / "request_manifest.csv")
    working = read_csv(output / "validated_calls_working.csv")
    valid_ids = {row["call_id"] for row in working}
    if len(valid_ids) != len(working):
        raise RuntimeError("working valid-call dataset has duplicate call_id values")
    deletion_rows = [
        row
        for row in manifest
        if row["storage_disposition"] == "delete_after_manifest_freeze"
    ]
    retained_rows = [row for row in manifest if row["storage_disposition"] == "retain"]
    for row in manifest:
        path = (ROOT / row["raw_path"]).resolve()
        if not (
            path.is_relative_to(RAW_ROOT.resolve())
            or path.is_relative_to(LEGACY_RAW_ROOT.resolve())
        ):
            raise RuntimeError(f"refusing out-of-scope raw path: {path}")
        if not path.is_file() or sha256_file(path) != row["raw_sha256"]:
            raise RuntimeError(f"pre-deletion path/hash check failed: {path}")
    frozen_hash = sha256_file(output / "request_manifest.csv")
    deletion_plan = [
        {
            "raw_path": row["raw_path"],
            "raw_size_bytes": row["raw_size_bytes"],
            "raw_sha256": row["raw_sha256"],
            "validation_status": row["validation_status"],
            "deleted": "false",
        }
        for row in deletion_rows
    ]
    write_csv(
        output / "payload_deletion_manifest.csv",
        list(deletion_plan[0])
        if deletion_plan
        else [
            "raw_path",
            "raw_size_bytes",
            "raw_sha256",
            "validation_status",
            "deleted",
        ],
        deletion_plan,
    )
    if apply_delete:
        for plan in deletion_plan:
            path = ROOT / plan["raw_path"]
            path.unlink()
            plan["deleted"] = "true"
        write_csv(
            output / "payload_deletion_manifest.csv",
            list(deletion_plan[0]),
            deletion_plan,
        )
        if any((ROOT / row["raw_path"]).exists() for row in deletion_rows):
            raise RuntimeError(
                "post-deletion verification found a planned payload still present"
            )
    return {
        "request_manifest_sha256_before_deletion": frozen_hash,
        "retained_payloads": len(retained_rows),
        "retained_bytes": sum(int(row["raw_size_bytes"]) for row in retained_rows),
        "deletion_payloads": len(deletion_rows),
        "deletion_bytes": sum(int(row["raw_size_bytes"]) for row in deletion_rows),
        "deletion_applied": apply_delete,
    }


def report(
    output: Path,
    report_dir: Path,
    started: float,
    network: dict[str, Any],
    storage: dict[str, Any],
) -> dict[str, Any]:
    companies = read_csv(output / "pilot_companies.csv")
    eligible = read_csv(output / "eligible_firm_quarters.csv")
    attempts = read_csv(output / "request_manifest.csv")
    terminal = read_csv(output / "terminal_validation.csv")
    calls = read_csv(output / "validated_calls_working.csv")
    provenance = read_csv(output / "call_date_provenance.csv")
    validation_counts = Counter(row["validation_status"] for row in terminal)
    date_counts = Counter(row["date_status"] for row in calls)
    source_counts = Counter(row["source_type"] for row in provenance)
    agreement = Counter()
    by_call: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
    for row in provenance:
        by_call[row["call_id"]].append(row)
    for rows in by_call.values():
        ydates = {
            row["candidate_date"] for row in rows if row["source_type"] == "yfinance"
        }
        wdates = {
            row["candidate_date"]
            for row in rows
            if row["source_type"] != "yfinance" and row["candidate_date"]
        }
        if ydates and wdates:
            agreement["agree"] += int(bool(ydates & wdates))
            agreement["disagree"] += int(not bool(ydates & wdates))
        else:
            agreement["not_comparable"] += 1
    output_mtimes = [path.stat().st_mtime for path in output.glob("*.csv")]
    runtime = (
        max(time.monotonic() - started, time.time() - min(output_mtimes))
        if output_mtimes
        else time.monotonic() - started
    )
    full_rows = sum(
        1 for _ in csv.DictReader(UNIVERSE.open(newline="", encoding="utf-8"))
    )
    full_companies = len({row["company_id"] for row in read_csv(UNIVERSE)})
    unresolved_reasons = Counter()
    for row in calls:
        if row["date_status"] == "ambiguous":
            unresolved_reasons[
                "yfinance_candidate_lacks_explicit_fiscal-period evidence"
            ] += 1
        elif row["date_status"] == "no_source_found":
            unresolved_reasons["no qualifying yfinance or web source"] += 1
        elif row["date_status"] == "conflicting_sources":
            unresolved_reasons["qualifying sources conflict"] += 1
    source_quality = Counter(
        f"{row['source_type']}|{row['confidence']}|{row['status']}"
        for row in provenance
    )
    summary = {
        "pilot_companies": len(companies),
        "eligible_firm_quarters": len(eligible),
        "request_attempts": len(attempts),
        "terminal_validation_counts": dict(validation_counts),
        "valid_calls": len(calls),
        "validation_yield": len(calls) / len(eligible) if eligible else 0,
        "date_status_counts": dict(date_counts),
        "date_confirmation_coverage": date_counts["confirmed_call_date"] / len(calls)
        if calls
        else 0,
        "source_counts": dict(source_counts),
        "source_quality": dict(source_quality),
        "source_agreement": dict(agreement),
        "unresolved_reasons": dict(unresolved_reasons),
        "issuer_size_tiers": dict(
            Counter(row["current_market_cap_tier"] for row in companies)
        ),
        "historical_ticker_change_companies": sum(
            row["selection_role"] == "historical_ticker_change" for row in companies
        ),
        "runtime_seconds": runtime,
        "projected_full_universe_firm_quarters": full_rows,
        "projected_full_universe_companies": full_companies,
        "projected_remaining_companies": full_companies - len(companies),
        "projected_valid_calls_at_pilot_yield": round(
            full_rows * (len(calls) / len(eligible))
        )
        if eligible
        else 0,
        "remaining_universe_not_launched": True,
        **network,
        **storage,
    }
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "pilot_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    unresolved = [row for row in calls if row["date_status"] != "confirmed_call_date"]
    write_csv(
        report_dir / "unresolved_dates.csv",
        list(unresolved[0]) if unresolved else list(calls[0]),
        unresolved,
    )
    lines = [
        "# 50-company validation and date-mapping pilot",
        "",
        f"- Companies: {len(companies):,}",
        f"- Eligible firm-quarters: {len(eligible):,}",
        f"- Valid calls: {len(calls):,} ({summary['validation_yield']:.1%})",
        f"- Validation outcomes: {dict(validation_counts)}",
        f"- Confirmed call dates: {date_counts['confirmed_call_date']:,} ({summary['date_confirmation_coverage']:.1%} of valid calls)",
        f"- Other date outcomes: {dict(date_counts)}",
        f"- Source rows: {dict(source_counts)}",
        f"- Comparable-source agreement: {dict(agreement)}",
        f"- Unresolved reasons: {dict(unresolved_reasons)}",
        f"- Source quality: {dict(source_quality)}",
        f"- Issuer-size tiers: {summary['issuer_size_tiers']}",
        f"- Runtime: {runtime / 60:.1f} minutes",
        f"- Projected full-universe firm-quarters: {full_rows:,}",
        f"- Projected remaining companies: {full_companies - len(companies):,}",
        f"- Projected valid calls at pilot yield: {summary['projected_valid_calls_at_pilot_yield']:,}",
        "- Remaining universe: not launched; explicit review and approval required.",
        "",
        "Unresolved date rows are in `unresolved_dates.csv`. Canonical dates remain blank unless the source explicitly states issuer, fiscal quarter, and call date.",
    ]
    (report_dir / "PILOT_REPORT.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    manifest = {
        "created_at_utc": utc_now(),
        "version": "pilot_50_v20260918",
        "files": {
            path.relative_to(ROOT).as_posix(): sha256_file(path)
            for path in sorted(
                list(output.glob("*.csv"))
                + list(report_dir.glob("*.csv"))
                + list(report_dir.glob("*.json"))
                + list(report_dir.glob("*.md"))
            )
        },
        "remaining_universe_not_launched": True,
    }
    (output / "sha256_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "stage",
        choices=("select", "validate", "dates", "webdates", "delete", "report", "all"),
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--apply-delete", action="store_true")
    parser.add_argument("--sleep-seconds", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=20.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    started = time.monotonic()
    args.output.mkdir(parents=True, exist_ok=True)
    network: dict[str, Any] = {}
    storage: dict[str, Any] = {}
    if args.stage in {"select", "all"}:
        select_pilot(args.output)
    if args.stage in {"validate", "all"}:
        validate_pilot(args.output)
    if args.stage in {"dates", "all"}:
        _, network = map_dates(args.output, args.sleep_seconds, args.timeout)
    if args.stage in {"webdates", "all"}:
        network.update(web_date_fallback(args.output, args.sleep_seconds, args.timeout))
    if args.stage in {"delete", "all"}:
        storage = freeze_and_delete(args.output, args.apply_delete)
    if args.stage in {"report", "all"}:
        if not network:
            network = {
                "ticker_queries": "see provenance",
                "network_retrieved_at_utc": "see provenance",
            }
        if not storage:
            deletion_path = args.output / "payload_deletion_manifest.csv"
            request_path = args.output / "request_manifest.csv"
            if deletion_path.exists() and request_path.exists():
                deletion_rows = read_csv(deletion_path)
                request_rows = read_csv(request_path)
                retained_rows = [
                    row
                    for row in request_rows
                    if row["storage_disposition"] == "retain"
                ]
                storage = {
                    "request_manifest_sha256_before_deletion": sha256_file(
                        request_path
                    ),
                    "retained_payloads": len(retained_rows),
                    "retained_bytes": sum(
                        int(row["raw_size_bytes"]) for row in retained_rows
                    ),
                    "deletion_payloads": len(deletion_rows),
                    "deletion_bytes": sum(
                        int(row["raw_size_bytes"]) for row in deletion_rows
                    ),
                    "deletion_applied": bool(deletion_rows)
                    and all(row["deleted"] == "true" for row in deletion_rows),
                }
            else:
                storage = {"deletion_applied": False}
        summary = report(args.output, args.report_dir, started, network, storage)
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
