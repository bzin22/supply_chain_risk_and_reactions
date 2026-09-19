#!/usr/bin/env python3
"""Collect reproducible event dates, adjusted closes, and Carhart factors.

The Alpha Vantage ``EARNINGS`` endpoint returns all reported quarters for a
ticker.  An event labelled ``YYYYQn`` is matched to ``reportedDate`` in that
calendar quarter, which is the date used as ``call_date`` by the event study.
Raw provider payloads, the derived mapping, and a provenance manifest are
stored separately from all source transcript CSVs.

Run a bounded validation before the resumable full collection, for example:

    conda run -n dap-env python collect_earnings_event_inputs.py \
      --events artifacts/.../earnings_call_transcripts_scored.csv \
      --output-dir artifacts/.../event_study_inputs --max-tickers 3

Then omit ``--max-tickers`` to resume/complete the full collection.  The
script deliberately does not write transcript-derived files; use
``join_earnings_event_dates.py`` after the mapping is complete.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from study_period import validate_csv_event_dates_in_study_period, validate_csv_in_study_period


API_URL = "https://www.alphavantage.co/query"
FRENCH_URLS = {
    "fama_french_daily.zip": "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_daily_TXT.zip",
    "momentum_daily.zip": "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Momentum_Factor_daily_TXT.zip",
}
MAPPING_FIELDS = [
    "ticker", "quarter_label", "source_call_date", "event_date", "event_date_source",
    "mapping_status", "mapping_method", "fiscal_date_ending", "reported_date",
    "provider_function", "raw_response_file", "fetched_at_utc", "message",
]
PRICE_FIELDS = ["ticker", "date", "adjusted_close", "provider_function", "raw_response_file", "fetched_at_utc"]


class ProviderRateLimit(RuntimeError):
    """A non-success response that Alpha Vantage explicitly identifies as a limit."""


def configure_csv_field_size_limit() -> None:
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def atomic_write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", newline="", encoding="utf-8", dir=path.parent, delete=False) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def quarter_label(value: str) -> str:
    """Return a calendar YYYYQn label for a provider date, or blank."""

    try:
        parsed = datetime.strptime(value[:10], "%Y-%m-%d")
    except (TypeError, ValueError):
        return ""
    return f"{parsed.year}Q{((parsed.month - 1) // 3) + 1}"


def load_events(path: Path) -> tuple[dict[str, dict[str, str]], dict[str, set[str]]]:
    """Read only event keys and source dates; never retain transcript text."""

    events: dict[str, dict[str, str]] = {}
    quarters_by_ticker: dict[str, set[str]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"ticker", "quarter_label", "call_date"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path} lacks required columns: {sorted(missing)}")
        for row in reader:
            ticker = (row.get("ticker") or "").strip().upper()
            quarter = (row.get("quarter_label") or "").strip().upper()
            if not ticker or not quarter:
                raise ValueError("Event source contains blank ticker or quarter_label")
            key = f"{ticker}|{quarter}"
            source_date = (row.get("call_date") or "").strip()
            prior = events.get(key)
            if prior is not None and prior["source_call_date"] != source_date:
                raise ValueError(f"Conflicting source call_date values for {key}")
            events[key] = {"ticker": ticker, "quarter_label": quarter, "source_call_date": source_date}
            quarters_by_ticker.setdefault(ticker, set()).add(quarter)
    if not events:
        raise ValueError(f"No events in {path}")
    return events, quarters_by_ticker


class AlphaVantageClient:
    def __init__(self, api_key: str, minimum_interval_seconds: float) -> None:
        self.api_key = api_key
        self.minimum_interval_seconds = minimum_interval_seconds
        self.last_request_at: float | None = None

    def fetch(self, params: dict[str, str]) -> tuple[dict[str, Any], str]:
        if self.last_request_at is not None:
            remaining = self.minimum_interval_seconds - (time.monotonic() - self.last_request_at)
            if remaining > 0:
                time.sleep(remaining)
        query = urllib.parse.urlencode({**params, "apikey": self.api_key})
        request = urllib.request.Request(f"{API_URL}?{query}", headers={"User-Agent": "event-study-research/1.0"})
        self.last_request_at = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read().decode("utf-8")
        except urllib.error.URLError as exc:
            raise RuntimeError(f"network_error: {exc.reason}") from exc
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("invalid_json_response") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("unexpected_json_shape")
        return payload, utc_now()


def payload_message(payload: dict[str, Any]) -> str:
    for field in ("Information", "Note", "Error Message"):
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def provider_enforced_rate_limit(message: str) -> bool:
    text = message.lower()
    return "alpha vantage" in text and (
        "rate limit" in text or "requests per day" in text or "requests per minute" in text
    )


def cache_or_fetch(
    client: AlphaVantageClient,
    raw_path: Path,
    params: dict[str, str],
    valid: callable,
) -> tuple[dict[str, Any] | None, str, str, str]:
    """Return valid cached/fetched payload, source, timestamp, or error."""

    if raw_path.exists():
        try:
            cached = json.loads(raw_path.read_text(encoding="utf-8"))
            payload = cached.get("payload", cached)
            if isinstance(payload, dict) and valid(payload):
                return payload, "cache", str(cached.get("fetched_at_utc", "")), ""
        except (OSError, json.JSONDecodeError):
            pass
    try:
        payload, fetched_at = client.fetch(params)
    except RuntimeError as exc:
        return None, "live", "", str(exc)
    if not valid(payload):
        message = payload_message(payload) or "unexpected_api_payload"
        evidence_path = raw_path.with_name(f"{raw_path.stem}.provider_response.json")
        atomic_write_json(evidence_path, {
            "fetched_at_utc": fetched_at, "params": params, "payload": payload,
            "classification": "alpha_vantage_provider_rate_limit" if provider_enforced_rate_limit(message) else "invalid_api_payload",
        })
        if provider_enforced_rate_limit(message):
            raise ProviderRateLimit(
                f"Alpha Vantage enforced a provider-side rate limit for {params['function']}/{params['symbol']}; "
                f"evidence: {evidence_path}; message: {message}"
            )
        return None, "live", fetched_at, message
    atomic_write_json(raw_path, {"fetched_at_utc": fetched_at, "params": params, "payload": payload})
    return payload, "live", fetched_at, ""


def collect_dates(
    client: AlphaVantageClient,
    output_dir: Path,
    events: dict[str, dict[str, str]],
    quarters_by_ticker: dict[str, set[str]],
    tickers: list[str],
) -> list[dict[str, Any]]:
    raw_dir = output_dir / "alpha_vantage_earnings_raw"
    by_key: dict[str, dict[str, Any]] = {}
    errors: dict[str, tuple[str, str]] = {}
    for position, ticker in enumerate(tickers, start=1):
        raw_path = raw_dir / f"{ticker}.json"
        payload, source, fetched_at, error = cache_or_fetch(
            client, raw_path, {"function": "EARNINGS", "symbol": ticker},
            lambda candidate: isinstance(candidate.get("quarterlyEarnings"), list),
        )
        print(f"dates {position}/{len(tickers)} {ticker}: {'ok' if payload else error}", flush=True)
        if payload is None:
            errors[ticker] = (source, error)
            continue
        candidates: dict[str, list[dict[str, str]]] = {}
        for item in payload["quarterlyEarnings"]:
            if not isinstance(item, dict):
                continue
            reported = str(item.get("reportedDate") or "").strip()
            fiscal = str(item.get("fiscalDateEnding") or "").strip()
            label = quarter_label(reported)
            if label and reported:
                candidates.setdefault(label, []).append({"reported": reported, "fiscal": fiscal})
        for quarter in quarters_by_ticker[ticker]:
            key = f"{ticker}|{quarter}"
            matched = candidates.get(quarter, [])
            if len(matched) == 1:
                candidate = matched[0]
                by_key[key] = {
                    **events[key], "event_date": candidate["reported"],
                    "event_date_source": "alpha_vantage_earnings_reported_date",
                    "mapping_status": "matched", "mapping_method": "reported_date_calendar_quarter",
                    "fiscal_date_ending": candidate["fiscal"], "reported_date": candidate["reported"],
                    "provider_function": "EARNINGS", "raw_response_file": str(raw_path.relative_to(output_dir)),
                    "fetched_at_utc": fetched_at, "message": "",
                }
            elif not matched:
                by_key[key] = {
                    **events[key], "event_date": "", "event_date_source": "",
                    "mapping_status": "unmatched_quarter", "mapping_method": "reported_date_calendar_quarter",
                    "fiscal_date_ending": "", "reported_date": "", "provider_function": "EARNINGS",
                    "raw_response_file": str(raw_path.relative_to(output_dir)), "fetched_at_utc": fetched_at,
                    "message": "No quarterlyEarnings reportedDate in requested calendar quarter",
                }
            else:
                by_key[key] = {
                    **events[key], "event_date": "", "event_date_source": "",
                    "mapping_status": "ambiguous_quarter", "mapping_method": "reported_date_calendar_quarter",
                    "fiscal_date_ending": "", "reported_date": "", "provider_function": "EARNINGS",
                    "raw_response_file": str(raw_path.relative_to(output_dir)), "fetched_at_utc": fetched_at,
                    "message": f"{len(matched)} quarterlyEarnings entries in requested calendar quarter",
                }
    for ticker, (source, error) in errors.items():
        for quarter in quarters_by_ticker[ticker]:
            key = f"{ticker}|{quarter}"
            by_key[key] = {
                **events[key], "event_date": "", "event_date_source": "", "mapping_status": "api_unavailable",
                "mapping_method": "", "fiscal_date_ending": "", "reported_date": "", "provider_function": "EARNINGS",
                "raw_response_file": "", "fetched_at_utc": "", "message": f"{source}: {error}",
            }
    collected = set(tickers)
    return [by_key[key] for key in sorted(by_key) if events[key]["ticker"] in collected]


def collect_prices(client: AlphaVantageClient, output_dir: Path, tickers: list[str]) -> list[dict[str, Any]]:
    raw_dir = output_dir / "alpha_vantage_daily_adjusted_raw"
    rows: list[dict[str, Any]] = []
    for position, ticker in enumerate(tickers, start=1):
        raw_path = raw_dir / f"{ticker}.json"
        payload, source, fetched_at, error = cache_or_fetch(
            client, raw_path,
            {"function": "TIME_SERIES_DAILY_ADJUSTED", "symbol": ticker, "outputsize": "full"},
            lambda candidate: isinstance(candidate.get("Time Series (Daily)"), dict),
        )
        print(f"prices {position}/{len(tickers)} {ticker}: {'ok' if payload else error}", flush=True)
        if payload is None:
            continue
        series = payload["Time Series (Daily)"]
        for trading_date, values in series.items():
            if not isinstance(values, dict):
                continue
            adjusted = str(values.get("5. adjusted close") or "").strip()
            try:
                parsed = float(adjusted)
            except ValueError:
                continue
            if not math.isfinite(parsed) or parsed <= 0:
                continue
            rows.append({
                "ticker": ticker, "date": trading_date, "adjusted_close": adjusted,
                "provider_function": "TIME_SERIES_DAILY_ADJUSTED",
                "raw_response_file": str(raw_path.relative_to(output_dir)), "fetched_at_utc": fetched_at,
            })
    return sorted(rows, key=lambda row: (row["ticker"], row["date"]))


def download_factors(output_dir: Path) -> dict[str, dict[str, str]]:
    destination = output_dir / "fama_french"
    result: dict[str, dict[str, str]] = {}
    for filename, url in FRENCH_URLS.items():
        path = destination / filename
        if not path.exists():
            request = urllib.request.Request(url, headers={"User-Agent": "event-study-research/1.0"})
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    data = response.read()
            except urllib.error.URLError as exc:
                raise RuntimeError(f"Could not download {url}: {exc.reason}") from exc
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
                handle.write(data)
                temporary = Path(handle.name)
            os.replace(temporary, path)
        result[filename] = {"url": url, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, required=True, help="scored transcript event CSV")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-tickers", type=int, help="bounded validation limit; tickers are sorted")
    parser.add_argument("--tickers", help="comma-separated ticker subset; useful for an explicit bounded validation")
    parser.add_argument("--request-interval-seconds", type=float, default=1.1, help="default stays below 60 API requests/minute")
    parser.add_argument("--skip-prices", action="store_true")
    parser.add_argument("--skip-factors", action="store_true")
    args = parser.parse_args()
    configure_csv_field_size_limit()
    if args.max_tickers is not None and args.max_tickers < 1:
        raise SystemExit("--max-tickers must be positive")
    if args.request_interval_seconds <= 0:
        raise SystemExit("--request-interval-seconds must be positive")
    api_key = os.environ.get("ALPHAVANTAGE_API_KEY")
    if not api_key:
        raise SystemExit("ALPHAVANTAGE_API_KEY is not present in the environment")
    validate_csv_in_study_period(args.events, context="event-date collection input")
    validate_csv_event_dates_in_study_period(args.events, context="event-date collection input")
    events, quarters_by_ticker = load_events(args.events)
    all_tickers = sorted(quarters_by_ticker)
    requested_tickers = None
    if args.tickers:
        requested_tickers = [ticker.strip().upper() for ticker in args.tickers.split(",") if ticker.strip()]
        unknown = sorted(set(requested_tickers) - set(all_tickers))
        if unknown:
            raise SystemExit(f"--tickers not present in event source: {', '.join(unknown)}")
    tickers = requested_tickers if requested_tickers is not None else all_tickers
    if args.max_tickers is not None:
        tickers = tickers[: args.max_tickers]
    client = AlphaVantageClient(api_key, args.request_interval_seconds)
    try:
        date_rows = collect_dates(client, args.output_dir, events, quarters_by_ticker, tickers)
    except ProviderRateLimit as exc:
        atomic_write_json(args.output_dir / "provider_limit_evidence.json", {
            "detected_at_utc": utc_now(), "classification": "alpha_vantage_provider_rate_limit",
            "message": str(exc), "request_interval_seconds": args.request_interval_seconds,
            "local_ticker_limit": None,
        })
        raise SystemExit(str(exc))
    atomic_write_csv(args.output_dir / "earnings_event_date_mapping.csv", MAPPING_FIELDS, date_rows)
    price_rows: list[dict[str, Any]] = []
    if not args.skip_prices:
        try:
            price_rows = collect_prices(client, args.output_dir, tickers)
        except ProviderRateLimit as exc:
            atomic_write_json(args.output_dir / "provider_limit_evidence.json", {
                "detected_at_utc": utc_now(), "classification": "alpha_vantage_provider_rate_limit",
                "message": str(exc), "request_interval_seconds": args.request_interval_seconds,
                "local_ticker_limit": None,
            })
            raise SystemExit(str(exc))
        atomic_write_csv(args.output_dir / "adjusted_close_prices.csv", PRICE_FIELDS, price_rows)
    factors: dict[str, dict[str, str]] = {}
    if not args.skip_factors:
        factors = download_factors(args.output_dir)
    status_counts = Counter(row["mapping_status"] for row in date_rows)
    manifest = {
        "generated_at_utc": utc_now(), "events_source": str(args.events), "event_count_source": len(events),
        "ticker_count_source": len(all_tickers), "ticker_count_collected": len(tickers),
        "request_interval_seconds": args.request_interval_seconds, "date_mapping_status_counts": dict(status_counts),
        "adjusted_close_row_count": len(price_rows), "factor_files": factors,
        "date_mapping_rule": "match source YYYYQn to Alpha Vantage EARNINGS quarterlyEarnings.reportedDate calendar quarter",
    }
    atomic_write_json(args.output_dir / "collection_manifest.json", manifest)
    print(f"Wrote {args.output_dir / 'earnings_event_date_mapping.csv'}")
    print(f"Date mapping statuses: {dict(status_counts)}")
    if not args.skip_prices:
        print(f"Adjusted-close rows: {len(price_rows):,}")


if __name__ == "__main__":
    main()
