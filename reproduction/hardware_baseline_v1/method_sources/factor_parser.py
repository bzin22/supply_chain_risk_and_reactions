#!/usr/bin/env python3
"""Calculate Carhart four-factor event returns for earnings calls.

The script creates a compact, event-level CSV.  It reads the existing
``earnings_call_transcript_segments.csv`` only to identify one event per
``(ticker, quarter_label)`` and to retain company metadata.  It joins the
SCRisk/Resolution values from a separate scored transcript CSV, then adds
Carhart abnormal returns and sector SCRisk ranks.  It never copies the large
segment ``content`` field or transcript text into the output.

Inputs
------

``--segments``
    Segment CSV with at least ``ticker``, ``quarter_label``, ``call_date``,
    ``company_name``, ``sector``, and ``industry``.

``--supply-chain-scores``
    The later output of the supply-chain score calculator.  It must contain
    ``ticker``, ``quarter_label``, ``SCRisk``, and ``Resolution``.  Requiring
    this file is an intentional safety gate: the full event dataset should
    not be produced until the reviewed supply-chain library is ready.

``--prices``
    A local long-format CSV with ``ticker``, ``date``, and
    ``adjusted_close``.  Adjusted close is used so the return includes
    reinvested distributions.  The French Data Library provides factor
    portfolios, not individual company prices, so company prices are a
    separate cached input rather than something silently downloaded here.

``--factors`` and ``--momentum``
    Daily Fama/French three-factor data and daily momentum data.  Each may be
    an official Kenneth French TXT/ZIP download or a simple delimited file.
    The official downloads are:

    - https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_daily_TXT.zip
    - https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Momentum_Factor_daily_TXT.zip

    The official files report percentages; ``--factor-units percent`` is the
    default and converts them to decimals.  A combined factor file containing
    ``Mkt-RF, SMB, HML, RF, Mom`` can be used without ``--momentum``.

Event-study definition
----------------------

* Day 0 is the first factor-calendar trading day on or after ``call_date``.
  Day 1 is the next factor-calendar trading day.  This is the approved rule
  for calls whose timestamp is not available in the current schema.
* The estimation window is exactly 200 observations on event days -209
  through -10.  The model is fit separately for each call and never uses
  event-window observations.
* For each estimation day, the stock return is adjusted-close[t] /
  adjusted-close[t-1] - 1.  The dependent variable is stock return minus RF.
* The fitted model is ``R_i - RF = alpha + beta'M + error``, where M is
  ``(MKT-RF, SMB, HML, MOM)``.  Expected total return is RF plus the fitted
  excess return.  Abnormal return is actual total return minus expected total
  return, and ``CAR_0_1`` is the sum of day-0 and day-1 abnormal returns.
* Events missing any required price/factor observation receive a status and
  blank return fields instead of silently shortening the estimation window.
* An event whose scored transcript is marked ``transcript_integrity_status =
  content_absent`` is given ``event_status = excluded_transcript_integrity``.
  Its CAR fields and its original estimation status are still written, in
  ``car_estimation_status``.  Use ``--no-transcript-integrity-filter`` to keep
  these events in the study.
* SCRisk is ranked descending within each observed sector.  Equal scores use
  competition ranking (1, 1, 3), with ticker and quarter used only to make
  output ordering deterministic.

Example, for a future reviewed full run
----------------------------------------

    conda run -n dap-env python analysis/calculate_carhart_event_returns.py \
        --segments earnings_call_transcript_segments.csv \
        --supply-chain-scores earnings_call_transcripts_scored.csv \
        --prices prices_adjusted_close.csv \
        --factors F-F_Research_Data_Factors_daily_TXT.zip \
        --momentum F-F_Momentum_Factor_daily_TXT.zip \
        --output earnings_call_event_returns.csv

The script does not run this command automatically.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import math
import os
import re
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np


ESTIMATION_DAYS = 200
PRE_EVENT_GAP = 10
EXPECTED_SECTOR_COUNT = 9
DATE_RE = re.compile(r"^\s*(\d{8}|\d{4}-\d{2}-\d{2})")
NUMBER_SPLIT_RE = re.compile(r"[,\s]+")


def configure_csv_field_size_limit() -> None:
    """Accept source CSV fields that exceed the stdlib's small default."""

    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


@dataclass(frozen=True)
class FactorRow:
    """Daily factor observations, stored as decimal returns."""

    market_minus_rf: float
    smb: float
    hml: float
    momentum: float
    rf: float


@dataclass(frozen=True)
class EventResult:
    """Return-model result for one event, including failure status."""

    status: str
    error_message: str = ""
    event_trading_date: str = ""
    day_0_trading_date: str = ""
    day_1_trading_date: str = ""
    estimation_start: str = ""
    estimation_end: str = ""
    estimation_observations: int = 0
    alpha: float | None = None
    beta_market_minus_rf: float | None = None
    beta_smb: float | None = None
    beta_hml: float | None = None
    beta_momentum: float | None = None
    r_squared: float | None = None
    actual_return_day_0: float | None = None
    expected_return_day_0: float | None = None
    abnormal_return_day_0: float | None = None
    actual_return_day_1: float | None = None
    expected_return_day_1: float | None = None
    abnormal_return_day_1: float | None = None
    car_0_1: float | None = None


def parse_date(value: Any) -> date | None:
    """Parse ISO or YYYYMMDD dates, returning None for blank values."""

    text = "" if value is None else str(value).strip()
    if not text:
        return None
    text = text[:10]
    for pattern in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    raise ValueError(f"Unsupported date value: {value!r}")


def date_text(value: date | None) -> str:
    return "" if value is None else value.isoformat()


def ticker_value(row: dict[str, str]) -> str:
    return (row.get("ticker") or row.get("symbol") or "").strip().upper()


def event_key(row: dict[str, str]) -> tuple[str, str]:
    ticker = ticker_value(row)
    quarter = (row.get("quarter_label") or "").strip().upper()
    if not quarter:
        year = (row.get("year") or "").strip()
        quarter_number = (row.get("quarter") or "").strip()
        quarter = f"{year}Q{quarter_number}" if year and quarter_number else ""
    return ticker, quarter


def load_events_from_segments(path: Path, event_date_column: str = "call_date") -> list[dict[str, Any]]:
    """Collapse segment rows to one compact event record per earnings call."""

    events: dict[tuple[str, str], dict[str, Any]] = {}
    required = {"ticker", "quarter_label", event_date_column, "company_name", "sector", "industry"}
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path} is missing required columns: {sorted(missing)}")
        for row in reader:
            ticker, quarter = event_key(row)
            if not ticker or not quarter:
                raise ValueError(f"Segment row lacks ticker or quarter_label in {path}")
            key = (ticker, quarter)
            call_date = (row.get(event_date_column) or "").strip()
            if key not in events:
                events[key] = {
                    "ticker": ticker,
                    "company_name": (row.get("company_name") or "").strip(),
                    "sector": (row.get("sector") or "").strip(),
                    "industry": (row.get("industry") or "").strip(),
                    "year": (row.get("year") or "").strip(),
                    "quarter": (row.get("quarter") or "").strip(),
                    "quarter_label": quarter,
                    "call_date": call_date,
                    "segment_count": 1,
                }
                continue

            event = events[key]
            event["segment_count"] += 1
            if not event["call_date"] and call_date:
                event["call_date"] = call_date
            for field in ("company_name", "sector", "industry"):
                incoming = (row.get(field) or "").strip()
                if event[field] and incoming and event[field] != incoming:
                    raise ValueError(f"Conflicting {field} values for event {key} in {path}")

    if not events:
        raise ValueError(f"No transcript events found in {path}")
    return list(events.values())


SCORE_FIELDS = (
    "SCRisk", "Resolution", "SCRisk_raw", "Resolution_raw", "SCRisk_sd", "Resolution_sd",
    # Written by scoring/calculate_supply_chain_transcript_scores.py from the corrected
    # vocabulary onward.  A scored CSV produced before that column existed
    # joins as an empty string and is treated as unflagged.
    "transcript_integrity_status",
)

# A transcript that holds no spoken content still has a valid CAR, because the
# CAR comes from prices and factors rather than from the text.  What it does
# not have is a usable SCRisk.  Excluding it here, by the one status field
# every downstream consumer already filters on, keeps it out of the event study
# without discarding the estimation it did produce.
INTEGRITY_CONTENT_ABSENT = "content_absent"
EXCLUDED_FOR_INTEGRITY = "excluded_transcript_integrity"


def load_supply_chain_scores(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    """Load only score columns, avoiding retention of transcript_text."""

    scores: dict[tuple[str, str], dict[str, str]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"ticker", "quarter_label", "SCRisk", "Resolution"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path} is missing required score columns: {sorted(missing)}")
        for row in reader:
            key = event_key(row)
            if not all(key):
                raise ValueError(f"Score row lacks ticker or quarter_label in {path}")
            if key in scores:
                raise ValueError(f"Duplicate score row for event {key} in {path}")
            scores[key] = {field: (row.get(field) or "").strip() for field in SCORE_FIELDS}
    if not scores:
        raise ValueError(f"No score rows found in {path}")
    return scores


def join_scores(
    events: list[dict[str, Any]],
    scores: dict[tuple[str, str], dict[str, str]],
    allow_missing: bool,
) -> None:
    """Attach score fields to event rows and enforce complete joins by default."""

    missing_keys: list[tuple[str, str]] = []
    for event in events:
        key = (event["ticker"], event["quarter_label"])
        score = scores.get(key)
        if score is None:
            missing_keys.append(key)
            event["score_join_status"] = "missing_score"
            for field in SCORE_FIELDS:
                event[field] = ""
            continue

        event.update(score)
        event["score_join_status"] = "matched"
        event.setdefault("transcript_integrity_status", "")
    if missing_keys and not allow_missing:
        sample = ", ".join(f"{ticker}/{quarter}" for ticker, quarter in missing_keys[:5])
        raise ValueError(
            f"{len(missing_keys):,} segment events have no score row; examples: {sample}. "
            "Use --allow-missing-scores only for diagnostics."
        )


def load_prices(path: Path) -> dict[str, dict[date, float]]:
    """Load long-format adjusted closes keyed by ticker and date."""

    prices: dict[str, dict[date, float]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        ticker_field = "ticker" if "ticker" in fields else "symbol" if "symbol" in fields else None
        price_field = (
            "adjusted_close"
            if "adjusted_close" in fields
            else "Adj Close"
            if "Adj Close" in fields
            else None
        )
        if ticker_field is None or "date" not in fields or price_field is None:
            raise ValueError(
                f"{path} must contain ticker/symbol, date, and adjusted_close (or Adj Close)"
            )
        for row in reader:
            ticker = (row.get(ticker_field) or "").strip().upper()
            trading_date = parse_date(row.get("date"))
            if not ticker or trading_date is None:
                continue
            try:
                price = float(row.get(price_field) or "")
            except ValueError as exc:
                raise ValueError(f"Invalid adjusted close for {ticker} on {trading_date}") from exc
            if not math.isfinite(price) or price <= 0:
                raise ValueError(f"Adjusted close must be positive and finite for {ticker} on {trading_date}")
            series = prices.setdefault(ticker, {})
            if trading_date in series:
                raise ValueError(f"Duplicate price row for {ticker} on {trading_date}")
            series[trading_date] = price
    if not prices:
        raise ValueError(f"No valid price rows found in {path}")
    return prices


def read_factor_text(path: Path) -> str:
    """Read plain text or the first file in an official French ZIP archive."""

    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            candidates = [name for name in archive.namelist() if not name.endswith("/")]
            if not candidates:
                raise ValueError(f"No files found in factor archive {path}")
            return archive.read(candidates[0]).decode("latin-1")
    return path.read_text(encoding="latin-1")


def numeric_factor(value: str, units: str) -> float | None:
    try:
        number = float(value)
    except ValueError:
        return None
    # French files use -99.99 as a missing-data sentinel.
    if not math.isfinite(number) or abs(number) >= 90:
        return None
    return number / 100.0 if units == "percent" else number


def parse_factor_rows(path: Path, units: str, expected_values: int) -> dict[date, list[float]]:
    """Parse official French text/ZIP rows or simple date-first delimited files."""

    rows: dict[date, list[float]] = {}
    for line_number, line in enumerate(read_factor_text(path).splitlines(), start=1):
        match = DATE_RE.match(line)
        if match is None:
            continue
        parts = [part for part in NUMBER_SPLIT_RE.split(line.strip()) if part]
        if len(parts) < expected_values + 1:
            continue
        try:
            trading_date = parse_date(parts[0])
        except ValueError:
            continue
        if trading_date is None:
            continue
        values = [numeric_factor(value, units) for value in parts[1 : expected_values + 1]]
        if any(value is None for value in values):
            continue
        if trading_date in rows:
            raise ValueError(f"Duplicate factor row for {trading_date} in {path}")
        rows[trading_date] = [float(value) for value in values if value is not None]
    if not rows:
        raise ValueError(f"No daily factor rows found in {path}")
    return rows


def load_four_factors(path: Path, momentum_path: Path | None, units: str) -> dict[date, FactorRow]:
    """Load and join MKT-RF, SMB, HML, MOM, and RF factor observations."""

    # A standard Fama/French daily file has MKT-RF, SMB, HML, RF.  A custom
    # combined file may append MOM as its fifth value; both forms are supported.
    try:
        fama_french = parse_factor_rows(path, units, expected_values=5)
    except ValueError:
        fama_french = parse_factor_rows(path, units, expected_values=4)

    momentum: dict[date, list[float]] = {}
    if momentum_path is not None:
        momentum = parse_factor_rows(momentum_path, units, expected_values=1)

    factors: dict[date, FactorRow] = {}
    for trading_date, values in fama_french.items():
        if len(values) >= 5:
            market, smb, hml, rf, mom = values[:5]
        elif trading_date in momentum:
            market, smb, hml, rf = values[:4]
            mom = momentum[trading_date][0]
        else:
            continue
        factors[trading_date] = FactorRow(market, smb, hml, mom, rf)
    if not factors:
        raise ValueError("No dates contain all four Carhart factors")
    return factors


def daily_return(prices: dict[date, float], current: date, previous: date) -> float | None:
    """Return adjusted-close simple return, or None when either price is absent."""

    current_price = prices.get(current)
    previous_price = prices.get(previous)
    if current_price is None or previous_price is None:
        return None
    return current_price / previous_price - 1.0


def calculate_event_return(
    event: dict[str, Any],
    prices: dict[str, dict[date, float]],
    factors: dict[date, FactorRow],
    calendar: list[date],
) -> EventResult:
    """Fit one pre-event Carhart model and calculate CAR(0,1)."""

    call_date = parse_date(event.get("call_date"))
    if call_date is None:
        return EventResult("missing_call_date", "call_date is blank or invalid")

    event_index = bisect.bisect_left(calendar, call_date)
    if event_index >= len(calendar):
        return EventResult("event_after_factor_data", "No factor-calendar date on or after call_date")
    if event_index < ESTIMATION_DAYS + PRE_EVENT_GAP - 1:
        return EventResult("insufficient_pre_event_history", "Fewer than 200 observations before the gap")
    if event_index + 1 >= len(calendar):
        return EventResult("missing_day_1", "No factor-calendar trading day after event day 0")

    ticker = event["ticker"]
    ticker_prices = prices.get(ticker)
    if ticker_prices is None:
        return EventResult("missing_price_series", f"No price series for {ticker}")

    estimate_indices = range(
        event_index - (ESTIMATION_DAYS + PRE_EVENT_GAP - 1),
        event_index - PRE_EVENT_GAP + 1,
    )
    if len(estimate_indices) != ESTIMATION_DAYS:
        return EventResult("internal_window_error", "Estimation window did not contain exactly 200 dates")

    x_rows: list[list[float]] = []
    y_values: list[float] = []
    for index in estimate_indices:
        trading_date = calendar[index]
        previous_date = calendar[index - 1]
        factor = factors.get(trading_date)
        actual_return = daily_return(ticker_prices, trading_date, previous_date)
        if factor is None or actual_return is None:
            return EventResult(
                "missing_estimation_data",
                f"Missing factor or adjusted close on {trading_date.isoformat()}",
                estimation_observations=0,
            )
        x_rows.append([1.0, factor.market_minus_rf, factor.smb, factor.hml, factor.momentum])
        y_values.append(actual_return - factor.rf)

    x_matrix = np.asarray(x_rows, dtype=float)
    y_vector = np.asarray(y_values, dtype=float)
    coefficients, _, matrix_rank, _ = np.linalg.lstsq(x_matrix, y_vector, rcond=None)
    if matrix_rank < 5:
        return EventResult("singular_regression", "Carhart design matrix did not have full rank")

    fitted = x_matrix @ coefficients
    residuals = y_vector - fitted
    total_sum_squares = float(np.sum((y_vector - np.mean(y_vector)) ** 2))
    residual_sum_squares = float(np.sum(residuals**2))
    r_squared = None if total_sum_squares == 0.0 else 1.0 - residual_sum_squares / total_sum_squares

    event_values: list[tuple[float, float, float]] = []
    for index in (event_index, event_index + 1):
        trading_date = calendar[index]
        previous_date = calendar[index - 1]
        factor = factors.get(trading_date)
        actual_return = daily_return(ticker_prices, trading_date, previous_date)
        if factor is None or actual_return is None:
            return EventResult(
                "missing_event_data",
                f"Missing factor or adjusted close on {trading_date.isoformat()}",
                event_trading_date=date_text(calendar[event_index]),
                day_0_trading_date=date_text(calendar[event_index]),
                day_1_trading_date=date_text(calendar[event_index + 1]),
                estimation_start=date_text(calendar[event_index - 209]),
                estimation_end=date_text(calendar[event_index - 10]),
                estimation_observations=ESTIMATION_DAYS,
            )
        factor_vector = np.asarray(
            [1.0, factor.market_minus_rf, factor.smb, factor.hml, factor.momentum], dtype=float
        )
        expected_return = factor.rf + float(factor_vector @ coefficients)
        abnormal_return = actual_return - expected_return
        event_values.append((actual_return, expected_return, abnormal_return))

    day_0, day_1 = event_values
    return EventResult(
        status="ok",
        event_trading_date=date_text(calendar[event_index]),
        day_0_trading_date=date_text(calendar[event_index]),
        day_1_trading_date=date_text(calendar[event_index + 1]),
        estimation_start=date_text(calendar[event_index - 209]),
        estimation_end=date_text(calendar[event_index - 10]),
        estimation_observations=ESTIMATION_DAYS,
        alpha=float(coefficients[0]),
        beta_market_minus_rf=float(coefficients[1]),
        beta_smb=float(coefficients[2]),
        beta_hml=float(coefficients[3]),
        beta_momentum=float(coefficients[4]),
        r_squared=r_squared,
        actual_return_day_0=day_0[0],
        expected_return_day_0=day_0[1],
        abnormal_return_day_0=day_0[2],
        actual_return_day_1=day_1[0],
        expected_return_day_1=day_1[1],
        abnormal_return_day_1=day_1[2],
        car_0_1=day_0[2] + day_1[2],
    )


def exclude_content_absent_transcripts(events: list[dict[str, Any]]) -> int:
    """Re-status events whose transcript holds no spoken content.

    The CAR estimation status is preserved in ``car_estimation_status`` so no
    information is lost; only ``event_status`` changes, which is the field the
    charts and the zero-rate audit filter on.
    """

    excluded = 0
    for event in events:
        event.setdefault("transcript_integrity_status", "")
        event["car_estimation_status"] = event.get("event_status", "")
        if event.get("transcript_integrity_status") != INTEGRITY_CONTENT_ABSENT:
            continue
        excluded += 1
        event["event_status"] = EXCLUDED_FOR_INTEGRITY
        event["event_error_message"] = (
            "transcript holds no spoken content; excluded from the event study"
        )
    return excluded


def numeric_score(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


RANKED_SECTOR_METRICS = (
    ("SCRisk", "SCRisk_sector_rank", "sector_scrisk_rankable_count"),
    ("Resolution", "Resolution_sector_rank", "sector_resolution_rankable_count"),
    ("CAR_0_1", "CAR_0_1_sector_rank", "sector_car_0_1_rankable_count"),
)


def rank_metrics_by_sector(events: list[dict[str, Any]]) -> None:
    """Add descending competition ranks for scores and CAR within each sector."""

    groups: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        sector = event.get("sector", "")
        groups.setdefault(sector, []).append(event)

    for group in groups.values():
        for event in group:
            event["sector_event_count"] = len(group)
        for metric, rank_field, count_field in RANKED_SECTOR_METRICS:
            rankable = [event for event in group if numeric_score(event.get(metric)) is not None]
            ordered = sorted(
                rankable,
                key=lambda event: (
                    -float(event[metric]),
                    event.get("ticker", ""),
                    event.get("quarter_label", ""),
                ),
            )
            previous_value: float | None = None
            current_rank = 0
            for position, event in enumerate(ordered, start=1):
                value = float(event[metric])
                if previous_value is None or value != previous_value:
                    current_rank = position
                    previous_value = value
                event[rank_field] = current_rank
            for event in group:
                event[count_field] = len(rankable)
                event.setdefault(rank_field, "")
                # Retain the former SCRisk count name for downstream callers.
                if metric == "SCRisk":
                    event["sector_rankable_count"] = len(rankable)


OUTPUT_FIELDS = [
    "ticker", "company_name", "sector", "industry", "year", "quarter", "quarter_label",
    "call_date", "segment_count", "SCRisk", "Resolution", "SCRisk_raw", "Resolution_raw",
    "SCRisk_sd", "Resolution_sd", "score_join_status", "SCRisk_sector_rank",
    "Resolution_sector_rank", "CAR_0_1_sector_rank", "sector_event_count",
    "sector_rankable_count", "sector_scrisk_rankable_count",
    "sector_resolution_rankable_count", "sector_car_0_1_rankable_count",
    "event_status", "event_error_message",
    "event_trading_date", "day_0_trading_date", "day_1_trading_date", "estimation_start",
    "estimation_end", "estimation_observations", "alpha", "beta_market_minus_rf", "beta_smb",
    "beta_hml", "beta_momentum", "r_squared", "actual_return_day_0", "expected_return_day_0",
    "abnormal_return_day_0", "actual_return_day_1", "expected_return_day_1",
    "abnormal_return_day_1", "CAR_0_1",
    # Appended, so existing name-based readers of this CSV keep working.
    "transcript_integrity_status", "car_estimation_status",
]


def event_result_dict(result: EventResult) -> dict[str, Any]:
    return {
        "event_status": result.status,
        "event_error_message": result.error_message,
        "event_trading_date": result.event_trading_date,
        "day_0_trading_date": result.day_0_trading_date,
        "day_1_trading_date": result.day_1_trading_date,
        "estimation_start": result.estimation_start,
        "estimation_end": result.estimation_end,
        "estimation_observations": result.estimation_observations,
        "alpha": result.alpha,
        "beta_market_minus_rf": result.beta_market_minus_rf,
        "beta_smb": result.beta_smb,
        "beta_hml": result.beta_hml,
        "beta_momentum": result.beta_momentum,
        "r_squared": result.r_squared,
        "actual_return_day_0": result.actual_return_day_0,
        "expected_return_day_0": result.expected_return_day_0,
        "abnormal_return_day_0": result.abnormal_return_day_0,
        "actual_return_day_1": result.actual_return_day_1,
        "expected_return_day_1": result.expected_return_day_1,
        "abnormal_return_day_1": result.abnormal_return_day_1,
        "CAR_0_1": result.car_0_1,
    }


def write_output(path: Path, events: Iterable[dict[str, Any]], input_paths: Iterable[Path]) -> None:
    """Write atomically and refuse to overwrite any input file."""

    output_resolved = path.resolve()
    if any(output_resolved == input_path.resolve() for input_path in input_paths):
        raise ValueError("Refusing to overwrite an input file; choose a separate --output path")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", newline="", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for event in events:
            writer.writerow(event)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--segments", type=Path, required=True)
    parser.add_argument("--supply-chain-scores", type=Path, required=True)
    parser.add_argument("--prices", type=Path, required=True, help="long CSV: ticker,date,adjusted_close")
    parser.add_argument("--factors", type=Path, required=True, help="French daily 3-factor TXT/ZIP or CSV")
    parser.add_argument("--momentum", type=Path, help="French daily momentum TXT/ZIP; omit for combined factors")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--event-date-column", default="call_date",
        help="segment column holding the event date; use event_date for a date-enriched derivative",
    )
    parser.add_argument("--factor-units", choices=("percent", "decimal"), default="percent")
    parser.add_argument("--limit", type=int, help="score only the first N events for validation")
    parser.add_argument(
        "--allow-missing-scores",
        action="store_true",
        help="write unmatched events with blank SCRisk/Resolution; diagnostic use only",
    )
    parser.add_argument(
        "--no-transcript-integrity-filter",
        dest="filter_transcript_integrity",
        action="store_false",
        help=(
            "keep events whose transcript holds no spoken content in the event study. "
            "Reproduces the original run, which had no integrity filter"
        ),
    )
    return parser.parse_args()


def main() -> None:
    configure_csv_field_size_limit()
    args = parse_args()
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be positive")

    input_paths = [args.segments, args.supply_chain_scores, args.prices, args.factors]
    if args.momentum is not None:
        input_paths.append(args.momentum)

    events = load_events_from_segments(args.segments, args.event_date_column)
    if args.limit is not None:
        events = events[: args.limit]
    scores = load_supply_chain_scores(args.supply_chain_scores)
    join_scores(events, scores, args.allow_missing_scores)
    prices = load_prices(args.prices)
    factors = load_four_factors(args.factors, args.momentum, args.factor_units)
    calendar = sorted(factors)
    for event in events:
        result = calculate_event_return(event, prices, factors, calendar)
        event.update(event_result_dict(result))
    excluded = (
        exclude_content_absent_transcripts(events) if args.filter_transcript_integrity else 0
    )
    rank_metrics_by_sector(events)
    write_output(args.output, events, input_paths)

    successful = sum(event["event_status"] == "ok" for event in events)
    print(f"Excluded for transcript integrity: {excluded:,}")
    sector_count = len({event.get("sector", "") for event in events})
    print(f"Processed {len(events):,} earnings-call events")
    print(f"Successful CAR calculations: {successful:,}")
    print(f"Observed sectors: {sector_count} (expected study count: {EXPECTED_SECTOR_COUNT})")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
