"""Audited missing-pair collection and fiscal-release-date preparation."""

from __future__ import annotations
import argparse
import calendar
import hashlib
import json
import os
import re
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
import requests
from .inventory import ART, FINAL, OUT, read, request_queue, validate_payload, security_history
from analysis.primary_event_study import core
from analysis.primary_event_study.run import apply_date_policy, price_path

PLACEHOLDERS = (
    "transcript has been redacted",
    "content unavailable",
    "access denied",
    "copyright infringement",
    "this transcript is not available",
)
TRUNCATION = ("[truncated]", "transcript truncated", "content cut off")


def now():
    return datetime.now(timezone.utc).isoformat()


def append_record(path, row):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")
        f.flush()
        os.fsync(f.fileno())


def records():
    paths = [core.ROOT / "artifacts/hardware_portfolio_2010_2019_v1/api_requests.jsonl", ART / "api_requests.jsonl"]
    support = ART / 'supporting_cache_inventory.json'
    return (json.loads(support.read_text()) if support.exists() else []) + [json.loads(x) for p in paths if p.exists() for x in p.read_text().splitlines()]


class Client:
    def __init__(self):
        self.key = os.environ.get("ALPHAVANTAGE_API_KEY")
        if not self.key:
            raise RuntimeError("ALPHAVANTAGE_API_KEY unavailable")
        self.last = 0.0
        self.session = requests.Session()

    def fetch(self, params):
        previous = [r for r in records() if r["params"] == params]
        for r in reversed(previous):
            bounded_failure = (r["status"] == "technical_failure" and r.get("attempt") == 3
                               and ART in (core.ROOT / r["raw_path"]).parents)
            if r["status"] in ["ok", "no_transcript", "provider_unavailable"] or bounded_failure:
                p = core.ROOT / r["raw_path"]
                assert core.sha256(p) == r["raw_sha256"]
                wrapper = json.loads(p.read_text())
                return p, wrapper.get("payload", wrapper), r["status"]
        for attempt in range(1, 4):
            time.sleep(max(0, 1.1 - (time.monotonic() - self.last)))
            self.last = time.monotonic()
            stamp = now()
            payload = {}
            http = None
            try:
                res = self.session.get(
                    "https://www.alphavantage.co/query",
                    params={**params, "apikey": self.key},
                    timeout=60,
                )
                http = res.status_code
                try:
                    payload = res.json()
                except ValueError:
                    payload = {
                        "unparseable_body_sha256": hashlib.sha256(
                            res.content
                        ).hexdigest()
                    }
                status = classify(params, payload, http)
            except requests.RequestException as e:
                # Never serialize exceptions or URLs: requests exceptions can include keys.
                status = "technical_failure"
                payload = {"exception_type": type(e).__name__}
            label = "_".join(
                str(params.get(k, "")) for k in ["function", "symbol", "quarter"]
            )
            path = (
                ART / "raw" / f"{label}_{stamp.replace(':', '').replace('-', '')}.json"
            )
            wrapper = {
                "params": params,
                "requested_at_utc": stamp,
                "fetched_at_utc": now(),
                "http_status": http,
                "classification": status,
                "payload": payload,
            }
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x") as f:
                json.dump(wrapper, f)
            rec = {k: v for k, v in wrapper.items() if k != "payload"}
            rec.update(
                status=status,
                raw_path=core.relative(path),
                raw_sha256=core.sha256(path),
                attempt=attempt,
            )
            append_record(ART / "api_requests.jsonl", rec)
            print(
                params["function"],
                params["symbol"],
                params.get("quarter", ""),
                status,
                flush=True,
            )
            if status in ["provider_rate_limit", "entitlement_required"]:
                raise RuntimeError(f"{status}; response retained; new requests stopped")
            if status in ["ok", "no_transcript", "provider_unavailable"]:
                return path, payload, status
            if attempt < 3:
                time.sleep(2**attempt)
        return path, payload, status


def classify(params, payload, http):
    if http != 200 or not isinstance(payload, dict):
        return "technical_failure"
    msg = " ".join(
        str(payload.get(k, "")) for k in ["Note", "Information", "Error Message"]
    ).lower()
    if any(
        s in msg
        for s in [
            "rate limit",
            "requests per minute",
            "requests per day",
            "call frequency",
        ]
    ):
        return "provider_rate_limit"
    if "premium" in msg or "subscription" in msg:
        return "entitlement_required"
    if msg.strip():
        return "technical_failure"
    function = params["function"]
    if function == "EARNINGS_CALL_TRANSCRIPT":
        if (
            payload.get("symbol") != params["symbol"]
            or payload.get("quarter") != params["quarter"]
        ):
            return "technical_failure"
        return "ok" if payload.get("transcript") else "no_transcript"
    if function == "EARNINGS":
        return (
            "ok"
            if payload.get("symbol") == params["symbol"]
            and payload.get("quarterlyEarnings")
            else "provider_unavailable"
        )
    if function == "TIME_SERIES_DAILY_ADJUSTED":
        return (
            "ok"
            if payload.get("Meta Data", {}).get("2. Symbol") == params["symbol"]
            and payload.get("Time Series (Daily)")
            else "provider_unavailable"
        )
    raise ValueError(function)


def subtract_months(value, months):
    ordinal = value.year * 12 + value.month - 1 - months
    year, month0 = divmod(ordinal, 12)
    month = month0 + 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def map_fiscal_rows(payload):
    """Same fiscal mapping as ae9526a build_validated_earnings_calls_v1.py."""
    annual = sorted(
        {
            date.fromisoformat(r["fiscalDateEnding"])
            for r in payload.get("annualEarnings", [])
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(r.get("fiscalDateEnding", "")))
        }
    )
    result = []
    for row in payload.get("quarterlyEarnings", []):
        try:
            end = date.fromisoformat(row["fiscalDateEnding"])
            reported = date.fromisoformat(row["reportedDate"])
        except (ValueError, KeyError, TypeError):
            continue
        matches = []
        for a in annual:
            for q, months in [(4, 0), (3, 3), (2, 6), (1, 9)]:
                distance = abs((end - subtract_months(a, months)).days)
                if distance <= 35:
                    matches.append((distance, a, q))
        if matches:
            distance, a, q = min(matches)
            result.append(
                {
                    "quarter_label": f"{a.year}Q{q}",
                    "fiscal_date_ending": end.isoformat(),
                    "reported_date": reported.isoformat(),
                    "report_time": row.get("reportTime", ""),
                    "fiscal_mapping_distance_days": distance,
                    "fiscal_year_end": a.isoformat(),
                }
            )
    return result


def earnings_source(symbol, client=None):
    candidates = [core.ARCHIVE / "alpha_vantage_earnings_raw" / f"{symbol}.json"]
    candidates += [
        core.ROOT / r["raw_path"]
        for r in records()
        if r["params"] == {"function": "EARNINGS", "symbol": symbol}
        and r["status"] == "ok"
    ]
    for path in candidates:
        if path.exists():
            d = json.loads(path.read_text())
            p = d.get("payload", d)
            if p.get("symbol") == symbol and p.get("quarterlyEarnings"):
                return path, p
    if client:
        path, p, status = client.fetch({"function": "EARNINGS", "symbol": symbol})
        if status == "ok":
            return path, p
    return None, None


def review_pairs():
    pairs = read(ART / "pair_manifest.csv")
    companies = {r["portfolio_cik"]: r for r in read(ART / "company_manifest.csv")}
    terminal = defaultdict(list)
    for r in read(
        core.ROOT / "data/validated_earnings_calls/v1/terminal_validation.csv"
    ):
        terminal[(r["cik"], r["quarter_label"])].append(r)
    local = defaultdict(list)
    for r in read(ART / "local_cache_validation.csv"):
        local[(r["portfolio_cik"], r["quarter_label"])].append(r)
    reviewed = []
    for r in pairs:
        c = companies[r["portfolio_cik"]]
        q = r["quarter_label"]
        prev = terminal[(r["historical_cik"], q)]
        if r["decision"] == "valid_missing_request":
            if prev and all(x["validation_status"] == "no_transcript" for x in prev):
                r.update(
                    decision="unavailable_transcript",
                    reason="prior frozen validation established no transcript; preserve finding regardless older retry-state label",
                )
            elif any(
                x["status"] == "no_transcript" for x in local[(r["portfolio_cik"], q)]
            ):
                r.update(
                    decision="unavailable_transcript",
                    reason="local identity-matched payload has empty transcript and no provider error",
                )
        # Screen pre-listing fiscal periods using actual archived EARNINGS dates.
        # Only affects uncovered pairs, never discards the requested company.
        if not r["call_id"] and c["provider_history_start"] >= "2010-01-01":
            path, p = earnings_source(c["ticker"])
            match = [x for x in map_fiscal_rows(p or {}) if x["quarter_label"] == q]
            if match:
                ends = {x["fiscal_date_ending"] for x in match}
                if len(ends) == 1:
                    r["listing_period_fiscal_end"] = next(iter(ends))
                    r["listing_start"] = c["provider_history_start"]
                    r["listing_date_evidence"] = c["history_evidence_file"]
                    r["fiscal_calendar_evidence"] = core.relative(path)
                    if r["listing_period_fiscal_end"] < r["listing_start"]:
                        r.update(
                            decision="not_applicable",
                            reason="fiscal period ended before initial public listing",
                        )
            elif q.startswith("2010"):
                r.update(
                    decision="unresolved_identity",
                    reason="2010 IPO: missing historical fiscal period end; held for listing-period review",
                )
        r["request_symbols"] = c.get("study_provider_ticker") or r["ticker"]
        reviewed.append(r)
    core.write_csv(ART / "pair_manifest_reviewed.csv", reviewed)
    core.write_csv(ART / "missing_pair_allowlist_reviewed.csv", request_queue(reviewed))
    print("Reviewed pairs", dict(Counter(r["decision"] for r in reviewed)), flush=True)
    return reviewed


def content_validation(path, company, quarter):
    raw, status = validate_payload(
        path, company["aliases"].split(";"), quarter, {company["historical_cik"]}
    )
    if status != "valid":
        return None, status
    wrapper = json.loads(Path(path).read_text())
    payload = wrapper.get("payload", wrapper)
    plain = "\n\n".join(
        str(s.get("content", "")) for s in payload.get("transcript", [])
    )
    speakers = {
        str(s.get("speaker", "")).strip()
        for s in payload.get("transcript", [])
        if s.get("speaker")
    }
    if any(p in plain.lower() for p in PLACEHOLDERS):
        return None, "invalid_content_placeholder"
    if (
        any(p in plain.lower() for p in TRUNCATION)
        or len(re.findall(r"[a-z0-9]+", plain.lower())) < 150
        or len(speakers) < 2
    ):
        return None, "quarantine_incomplete_content"
    years = {int(y) for y in re.findall(r"\b20\d{2}\b", plain[:5000])}
    if years and all(abs(y - int(quarter[:4])) > 1 for y in years):
        return None, "quarantine_year_mismatch"
    hist = security_history()
    links = [
        r
        for r in hist
        if r["cik"] == company["historical_cik"]
        and r["ticker"] == raw["provider_symbol"]
    ]
    if not links:
        links = [
            r
            for r in hist
            if r["cik"] == company["historical_cik"]
            and r["ticker"] == company["ticker"]
        ]
    row = {k: v for k, v in raw.items() if k != "text"}
    row.update(
        call_id=f"CIK{company['historical_cik']}|{raw['provider_symbol']}|{quarter}",
        cik=company["historical_cik"],
        portfolio_cik=company["portfolio_cik"],
        company_id="CIK" + company["historical_cik"],
        company_name=company["company_name"],
        current_ticker=company["ticker"],
        historical_ticker=raw["provider_symbol"],
        quarter_label=quarter,
        security_id=links[0]["security_id"] if links else "",
        validation_status="valid",
        validation_reason="payload identity, historical issuer link, content/placeholder/truncation/year checks",
        transcript_origin="downloaded"
        if ART in Path(path).parents
        else "validated_local_cache",
        transcript_source_path=raw["raw_path"],
    )
    return row, "valid"


def collect(limit=None):
    pairs = read(ART / "pair_manifest_reviewed.csv")
    companies = {r["portfolio_cik"]: r for r in read(ART / "company_manifest.csv")}
    queue = request_queue(pairs)
    client = Client()
    out = []
    # Successfully requested pairs are resumed directly from hashed raw responses.
    if limit is not None:
        # Bounded pilot: one pair per issuer before additional quarters.
        groups = defaultdict(list)
        for r in queue:
            groups[r["ticker"]].append(r)
        ordered = sorted(groups, key=lambda x: (x != "GRMN", x))
        queue = [
            groups[t][i]
            for i in range(max(map(len, groups.values()), default=0))
            for t in ordered
            if i < len(groups[t])
        ][:limit]
    if limit is None:
        assert (OUT / "pilot/INSPECTED.md").is_file(), (
            "Inspected scoring/CAR/collection pilot required"
        )
    for pair in queue:
        path, p, status = client.fetch(
            {
                "function": "EARNINGS_CALL_TRANSCRIPT",
                "symbol": pair.get("request_symbols") or pair["ticker"],
                "quarter": pair["quarter_label"],
            }
        )
        row, validation = (
            content_validation(
                path, companies[pair["portfolio_cik"]], pair["quarter_label"]
            )
            if status == "ok"
            else (None, status)
        )
        out.append(
            {
                **pair,
                "collection_status": status,
                "validation_status": validation,
                "new_call_id": row["call_id"] if row else "",
                "new_raw_path": core.relative(path),
                "new_raw_sha256": core.sha256(path),
            }
        )
    core.write_csv(
        ART / ("collection_pilot.csv" if limit is not None else "collection_full.csv"),
        out,
    )
    return out


def prepare(download_support=False, pilot=False):
    companies = {r["portfolio_cik"]: r for r in read(ART / "company_manifest.csv")}
    alias_plan = (
        read(ART / "alias_missing_pairs.csv")
        if (ART / "alias_missing_pairs.csv").exists()
        else []
    )
    alias_evidence = {}
    for p in alias_plan:
        c = companies[p["portfolio_cik"]]
        if p["provider_alias"] not in c["aliases"].split(";"):
            c["aliases"] += ";" + p["provider_alias"]
        alias_evidence[(p["provider_alias"], p["quarter_label"])] = p[
            "identity_evidence_url"
        ]
    original = read(FINAL / "transcript_references.csv")
    rows = []
    validation = []
    for r in original:
        if r["transcript_origin"] == "frozen_v1":
            rows.append(r)
            continue
        v, status = content_validation(
            core.ROOT / r["raw_path"], companies[r["portfolio_cik"]], r["quarter_label"]
        )
        validation.append(
            {"call_id": r["call_id"], "status": status, "raw_path": r["raw_path"]}
        )
        if v:
            rows.append(v)
    have = {(r["portfolio_cik"], r["quarter_label"]) for r in rows}
    symbol_company = {
        symbol: r for r in companies.values() for symbol in r["aliases"].split(";")
    }
    for req in records():
        if (
            req["params"]["function"] != "EARNINGS_CALL_TRANSCRIPT"
            or req["status"] != "ok"
        ):
            continue
        c = symbol_company.get(req["params"]["symbol"])
        if c is None:
            continue
        q = req["params"]["quarter"]
        if (c["portfolio_cik"], q) in have:
            continue
        r, status = content_validation(core.ROOT / req["raw_path"], c, q)
        validation.append(
            {
                "call_id": r["call_id"] if r else "",
                "status": status,
                "raw_path": req["raw_path"],
            }
        )
        if r:
            if req["params"]["symbol"] != c["ticker"]:
                r["alias_identity_evidence"] = alias_evidence.get(
                    (req["params"]["symbol"], q), c.get("identity_evidence", "")
                )
                assert r["alias_identity_evidence"], "Unreviewed provider alias"
                r["price_ticker_override"] = c["ticker"] if not c.get("study_provider_ticker") else ""
            rows.append(r)
            have.add((c["portfolio_cik"], q))
    client = Client() if download_support else None
    from .sic import history as build_history, assign as assign_historical_sic

    history = build_history()
    date_cache = {}
    date_audit = []
    prior_dates = defaultdict(list)
    for name in [
        "reported_date_rows",
        "targeted_reported_date_rows",
        "yfinance_reported_date_rows",
        "history_web_reported_date_rows",
    ]:
        path = core.ROOT / f"data/validated_earnings_calls/v1/{name}.csv"
        for r in read(path):
            prior_dates[(r["historical_ticker"], r["quarter_label"])].append((path, r))
    for r in rows:
        if r["transcript_origin"] != "frozen_v1":
            c = companies[r["portfolio_cik"]]
            if r["historical_ticker"] != c["ticker"] and not c.get("study_provider_ticker"):
                r["alias_identity_evidence"] = c.get("additional_alias_evidence") or c["identity_evidence"]
                r["price_ticker_override"] = c["ticker"]
            sym = r.get("price_ticker_override") or r["historical_ticker"]
            q = r["quarter_label"]
            c = companies[r["portfolio_cik"]]
            choices = prior_dates[(sym, q)]
            if not choices:
                if sym not in date_cache:
                    date_cache[sym] = earnings_source(
                        sym,
                        client
                        if not pilot or sym in ["GRMN", "MRVL", "AMD", "FORM", "IIVI", "HUBB", "NANO", "ONTO", "ADTN"]
                        else None,
                    )
                path, p = date_cache[sym]
                if p:
                    choices = [
                        (path, x) for x in map_fiscal_rows(p) if x["quarter_label"] == q
                    ]
            r.update(
                earnings_call_date="",
                date_fiscal_date_ending="",
                confirmed_call_date="",
                call_date_confirmation_status="no_independent_live_call_evidence",
                date_source_agreement="not_compared",
            )
            unique = {(x["fiscal_date_ending"], x["reported_date"]) for _, x in choices}
            if len(unique) == 1:
                path, d = choices[0]
                r.update(
                    earnings_call_date=d["reported_date"],
                    date_fiscal_date_ending=d["fiscal_date_ending"],
                    date_source_url=d.get(
                        "source_url",
                        "https://www.alphavantage.co/documentation/#earnings",
                    ),
                    date_match_method=d.get(
                        "match_method",
                        "alpha_vantage_fiscalDateEnding_plus_annual_fiscal_year_end",
                    ),
                    date_response_sha256=d.get("response_sha256", core.sha256(path)),
                    date_evidence_path=core.relative(path),
                    date_evidence_sha256=core.sha256(path),
                    date_report_time=d.get("report_time", ""),
                    date_status="reported_date_mapped",
                )
            else:
                r["date_status"] = (
                    "conflicting_release_date_candidates"
                    if choices
                    else "missing_release_date"
                )
            apply_date_policy(r, "release")
            # Override frozen-only source assumption in legacy helper for new transcripts.
            r["call_date_source_path"] = r.get("date_evidence_path", "")
            r["call_date_source_sha256"] = r.get("date_evidence_sha256", "")
            r["event_date_assumption"] = (
                "earnings-release reportedDate; no after-hours shift; independent live-call date remains separate"
            )
        r.update(assign_historical_sic(r, history))
        date_audit.append(
            {
                k: v
                for k, v in r.items()
                if k
                in [
                    "call_id",
                    "cik",
                    "quarter_label",
                    "earnings_call_date",
                    "confirmed_call_date",
                    "call_date_confirmation_status",
                ]
                or k.startswith(("date_", "sic_", "event_date", "call_date_source"))
            }
        )
        # New/previous missing adjusted prices are fetched only when no valid cache exists.
        if download_support and (not pilot or r["transcript_origin"] == "downloaded"):
            sym = r.get("price_ticker_override") or r["historical_ticker"]
            path, _ = price_path(sym)
            good = False
            if path.exists():
                d = json.loads(path.read_text())
                p = d.get("payload", d)
                good = (
                    bool(p.get("Time Series (Daily)"))
                    and p.get("Meta Data", {}).get("2. Symbol") == sym
                )
            if not good and not any(
                x["params"].get("function") == "TIME_SERIES_DAILY_ADJUSTED"
                and x["params"].get("symbol") == sym
                for x in records()
            ):
                client.fetch(
                    {
                        "function": "TIME_SERIES_DAILY_ADJUSTED",
                        "symbol": sym,
                        "outputsize": "full",
                    }
                )
    core.write_csv(
        FINAL / ("prepared_pilot_calls.csv" if pilot else "prepared_calls.csv"), rows
    )
    core.write_csv(
        ART
        / (
            "new_content_validation_pilot.csv"
            if pilot
            else "new_content_validation.csv"
        ),
        validation,
    )
    core.write_csv(
        ART / ("date_sic_audit_pilot.csv" if pilot else "date_sic_audit.csv"),
        date_audit,
    )
    print(
        "Prepared",
        len(rows),
        "calls",
        dict(Counter(x["transcript_origin"] for x in rows)),
        flush=True,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("stage", choices=["review", "collect", "prepare"])
    p.add_argument("--limit", type=int)
    p.add_argument("--download-support", action="store_true")
    p.add_argument("--pilot", action="store_true")
    a = p.parse_args()
    if a.stage == "review":
        review_pairs()
    elif a.stage == "collect":
        collect(a.limit)
    else:
        prepare(a.download_support, a.pilot)
