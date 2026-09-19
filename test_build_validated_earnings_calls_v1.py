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


def _write_csv(path, fields, rows) -> None:
    import csv

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _date_row(ticker: str, quarter: str, reported: str, fiscal_end: str) -> dict:
    return {
        "historical_ticker": ticker,
        "quarter_label": quarter,
        "fiscal_date_ending": fiscal_end,
        "reported_date": reported,
        "report_time": "pre-market",
        "fiscal_mapping_distance_days": "0",
        "fiscal_year_end": "12",
        "source_url": "https://example.test/earnings",
        "source_title": "Test source",
        "evidence_snippet": "reported",
        "retrieval_timestamp_utc": "2026-01-01T00:00:00+00:00",
        "match_method": "fiscal_date_ending",
        "confidence": "high",
        "status": "ok",
        "response_sha256": "a" * 64,
    }


def test_load_date_evidence_separates_conflict_from_missing(tmp_path) -> None:
    from build_validated_earnings_calls_v1 import (
        DATE_ROW_FIELDS,
        load_date_evidence,
        load_date_map,
    )

    _write_csv(
        tmp_path / "reported_date_rows.csv",
        DATE_ROW_FIELDS,
        [
            # Restated 53-week quarter: two fiscal period ends map to 2012Q4.
            _date_row("AAA", "2012Q4", "2013-02-01", "2012-12-31"),
            _date_row("AAA", "2012Q4", "2013-02-05", "2013-01-05"),
            _date_row("BBB", "2012Q4", "2013-02-10", "2012-12-31"),
        ],
    )
    resolved, conflicts = load_date_evidence(tmp_path)
    assert ("AAA", "2012Q4") not in resolved
    assert conflicts[("AAA", "2012Q4")] == ["2013-02-01", "2013-02-05"]
    assert resolved[("BBB", "2012Q4")]["reported_date"] == "2013-02-10"
    assert conflicts.get(("BBB", "2012Q4")) is None
    # Gap-filling collectors read load_date_map, so a conflicted key stays open.
    assert ("AAA", "2012Q4") not in load_date_map(tmp_path)


def test_delete_nonretained_writes_an_empty_manifest(tmp_path) -> None:
    from build_validated_earnings_calls_v1 import (
        delete_nonretained,
        manifest_fields,
    )

    fields = manifest_fields()
    _write_csv(
        tmp_path / "request_manifest.csv",
        fields,
        [
            {
                **dict.fromkeys(fields, ""),
                "raw_path": "artifacts/raw/kept.json",
                "raw_sha256": "b" * 64,
                "validation_status": "valid",
            }
        ],
    )
    summary = delete_nonretained(tmp_path)
    assert summary["candidate_payloads"] == 0
    assert summary["payloads_deleted_this_run"] == 0
    header = (tmp_path / "payload_deletion_manifest.csv").read_text().splitlines()
    assert header[0].startswith("raw_path,raw_sha256,validation_status")
    assert len(header) == 1


def _finalize_fixture(tmp_path):
    import hashlib
    import json

    from build_validated_earnings_calls_v1 import DATE_ROW_FIELDS, WORKING_FIELDS

    output = tmp_path / "work"
    output.mkdir()
    text = "[Tim Cook | CEO] revenue guidance"
    _write_csv(
        output / "validated_calls_working.csv",
        WORKING_FIELDS,
        [
            {
                **dict.fromkeys(WORKING_FIELDS, ""),
                "call_id": "C1|AAA|2012Q4",
                "company_id": "C1",
                "historical_ticker": "AAA",
                "quarter_label": "2012Q4",
                "transcript_text": text,
                "validation_status": "valid",
                "canonical_transcript_sha256": hashlib.sha256(
                    text.encode()
                ).hexdigest(),
            }
        ],
    )
    _write_csv(
        output / "reported_date_rows.csv",
        DATE_ROW_FIELDS,
        [_date_row("AAA", "2012Q4", "2013-02-01", "2012-12-31")],
    )
    (output / "validation_summary.json").write_text(
        json.dumps({"attempts": 1}), encoding="utf-8"
    )
    return output


def test_finalize_records_absent_optional_manifests(tmp_path) -> None:
    import json

    from build_validated_earnings_calls_v1 import finalize

    output = _finalize_fixture(tmp_path)
    summary = finalize(output, tmp_path / "final", tmp_path / "report")
    assert summary["row_count"] == 1
    manifests = summary["source_manifest_sha256"]
    assert manifests["targeted_date_request_manifest.csv"] == "absent"
    assert manifests["payload_deletion_manifest.csv"] == "absent"
    manifest_path = (
        tmp_path / "final"
        / "earnings_call_transcripts_validated_2010_2019_v1.manifest.json"
    )
    assert json.loads(manifest_path.read_text())["sha256"] == summary["sha256"]


def test_finalize_fails_before_writing_when_validation_summary_is_missing(
    tmp_path,
) -> None:
    import pytest

    from build_validated_earnings_calls_v1 import finalize

    output = _finalize_fixture(tmp_path)
    (output / "validation_summary.json").unlink()
    final_dir = tmp_path / "final"
    with pytest.raises(FileNotFoundError):
        finalize(output, final_dir, tmp_path / "report")
    assert not (
        final_dir / "earnings_call_transcripts_validated_2010_2019_v1.csv"
    ).exists()
