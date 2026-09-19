from datetime import date

from validate_date_map_pilot import (
    explicit_web_match,
    fiscal_period_end,
    parse_date_text,
    result_looks_relevant,
)


def test_fiscal_period_end_handles_noncalendar_year() -> None:
    assert fiscal_period_end(2012, 3, 5) == date(2012, 2, 29)
    assert fiscal_period_end(2012, 1, 5) == date(2011, 8, 31)


def test_explicit_web_match_requires_quarter_and_event_date() -> None:
    call = {
        "quarter_label": "2019Q3",
        "historical_ticker": "AAPL",
        "company_name": "Apple Inc",
    }
    result = {
        "title": "Apple Inc. (AAPL) Q3 2019 Earnings Call Transcript",
        "snippet": "AAPL earnings call for the period ending July 30, 2019.",
    }
    found, _ = explicit_web_match(
        result,
        call,
        result["title"],
        "Apple Inc. Q3 2019 Earnings Call Jul 30, 2019, 5:00 p.m. ET",
    )
    assert found == date(2019, 7, 30)


def test_search_result_prefilter_rejects_wrong_year() -> None:
    call = {
        "quarter_label": "2019Q3",
        "historical_ticker": "AAPL",
        "company_name": "Apple Inc",
    }
    assert result_looks_relevant(
        {"title": "Apple (AAPL) Q3 2019 Earnings Call Transcript", "snippet": ""}, call
    )
    assert not result_looks_relevant(
        {"title": "Apple (AAPL) Q3 2020 Earnings Call Transcript", "snippet": ""}, call
    )


def test_parse_date_text_does_not_use_year_only() -> None:
    assert parse_date_text("Q3 2019 earnings call") is None
    assert parse_date_text("July 30, 2019") == date(2019, 7, 30)
