from __future__ import annotations

from pathlib import Path

import pytest

from collect_transcript_pilot import (
    immutable_raw_path,
    index_manifest_rows,
    load_universe,
    prior_state,
    request_once,
    validate_requests_per_minute,
    validate_success,
    write_exclusive_json,
)


def test_allocated_request_ceiling_accepts_75_rpm() -> None:
    validate_requests_per_minute(75)
    with pytest.raises(ValueError, match=r"\(0, 75\]"):
        validate_requests_per_minute(75.01)


def test_prior_no_transcript_is_terminal_without_retry() -> None:
    row = {
        "company_id": "CIK0000320193",
        "provider_ticker": "AAPL",
        "quarter_label": "2019Q4",
    }
    manifest = [{
        **row,
        "provider_status": "no_transcript",
        "terminal_status": "nonterminal_failure",
        "attempt_number": "1",
    }]
    state, attempts, had_no_transcript = prior_state(row, {}, index_manifest_rows(manifest))
    assert state == "terminal_provider_unavailability"
    assert attempts == 1
    assert had_no_transcript is True


def test_prior_invalid_api_call_is_terminal_without_retry() -> None:
    row = {
        "company_id": "CIK0000320193",
        "provider_ticker": "AAPL",
        "quarter_label": "2019Q4",
    }
    manifest = [{
        **row,
        "provider_status": "api_error",
        "terminal_status": "nonterminal_failure",
        "attempt_number": "1",
    }]
    state, attempts, had_no_transcript = prior_state(row, {}, index_manifest_rows(manifest))
    assert state == "terminal_provider_failure"
    assert attempts == 1
    assert had_no_transcript is False


def test_pilot_universe_is_bounded_and_unique() -> None:
    rows = load_universe(
        Path("data/pilot/pilot_universe_v20260916/eligible_firm_quarters.csv")
    )
    assert len(rows) == 186
    assert {row["quarter_label"][:4] for row in rows} <= {str(y) for y in range(2010, 2020)}
    assert any(row["provider_ticker"] == "PKI" for row in rows)
    assert not any(row["provider_ticker"] == "RVTY" for row in rows)


def test_raw_attempt_write_is_immutable(tmp_path: Path) -> None:
    path = tmp_path / "attempt.json"
    write_exclusive_json(path, {"one": 1})
    with pytest.raises(FileExistsError):
        write_exclusive_json(path, {"two": 2})


def test_ticker_reuse_identity_mismatch_is_quarantined() -> None:
    payload = [
        {"speaker": "Operator", "content": "Sunation Energy " + "word " * 200}
    ]
    classification, reason, *_ = validate_success(
        payload, company_id="CIK0000945436", quarter="2015Q1"
    )
    assert classification == "quarantine"
    assert "ticker-reuse" in reason


def test_opening_year_mismatch_is_quarantined() -> None:
    payload = [
        {"speaker": "Operator", "content": "Apple fiscal year 2024 " + "word " * 200}
    ]
    classification, reason, *_ = validate_success(
        payload, company_id="CIK0000320193", quarter="2012Q1"
    )
    assert classification == "quarantine"
    assert "conflict" in reason


def test_request_exception_never_persists_url_or_api_key() -> None:
    class FailedSession:
        def get(self, *args: object, **kwargs: object) -> None:
            raise __import__("requests").ConnectionError(
                "failed https://example.test/?apikey=secret-value"
            )

    row = {"provider_ticker": "AAPL", "quarter_label": "2019Q4"}
    _, _, _, status = request_once(FailedSession(), "secret-value", row, 1.0)  # type: ignore[arg-type]
    assert status == "request_error_ConnectionError"
    assert "secret-value" not in status
    assert "http" not in status
