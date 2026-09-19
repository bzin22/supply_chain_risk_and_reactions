# No-transcript retry protocol amendment

Date: 2026-09-18

At the study owner's direction, Alpha Vantage responses classified as
`no_transcript` are terminal provider-unavailability outcomes after the first
request. They are not automatically retried in a later collection session.

Existing raw responses and append-only request-manifest records are unchanged.
Rows previously labeled `retry_in_later_session` are treated as terminal by the
collector when it reconstructs state for any resumed run. Transport errors,
HTTP failures, and explicit provider rate-limit/information responses remain
eligible for bounded retries. Deterministic `Invalid API call` responses are
terminal and are not retried.
