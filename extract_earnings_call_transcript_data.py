"""Collect Alpha Vantage earnings-call transcripts and speaker metadata."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import tempfile
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

URL = "https://www.alphavantage.co/query"
STUDY_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = STUDY_DIR / "diversified_450_companies_9_sectors.csv"
DEFAULT_RAW_DIR = STUDY_DIR / "artifacts" / "earnings_call_responses"
QUARTER_PATTERN = re.compile(r"^(20\d{2})Q([1-4])$")

TRANSCRIPT_FIELDS = [
    "status", "ticker", "company_name", "sector", "industry", "year", "quarter",
    "quarter_label", "call_date", "segment_count", "word_count", "management_word_count",
    "analyst_question_word_count", "analyst_question_count",
    "mean_alphavantage_sentiment", "management_mean_alphavantage_sentiment",
    "analyst_question_mean_alphavantage_sentiment", "api_message", "transcript_text",
    "fetched_at_utc",
]
SEGMENT_FIELDS = [
    "ticker", "company_name", "sector", "industry", "year", "quarter", "quarter_label",
    "call_date", "segment_number", "speaker", "title", "speaker_role", "turn_type",
    "is_analyst_question", "content", "alphavantage_sentiment", "fetched_at_utc",
]


def parse_quarter(value: str) -> tuple[int, int]:
    match = QUARTER_PATTERN.fullmatch(value.upper())
    if not match:
        raise argparse.ArgumentTypeError("quarter must use YYYYQn format, e.g. 2024Q4")
    return int(match.group(1)), int(match.group(2))


def quarter_labels(start: str, end: str) -> list[str]:
    start_year, start_quarter = parse_quarter(start)
    end_year, end_quarter = parse_quarter(end)
    start_index = start_year * 4 + start_quarter - 1
    end_index = end_year * 4 + end_quarter - 1
    if start_index > end_index:
        raise ValueError("start quarter must not be later than end quarter")
    return [f"{index // 4:04d}Q{index % 4 + 1}" for index in range(start_index, end_index + 1)]


def load_companies(path: Path) -> dict[str, dict[str, str]]:
    required = {"symbol", "name", "sector", "industry"}
    companies: dict[str, dict[str, str]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path} is missing required columns: {sorted(missing)}")
        for row in reader:
            ticker = (row.get("symbol") or "").strip().upper()
            if ticker:
                companies.setdefault(
                    ticker,
                    {
                        "company_name": (row.get("name") or "").strip(),
                        "sector": (row.get("sector") or "").strip(),
                        "industry": (row.get("industry") or "").strip(),
                    },
                )
    if not companies:
        raise ValueError(f"No tickers found in {path}")
    return companies


def text_value(value: Any) -> str:
    return "" if value is None else str(value).strip()


def response_segments(payload: Any) -> list[dict[str, Any]]:
    candidates: Any = payload
    if isinstance(payload, dict):
        for key in ("transcript", "segments", "data", "results"):
            if isinstance(payload.get(key), list):
                candidates = payload[key]
                break
    if not isinstance(candidates, list):
        return []
    return [item for item in candidates if isinstance(item, dict) and item.get("content")]


def classify_response(response: requests.Response, payload: Any) -> str:
    if response.status_code != 200:
        return f"http_error_{response.status_code}"
    if isinstance(payload, dict):
        if "Note" in payload:
            return "rate_limited"
        if "Information" in payload:
            return "information"
        if "Error Message" in payload:
            return "api_error"
    return "success" if response_segments(payload) else "no_transcript"


def api_message(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("Note", "Information", "Error Message"):
        if key in payload:
            return text_value(payload[key])
    return ""


def speaker_role(speaker: str, title: str) -> str:
    combined = f"{speaker} {title}".lower()
    if "operator" in combined or "moderator" in combined:
        return "operator"
    if "investor relations" in combined or "ir representative" in combined:
        return "investor_relations"
    if "analyst" in combined or any(
        term in combined for term in ("equity research", "research associate", "securities")
    ):
        return "analyst"
    management_terms = (
        "chief executive", "chief financial", "chief operating", "chief technology",
        "chief marketing", "chief revenue", "ceo", "cfo", "coo", "cto", "president",
        "vice president", "vp ", "treasurer", "founder", "executive", "managing director",
    )
    if any(term in combined for term in management_terms):
        return "management"
    return "unknown"


def looks_like_qa_marker(content: str) -> bool:
    normalized = re.sub(r"[^a-z]+", " ", content.lower())
    return any(
        marker in normalized
        for marker in (
            "question and answer", "question and answers", "open the call to questions",
            "take your questions", "take questions", "begin the question", "operator instructions",
        )
    )


def looks_like_question(content: str) -> bool:
    normalized = content.strip().lower()
    return "?" in content or normalized.startswith(
        ("what ", "why ", "how ", "could you ", "can you ", "would you ", "do you ")
    )


def normalize_segments(raw_segments: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    qa_started = False
    for index, raw in enumerate(raw_segments):
        speaker = text_value(raw.get("speaker"))
        title = text_value(raw.get("title") or raw.get("speaker_title"))
        content = text_value(raw.get("content"))
        role = speaker_role(speaker, title)
        qa_started = qa_started or looks_like_qa_marker(content)
        if role == "analyst" and (qa_started or looks_like_question(content)):
            turn_type = "question"
        elif role == "management" and qa_started:
            turn_type = "answer"
        elif role == "operator" and not qa_started:
            turn_type = "introduction"
        else:
            turn_type = "statement"
        normalized.append(
            {
                "segment_number": index,
                "speaker": speaker,
                "title": title,
                "speaker_role": role,
                "turn_type": turn_type,
                "is_analyst_question": role == "analyst" and turn_type == "question",
                "content": content,
                "alphavantage_sentiment": text_value(
                    raw.get("sentiment") or raw.get("score")
                ),
            }
        )
    return normalized


def word_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


def numeric_values(segments: Iterable[dict[str, Any]]) -> list[float]:
    values = []
    for segment in segments:
        try:
            values.append(float(segment["alphavantage_sentiment"]))
        except (KeyError, TypeError, ValueError):
            continue
    return values


def mean_sentiment(segments: Iterable[dict[str, Any]]) -> str:
    values = numeric_values(segments)
    return "" if not values else f"{sum(values) / len(values):.6f}"


def call_date(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("call_date", "date", "published_date", "timestamp"):
        if payload.get(key):
            return text_value(payload[key])
    return ""


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(value, handle, ensure_ascii=False)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def write_csv_atomic(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", newline="", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def raw_path(raw_dir: Path, ticker: str, quarter: str) -> Path:
    return raw_dir / f"{ticker}_{quarter}.json"


def load_raw_results(raw_dir: Path) -> dict[tuple[str, str], dict[str, Any]]:
    results = {}
    if not raw_dir.exists():
        return results
    for path in sorted(raw_dir.glob("*.json")):
        with path.open(encoding="utf-8") as handle:
            result = json.load(handle)
        key = (result.get("ticker", ""), result.get("quarter_label", ""))
        if all(key):
            results[key] = result
    return results


def build_rows(
    result: dict[str, Any],
    company: dict[str, str],
    segment_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    ticker = result["ticker"]
    label = result["quarter_label"]
    year, quarter = parse_quarter(label)
    segments = normalize_segments(response_segments(result.get("payload")))
    fetched_at = result["fetched_at_utc"]
    date = call_date(result.get("payload"))
    transcript = "\n\n".join(segment["content"] for segment in segments)
    management = [item for item in segments if item["speaker_role"] == "management"]
    analyst_questions = [item for item in segments if item["is_analyst_question"]]
    segment_rows.extend(
        {
            **company,
            "ticker": ticker,
            "year": year,
            "quarter": quarter,
            "quarter_label": label,
            "call_date": date,
            "fetched_at_utc": fetched_at,
            **segment,
        }
        for segment in segments
    )
    return {
        "status": result["status"],
        **company,
        "ticker": ticker,
        "year": year,
        "quarter": quarter,
        "quarter_label": label,
        "call_date": date,
        "segment_count": len(segments),
        "word_count": word_count(transcript),
        "management_word_count": word_count(" ".join(item["content"] for item in management)),
        "analyst_question_word_count": word_count(
            " ".join(item["content"] for item in analyst_questions)
        ),
        "analyst_question_count": len(analyst_questions),
        "mean_alphavantage_sentiment": mean_sentiment(segments),
        "management_mean_alphavantage_sentiment": mean_sentiment(management),
        "analyst_question_mean_alphavantage_sentiment": mean_sentiment(analyst_questions),
        "api_message": result.get("api_message", ""),
        "transcript_text": transcript,
        "fetched_at_utc": fetched_at,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=STUDY_DIR)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--start-quarter", default="2010Q1")
    parser.add_argument("--end-quarter", default="2024Q4")
    parser.add_argument("--requests-per-minute", type=float, default=60.0)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--limit", type=int, help="process only the first N pairs")
    parser.add_argument("--force", action="store_true", help="refetch completed pairs")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    api_key = os.environ.get("ALPHAVANTAGE_API_KEY")
    if not api_key:
        raise SystemExit("Set ALPHAVANTAGE_API_KEY before running this script.")
    if args.requests_per_minute <= 0:
        raise SystemExit("--requests-per-minute must be positive")

    companies = load_companies(args.input)
    quarters = quarter_labels(args.start_quarter, args.end_quarter)
    pairs = [(ticker, quarter) for ticker in companies for quarter in quarters]
    if args.limit is not None:
        if args.limit < 1:
            raise SystemExit("--limit must be positive")
        pairs = pairs[: args.limit]

    raw_results = load_raw_results(args.raw_dir)
    completed = {"success", "no_transcript"}
    pending = [
        pair for pair in pairs
        if args.force or pair not in raw_results or raw_results[pair].get("status") not in completed
    ]
    print(
        f"Companies: {len(companies)}; quarters: {len(quarters)}; "
        f"requested: {len(pairs)}; pending: {len(pending)}"
    )
    interval = 60.0 / args.requests_per_minute * 1.02

    with requests.Session() as session:
        for index, (ticker, quarter) in enumerate(pending, start=1):
            request_started = time.monotonic()
            params = {
                "function": "EARNINGS_CALL_TRANSCRIPT",
                "symbol": ticker,
                "quarter": quarter,
                "apikey": api_key,
            }
            fetched_at = datetime.now(UTC).isoformat()
            response: requests.Response | None = None
            try:
                response = session.get(URL, params=params, timeout=args.timeout)
                try:
                    payload: Any = response.json()
                    response_text = ""
                except ValueError:
                    payload = None
                    response_text = response.text
                status = classify_response(response, payload)
                message = api_message(payload)
            except requests.RequestException as exc:
                payload = None
                response_text = ""
                status = f"request_error_{type(exc).__name__}"
                message = str(exc)

            result = {
                "ticker": ticker,
                "quarter_label": quarter,
                "status": status,
                "http_status": response.status_code if response is not None else None,
                "api_message": message,
                "payload": payload,
                "response_text": response_text,
                "fetched_at_utc": fetched_at,
            }
            raw_results[(ticker, quarter)] = result
            write_json_atomic(raw_path(args.raw_dir, ticker, quarter), result)
            print(f"[{index}/{len(pending)}] {ticker} {quarter}: {status}")
            next_start = request_started + interval
            time.sleep(max(0.0, next_start - time.monotonic()))

    transcript_rows: list[dict[str, Any]] = []
    segment_rows: list[dict[str, Any]] = []
    for ticker, quarter in pairs:
        result = raw_results.get((ticker, quarter))
        if result is not None:
            transcript_rows.append(build_rows(result, companies[ticker], segment_rows))

    write_csv_atomic(
        args.output_dir / "earnings_call_transcripts.csv", TRANSCRIPT_FIELDS, transcript_rows
    )
    write_csv_atomic(
        args.output_dir / "earnings_call_transcript_segments.csv", SEGMENT_FIELDS, segment_rows
    )
    print(
        f"Wrote {len(transcript_rows)} transcript rows and {len(segment_rows)} "
        f"speaker-turn rows to {args.output_dir}"
    )


if __name__ == "__main__":
    main()
