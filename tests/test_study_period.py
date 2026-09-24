from __future__ import annotations

import csv
from pathlib import Path

import pytest

from collection.extract_earnings_call_transcript_data import parse_args, study_quarters
from collection.study_period import (
    STUDY_END,
    STUDY_START,
    validate_csv_event_dates_in_study_period,
    validate_csv_in_study_period,
    validate_study_quarter,
)


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["ticker", "quarter_label"])
        writer.writeheader()
        writer.writerows(rows)


def test_hard_study_quarters_are_exactly_2010q1_through_2019q4() -> None:
    quarters = study_quarters()
    assert quarters[0] == STUDY_START
    assert quarters[-1] == STUDY_END
    assert len(quarters) == 40


@pytest.mark.parametrize("quarter", ["2009Q4", "2020Q1", "2024Q4"])
def test_requested_quarter_outside_study_period_fails(quarter: str) -> None:
    with pytest.raises(ValueError, match="outside the hard study period"):
        validate_study_quarter(quarter)


@pytest.mark.parametrize(
    "context",
    [
        "transcript input", "segment input", "scoring input", "standardization input",
        "CAR input", "quintile input", "regression input",
    ],
)
def test_any_analysis_input_with_post_2019_observation_fails(
    tmp_path: Path, context: str
) -> None:
    path = tmp_path / "input.csv"
    write_rows(
        path,
        [
            {"ticker": "SAFE", "quarter_label": "2019Q4"},
            {"ticker": "LATE", "quarter_label": "2020Q1"},
        ],
    )
    with pytest.raises(ValueError, match="LATE 2020Q1"):
        validate_csv_in_study_period(path, context=context)


def test_collector_exposes_no_runtime_period_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["collector", "--input", "companies.csv", "--end-quarter", "2020Q1"],
    )
    with pytest.raises(SystemExit):
        parse_args()


def test_post_2019_call_date_fails_even_for_2019q4(tmp_path: Path) -> None:
    path = tmp_path / "event_dates.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["ticker", "quarter_label", "call_date"])
        writer.writeheader()
        writer.writerow({"ticker": "LATE", "quarter_label": "2019Q4", "call_date": "2020-01-15"})
    with pytest.raises(ValueError, match="out-of-period call_date 2020-01-15"):
        validate_csv_event_dates_in_study_period(path, context="CAR input")


def test_transcript_text_helpers_remain_available():
    from collection.extract_earnings_call_transcript_data import looks_like_qa_marker, word_count

    assert word_count("one two\nthree") == 3
    assert looks_like_qa_marker("Question and Answer Session")
