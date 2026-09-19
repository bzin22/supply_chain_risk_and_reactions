# Review files

- `response_manifest.csv`: one row per requested ticker-quarter.
- `short_and_flagged_excerpts.csv`: bounded beginning and ending excerpts for short or integrity-flagged calls.
- `retry_provider_information.csv`: provider Information/Note responses.
- `retry_api_errors.csv`: API-error responses.
- `retry_unverifiable_no_transcript.csv`: optional rechecks for provider `no_transcript` results.
- `coverage_by_year.csv`, `coverage_by_ticker.csv`, `coverage_by_current_sector.csv`, `coverage_by_response_classification.csv`, and `coverage_by_period.csv`: coverage tables.
- `dictionary_replication_checklist.csv`: exact-replication requirements and current gaps.
- `audit_summary.json`: machine-readable headline checks and counts.
- `AUDIT_REPORT.md`: findings, definitions, and limitations.
- `audit_cached_responses.py`: reproducible read-only audit code. It writes only within this directory.
