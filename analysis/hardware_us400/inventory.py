"""Offline issuer-quarter reconciliation. No network calls or source writes."""

from __future__ import annotations
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from analysis.primary_event_study import core
from analysis.primary_event_study.run import metadata
from analysis.primary_event_study.prepare import CACHE

UNIVERSE = (
    core.ROOT
    / "data/hardware_portfolio/us_400_v2/hardware_portfolio_public_2010.csv"
)
VERSION = "hardware_portfolio_us400_2010_2019_v1"
ART = core.ROOT / "artifacts" / VERSION
FINAL = core.ROOT / "data/final" / VERSION
OUT = core.ROOT / "outputs" / VERSION
MRVL_URL = (
    "https://www.sec.gov/Archives/edgar/data/1058057/000119312521122807/d156000d8k.htm"
)
EXTRA_ALIASES = {
    "WWD": (["WGOV"], "https://www.sec.gov/Archives/edgar/data/108312/000129993311000298/exhibit3.htm"),
    "ALNT": (
        ["AMOT"],
        "https://www.sec.gov/Archives/edgar/data/46129/000155837024002487/alnt-20231231x10k.htm",
    ),
    "KRMD": (
        ["REPR"],
        "https://investors.korumedical.com/news-events/press-releases/detail/46/rms-medical-products-announces-rebranding-to-koru-medical-systems",
    ),
    "GNSS": (
        ["LRAD"],
        "https://www.sec.gov/Archives/edgar/data/924383/000143774919020490/lrad20191023_8k.htm",
    ),
    "GEOS": (
        ["OYOG"],
        "https://www.sec.gov/Archives/edgar/data/1001115/000118143112052254/rrd357056_38534.htm",
    ),
    "INSG": (
        ["NVTL"],
        "https://www.globenewswire.com/news-release/2014/10/09/671933/33045/en/Novatel-Wireless-Announces-Ticker-Symbol-Change-to-MIFI.html",
    ),
}


def read(path):
    with Path(path).open() as f:
        return list(csv.DictReader(f))


def source_path(path):
    path = Path(path).resolve()
    return str(path.relative_to(core.ROOT)) if path.is_relative_to(core.ROOT) else str(path)


def security_history():
    hist = read(CACHE / "ticker_history.csv")
    # Current Coherent is the continuing II-VI issuer, not the acquired legacy
    # Coherent equity. Its pre-2022 ticker is isolated from legacy COHR prices.
    c = next(r for r in read(UNIVERSE) if r["ticker"] == "COHR")
    assert c["historical_cik"] == "0000820318" and c["study_provider_ticker"] == "IIVI"
    hist.append({"ticker": "IIVI", "cik": "0000820318", "security_id": "HW400-IIVI-820318",
                 "mapping_source": c["identity_evidence"], "valid_from": "2010-01-01", "valid_to": "2019-12-31"})
    return hist


def payload_text(payload):
    parts = []
    for s in payload.get("transcript", []):
        content = str(s.get("content") or "").strip()
        speaker = str(s.get("speaker") or "Unknown").strip()
        title = str(s.get("title") or "").strip()
        if content:
            parts.append(f"[{speaker}{' | ' + title if title else ''}] {content}")
    return "\n\n".join(parts)


def validate_payload(path, symbols, quarter, ciks, frozen=False):
    d = json.loads(Path(path).read_text())
    p = d.get("payload", d)
    if not isinstance(p, dict):
        return None, "invalid_payload"
    if any(k in p for k in ["Note", "Information", "Error Message"]):
        return None, "provider_or_technical_error"
    if p.get("symbol") not in symbols or p.get("quarter") != quarter:
        return None, "payload_identity_mismatch"
    if d.get("cik") and d["cik"].zfill(10) not in ciks:
        return None, "wrapper_issuer_mismatch"
    text = payload_text(p)
    if not text:
        return None, "no_transcript"
    tokens = core.scorer.tokenize(text)
    if not frozen and (len(tokens) < 100 or len(p.get("transcript", [])) < 2):
        return None, "content_requires_review"
    return {
        "text": text,
        "raw_sha256": core.sha256(path),
        "canonical_transcript_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "segment_count": len(p["transcript"]),
        "token_count": len(tokens),
        "provider_symbol": p["symbol"],
        "raw_path": source_path(path),
        "payload_symbol_match": True,
        "payload_quarter_match": True,
    }, "valid"


def request_queue(pairs, completed=()):
    """Allow only explicit missing decisions; completed/reused pairs cannot enter."""
    done = set(completed)
    result = [
        r
        for r in pairs
        if r["decision"] == "valid_missing_request"
        and (r["portfolio_cik"], r["quarter_label"]) not in done
    ]
    assert not any(
        r.get("call_id") or str(r.get("reuse_approved", "")).lower() == "true"
        for r in result
    )
    assert len({(r["portfolio_cik"], r["quarter_label"]) for r in result}) == len(
        result
    )
    return result


def build():
    csv.field_size_limit(100_000_000)
    for p in [ART, FINAL, OUT]:
        if p.exists():
            raise FileExistsError(f"Refusing to overwrite {p}; use a new version")
    assert core.sha256(core.SOURCE) == core.SOURCE_HASH
    u = read(UNIVERSE)
    assert len(u) == 400 and len({r["source_cik"] for r in u}) == 400
    hist = security_history()
    m = metadata("release")
    by_cik = defaultdict(list)
    for r in m:
        by_cik[r["cik"]].append(r)
    all_links = defaultdict(set)
    for r in hist:
        all_links[r["ticker"]].add(r["cik"])
    identities = []
    symbol_to_ciks = defaultdict(set)
    for c in u:
        cik = c["source_cik"]
        issuer = c.get("historical_cik") or ("0001058057" if c["ticker"] == "MRVL" else cik)
        aliases = (
            {c["ticker"]}
            | set(filter(None, c.get("historical_aliases", "").split(";")))
            | {x["ticker"] for x in hist if x["cik"] == issuer}
            | set(EXTRA_ALIASES.get(c["ticker"], ([], ""))[0])
        )
        if c.get("study_provider_ticker"):
            aliases = {c["study_provider_ticker"]}
        for s in aliases:
            symbol_to_ciks[s].add(issuer)
        identities.append(
            {
                **c,
                "portfolio_cik": cik,
                "historical_cik": issuer,
                "aliases": ";".join(sorted(aliases)),
                "identity_evidence": c.get("identity_evidence") or (MRVL_URL
                if c["ticker"] == "MRVL"
                else core.relative(CACHE / "ticker_history.csv")),
                "additional_alias_evidence": EXTRA_ALIASES.get(c["ticker"], ([], ""))[
                    1
                ],
                "identity_note": "2021 one-for-one successor; use predecessor CIK for 2010-2019"
                if c["ticker"] == "MRVL"
                else c.get("identity_note", "frozen issuer/security mapping; current universe membership preserved"),
            }
        )
    # Bounded inventory of known collections and all JSON raw files in repository,
    # archive and the adjacent historical data-pipeline project. Only candidate
    # issuer/ticker + study-quarter files are parsed, never arbitrary JSON content.
    index = defaultdict(list)
    scanned = Counter()
    roots = [
        core.ROOT / p
        for p in [
            "artifacts/full_transcript_collection_v20260917/raw",
            "artifacts/transcript_pilot_20260916/raw",
            "artifacts/representative_coverage_pilot_v20260916/raw",
            "artifacts/earnings_call_responses",
            ".archive/duplicate_attempts_20260918/artifacts/full_transcript_collection_v20260917/raw",
            ".archive/post_2019_removed_20260916/artifacts/earnings_call_responses",
            "artifacts/hardware_portfolio_2010_2019_v1/raw",
        ]
    ]
    roots += [core.ROOT, core.ROOT.parent / "data_analysis_pipeline"]
    seen_paths = set()
    symbols = set(symbol_to_ciks)
    for root in roots:
        if not root.exists():
            continue
        print("Inventory", root, flush=True)
        for path in root.rglob("*.json"):
            if path in seen_paths:
                continue
            seen_paths.add(path)
            scanned[str(root)] += 1
            match = re.fullmatch(r"(.+)_(201\dQ[1-4])", path.stem)
            if match and match[1] in symbols:
                index[(match[1], match[2])].append(path)
            elif path.name.startswith("EARNINGS_CALL_TRANSCRIPT_"):
                wrapper = json.loads(path.read_text())
                params = wrapper.get("params", {})
                if params.get("symbol") in symbols and re.fullmatch(r"201\dQ[1-4]", params.get("quarter", "")):
                    index[(params["symbol"], params["quarter"])].append(path)
            else:
                # issuer/ticker/quarter/attempt.json layout
                if (
                    len(path.parts) >= 4
                    and re.fullmatch(r"201\dQ[1-4]", path.parent.name)
                    and path.parent.parent.name in symbols
                ):
                    index[(path.parent.parent.name, path.parent.name)].append(path)
    terminal = read(
        core.ROOT / "data/validated_earnings_calls/v1/terminal_validation.csv"
    )
    terminals = defaultdict(list)
    for r in terminal:
        terminals[(r["cik"], r["quarter_label"])].append(r)
    selected = []
    pairs = []
    cache_audit = []
    dups = []
    protected = {}

    def protect(p):
        p = Path(p)
        if p.is_file() and str(p) not in protected:
            protected[str(p)] = core.sha256(p)

    for p in [
        core.SOURCE,
        UNIVERSE,
        *core.DICTIONARIES.values(),
        *CACHE.glob("*.csv"),
        core.DATE_MAP,
        core.ROOT / "data/validated_earnings_calls/v1/terminal_validation.csv",
        core.ROOT / "data/call_dates/call_dates_v20260916/source_evidence.csv",
    ]:
        protect(p)
    frozen_by_id = {}
    # Verify canonical text without copying the frozen corpus.
    wanted = {r["historical_cik"] for r in identities}
    with core.SOURCE.open() as f:
        for ordinal, r in enumerate(csv.DictReader(f), 1):
            if r["cik"] not in wanted:
                continue
            assert (
                hashlib.sha256(r["transcript_text"].encode()).hexdigest()
                == r["canonical_transcript_sha256"]
            )
            frozen_by_id[r["call_id"]] = ordinal
    for c in identities:
        cik = c["portfolio_cik"]
        issuer = c["historical_cik"]
        aliases = c["aliases"].split(";")
        frozen = {r["quarter_label"]: r for r in by_cik[issuer]}
        links = [r for r in hist if r["cik"] == issuer and r["ticker"] == (c.get("study_provider_ticker") or c["ticker"])]
        for year in range(2010, 2020):
            for q in range(1, 5):
                quarter = f"{year}Q{q}"
                pair = {
                    "portfolio_cik": cik,
                    "historical_cik": issuer,
                    "ticker": c["ticker"],
                    "quarter_label": quarter,
                    "aliases_searched": c["aliases"],
                    "decision": "",
                    "reason": "",
                    "call_id": "",
                    "reuse_approved": False,
                }
                if quarter in frozen:
                    r = dict(frozen[quarter])
                    p = core.ROOT / r["raw_path"]
                    assert p.is_file()
                    raw, status = validate_payload(
                        p, aliases, quarter, {issuer}, frozen=True
                    )
                    assert status == "valid" and raw["raw_sha256"] == r["raw_sha256"]
                    # Frozen text is authoritative and not normalized/rebuilt.
                    r.update(
                        portfolio_cik=cik,
                        current_ticker=c["ticker"],
                        transcript_origin="frozen_v1",
                        transcript_source_path=core.relative(core.SOURCE),
                        source_row_ordinal=frozen_by_id[r["call_id"]],
                    )
                    pair.update(
                        decision="reuse_frozen",
                        reason="validated issuer-quarter and frozen text/raw hashes",
                        call_id=r["call_id"],
                        reuse_approved=True,
                    )
                    protect(p)
                    selected.append(r)
                else:
                    candidates = []
                    for sym in aliases:
                        for p in sorted(index[(sym, quarter)]):
                            raw, status = validate_payload(
                                p, aliases, quarter, {issuer}
                            )
                            cache_audit.append(
                                {
                                    "portfolio_cik": cik,
                                    "quarter_label": quarter,
                                    "path": str(p),
                                    "status": status,
                                }
                            )
                            if status == "valid":
                                if (
                                    len(
                                        all_links.get(sym, {issuer})
                                        | symbol_to_ciks[sym]
                                    )
                                    > 1
                                ):
                                    cache_audit[-1]["status"] = (
                                        "ticker_reuse_requires_review"
                                    )
                                    continue
                                candidates.append(raw)
                    previous = terminals[(issuer, quarter)]
                    invalid = [
                        x
                        for x in previous
                        if x["validation_status"] in ["invalid_content", "quarantine"]
                    ]
                    valid = [
                        x
                        for x in candidates
                        if not any(x["raw_sha256"] == z["raw_sha256"] for z in invalid)
                    ]
                    if valid:
                        distinct = {x["canonical_transcript_sha256"] for x in valid}
                        if len(distinct) > 1:
                            pair.update(
                                decision="unresolved_identity",
                                reason="conflicting cached transcript contents",
                            )
                        else:
                            chosen = valid[0]
                            p = core.ROOT / chosen["raw_path"]
                            protect(p)
                            r = {k: v for k, v in chosen.items() if k != "text"}
                            r.update(
                                call_id=f"CIK{issuer}|{chosen['provider_symbol']}|{quarter}",
                                company_id=f"CIK{issuer}",
                                cik=issuer,
                                portfolio_cik=cik,
                                company_name=c["company_name"],
                                current_ticker=c["ticker"],
                                historical_ticker=chosen["provider_symbol"],
                                security_id=links[0]["security_id"] if links else "",
                                quarter_label=quarter,
                                validation_status="valid",
                                validation_reason="cached payload symbol/quarter and evidenced issuer link; substantive segmented call",
                                transcript_origin="validated_local_cache",
                                transcript_source_path=chosen["raw_path"],
                            )
                            selected.append(r)
                            pair.update(
                                decision="reuse_local_cache",
                                reason="validated payload and historical issuer link",
                                call_id=r["call_id"],
                                reuse_approved=True,
                            )
                            for d in valid[1:]:
                                dups.append(
                                    {
                                        "call_id": r["call_id"],
                                        "duplicate_path": d["raw_path"],
                                        "retained_path": r["raw_path"],
                                    }
                                )
                    elif invalid:
                        pair.update(
                            decision="unavailable_transcript",
                            reason="prior content quarantine retained",
                        )
                    elif previous and all(
                        x["validation_status"] == "no_transcript"
                        and x["terminal_status"] == "terminal_provider_unavailability"
                        for x in previous
                    ):
                        pair.update(
                            decision="unavailable_transcript",
                            reason="prior later-session retries adjudicated provider unavailability; raw was deleted under prior frozen manifest",
                        )
                    else:
                        pair.update(
                            decision="valid_missing_request",
                            reason="no usable transcript in reconciled local caches; technical failures remain retryable",
                        )
                pairs.append(pair)
    for p in [ART, FINAL, OUT]:
        p.mkdir(parents=True)
    core.write_csv(ART / "company_manifest.csv", identities)
    core.write_csv(ART / "security_history.csv", hist)
    core.write_csv(FINAL / "transcript_references.csv", selected)
    core.write_csv(ART / "pair_manifest.csv", pairs)
    core.write_csv(ART / "missing_pair_allowlist.csv", request_queue(pairs))
    core.write_csv(ART / "local_cache_validation.csv", cache_audit)
    core.write_csv(ART / "duplicate_decisions.csv", dups)
    core.write_json(ART / "preserved_inputs.json", protected)
    summary = {
        "selected_firms": len(u),
        "selected_pairs": len(pairs),
        "decisions": dict(Counter(x["decision"] for x in pairs)),
        "reusable_calls": len(selected),
        "reusable_firms": len({x["portfolio_cik"] for x in selected}),
        "download_requests": 0,
        "raw_json_files_inventoried": dict(scanned),
        "local_inventory_roots": [str(x) for x in roots],
        "universe_selection": "current US operational headquarters and surviving/current listings, public by 2010; not point-in-time census",
        "listing_period_review": "required before any request; missing allowlist provisional until supporting date/listing checks",
    }
    core.write_json(ART / "inventory_summary.json", summary)
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    build()
