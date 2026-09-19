#!/usr/bin/env python3
"""Read-only audit of cached Alpha Vantage earnings-call responses."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "artifacts" / "earnings_call_responses"
COMPANIES_CSV = ROOT / "data" / "provisional" / "convenience_sample_450_companies_9_sectors.csv"
OUT_DIR = Path(__file__).resolve().parent

TOKEN_RE = re.compile(r"[A-Za-z]+(?:['’.-][A-Za-z]+)*|\d+(?:\.\d+)?")
QUARTER_RE = re.compile(r"^(20\d{2})Q([1-4])$")

ALL_CLASSIFICATIONS = (
    "valid full transcript",
    "no transcript",
    "provider information/rate-limit response",
    "API error",
    "placeholder/redacted",
    "copyright/boilerplate",
    "probably truncated",
    "malformed",
    "duplicate",
    "uncertain/manual review",
)

MARKERS: tuple[tuple[str, str], ...] = (
    ("redacted_spoken_content", "(full spoken content)"),
    ("provider_copyright_policy", "copyright policy: all transcripts on this site"),
    ("transcript_unavailable", "transcript is not available"),
    ("not_available", "not available"),
    ("placeholder_redacted", "[redacted]"),
    ("placeholder_omitted", "[omitted]"),
    ("forward_looking_statements", "forward-looking statements"),
    ("operator_instructions", "operator instructions"),
    ("question_and_answer", "question-and-answer"),
    ("questions_and_answers", "questions and answers"),
    ("call_conclusion", "concludes today's conference call"),
    ("thank_you_participating", "thank you for participating"),
)

MANIFEST_FIELDS = [
    "ticker", "company_name", "current_sector", "current_industry", "year",
    "quarter", "quarter_label", "period_scope", "raw_file_path",
    "raw_file_size_bytes", "raw_file_sha256", "provider_status", "http_status",
    "provider_message", "payload_reported_date_unverified", "segment_count",
    "opening_years_detected", "opening_year_mismatch",
    "token_count", "distinct_token_count", "distinct_token_ratio", "short_under_1000",
    "detected_boilerplate_markers", "normalized_transcript_sha256",
    "duplicate_group_size", "duplicate_canonical_raw_path", "response_classification",
    "classification_reasons", "recommended_action", "fetched_at_utc",
]


def load_companies() -> dict[str, dict[str, str]]:
    companies: dict[str, dict[str, str]] = {}
    with COMPANIES_CSV.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            ticker = (row.get("symbol") or "").strip().upper()
            if ticker and ticker not in companies:
                companies[ticker] = {
                    "company_name": (row.get("name") or "").strip(),
                    "current_sector": (row.get("sector") or "").strip(),
                    "current_industry": (row.get("industry") or "").strip(),
                }
    return companies


def segments_from_payload(payload: Any) -> list[dict[str, Any]]:
    candidates: Any = payload
    if isinstance(payload, dict):
        for key in ("transcript", "segments", "data", "results"):
            if isinstance(payload.get(key), list):
                candidates = payload[key]
                break
    if not isinstance(candidates, list):
        return []
    return [item for item in candidates if isinstance(item, dict) and str(item.get("content") or "").strip()]


def provider_message(result: dict[str, Any]) -> str:
    message = str(result.get("api_message") or "").strip()
    payload = result.get("payload")
    if not message and isinstance(payload, dict):
        for key in ("Information", "Note", "Error Message"):
            if payload.get(key):
                message = str(payload[key]).strip()
                break
    return re.sub(r"\s+", " ", message)


def reported_date(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("reportedDate", "reported_date", "call_date", "date", "published_date", "timestamp"):
        value = payload.get(key)
        if value:
            return str(value).strip()
    return ""


def period_scope(year: int) -> str:
    if 2008 <= year <= 2019:
        return "paper_period_2008_2019"
    if 2020 <= year <= 2024:
        return "current_extension_2020_2024"
    return "outside_defined_periods"


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    companies = load_companies()
    rows: list[dict[str, Any]] = []
    excerpts_by_key: dict[tuple[str, str], dict[str, str]] = {}
    hash_paths: dict[str, list[str]] = defaultdict(list)

    expected_pairs = {
        (ticker, f"{year}Q{quarter}")
        for ticker in companies
        for year in range(2010, 2025)
        for quarter in range(1, 5)
    }
    found_pairs: set[tuple[str, str]] = set()

    for path in sorted(RAW_DIR.glob("*.json")):
        rel_path = path.relative_to(ROOT).as_posix()
        raw_bytes = path.read_bytes()
        raw_hash = hashlib.sha256(raw_bytes).hexdigest()
        parse_error = ""
        result: Any
        try:
            result = json.loads(raw_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            result = {}
            parse_error = f"{type(exc).__name__}: {exc}"

        filename_match = re.match(r"^(.+)_(20\d{2}Q[1-4])\.json$", path.name)
        filename_ticker = filename_match.group(1) if filename_match else ""
        filename_quarter = filename_match.group(2) if filename_match else ""
        ticker = str(result.get("ticker") or filename_ticker).strip().upper() if isinstance(result, dict) else filename_ticker
        label = str(result.get("quarter_label") or filename_quarter).strip().upper() if isinstance(result, dict) else filename_quarter
        match = QUARTER_RE.fullmatch(label)
        year = int(match.group(1)) if match else 0
        quarter = int(match.group(2)) if match else 0
        if ticker and label:
            found_pairs.add((ticker, label))

        payload = result.get("payload") if isinstance(result, dict) else None
        segments = segments_from_payload(payload)
        contents = [str(segment.get("content") or "").strip() for segment in segments]
        transcript = "\n\n".join(contents).strip()
        tokens = [token.lower() for token in TOKEN_RE.findall(transcript)]
        token_count = len(tokens)
        distinct_count = len(set(tokens))
        distinct_ratio = distinct_count / token_count if token_count else 0.0
        normalized_text = " ".join(tokens)
        transcript_hash = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest() if normalized_text else ""
        if transcript_hash:
            hash_paths[transcript_hash].append(rel_path)

        lower = transcript.lower()
        markers = [name for name, needle in MARKERS if needle in lower]
        status = str(result.get("status") or "").strip() if isinstance(result, dict) else ""
        http_status = result.get("http_status", "") if isinstance(result, dict) else ""
        message = provider_message(result) if isinstance(result, dict) else ""
        reasons: list[str] = []
        classification = "uncertain/manual review"
        action = "inspect raw response manually"

        payload_info = isinstance(payload, dict) and any(key in payload for key in ("Information", "Note"))
        payload_api_error = isinstance(payload, dict) and "Error Message" in payload
        opening = transcript[:800]
        opening_years = sorted({
            int(value)
            for pattern in (
                r"(?:first|second|third|fourth|q[1-4])\s+quarter(?:\s+of)?\s+(20\d{2})\b",
                r"\bq[1-4]\s+(20\d{2})\b",
                r"\b(20\d{2})\s+(?:first|second|third|fourth|q[1-4])\s+quarter\b",
                r"\b(20\d{2})\s+earnings(?:\s+conference)?\s+call\b",
                r"earnings(?:\s+conference)?\s+call(?:\s+for)?\s+(20\d{2})\b",
            )
            for value in re.findall(pattern, opening, flags=re.IGNORECASE)
        })
        opening_year_mismatch = bool(year and opening_years and all(abs(value - year) > 1 for value in opening_years))
        filename_mismatch = bool(
            isinstance(result, dict)
            and ((result.get("ticker") and str(result.get("ticker")).strip().upper() != filename_ticker)
                 or (result.get("quarter_label") and str(result.get("quarter_label")).strip().upper() != filename_quarter))
        )

        if parse_error:
            classification = "malformed"
            reasons.append("raw file is not valid JSON")
            action = "repair collection/parsing issue and retry without overwriting raw file"
        elif not isinstance(result, dict) or filename_match is None or not ticker or not match or filename_mismatch:
            classification = "malformed"
            reasons.append("wrapper or ticker-quarter metadata is malformed")
            action = "inspect wrapper metadata and retry without overwriting raw file"
        elif status in {"information", "rate_limited"} or payload_info:
            classification = "provider information/rate-limit response"
            reasons.append("provider returned Information or Note rather than transcript content")
            action = "retry with rate control; preserve this response"
        elif status.startswith(("api_error", "http_error", "request_error")) or payload_api_error:
            classification = "API error"
            reasons.append("provider or transport error status")
            action = "retry after diagnosing provider/transport error; preserve this response"
        elif "provider_copyright_policy" in markers:
            classification = "copyright/boilerplate"
            reasons.append("provider copyright notice appears in transcript content")
            action = "exclude from scoring; retain raw response for provenance"
        elif any(marker in markers for marker in ("redacted_spoken_content", "placeholder_redacted", "placeholder_omitted")):
            classification = "placeholder/redacted"
            reasons.append("explicit redaction or omitted-spoken-content marker")
            action = "exclude from scoring and seek a licensed/complete transcript"
        elif "transcript_unavailable" in markers:
            classification = "placeholder/redacted"
            reasons.append("transcript segments state that the transcript is unavailable")
            action = "exclude from scoring and verify availability with an alternate source"
        elif status == "no_transcript" and not segments:
            classification = "no transcript"
            reasons.append("provider status is no_transcript and no content segments are present")
            action = "retain as no transcript; optionally re-query to verify availability"
        elif not segments or not transcript:
            classification = "malformed"
            reasons.append("response lacks usable transcript segments despite non-no_transcript status")
            action = "inspect payload shape and retry if appropriate"
        elif distinct_ratio < 0.10 and token_count >= 500:
            classification = "copyright/boilerplate"
            reasons.append("degenerate repeated vocabulary indicates boilerplate")
            action = "exclude from scoring; inspect repeated content"
        else:
            final_segment_tokens = len(TOKEN_RE.findall(contents[-1])) if contents else 0
            final_trimmed = transcript.rstrip()
            abrupt_end = bool(final_trimmed and final_trimmed[-1] not in '.!?)]\"\'')
            ellipsis_end = final_trimmed.endswith(("...", "…"))
            short = token_count < 1000
            if short:
                reasons.append("short_under_1000")
            if token_count < 150 and len(segments) <= 3:
                classification = "probably truncated"
                reasons.append("very short content with at most three segments")
                action = "manual review; retry or find complete transcript if truncation is confirmed"
            elif opening_year_mismatch:
                classification = "uncertain/manual review"
                reasons.append("opening earnings-call year conflicts with requested quarter")
                action = "verify ticker-quarter identity against an independent call source"
            elif short and (len(segments) == 1 or ellipsis_end or (abrupt_end and final_segment_tokens < 30)):
                classification = "probably truncated"
                reasons.append("short content plus structural truncation signal")
                action = "manual review; retry or find complete transcript if truncation is confirmed"
            elif short:
                classification = "uncertain/manual review"
                reasons.append("short call is not rejected on length alone")
                action = "review beginning and ending excerpts before inclusion"
            else:
                classification = "valid full transcript"
                reasons.append("substantive segmented transcript without detected integrity flags")
                action = "retain for transcript analysis; separately verify earnings-call date"

        company = companies.get(ticker, {"company_name": "", "current_sector": "", "current_industry": ""})
        row = {
            "ticker": ticker,
            **company,
            "year": year or "",
            "quarter": quarter or "",
            "quarter_label": label,
            "period_scope": period_scope(year) if year else "",
            "raw_file_path": rel_path,
            "raw_file_size_bytes": len(raw_bytes),
            "raw_file_sha256": raw_hash,
            "provider_status": status,
            "http_status": http_status if http_status is not None else "",
            "provider_message": message,
            "payload_reported_date_unverified": reported_date(payload),
            "segment_count": len(segments),
            "opening_years_detected": ";".join(str(value) for value in opening_years),
            "opening_year_mismatch": "yes" if opening_year_mismatch else "no",
            "token_count": token_count,
            "distinct_token_count": distinct_count,
            "distinct_token_ratio": f"{distinct_ratio:.6f}" if token_count else "",
            "short_under_1000": "yes" if 0 < token_count < 1000 else "no",
            "detected_boilerplate_markers": ";".join(markers),
            "normalized_transcript_sha256": transcript_hash,
            "duplicate_group_size": "",
            "duplicate_canonical_raw_path": "",
            "response_classification": classification,
            "classification_reasons": ";".join(reasons),
            "recommended_action": action,
            "fetched_at_utc": str(result.get("fetched_at_utc") or "") if isinstance(result, dict) else "",
        }
        rows.append(row)

        if 0 < token_count < 1000 or classification in {
            "probably truncated", "placeholder/redacted", "copyright/boilerplate", "uncertain/manual review"
        }:
            excerpts_by_key[(ticker, label)] = {
                "ticker": ticker,
                "quarter_label": label,
                "raw_file_path": rel_path,
                "response_classification": classification,
                "token_count": str(token_count),
                "segment_count": str(len(segments)),
                "beginning_excerpt": re.sub(r"\s+", " ", transcript[:500]).strip(),
                "ending_excerpt": re.sub(r"\s+", " ", transcript[-500:]).strip(),
            }

    # Apply exact normalized-body duplicate classification after all hashes are known.
    for row in rows:
        transcript_hash = row["normalized_transcript_sha256"]
        if not transcript_hash:
            continue
        paths = sorted(hash_paths[transcript_hash])
        row["duplicate_group_size"] = len(paths)
        row["duplicate_canonical_raw_path"] = paths[0]
        if len(paths) > 1 and row["raw_file_path"] != paths[0] and row["response_classification"] == "valid full transcript":
            row["response_classification"] = "duplicate"
            row["classification_reasons"] += ";exact normalized transcript duplicate"
            row["recommended_action"] = "exclude duplicate row from analysis; retain raw response"

    rows.sort(key=lambda row: (row["ticker"], row["year"] or 0, row["quarter"] or 0))
    write_csv(OUT_DIR / "response_manifest.csv", MANIFEST_FIELDS, rows)

    excerpt_fields = [
        "ticker", "quarter_label", "raw_file_path", "response_classification",
        "token_count", "segment_count", "beginning_excerpt", "ending_excerpt",
    ]
    excerpt_rows = [excerpts_by_key[key] for key in sorted(excerpts_by_key)]
    write_csv(OUT_DIR / "short_and_flagged_excerpts.csv", excerpt_fields, excerpt_rows)

    retry_fields = ["ticker", "quarter_label", "raw_file_path", "provider_status", "http_status", "provider_message", "recommended_action"]
    provider_retry = [row for row in rows if row["response_classification"] == "provider information/rate-limit response"]
    api_retry = [row for row in rows if row["response_classification"] == "API error"]
    no_transcript_retry = [row for row in rows if row["response_classification"] == "no transcript"]
    write_csv(OUT_DIR / "retry_provider_information.csv", retry_fields, provider_retry)
    write_csv(OUT_DIR / "retry_api_errors.csv", retry_fields, api_retry)
    write_csv(OUT_DIR / "retry_unverifiable_no_transcript.csv", retry_fields, no_transcript_retry)

    def summary_rows(group_fields: list[str]) -> list[dict[str, Any]]:
        grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[tuple(row[field] for field in group_fields)].append(row)
        output: list[dict[str, Any]] = []
        for key in sorted(grouped, key=lambda value: tuple(str(item) for item in value)):
            members = grouped[key]
            classes = Counter(member["response_classification"] for member in members)
            output.append({
                **dict(zip(group_fields, key)),
                "requested_count": len(members),
                "provider_success_count": sum(member["provider_status"] == "success" for member in members),
                "valid_full_transcript_count": classes["valid full transcript"],
                "duplicate_count": classes["duplicate"],
                "no_transcript_count": classes["no transcript"],
                "flagged_or_error_count": len(members) - classes["valid full transcript"] - classes["duplicate"] - classes["no transcript"],
            })
        return output

    summary_fields = [
        "requested_count", "provider_success_count", "valid_full_transcript_count",
        "duplicate_count", "no_transcript_count", "flagged_or_error_count",
    ]
    write_csv(OUT_DIR / "coverage_by_year.csv", ["year", *summary_fields], summary_rows(["year"]))
    write_csv(OUT_DIR / "coverage_by_ticker.csv", ["ticker", *summary_fields], summary_rows(["ticker"]))
    write_csv(OUT_DIR / "coverage_by_current_sector.csv", ["current_sector", *summary_fields], summary_rows(["current_sector"]))

    class_counts = Counter(row["response_classification"] for row in rows)
    class_rows = [
        {
            "response_classification": classification,
            "count": class_counts[classification],
            "share_of_requested": f"{class_counts[classification] / len(rows):.6f}",
        }
        for classification in ALL_CLASSIFICATIONS
    ]
    write_csv(
        OUT_DIR / "coverage_by_response_classification.csv",
        ["response_classification", "count", "share_of_requested"],
        class_rows,
    )

    period_rows = summary_rows(["period_scope"])
    write_csv(OUT_DIR / "coverage_by_period.csv", ["period_scope", *summary_fields], period_rows)

    missing = sorted(expected_pairs - found_pairs)
    extra = sorted(found_pairs - expected_pairs)
    audit_summary = {
        "requested_pair_count": len(expected_pairs),
        "raw_file_count": len(rows),
        "missing_requested_pairs": [f"{ticker}_{quarter}" for ticker, quarter in missing],
        "unexpected_pairs": [f"{ticker}_{quarter}" for ticker, quarter in extra],
        "classification_counts": {classification: class_counts[classification] for classification in ALL_CLASSIFICATIONS},
        "short_under_1000_count": sum(row["short_under_1000"] == "yes" for row in rows),
        "exact_duplicate_hash_groups": sum(len(paths) > 1 for paths in hash_paths.values()),
        "provider_information_retry_count": len(provider_retry),
        "api_error_retry_count": len(api_retry),
        "unverifiable_no_transcript_retry_count": len(no_transcript_retry),
        "reported_date_policy": "Payload reportedDate/date fields are recorded only as unverified provider metadata, never as verified earnings-call dates.",
        "paper_period_cache_note": "The paper covers 2008-2019. This cache begins at 2010Q1, so it contains no 2008-2009 requests.",
    }
    (OUT_DIR / "audit_summary.json").write_text(json.dumps(audit_summary, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
