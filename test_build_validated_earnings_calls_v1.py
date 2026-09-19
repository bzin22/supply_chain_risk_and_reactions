from build_validated_earnings_calls_v1 import (
    map_fiscal_rows,
    parse_explicit_history_rows,
    subtract_months,
)


def test_subtract_months_clamps_month_end() -> None:
    from datetime import date

    assert subtract_months(date(2012, 5, 31), 3) == date(2012, 2, 29)


def test_map_fiscal_rows_uses_annual_fiscal_year() -> None:
    payload = {
        "annualEarnings": [{"fiscalDateEnding": "2012-05-31"}],
        "quarterlyEarnings": [
            {
                "fiscalDateEnding": "2012-02-29",
                "reportedDate": "2012-03-20",
                "reportTime": "pre-market",
            },
            {
                "fiscalDateEnding": "2011-08-31",
                "reportedDate": "2011-09-21",
            },
        ],
    }
    rows = map_fiscal_rows(payload)
    assert rows[0]["quarter_label"] == "2012Q3"
    assert rows[0]["reported_date"] == "2012-03-20"
    assert rows[1]["quarter_label"] == "2012Q1"


def test_map_fiscal_rows_rejects_unanchored_quarter() -> None:
    payload = {
        "annualEarnings": [{"fiscalDateEnding": "2012-05-31"}],
        "quarterlyEarnings": [
            {"fiscalDateEnding": "2010-01-15", "reportedDate": "2010-02-01"}
        ],
    }
    assert map_fiscal_rows(payload) == []


def test_parse_explicit_history_rows() -> None:
    body = b'<tr><td class="tstyle">Q4 2019</td><td align="center">2/3/2020</td></tr>'
    assert parse_explicit_history_rows(body) == [
        {"quarter_label": "2019Q4", "reported_date": "2020-02-03"}
    ]
