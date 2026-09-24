"""Hard study-period rules shared by collection and analysis code."""

from __future__ import annotations

import argparse
import csv
import re
import sys
from datetime import date
from pathlib import Path
from typing import Iterable, Mapping

STUDY_START = "2010Q1"
STUDY_END = "2019Q4"
STUDY_START_YEAR = 2010
STUDY_END_YEAR = 2019
STUDY_START_DATE = date(2010, 1, 1)
STUDY_END_DATE = date(2019, 12, 31)
QUARTER_PATTERN = re.compile(r"^(\d{4})Q([1-4])$")


def parse_quarter(value: str) -> tuple[int, int]:
    normalized = str(value).strip().upper()
    match = QUARTER_PATTERN.fullmatch(normalized)
    if not match:
        raise argparse.ArgumentTypeError(
            f"quarter must use YYYYQn format within {STUDY_START}-{STUDY_END}"
        )
    return int(match.group(1)), int(match.group(2))


def validate_study_quarter(value: str) -> str:
    year, quarter = parse_quarter(value)
    normalized = f"{year:04d}Q{quarter}"
    if not (STUDY_START <= normalized <= STUDY_END):
        raise ValueError(
            f"{normalized} is outside the hard study period "
            f"{STUDY_START}-{STUDY_END}; changing the period requires a code change"
        )
    return normalized


def study_quarters() -> list[str]:
    return [f"{year}Q{quarter}" for year in range(2010, 2020) for quarter in range(1, 5)]


def row_quarter(row: Mapping[str, str]) -> str | None:
    value = (row.get("quarter_label") or "").strip().upper()
    if value:
        return value
    year = (row.get("year") or "").strip()
    quarter = (row.get("quarter") or "").strip()
    if year and quarter:
        return f"{year}Q{quarter}"
    return None


def validate_rows_in_study_period(
    rows: Iterable[Mapping[str, str]], *, source: str = "input"
) -> None:
    for line_number, row in enumerate(rows, start=2):
        quarter = row_quarter(row)
        if quarter is None:
            raise ValueError(f"{source}:{line_number} has no quarter_label or year/quarter")
        try:
            validate_study_quarter(quarter)
        except (argparse.ArgumentTypeError, ValueError) as exc:
            ticker = (row.get("ticker") or row.get("symbol") or "").strip()
            raise ValueError(
                f"{source}:{line_number} contains out-of-period observation "
                f"{ticker or '<unknown ticker>'} {quarter}: {exc}"
            ) from exc


def validate_csv_in_study_period(path: Path, *, context: str = "analysis input") -> None:
    csv.field_size_limit(sys.maxsize)
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        if "quarter_label" not in fields and not {"year", "quarter"}.issubset(fields):
            raise ValueError(f"{context} {path} has no usable study-quarter columns")
        validate_rows_in_study_period(reader, source=str(path))


def validate_csv_event_dates_in_study_period(
    path: Path,
    *,
    context: str = "event-date input",
    fields: tuple[str, ...] = (
        "call_date", "earnings_call_date", "candidate_call_date",
        "transcript_explicit_call_date",
        "earnings_announcement_date", "explicit_call_date", "filing_date",
        "filing_date_candidate_only",
    ),
) -> None:
    csv.field_size_limit(sys.maxsize)
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        available = [field for field in fields if field in set(reader.fieldnames or [])]
        if not available:
            return
        for line_number, row in enumerate(reader, start=2):
            for field in available:
                value = (row.get(field) or "").strip()
                if not value:
                    continue
                for date_value in value.split(";"):
                    try:
                        parsed = date.fromisoformat(date_value)
                    except ValueError as exc:
                        raise ValueError(
                            f"{context} {path}:{line_number} has invalid {field} {date_value!r}"
                        ) from exc
                    if not (STUDY_START_DATE <= parsed <= STUDY_END_DATE):
                        raise ValueError(
                            f"{context} {path}:{line_number} contains out-of-period "
                            f"{field} {date_value}; hard date boundary is "
                            f"{STUDY_START_DATE.isoformat()}-{STUDY_END_DATE.isoformat()}"
                        )
