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


def _payload_source(raw_path, recorded_sha256: str) -> dict:
    return {
        "session_id": "test",
        "company_id": "C1",
        "cik": "0000000001",
        "company_name": "Apple Inc",
        "provider_ticker": "AAPL",
        "quarter_label": "2015Q2",
        "attempt_number": "1",
        "requested_at_utc": "2026-01-01T00:00:00+00:00",
        "completed_at_utc": "2026-01-01T00:00:01+00:00",
        "http_status": "200",
        "provider_status": "ok",
        "raw_path": str(raw_path),
        "raw_size_bytes": "0",
        "raw_sha256": recorded_sha256,
        "classification": "valid",
        "validation_reason": "",
        "terminal_status": "valid",
        "retry_status": "",
        "segment_count": "2",
        "token_count": "200",
        "normalized_transcript_sha256": "",
        "api_message": "",
    }


def _eligible() -> dict:
    return {
        "company_id": "C1",
        "cik": "0000000001",
        "company_name": "Apple Inc",
        "security_id": "S1",
        "provider_ticker": "AAPL",
        "quarter_label": "2015Q2",
    }


def _write_transcript(tmp_path):
    import hashlib
    import json

    body = " ".join(["apple supply chain revenue guidance"] * 60)
    payload = {
        "symbol": "AAPL",
        "quarter": "2015Q2",
        "transcript": [
            {"speaker": "Tim Cook", "title": "CEO", "content": body},
            {"speaker": "Luca Maestri", "title": "CFO", "content": body},
        ],
    }
    raw_path = tmp_path / "raw.json"
    raw_path.write_text(json.dumps({"payload": payload}), encoding="utf-8")
    return raw_path, hashlib.sha256(raw_path.read_bytes()).hexdigest()


def test_initial_classification_accepts_matching_raw_hash(tmp_path) -> None:
    from validate_date_map_pilot import initial_classification

    raw_path, digest = _write_transcript(tmp_path)
    row = initial_classification(_payload_source(raw_path, digest), _eligible(), [])
    assert row["raw_sha256_verified"] == "true"
    assert row["validation_status"] == "valid"


def test_initial_classification_quarantines_tampered_payload(tmp_path) -> None:
    from validate_date_map_pilot import initial_classification

    raw_path, _ = _write_transcript(tmp_path)
    row = initial_classification(
        _payload_source(raw_path, "0" * 64), _eligible(), []
    )
    assert row["raw_sha256_verified"] == "false"
    assert row["validation_status"] == "quarantine"
    assert "raw_sha256_mismatch" in row["validation_flags"]


def test_web_user_agent_requires_a_contact_email(monkeypatch) -> None:
    import pytest

    from validate_date_map_pilot import web_user_agent

    monkeypatch.setenv("WEB_USER_AGENT", "Mozilla/5.0")
    with pytest.raises(RuntimeError):
        web_user_agent()
    monkeypatch.setenv("WEB_USER_AGENT", "recreation-study (bryan@usereframe.ai)")
    assert web_user_agent() == "recreation-study (bryan@usereframe.ai)"
