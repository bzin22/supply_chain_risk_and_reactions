"""Build the versioned 2010Q1-2019Q4 US operating-company universe.

The source capture is intentionally separate from the deterministic build.
Raw provider responses are immutable and checksummed.  This script never
collects earnings-call transcripts.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Iterable

import requests

from study_period import STUDY_END, STUDY_START, study_quarters, validate_study_quarter

ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = ROOT / "artifacts" / "historical_universe_sources_v20260916"
OUTPUT_ROOT = ROOT / "data" / "universe" / "us_operating_companies_v20260916"
LISTING_URL = "https://www.alphavantage.co/query"
DISCOVERY_PATH = ROOT / "artifacts" / "sec_10k_supply_chain" / "discovered_filings.json"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SEC_COMPANY_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions"

EXCLUDED_NAME_PATTERNS = (
    ("warrant", re.compile(r"\b(warrant|warrants|wt|wts)\b", re.I)),
    ("right", re.compile(r"\b(right|rights|rt|rts)\b", re.I)),
    ("unit", re.compile(r"\b(unit|units)\b", re.I)),
    ("preferred", re.compile(r"\b(preferred|preference|depositary shares?)\b", re.I)),
    ("fund", re.compile(r"\b(etf|fund|shares index)\b", re.I)),
    ("acquisition_vehicle", re.compile(r"\b(acquisition corp|blank check)\b", re.I)),
    ("when_issued", re.compile(r"\bwhen issued\b", re.I)),
)

COMPANY_SUFFIXES = {
    "inc", "incorporated", "corp", "corporation", "co", "company", "ltd",
    "limited", "plc", "llc", "lp", "holdings", "holding", "group", "the",
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def quarter_end(label: str) -> date:
    year = int(label[:4])
    quarter = int(label[-1])
    month_day = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}[quarter]
    return date(year, *month_day)


def quarter_start(label: str) -> date:
    year = int(label[:4])
    quarter = int(label[-1])
    return date(year, 1 + (quarter - 1) * 3, 1)


def parse_date(value: str | None) -> date | None:
    value = (value or "").strip()
    if not value or value.lower() in {"null", "none", "n/a"}:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def normalize_name(value: str, *, relaxed: bool = False) -> str:
    tokens = re.findall(r"[a-z0-9]+", value.lower().replace("&", " and "))
    if relaxed:
        tokens = [token for token in tokens if token not in COMPANY_SUFFIXES]
    return " ".join(tokens)


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def valid_listing_csv(payload: bytes) -> tuple[bool, str, int]:
    text = payload.decode("utf-8-sig", errors="replace")
    rows = list(csv.DictReader(text.splitlines()))
    required = {"symbol", "name", "exchange", "assetType", "ipoDate", "delistingDate", "status"}
    if not rows:
        return False, "empty or provider-information response", 0
    if required - set(rows[0]):
        return False, f"missing columns {sorted(required - set(rows[0]))}", len(rows)
    return True, "validated listing-status CSV", len(rows)


def capture_listings(args: argparse.Namespace) -> None:
    api_key = os.environ.get("ALPHAVANTAGE_API_KEY")
    if not api_key:
        raise RuntimeError("ALPHAVANTAGE_API_KEY is not present in this process")
    raw_root = args.source_root / "listing_status"
    manifest_path = args.source_root / "listing_status_manifest.csv"
    manifest_rows: list[dict[str, object]] = []
    if manifest_path.exists():
        with manifest_path.open(newline="", encoding="utf-8") as handle:
            manifest_rows = list(csv.DictReader(handle))
    recorded = {(row["quarter_label"], row["state"]): row for row in manifest_rows}
    interval = 60.0 / args.requests_per_minute
    with requests.Session() as session:
        for label in study_quarters():
            validate_study_quarter(label)
            snapshot_date = quarter_end(label).isoformat()
            for state in ("active", "delisted"):
                destination = raw_root / f"{label}_{snapshot_date}_{state}.csv"
                prior = recorded.get((label, state))
                if destination.exists() and prior:
                    payload = destination.read_bytes()
                    if sha256_bytes(payload) != prior["sha256"]:
                        raise RuntimeError(f"immutable source checksum mismatch: {destination}")
                    continue
                if destination.exists():
                    raise RuntimeError(f"unmanifested source exists; refusing overwrite: {destination}")
                reason = ""
                for attempt in range(1, args.max_attempts + 1):
                    started = time.monotonic()
                    requested_at = utc_now()
                    response = session.get(
                        LISTING_URL,
                        params={
                            "function": "LISTING_STATUS",
                            "date": snapshot_date,
                            "state": state,
                            "apikey": api_key,
                        },
                        timeout=args.timeout,
                    )
                    payload = response.content
                    valid, reason, row_count = valid_listing_csv(payload)
                    if response.status_code == 200 and valid:
                        atomic_write_bytes(destination, payload)
                        row = {
                            "quarter_label": label,
                            "snapshot_date": snapshot_date,
                            "state": state,
                            "attempt": attempt,
                            "requested_at_utc": requested_at,
                            "completed_at_utc": utc_now(),
                            "http_status": response.status_code,
                            "raw_path": destination.relative_to(ROOT).as_posix(),
                            "size_bytes": len(payload),
                            "sha256": sha256_bytes(payload),
                            "row_count": row_count,
                            "classification": "valid_listing_snapshot",
                            "validation_reason": reason,
                        }
                        manifest_rows.append(row)
                        recorded[(label, state)] = row
                        write_csv(manifest_path, list(row), manifest_rows)
                        print(f"captured {label} {state}: {row_count:,} rows", flush=True)
                        break
                    if attempt == args.max_attempts:
                        raise RuntimeError(
                            f"failed {label} {state} after {attempt} attempts: HTTP "
                            f"{response.status_code}; {reason}"
                        )
                    time.sleep(min(args.backoff_base ** attempt, 60.0))
                    elapsed = time.monotonic() - started
                    if elapsed < interval:
                        time.sleep(interval - elapsed)
                elapsed = time.monotonic() - started
                if elapsed < interval:
                    time.sleep(interval - elapsed)


def capture_sec_current_tickers(args: argparse.Namespace) -> None:
    user_agent = os.environ.get("SEC_USER_AGENT")
    if not user_agent:
        raise RuntimeError("SEC_USER_AGENT is not present in this process")
    destination = args.source_root / "sec" / "company_tickers_exchange.json"
    manifest_path = args.source_root / "sec_source_manifest.csv"
    if destination.exists() and manifest_path.exists():
        return
    response = requests.get(
        SEC_TICKERS_URL,
        headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
        timeout=args.timeout,
    )
    response.raise_for_status()
    parsed = response.json()
    if not isinstance(parsed, dict) or "data" not in parsed or "fields" not in parsed:
        raise RuntimeError("unexpected SEC ticker mapping structure")
    payload = response.content
    atomic_write_bytes(destination, payload)
    row = {
        "source": "SEC company_tickers_exchange",
        "retrieved_at_utc": utc_now(),
        "url": SEC_TICKERS_URL,
        "raw_path": destination.relative_to(ROOT).as_posix(),
        "size_bytes": len(payload),
        "sha256": sha256_bytes(payload),
        "classification": "current_only_identity_crosswalk",
    }
    write_csv(manifest_path, list(row), [row])


def resolved_ciks(output_root: Path) -> list[str]:
    path = output_root / "securities.csv"
    if not path.exists():
        raise RuntimeError("run the preliminary build before SEC metadata capture")
    with path.open(newline="", encoding="utf-8") as handle:
        return sorted({row["cik"] for row in csv.DictReader(handle) if row["cik"]})


def parse_sec_company_xml(payload: bytes) -> dict[str, str]:
    root = ET.fromstring(payload)
    values: dict[str, str] = {}
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag in {"assigned-sic", "assigned-sic-desc", "cik", "conformed-name", "fiscal-year-end", "state-location"}:
            values.setdefault(tag, (element.text or "").strip())
    return values


class RequestStartLimiter:
    """Thread-safe leaky-bucket limiter for SEC request starts."""

    def __init__(self, requests_per_second: float) -> None:
        self.interval = (1.0 / requests_per_second) + 0.001
        self.lock = threading.Lock()
        self.next_start = 0.0

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            start = max(now, self.next_start)
            self.next_start = start + self.interval
            delay = start - now
            if delay:
                time.sleep(delay)


def capture_sec_company_metadata(args: argparse.Namespace) -> None:
    user_agent = os.environ.get("SEC_USER_AGENT")
    if not user_agent:
        raise RuntimeError("SEC_USER_AGENT is not present in this process")
    ciks = resolved_ciks(args.output_root)
    raw_root = args.source_root / "sec" / "company_metadata"
    manifest_path = args.source_root / "sec_company_metadata_manifest.csv"
    manifest_rows: list[dict[str, object]] = []
    if manifest_path.exists():
        with manifest_path.open(newline="", encoding="utf-8") as handle:
            manifest_rows = list(csv.DictReader(handle))
    recorded = {row["cik"]: row for row in manifest_rows}
    headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}
    pending: list[str] = []
    for cik in ciks:
        suffix = ".json" if args.sec_metadata_endpoint == "submissions" else ".xml"
        destination = raw_root / f"CIK{cik}{suffix}"
        prior = recorded.get(cik)
        if prior:
            prior_path = ROOT / str(prior["raw_path"])
            payload = prior_path.read_bytes()
            if sha256_bytes(payload) != prior["sha256"]:
                raise RuntimeError(f"immutable SEC checksum mismatch: {prior_path}")
            continue
        if destination.exists():
            raise RuntimeError(f"unmanifested SEC source exists; refusing overwrite: {destination}")
        pending.append(cik)

    limiter = RequestStartLimiter(args.sec_requests_per_second)

    def fetch(cik: str) -> tuple[str, bytes, dict[str, str], int, str, str, int, str]:
        reason = ""
        for attempt in range(1, args.max_attempts + 1):
            limiter.wait()
            requested_at = utc_now()
            try:
                if args.sec_metadata_endpoint == "submissions":
                    url = f"{SEC_SUBMISSIONS_URL}/CIK{cik}.json"
                    response = requests.get(url, headers=headers, timeout=args.timeout)
                else:
                    url = SEC_COMPANY_URL
                    response = requests.get(
                        url,
                        params={"action": "getcompany", "CIK": cik, "output": "atom", "count": 1},
                        headers=headers,
                        timeout=args.timeout,
                    )
                payload = response.content
                if response.status_code == 200 and args.sec_metadata_endpoint == "submissions":
                    value = response.json()
                    metadata = {
                        "cik": str(value.get("cik", "")),
                        "assigned-sic": str(value.get("sic", "")),
                        "assigned-sic-desc": str(value.get("sicDescription", "")),
                        "conformed-name": str(value.get("name", "")),
                    }
                else:
                    metadata = parse_sec_company_xml(payload) if response.status_code == 200 else {}
                valid = metadata.get("cik", "").zfill(10) == cik
                reason = "validated SEC company metadata" if valid else "missing or mismatched SEC CIK"
            except (requests.RequestException, ET.ParseError, ValueError) as exc:
                response = None
                payload = b""
                metadata = {}
                valid = False
                reason = type(exc).__name__
            if valid:
                return cik, payload, metadata, response.status_code, requested_at, reason, attempt, url
            if attempt == args.max_attempts:
                raise RuntimeError(f"failed SEC company metadata CIK {cik}: {reason}")
            time.sleep(min(args.backoff_base ** attempt, 60.0))
        raise RuntimeError(f"unreachable SEC fetch state for CIK {cik}")

    completed = len(ciks) - len(pending)
    with ThreadPoolExecutor(max_workers=args.sec_workers) as executor:
        futures = {executor.submit(fetch, cik): cik for cik in pending}
        for future in as_completed(futures):
            cik, payload, metadata, http_status, requested_at, reason, attempt, url = future.result()
            suffix = ".json" if args.sec_metadata_endpoint == "submissions" else ".xml"
            destination = raw_root / f"CIK{cik}{suffix}"
            atomic_write_bytes(destination, payload)
            row = {
                "cik": cik, "attempt": attempt, "requested_at_utc": requested_at,
                "completed_at_utc": utc_now(), "http_status": http_status,
                "source_url": url, "source_format": args.sec_metadata_endpoint,
                "raw_path": destination.relative_to(ROOT).as_posix(),
                "size_bytes": len(payload), "sha256": sha256_bytes(payload),
                "sic": metadata.get("assigned-sic", ""),
                "sic_description": metadata.get("assigned-sic-desc", ""),
                "conformed_name": metadata.get("conformed-name", ""),
                "classification": "valid_sec_company_metadata",
                "validation_reason": reason,
            }
            manifest_rows.append(row)
            recorded[cik] = row
            write_csv(manifest_path, list(row), manifest_rows)
            completed += 1
            if completed % 100 == 0 or completed == len(ciks):
                print(f"captured SEC metadata {completed:,}/{len(ciks):,}", flush=True)


def load_sec_company_metadata(source_root: Path) -> dict[str, dict[str, str]]:
    path = source_root / "sec_company_metadata_manifest.csv"
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        raw_path = ROOT / row["raw_path"]
        payload = raw_path.read_bytes()
        if sha256_bytes(payload) != row["sha256"]:
            raise RuntimeError(f"SEC company metadata checksum mismatch: {raw_path}")
        text = payload.decode("utf-8", errors="replace")
        state_of_incorporation = ""
        business_state_or_country = ""
        forms: set[str] = set()
        if raw_path.suffix.lower() == ".json":
            value = json.loads(text)
            state_of_incorporation = str(value.get("stateOfIncorporation") or "").upper()
            business_state_or_country = str(
                value.get("addresses", {}).get("business", {}).get("stateOrCountry") or ""
            ).upper()
            forms = {str(item).upper() for item in value.get("filings", {}).get("recent", {}).get("form", [])}
        else:
            match = re.search(r"<state-of-incorporation>(.*?)</state-of-incorporation>", text, re.I | re.S)
            state_of_incorporation = html.unescape(match.group(1)).strip().upper() if match else ""
            business = re.search(r'<address type="business">(.*?)</address>', text, re.I | re.S)
            if business:
                match = re.search(r"<state>(.*?)</state>", business.group(1), re.I | re.S)
                business_state_or_country = html.unescape(match.group(1)).strip().upper() if match else ""
            forms = {item.upper() for item in re.findall(r"<filing-type>(.*?)</filing-type>", text, re.I | re.S)}
        us_codes = {
            "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
            "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
            "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
            "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
            "WI", "WY", "DC", "PR", "VI", "GU", "AS", "MP", "US",
        }
        domicile_code = state_of_incorporation or business_state_or_country
        if domicile_code in us_codes:
            domicile_status = "us"
        elif domicile_code:
            domicile_status = "foreign"
        elif forms & {"20-F", "20-F/A", "40-F", "40-F/A"} and not forms & {"10-K", "10-K/A", "10-KT"}:
            domicile_status = "foreign"
        else:
            domicile_status = "unknown"
        result[row["cik"]] = {
            **row,
            "state_of_incorporation": state_of_incorporation,
            "business_state_or_country": business_state_or_country,
            "issuer_domicile_status": domicile_status,
        }
    return result


def parse_historical_sic(payload: bytes) -> tuple[str, str]:
    text = html.unescape(payload.decode("utf-8", errors="replace"))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    match = re.search(r"STANDARD INDUSTRIAL CLASSIFICATION:\s*(.*?)\s*\[(\d{3,4})\]", text, re.I)
    if not match:
        return "", ""
    return match.group(2).zfill(4), match.group(1).strip()


def capture_historical_sic(args: argparse.Namespace) -> None:
    user_agent = os.environ.get("SEC_USER_AGENT")
    if not user_agent:
        raise RuntimeError("SEC_USER_AGENT is not present in this process")
    ciks = set(resolved_ciks(args.output_root))
    discovery = json.loads(DISCOVERY_PATH.read_text())
    latest: dict[str, dict[str, str]] = {}
    for row in discovery:
        cik = str(row["cik"]).zfill(10)
        filed = row.get("filed", "")
        if cik in ciks and "2009-01-01" <= filed <= "2019-12-31":
            if cik not in latest or filed > latest[cik]["filed"]:
                latest[cik] = row
    manifest_path = args.source_root / "sec_historical_sic_manifest.csv"
    manifest_rows: list[dict[str, object]] = []
    if manifest_path.exists():
        with manifest_path.open(newline="", encoding="utf-8") as handle:
            manifest_rows = list(csv.DictReader(handle))
    recorded = {row["cik"]: row for row in manifest_rows}
    limiter = RequestStartLimiter(args.sec_requests_per_second)
    headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}
    tasks = []
    for cik, filing in sorted(latest.items()):
        prior = recorded.get(cik)
        if prior:
            raw_path = ROOT / str(prior["raw_path"])
            if sha256_bytes(raw_path.read_bytes()) != prior["sha256"]:
                raise RuntimeError(f"historical SIC checksum mismatch: {raw_path}")
            continue
        accession = Path(filing["filename"]).name.removesuffix(".txt")
        accession_plain = accession.replace("-", "")
        cik_plain = str(int(cik))
        url = (
            f"https://www.sec.gov/Archives/edgar/data/{cik_plain}/{accession_plain}/"
            f"{accession}-index-headers.html"
        )
        destination = args.source_root / "sec" / "historical_sic" / cik / f"{accession}.html"
        tasks.append((cik, filing, accession, url, destination))

    def fetch(task: tuple[str, dict[str, str], str, str, Path]) -> dict[str, object]:
        cik, filing, accession, url, destination = task
        reason = ""
        for attempt in range(1, args.max_attempts + 1):
            limiter.wait()
            requested_at = utc_now()
            try:
                response = requests.get(url, headers=headers, timeout=args.timeout)
                payload = response.content
                sic, description = parse_historical_sic(payload) if response.status_code == 200 else ("", "")
                valid = bool(sic) and b"Request Rate Threshold Exceeded" not in payload
                reason = "validated filing-header SIC" if valid else f"HTTP {response.status_code} or missing SIC"
            except requests.RequestException as exc:
                response = None
                payload = b""
                sic = description = ""
                valid = False
                reason = type(exc).__name__
            if valid:
                atomic_write_bytes(destination, payload)
                return {
                    "cik": cik, "accession_number": accession, "filing_date": filing["filed"],
                    "source_url": url, "attempt": attempt, "requested_at_utc": requested_at,
                    "completed_at_utc": utc_now(),
                    "http_status": response.status_code if response is not None else "",
                    "raw_path": destination.relative_to(ROOT).as_posix(),
                    "size_bytes": len(payload), "sha256": sha256_bytes(payload),
                    "sic": sic, "sic_description": description,
                    "classification": "valid_historical_10k_header_sic",
                    "validation_reason": reason,
                }
            if attempt == args.max_attempts:
                raise RuntimeError(f"failed historical SIC for CIK {cik}: {reason}")
            time.sleep(min(args.backoff_base ** attempt, 60))
        raise RuntimeError("unreachable historical SIC fetch state")

    completed = len(latest) - len(tasks)
    with ThreadPoolExecutor(max_workers=args.sec_workers) as executor:
        futures = {executor.submit(fetch, task): task for task in tasks}
        for future in as_completed(futures):
            row = future.result()
            manifest_rows.append(row)
            write_csv(manifest_path, list(row), manifest_rows)
            completed += 1
            if completed % 100 == 0 or completed == len(latest):
                print(f"captured historical SIC {completed:,}/{len(latest):,}", flush=True)
    (args.source_root / "sec_historical_sic_complete.json").write_text(
        json.dumps({"completed_at_utc": utc_now(), "resolved_ciks_with_10k": len(latest)}) + "\n"
    )
    unavailable = [{"cik": cik, "reason": "no exact 10-K filing in 2009-2019 discovery"} for cik in sorted(ciks - set(latest))]
    if unavailable:
        write_csv(args.output_root / "historical_sic_unavailable.csv", list(unavailable[0]), unavailable)


def load_historical_sic(source_root: Path) -> dict[str, dict[str, str]]:
    path = source_root / "sec_historical_sic_manifest.csv"
    if not path.exists() or not (source_root / "sec_historical_sic_complete.json").exists():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        raw_path = ROOT / row["raw_path"]
        if sha256_bytes(raw_path.read_bytes()) != row["sha256"]:
            raise RuntimeError(f"historical SIC checksum mismatch: {raw_path}")
    return {row["cik"]: row for row in rows}


def sic_division(sic: str) -> str:
    if not sic or not sic.isdigit():
        return "unknown"
    value = int(sic)
    boundaries = (
        (100, "agriculture"), (1500, "mining"), (1800, "construction"),
        (4000, "manufacturing"), (5000, "transportation_communications_utilities"),
        (5200, "wholesale_trade"), (6000, "retail_trade"),
        (7000, "finance_insurance_real_estate"), (9000, "services"),
        (10000, "public_administration"),
    )
    for upper, label in boundaries:
        if value < upper:
            return label
    return "unknown"


def sec_operating_exclusion(sic: str, description: str) -> str:
    if sic in {"6722", "6726", "6770"}:
        return f"non_operating_sic_{sic}"
    if re.search(r"unit investment trust|investment offices|blank checks", description, re.I):
        return "non_operating_sic_description"
    return ""


@dataclass(frozen=True)
class Security:
    security_id: str
    symbol: str
    name: str
    exchange: str
    asset_type: str
    ipo_date: str
    delisting_date: str
    provider_status: str
    first_seen_quarter: str
    last_seen_quarter: str


def exclusion_reason(row: dict[str, str]) -> str:
    if row["assetType"].strip().lower() != "stock":
        return f"asset_type_{row['assetType'].strip().lower() or 'missing'}"
    for label, pattern in EXCLUDED_NAME_PATTERNS:
        if pattern.search(row["name"]):
            return f"name_pattern_{label}"
    symbol = row["symbol"].upper()
    # Alpha Vantage uses separator-plus-P forms for listed preferred classes
    # (for example CHK-P-D, SCE--P-D, BAC-PL, and TY-P).
    if re.search(r"(?:--?P(?:-?[A-Z])?|[.-]PR(?:[.-]?[A-Z])?)$", symbol):
        return "symbol_suffix_preferred_share"
    if re.search(r"[-.](W|WS|WT|R|RT|U)$", symbol):
        return "symbol_suffix_non_common_security"
    return ""


def load_listing_observations(source_root: Path) -> list[dict[str, str]]:
    manifest_path = source_root / "listing_status_manifest.csv"
    with manifest_path.open(newline="", encoding="utf-8") as handle:
        manifest = list(csv.DictReader(handle))
    expected = {(q, state) for q in study_quarters() for state in ("active", "delisted")}
    observed = {(row["quarter_label"], row["state"]) for row in manifest}
    if observed != expected:
        raise RuntimeError(f"listing snapshot set incomplete: missing {sorted(expected - observed)[:5]}")
    rows: list[dict[str, str]] = []
    for item in manifest:
        path = ROOT / item["raw_path"]
        payload = path.read_bytes()
        if sha256_bytes(payload) != item["sha256"]:
            raise RuntimeError(f"source checksum mismatch: {path}")
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                row["snapshot_quarter"] = item["quarter_label"]
                row["snapshot_state"] = item["state"]
                rows.append(row)
    return rows


def load_sec_name_maps() -> tuple[dict[str, set[str]], dict[str, set[str]], dict[tuple[str, str], set[str]]]:
    discovery = json.loads(DISCOVERY_PATH.read_text())
    exact: dict[str, set[str]] = defaultdict(set)
    relaxed: dict[str, set[str]] = defaultdict(set)
    for row in discovery:
        filed = row.get("filed", "")
        if not ("2009-01-01" <= filed <= "2019-12-31"):
            continue
        cik = str(row["cik"]).zfill(10)
        exact[normalize_name(row["company"])].add(cik)
        relaxed[normalize_name(row["company"], relaxed=True)].add(cik)
    ticker_map: dict[tuple[str, str], set[str]] = defaultdict(set)
    sec_path = SOURCE_ROOT / "sec" / "company_tickers_exchange.json"
    if sec_path.exists():
        obj = json.loads(sec_path.read_text())
        fields = obj["fields"]
        for values in obj["data"]:
            row = dict(zip(fields, values, strict=False))
            cik = str(row.get("cik", "")).zfill(10)
            ticker = str(row.get("ticker", "")).upper()
            exchange = str(row.get("exchange", "")).upper()
            if cik.strip("0") and ticker:
                ticker_map[(ticker, exchange)].add(cik)
    return exact, relaxed, ticker_map


def resolve_cik(
    security: Security,
    exact: dict[str, set[str]],
    relaxed: dict[str, set[str]],
    ticker_map: dict[tuple[str, str], set[str]],
) -> tuple[str, str, str]:
    candidates = exact.get(normalize_name(security.name), set())
    if len(candidates) == 1:
        return next(iter(candidates)), "sec_10k_exact_name", "unique exact issuer-name match"
    candidates = relaxed.get(normalize_name(security.name, relaxed=True), set())
    if len(candidates) == 1:
        return next(iter(candidates)), "sec_10k_relaxed_name", "unique normalized issuer-name match"
    candidates = ticker_map.get((security.symbol, security.exchange.upper()), set())
    if len(candidates) == 1:
        return next(iter(candidates)), "sec_current_ticker_exchange", "unique current ticker/exchange crosswalk"
    if candidates:
        return "", "unresolved", f"ambiguous CIK candidates: {','.join(sorted(candidates))}"
    return "", "unresolved", "no unique public CIK match"


def build_universe(args: argparse.Namespace) -> None:
    observations = load_listing_observations(args.source_root)
    exact, relaxed, ticker_map = load_sec_name_maps()
    sec_metadata = load_sec_company_metadata(args.source_root)
    historical_sic = load_historical_sic(args.source_root)
    grouped: dict[tuple[str, str, str, str, str], list[dict[str, str]]] = defaultdict(list)
    excluded_rows: list[dict[str, object]] = []
    for row in observations:
        reason = exclusion_reason(row)
        if reason:
            excluded_rows.append({
                "symbol": row["symbol"], "name": row["name"], "exchange": row["exchange"],
                "asset_type": row["assetType"], "ipo_date": row["ipoDate"],
                "delisting_date": row["delistingDate"], "snapshot_quarter": row["snapshot_quarter"],
                "exclusion_reason": reason,
            })
            continue
        key = (
            row["symbol"].upper(), row["name"].strip(), row["exchange"].upper(),
            row["ipoDate"].strip(), row["delistingDate"].strip(),
        )
        grouped[key].append(row)

    securities: list[dict[str, object]] = []
    companies: dict[str, dict[str, object]] = {}
    ticker_history: list[dict[str, object]] = []
    eligible: list[dict[str, object]] = []
    identity_review: list[dict[str, object]] = []
    for key, rows in sorted(grouped.items()):
        symbol, name, exchange, ipo_value, delist_value = key
        seen_quarters = sorted({row["snapshot_quarter"] for row in rows})
        active_quarters = {
            row["snapshot_quarter"] for row in rows if row["snapshot_state"] == "active"
        }
        security_id = "AVS" + hashlib.sha256("|".join(key).encode()).hexdigest()[:16].upper()
        security = Security(
            security_id, symbol, name, exchange, rows[0]["assetType"], ipo_value,
            delist_value, rows[-1]["status"], seen_quarters[0], seen_quarters[-1],
        )
        cik, match_method, match_reason = resolve_cik(security, exact, relaxed, ticker_map)
        metadata = sec_metadata.get(cik, {}) if cik else {}
        historical = historical_sic.get(cik, {}) if cik else {}
        sic = historical.get("sic", "") or metadata.get("sic", "")
        sic_description = historical.get("sic_description", "") or metadata.get("sic_description", "")
        sic_source = "study_period_10k_header" if historical.get("sic") else ("current_sec_company_metadata" if sic else "unresolved")
        operating_exclusion = sec_operating_exclusion(sic, sic_description)
        if not operating_exclusion and metadata.get("issuer_domicile_status") == "foreign":
            operating_exclusion = f"sec_foreign_issuer_{metadata.get('state_of_incorporation') or metadata.get('business_state_or_country') or 'form'}"
        if not operating_exclusion and metadata.get("issuer_domicile_status") != "us":
            operating_exclusion = "sec_us_domicile_unverified"
        company_id = f"CIK{cik}" if cik else "AVC" + hashlib.sha256(normalize_name(name, relaxed=True).encode()).hexdigest()[:16].upper()
        securities.append({
            **security.__dict__, "company_id": company_id, "cik": cik,
            "cik_match_method": match_method, "cik_match_reason": match_reason,
            "sic": sic, "sic_description": sic_description,
            "sic_division": sic_division(sic), "sic_source": sic_source,
            "issuer_domicile_status": metadata.get("issuer_domicile_status", "unknown"),
            "state_of_incorporation": metadata.get("state_of_incorporation", ""),
            "security_class": "excluded_non_operating" if operating_exclusion else "common_stock_candidate",
        })
        companies.setdefault(company_id, {
            "company_id": company_id, "cik": cik, "canonical_name": name,
            "identity_status": "resolved_cik" if cik else "unresolved_public_identifier",
            "identity_source": match_method, "sic": sic,
            "sic_description": sic_description, "sic_division": sic_division(sic),
            "sic_source": sic_source,
            "issuer_domicile_status": metadata.get("issuer_domicile_status", "unknown"),
            "state_of_incorporation": metadata.get("state_of_incorporation", ""),
        })
        ticker_history.append({
            "company_id": company_id, "security_id": security_id, "cik": cik,
            "ticker": symbol, "exchange": exchange,
            "effective_start": ipo_value if parse_date(ipo_value) else quarter_start(seen_quarters[0]).isoformat(),
            "effective_end": delist_value if parse_date(delist_value) else quarter_end(seen_quarters[-1]).isoformat(),
            "start_source": "Alpha Vantage ipoDate" if parse_date(ipo_value) else "first observed quarter",
            "end_source": "Alpha Vantage delistingDate" if parse_date(delist_value) else "last observed quarter",
        })
        if not cik:
            identity_review.append({
                "company_id": company_id, "security_id": security_id, "symbol": symbol,
                "name": name, "exchange": exchange, "review_reason": match_reason,
            })
        if operating_exclusion:
            excluded_rows.append({
                "symbol": symbol, "name": name, "exchange": exchange,
                "asset_type": security.asset_type, "ipo_date": ipo_value,
                "delisting_date": delist_value, "snapshot_quarter": "all",
                "exclusion_reason": operating_exclusion,
            })
            continue
        start = parse_date(ipo_value) or quarter_start(seen_quarters[0])
        end = parse_date(delist_value) or date(2019, 12, 31)
        for label in study_quarters():
            if start <= quarter_end(label) and end >= quarter_start(label):
                eligible.append({
                    "company_id": company_id, "security_id": security_id, "cik": cik,
                    "company_name": name, "provider_ticker": symbol, "exchange": exchange,
                    "sic": sic, "sic_division": sic_division(sic), "quarter_label": label,
                    "issuer_domicile_status": metadata.get("issuer_domicile_status", "unknown"),
                    "state_of_incorporation": metadata.get("state_of_incorporation", ""),
                    "eligibility_start": start.isoformat(), "eligibility_end": end.isoformat(),
                    "eligibility_source": "Alpha Vantage listing interval",
                    "identity_status": "resolved_cik" if cik else "unresolved_public_identifier",
                    "active_at_quarter_end": label in active_quarters,
                })

    # Preserve all eligible securities, then select one effective provider
    # ticker per issuer-quarter.  Active-at-quarter-end evidence outranks an
    # overlapping inactive class or stale ticker interval.
    eligible_security_quarters = [row for row in eligible if row["cik"]]
    unresolved_security_quarters = [row for row in eligible if not row["cik"]]
    by_firm_quarter: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in eligible_security_quarters:
        by_firm_quarter[(str(row["company_id"]), str(row["quarter_label"]))].append(row)
    exchange_priority = {"NYSE": 0, "NASDAQ": 1, "NYSE MKT": 2, "NYSE ARCA": 3, "BATS": 4}
    request_eligible: list[dict[str, object]] = []
    selection_rows: list[dict[str, object]] = []
    for key, candidates in sorted(by_firm_quarter.items()):
        ranked = sorted(
            candidates,
            key=lambda row: (
                not bool(row["active_at_quarter_end"]),
                exchange_priority.get(str(row["exchange"]), 99),
                any(mark in str(row["provider_ticker"]) for mark in "-.") ,
                len(str(row["provider_ticker"])),
                str(row["security_id"]),
            ),
        )
        chosen = dict(ranked[0])
        chosen["candidate_security_count"] = len(ranked)
        chosen["primary_selection_reason"] = (
            "only eligible resolved security" if len(ranked) == 1
            else "ranked by active quarter-end evidence, exchange, and plain common-stock symbol"
        )
        request_eligible.append(chosen)
        for rank, candidate in enumerate(ranked, start=1):
            selection_rows.append({
                "company_id": key[0], "quarter_label": key[1],
                "security_id": candidate["security_id"],
                "provider_ticker": candidate["provider_ticker"],
                "exchange": candidate["exchange"],
                "active_at_quarter_end": candidate["active_at_quarter_end"],
                "selection_rank": rank, "selected": rank == 1,
            })
    args.output_root.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_root / "companies.csv", list(next(iter(companies.values()))), companies.values())
    write_csv(args.output_root / "securities.csv", list(securities[0]), securities)
    write_csv(args.output_root / "ticker_history.csv", list(ticker_history[0]), ticker_history)
    write_csv(args.output_root / "eligible_security_quarters.csv", list(eligible_security_quarters[0]), eligible_security_quarters)
    write_csv(args.output_root / "eligible_firm_quarters.csv", list(request_eligible[0]), request_eligible)
    write_csv(args.output_root / "primary_security_selection.csv", list(selection_rows[0]), selection_rows)
    write_csv(args.output_root / "exclusions.csv", list(excluded_rows[0]), excluded_rows)
    write_csv(args.output_root / "identity_review.csv", list(identity_review[0]), identity_review)
    coverage = Counter((row["quarter_label"][:4], row["exchange"], row["sic_division"]) for row in request_eligible)
    coverage_rows = [
        {"year": year, "exchange": exchange, "sic_division": sic, "eligible_firm_quarters": count}
        for (year, exchange, sic), count in sorted(coverage.items())
    ]
    write_csv(args.output_root / "coverage_by_year_exchange_sic.csv", list(coverage_rows[0]), coverage_rows)
    for dimension, getter in (
        ("year", lambda row: str(row["quarter_label"])[:4]),
        ("exchange", lambda row: str(row["exchange"])),
        ("sic_division", lambda row: str(row["sic_division"])),
    ):
        grouped_rows: dict[str, list[dict[str, object]]] = defaultdict(list)
        for row in request_eligible:
            grouped_rows[getter(row)].append(row)
        table = [
            {
                dimension: value,
                "eligible_firm_quarters": len(rows),
                "unique_companies": len({str(row["company_id"]) for row in rows}),
            }
            for value, rows in sorted(grouped_rows.items())
        ]
        write_csv(args.output_root / f"coverage_by_{dimension}.csv", list(table[0]), table)
    source_manifest = []
    for source_manifest_path in (
        args.source_root / "listing_status_manifest.csv",
        args.source_root / "sec_source_manifest.csv",
        args.source_root / "sec_company_metadata_manifest.csv",
    ):
        if not source_manifest_path.exists():
            continue
        with source_manifest_path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                source_manifest.append({"manifest": source_manifest_path.name, **row})
    all_fields = sorted({key for row in source_manifest for key in row})
    write_csv(args.output_root / "source_manifest.csv", all_fields, source_manifest)
    summary = {
        "version": "v20260916",
        "study_period": f"{STUDY_START}-{STUDY_END}",
        "built_at_utc": utc_now(),
        "listing_observations": len(observations),
        "candidate_common_stock_securities": len(securities),
        "resolved_cik_securities": sum(bool(row["cik"]) for row in securities),
        "unresolved_identity_securities": len(identity_review),
        "excluded_listing_observations": len(excluded_rows),
        "eligible_resolved_firm_quarters": len(request_eligible),
        "eligible_resolved_security_quarters": len(eligible_security_quarters),
        "firm_quarters_with_multiple_security_candidates": sum(
            len(rows) > 1 for rows in by_firm_quarter.values()
        ),
        "eligible_unresolved_security_quarters": len(unresolved_security_quarters),
        "eligible_unresolved_firm_quarters": len({
            (str(row["company_id"]), str(row["quarter_label"]))
            for row in unresolved_security_quarters
        }),
        "limitations": [
            (
                "SIC uses the latest available 2009-2019 exact 10-K header; within-period SIC changes are not reconstructed."
                if historical_sic else
                "SIC uses complete current SEC issuer metadata; historical SIC changes are not reconstructed."
            ),
            "Current SEC ticker data is identity corroboration only, not historical membership evidence.",
            "SEC state-of-incorporation metadata must confirm US domicile; unverified domicile is excluded.",
            "Unresolved public identifiers are excluded from transcript request inputs.",
        ],
    }
    (args.output_root / "manifest.json").write_text(json.dumps(summary, indent=2) + "\n")
    (args.output_root / "SOURCES.md").write_text(
        "# Point-in-time universe sources\n\n"
        "Version: v20260916\n\n"
        "- Alpha Vantage `LISTING_STATUS`: immutable active and delisted snapshots at "
        "each of the 40 quarter ends from 2010Q1 through 2019Q4. Listing intervals "
        "and historical provider tickers come from these snapshots. "
        "https://www.alphavantage.co/documentation/\n"
        "- SEC exact Form 10-K discovery manifest: reused local quarterly-index discovery "
        "for issuer-name-to-CIK matching; no 10-K population redownload.\n"
        "- SEC company ticker/exchange JSON: current-only identity corroboration, never "
        "used as historical membership evidence. "
        "https://www.sec.gov/files/company_tickers_exchange.json\n"
        "- SEC submissions/company metadata: CIK, current name, former-name and SIC "
        "metadata, captured per resolved issuer. "
        "https://data.sec.gov/submissions/\n"
        + (
            "- SEC 10-K filing headers: latest exact 10-K header available from 2009-2019 "
            "for study-period SIC evidence.\n\n"
            if historical_sic else
            "- SIC limitation: the active build uses complete current SEC issuer metadata; "
            "the incomplete historical-header experiment is not an active input.\n\n"
        )
        + "## Inclusion and exclusion\n\n"
        "The request universe contains resolved SEC issuers with US-listed common-stock "
        "candidate securities whose listing interval overlaps the calendar quarter. ETFs, "
        "funds, warrants, rights, units, preferred shares, test/non-common issues, blank-check "
        "companies, and SEC investment-company SICs are excluded. Unresolved identities "
        "remain in `identity_review.csv` and are not transcript request inputs. Multiple "
        "security candidates are preserved, while `eligible_firm_quarters.csv` selects one "
        "effective provider ticker per issuer-quarter using quarter-end activity, exchange, "
        "and plain common-stock-symbol evidence.\n\n"
        "All raw sources are checksummed in `source_manifest.csv`.\n"
    )
    print(json.dumps(summary, indent=2), flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("capture", "sec-metadata", "historical-sic", "build", "all"))
    parser.add_argument("--source-root", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--requests-per-minute", type=float, default=30.0)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--max-attempts", type=int, default=5)
    parser.add_argument("--backoff-base", type=float, default=2.0)
    parser.add_argument("--sec-requests-per-second", type=float, default=8.0)
    parser.add_argument("--sec-workers", type=int, default=32)
    parser.add_argument("--sec-metadata-endpoint", choices=("submissions", "browse"), default="submissions")
    args = parser.parse_args()
    if not 0 < args.requests_per_minute <= 30:
        parser.error("--requests-per-minute must be in (0, 30]")
    if not 0 < args.sec_requests_per_second <= 9:
        parser.error("--sec-requests-per-second must be in (0, 9]")
    if not 1 <= args.sec_workers <= 64:
        parser.error("--sec-workers must be in [1, 64]")
    return args


def main() -> None:
    args = parse_args()
    if args.stage in {"capture", "all"}:
        capture_listings(args)
        capture_sec_current_tickers(args)
    if args.stage in {"sec-metadata", "all"}:
        capture_sec_company_metadata(args)
    if args.stage in {"historical-sic", "all"}:
        capture_historical_sic(args)
    if args.stage in {"build", "all"}:
        build_universe(args)


if __name__ == "__main__":
    main()
