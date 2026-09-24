"""Build an independent, auditable call-date mapping for valid transcripts.

No date is inferred from a quarter label, report period, or SEC filing date.
Those fields may only define a broad candidate-retrieval window.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

from collection.build_historical_universe import (
    RequestStartLimiter,
    atomic_write_bytes,
    normalize_name,
    quarter_end,
    quarter_start,
    sha256_bytes,
    utc_now,
    write_csv,
)
from collection.study_period import validate_study_quarter

ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = ROOT / "review" / "alpha_vantage_transcript_audit_20260916" / "response_manifest.csv"
PILOT_TERMINAL_PATH = ROOT / "review" / "representative_coverage_pilot_20260916" / "terminal_state_manifest.csv"
UNIVERSE_ROOT = ROOT / "data" / "universe" / "us_operating_companies_v20260916"
OUTPUT_ROOT = ROOT / "data" / "call_dates" / "call_dates_v20260916"
SOURCE_ROOT = ROOT / "artifacts" / "call_date_sources_v20260916"
SUBMISSIONS_URL = "https://data.sec.gov/submissions"

MAPPING_FIELDS = [
    "ticker", "quarter_label", "fiscal_quarter", "company_name", "company_id", "cik",
    "identity_status", "identity_reason", "transcript_source", "transcript_raw_path", "transcript_sha256",
    "transcript_explicit_call_date", "transcript_date_evidence_excerpt",
    "earnings_announcement_date", "earnings_call_date", "candidate_call_date",
    "call_date_source_type",
    "call_date_source_url", "call_date_source_raw_path", "call_date_source_sha256",
    "evidence_excerpt", "independent_source_count", "confidence", "mapping_status",
    "validation_reason",
]


def initialize_mapping(args: argparse.Namespace) -> None:
    with AUDIT_PATH.open(newline="", encoding="utf-8") as handle:
        audit_rows = [
            {**row, "transcript_source": "legacy_valid_corpus"}
            for row in csv.DictReader(handle)
            if 2010 <= int(row["year"]) <= 2019
            and row["response_classification"] == "valid full transcript"
        ]
    if PILOT_TERMINAL_PATH.exists():
        with PILOT_TERMINAL_PATH.open(newline="", encoding="utf-8") as handle:
            pilot_rows = [row for row in csv.DictReader(handle) if row["terminal_state"] == "valid"]
        existing = {(row["ticker"].upper(), row["quarter_label"]) for row in audit_rows}
        for row in pilot_rows:
            key = (row["provider_ticker"].upper(), row["quarter_label"])
            if key in existing:
                continue
            audit_rows.append({
                "ticker": row["provider_ticker"], "quarter_label": row["quarter_label"],
                "company_name": row["company_name"], "raw_file_path": row["raw_path"],
                "raw_file_sha256": row["raw_sha256"], "transcript_source": "representative_pilot",
                "preset_company_id": row["company_id"], "preset_cik": row["cik"],
            })
            existing.add(key)
    with (args.universe_root / "eligible_firm_quarters.csv").open(newline="", encoding="utf-8") as handle:
        universe = list(csv.DictReader(handle))
    with (args.universe_root / "companies.csv").open(newline="", encoding="utf-8") as handle:
        companies = list(csv.DictReader(handle))
    by_ticker_quarter: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    by_name: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in universe:
        by_ticker_quarter[(row["provider_ticker"].upper(), row["quarter_label"])].append(row)
    for row in companies:
        by_name[normalize_name(row["canonical_name"], relaxed=True)].append(row)

    mapping: list[dict[str, object]] = []
    identity_review: list[dict[str, object]] = []
    for row in audit_rows:
        ticker = row["ticker"].upper()
        quarter = validate_study_quarter(row["quarter_label"])
        matches = by_ticker_quarter.get((ticker, quarter), [])
        identity_status = ""
        identity_reason = ""
        company_id = cik = ""
        if row.get("preset_cik"):
            company_id, cik = row["preset_company_id"], row["preset_cik"]
            identity_status = "resolved_from_representative_universe"
            identity_reason = "pilot row carries the versioned point-in-time CIK"
        elif len(matches) == 1:
            match = matches[0]
            company_id, cik = match["company_id"], match["cik"]
            identity_status = "resolved_point_in_time_ticker"
            identity_reason = "unique eligible ticker and quarter match"
        elif len(matches) > 1:
            identity_status = "unresolved_ambiguous_ticker"
            identity_reason = f"{len(matches)} eligible issuer matches"
        else:
            names = by_name.get(normalize_name(row["company_name"], relaxed=True), [])
            if len(names) == 1 and names[0]["cik"]:
                company_id, cik = names[0]["company_id"], names[0]["cik"]
                identity_status = "resolved_unique_company_name"
                identity_reason = "ticker not effective in quarter; unique normalized company-name match"
            else:
                identity_status = "unresolved_no_point_in_time_identity"
                identity_reason = "no unique eligible ticker-quarter or company-name match"
        mapping_row = {
            "ticker": ticker, "quarter_label": quarter, "fiscal_quarter": quarter,
            "company_name": row["company_name"], "company_id": company_id, "cik": cik,
            "identity_status": identity_status, "identity_reason": identity_reason,
            "transcript_source": row["transcript_source"],
            "transcript_raw_path": row["raw_file_path"],
            "transcript_sha256": row["raw_file_sha256"],
            "transcript_explicit_call_date": "", "transcript_date_evidence_excerpt": "",
            "earnings_announcement_date": "", "earnings_call_date": "",
            "candidate_call_date": "",
            "call_date_source_type": "", "call_date_source_url": "",
            "call_date_source_raw_path": "", "call_date_source_sha256": "",
            "evidence_excerpt": "", "independent_source_count": 0,
            "confidence": "unresolved",
            "mapping_status": "pending_sec_evidence" if cik else "unresolved_identity",
            "validation_reason": "awaiting explicit independent call-date evidence" if cik else identity_reason,
        }
        mapping.append(mapping_row)
        if not cik:
            identity_review.append(mapping_row)
    mapping.sort(key=lambda row: (str(row["ticker"]), str(row["quarter_label"])))
    args.output_root.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_root / "call_date_mapping.csv", MAPPING_FIELDS, mapping)
    write_csv(args.output_root / "identity_review.csv", MAPPING_FIELDS, identity_review)
    manifest = {
        "version": "v20260916", "created_at_utc": utc_now(),
        "study_period": "2010Q1-2019Q4", "valid_transcript_rows": len(mapping),
        "resolved_identity_rows": sum(bool(row["cik"]) for row in mapping),
        "unresolved_identity_rows": len(identity_review),
        "assigned_call_dates": 0,
        "date_rule": "explicit independent source evidence only; no inference from quarter or filing date",
    }
    (args.output_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


def valid_submission(payload: bytes, cik: str) -> dict[str, Any]:
    value = json.loads(payload)
    returned = str(value.get("cik", "")).zfill(10)
    if returned != cik:
        raise ValueError(f"SEC submissions CIK mismatch {returned} != {cik}")
    if not isinstance(value.get("filings"), dict):
        raise ValueError("SEC submissions response lacks filings")
    return value


def fetch_many(
    tasks: list[tuple[str, str, Path, str]], *, user_agent: str, max_rps: float,
    workers: int, attempts: int, timeout: float,
) -> list[dict[str, object]]:
    limiter = RequestStartLimiter(max_rps)
    headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}

    def fetch(task: tuple[str, str, Path, str]) -> dict[str, object]:
        cik, url, destination, source_kind = task
        reason = ""
        for attempt in range(1, attempts + 1):
            limiter.wait()
            requested_at = utc_now()
            try:
                response = requests.get(url, headers=headers, timeout=timeout)
                payload = response.content
                if response.status_code != 200:
                    reason = f"HTTP {response.status_code}"
                else:
                    parsed = json.loads(payload)
                    if source_kind == "main_submissions":
                        valid_submission(payload, cik)
                    elif not isinstance(parsed, dict) or "accessionNumber" not in parsed:
                        raise ValueError("unexpected supplemental submissions structure")
                    atomic_write_bytes(destination, payload)
                    return {
                        "cik": cik, "source_kind": source_kind, "url": url,
                        "attempt": attempt, "requested_at_utc": requested_at,
                        "completed_at_utc": utc_now(), "http_status": response.status_code,
                        "raw_path": destination.relative_to(ROOT).as_posix(),
                        "size_bytes": len(payload), "sha256": sha256_bytes(payload),
                        "classification": "valid_sec_submissions_json",
                        "validation_reason": "validated JSON structure",
                    }
            except (requests.RequestException, json.JSONDecodeError, ValueError) as exc:
                reason = type(exc).__name__
            if attempt == attempts:
                raise RuntimeError(f"failed {source_kind} for CIK {cik}: {reason}")
            time.sleep(min(2**attempt, 60))
        raise RuntimeError("unreachable fetch state")

    results: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(fetch, task): task for task in tasks}
        for index, future in enumerate(as_completed(futures), start=1):
            results.append(future.result())
            if index % 50 == 0 or index == len(tasks):
                print(f"captured SEC submission sources {index:,}/{len(tasks):,}", flush=True)
    return results


def capture_submissions(args: argparse.Namespace) -> None:
    user_agent = os.environ.get("SEC_USER_AGENT")
    if not user_agent:
        raise RuntimeError("SEC_USER_AGENT is not present in this process")
    with (args.output_root / "call_date_mapping.csv").open(newline="", encoding="utf-8") as handle:
        mapping = list(csv.DictReader(handle))
    ciks = sorted({row["cik"] for row in mapping if row["cik"]})
    manifest_path = args.source_root / "source_manifest.csv"
    existing: list[dict[str, object]] = []
    if manifest_path.exists():
        with manifest_path.open(newline="", encoding="utf-8") as handle:
            existing = list(csv.DictReader(handle))
    recorded = {row["raw_path"]: row for row in existing}
    tasks: list[tuple[str, str, Path, str]] = []
    for cik in ciks:
        destination = args.source_root / "sec_submissions" / f"CIK{cik}.json"
        relative = destination.relative_to(ROOT).as_posix()
        if destination.exists() and relative in recorded:
            if sha256_bytes(destination.read_bytes()) != recorded[relative]["sha256"]:
                raise RuntimeError(f"immutable submissions checksum mismatch: {destination}")
            continue
        if destination.exists():
            raise RuntimeError(f"unmanifested submissions source exists: {destination}")
        tasks.append((cik, f"{SUBMISSIONS_URL}/CIK{cik}.json", destination, "main_submissions"))
    captured = fetch_many(
        tasks, user_agent=user_agent, max_rps=args.sec_requests_per_second,
        workers=args.sec_workers, attempts=args.max_attempts, timeout=args.timeout,
    ) if tasks else []
    existing.extend(captured)
    if captured:
        write_csv(manifest_path, list(existing[0]), existing)

    supplemental_tasks: list[tuple[str, str, Path, str]] = []
    for cik in ciks:
        main_path = args.source_root / "sec_submissions" / f"CIK{cik}.json"
        value = valid_submission(main_path.read_bytes(), cik)
        for item in value["filings"].get("files", []):
            filing_from = item.get("filingFrom", "")
            filing_to = item.get("filingTo", "")
            if filing_to < "2009-01-01" or filing_from > "2020-12-31":
                continue
            name = item["name"]
            destination = args.source_root / "sec_submissions" / "supplemental" / name
            relative = destination.relative_to(ROOT).as_posix()
            if destination.exists() and relative in recorded:
                continue
            supplemental_tasks.append((cik, f"{SUBMISSIONS_URL}/{name}", destination, "supplemental_submissions"))
    supplemental = fetch_many(
        supplemental_tasks, user_agent=user_agent, max_rps=args.sec_requests_per_second,
        workers=args.sec_workers, attempts=args.max_attempts, timeout=args.timeout,
    ) if supplemental_tasks else []
    existing.extend(supplemental)
    if existing:
        write_csv(manifest_path, list(existing[0]), existing)
    print(json.dumps({"unique_ciks": len(ciks), "main_sources": len(ciks), "supplemental_sources": len(supplemental_tasks)}, indent=2))


def columnar_rows(value: dict[str, Any]) -> list[dict[str, Any]]:
    keys = [key for key, item in value.items() if isinstance(item, list)]
    if not keys:
        return []
    length = max(len(value[key]) for key in keys)
    return [
        {key: value[key][index] if index < len(value[key]) else "" for key in keys}
        for index in range(length)
    ]


def build_candidates(args: argparse.Namespace) -> None:
    manifest_path = args.source_root / "source_manifest.csv"
    with manifest_path.open(newline="", encoding="utf-8") as handle:
        manifest = list(csv.DictReader(handle))
    filings: dict[tuple[str, str], dict[str, object]] = {}
    for source in manifest:
        path = ROOT / source["raw_path"]
        if sha256_bytes(path.read_bytes()) != source["sha256"]:
            raise RuntimeError(f"submissions checksum mismatch: {path}")
        value = json.loads(path.read_text())
        if source["source_kind"] == "main_submissions":
            rows = columnar_rows(value["filings"]["recent"])
        else:
            rows = columnar_rows(value)
        for row in rows:
            form = str(row.get("form", "")).upper()
            filed = str(row.get("filingDate", ""))
            items = str(row.get("items", ""))
            if form not in {"8-K", "8-K/A"} or not ("2010-01-01" <= filed <= "2019-12-31"):
                continue
            if "2.02" not in items and "7.01" not in items and "8.01" not in items:
                continue
            accession = str(row.get("accessionNumber", ""))
            if not accession:
                continue
            filings[(source["cik"], accession)] = {
                "cik": source["cik"], "accession_number": accession,
                "filing_date": filed, "report_date": row.get("reportDate", ""),
                "form": form, "items": items, "primary_document": row.get("primaryDocument", ""),
                "source_submissions_path": source["raw_path"],
            }
    filing_rows = sorted(filings.values(), key=lambda row: (str(row["cik"]), str(row["filing_date"]), str(row["accession_number"])))
    write_csv(args.output_root / "sec_8k_candidates.csv", list(filing_rows[0]), filing_rows)

    with (args.output_root / "call_date_mapping.csv").open(newline="", encoding="utf-8") as handle:
        mapping = list(csv.DictReader(handle))
    by_cik: dict[str, list[dict[str, object]]] = defaultdict(list)
    for filing in filing_rows:
        by_cik[str(filing["cik"])].append(filing)
    links: list[dict[str, object]] = []
    for row in mapping:
        if not row["cik"]:
            continue
        start = quarter_start(row["quarter_label"]) - timedelta(days=60)
        end = quarter_end(row["quarter_label"]) + timedelta(days=180)
        for filing in by_cik.get(row["cik"], []):
            filed = date.fromisoformat(str(filing["filing_date"]))
            if start <= filed <= end:
                links.append({
                    "ticker": row["ticker"], "quarter_label": row["quarter_label"],
                    "cik": row["cik"], "accession_number": filing["accession_number"],
                    "filing_date_candidate_only": filing["filing_date"],
                    "items": filing["items"],
                    "retrieval_window_start": start.isoformat(),
                    "retrieval_window_end": end.isoformat(),
                    "date_assignment_prohibited": True,
                })
    write_csv(args.output_root / "transcript_8k_candidate_links.csv", list(links[0]), links)
    print(json.dumps({"candidate_8k_filings": len(filing_rows), "transcript_candidate_links": len(links)}, indent=2))


def fetch_documents(
    tasks: list[dict[str, str]], *, manifest_path: Path, user_agent: str,
    max_rps: float, workers: int, attempts: int, timeout: float,
) -> None:
    existing: list[dict[str, object]] = []
    if manifest_path.exists():
        with manifest_path.open(newline="", encoding="utf-8") as handle:
            existing = list(csv.DictReader(handle))
    recorded = {str(row["raw_path"]): row for row in existing}
    manifest_fields = list(existing[0]) if existing else [
        "cik", "accession_number", "source_kind", "document_name", "url", "raw_path",
        "attempt", "requested_at_utc", "completed_at_utc", "http_status", "size_bytes",
        "sha256", "classification", "validation_reason",
    ]
    pending: list[dict[str, str]] = []
    recovered_rows: list[dict[str, object]] = []
    for task in tasks:
        destination = ROOT / task["raw_path"]
        prior = recorded.get(task["raw_path"])
        if prior:
            if str(prior.get("classification", "")).startswith("terminal_sec_source_unavailable"):
                continue
            if sha256_bytes(destination.read_bytes()) != prior["sha256"]:
                raise RuntimeError(f"immutable filing-source checksum mismatch: {destination}")
            continue
        if destination.exists():
            payload = destination.read_bytes()
            if not payload or b"Request Rate Threshold Exceeded" in payload:
                raise RuntimeError(f"invalid unmanifested filing source exists: {destination}")
            recovered_at = datetime.fromtimestamp(destination.stat().st_mtime, UTC).isoformat()
            recovered_rows.append({
                **task, "attempt": "", "requested_at_utc": recovered_at,
                "completed_at_utc": recovered_at, "http_status": "",
                "size_bytes": len(payload), "sha256": sha256_bytes(payload),
                "classification": "valid_sec_filing_document_recovered",
                "validation_reason": "raw file recovered after interrupted manifest checkpoint",
            })
            continue
        pending.append(task)
    limiter = RequestStartLimiter(max_rps)
    headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}
    thread_state = threading.local()

    def session() -> requests.Session:
        if not hasattr(thread_state, "session"):
            thread_state.session = requests.Session()
        return thread_state.session

    def fetch(task: dict[str, str]) -> dict[str, object]:
        reason = ""
        for attempt in range(1, attempts + 1):
            limiter.wait()
            requested_at = utc_now()
            try:
                response = session().get(task["url"], headers=headers, timeout=timeout)
                payload = response.content
                blocked = b"Request Rate Threshold Exceeded" in payload
                valid = response.status_code == 200 and bool(payload) and not blocked
                reason = "validated SEC filing document" if valid else f"HTTP {response.status_code} or SEC throttle page"
            except requests.RequestException as exc:
                response = None
                payload = b""
                valid = False
                reason = type(exc).__name__
            if valid:
                destination = ROOT / task["raw_path"]
                atomic_write_bytes(destination, payload)
                return {
                    **task, "attempt": attempt, "requested_at_utc": requested_at,
                    "completed_at_utc": utc_now(),
                    "http_status": response.status_code if response is not None else "",
                    "size_bytes": len(payload), "sha256": sha256_bytes(payload),
                    "classification": "valid_sec_filing_document",
                    "validation_reason": reason,
                }
            if (response is not None and response.status_code == 404) or attempt == attempts:
                return {
                    **task, "attempt": attempt, "requested_at_utc": requested_at,
                    "completed_at_utc": utc_now(),
                    "http_status": response.status_code if response is not None else "",
                    "size_bytes": 0, "sha256": "",
                    "classification": "terminal_sec_source_unavailable",
                    "validation_reason": reason,
                }
            time.sleep(min(2**attempt, 60))
        raise RuntimeError("unreachable filing-document fetch state")

    for row in recovered_rows:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with manifest_path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=manifest_fields, extrasaction="ignore")
            if handle.tell() == 0:
                writer.writeheader()
            writer.writerow(row)
    if recovered_rows:
        print(f"recovered {len(recovered_rows):,} interrupted manifest rows", flush=True)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(fetch, task): task for task in pending}
        for index, future in enumerate(as_completed(futures), start=1):
            row = future.result()
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            with manifest_path.open("a", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=manifest_fields, extrasaction="ignore")
                if handle.tell() == 0:
                    writer.writeheader()
                writer.writerow(row)
                handle.flush()
                os.fsync(handle.fileno())
            if index % 100 == 0 or index == len(pending):
                print(f"captured filing documents {index:,}/{len(pending):,}", flush=True)


def linked_item_202_filings(args: argparse.Namespace) -> list[dict[str, str]]:
    with (args.output_root / "sec_8k_candidates.csv").open(newline="", encoding="utf-8") as handle:
        filings = list(csv.DictReader(handle))
    with (args.output_root / "transcript_8k_candidate_links.csv").open(newline="", encoding="utf-8") as handle:
        links = list(csv.DictReader(handle))
    linked = {(row["cik"], row["accession_number"]) for row in links}
    return [
        row for row in filings
        if (row["cik"], row["accession_number"]) in linked
        and "2.02" in row["items"] and row["primary_document"]
    ]


def capture_primary_documents(args: argparse.Namespace) -> None:
    user_agent = os.environ.get("SEC_USER_AGENT")
    if not user_agent:
        raise RuntimeError("SEC_USER_AGENT is not present in this process")
    tasks: list[dict[str, str]] = []
    for row in linked_item_202_filings(args):
        cik_plain = str(int(row["cik"]))
        accession_plain = row["accession_number"].replace("-", "")
        name = Path(row["primary_document"]).name
        url = f"https://www.sec.gov/Archives/edgar/data/{cik_plain}/{accession_plain}/{name}"
        destination = args.source_root / "sec_filing_documents" / row["cik"] / row["accession_number"] / name
        tasks.append({
            "cik": row["cik"], "accession_number": row["accession_number"],
            "source_kind": "primary_8k", "document_name": name, "url": url,
            "raw_path": destination.relative_to(ROOT).as_posix(),
        })
    fetch_documents(
        tasks, manifest_path=args.source_root / "filing_document_manifest.csv",
        user_agent=user_agent, max_rps=args.sec_requests_per_second,
        workers=args.sec_workers, attempts=args.max_attempts, timeout=args.timeout,
    )


def capture_filing_indexes(args: argparse.Namespace) -> None:
    user_agent = os.environ.get("SEC_USER_AGENT")
    if not user_agent:
        raise RuntimeError("SEC_USER_AGENT is not present in this process")
    exhibit_path = args.output_root / "exhibit_requests.csv"
    linked_exhibits: set[tuple[str, str]] = set()
    if exhibit_path.exists():
        with exhibit_path.open(newline="", encoding="utf-8") as handle:
            linked_exhibits = {
                (row["cik"], row["accession_number"]) for row in csv.DictReader(handle)
            }
    tasks: list[dict[str, str]] = []
    for row in linked_item_202_filings(args):
        key = (row["cik"], row["accession_number"])
        if key in linked_exhibits:
            continue
        cik_plain = str(int(row["cik"]))
        accession_plain = row["accession_number"].replace("-", "")
        url = f"https://www.sec.gov/Archives/edgar/data/{cik_plain}/{accession_plain}/index.json"
        destination = args.source_root / "sec_filing_documents" / row["cik"] / row["accession_number"] / "index.json"
        tasks.append({
            "cik": row["cik"], "accession_number": row["accession_number"],
            "source_kind": "filing_index", "document_name": "index.json", "url": url,
            "raw_path": destination.relative_to(ROOT).as_posix(),
        })
    fetch_documents(
        tasks, manifest_path=args.source_root / "filing_document_manifest.csv",
        user_agent=user_agent, max_rps=args.sec_requests_per_second,
        workers=args.sec_workers, attempts=args.max_attempts, timeout=args.timeout,
    )


class LinkTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self._href = ""
        self._link_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            self._href = dict(attrs).get("href") or ""
            self._link_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href:
            self.links.append((self._href, " ".join(self._link_parts)))
            self._href = ""
            self._link_parts = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.text_parts.append(data.strip())
            if self._href:
                self._link_parts.append(data.strip())


def discover_exhibits(args: argparse.Namespace) -> None:
    manifest_path = args.source_root / "filing_document_manifest.csv"
    allowed_accessions = {
        (row["cik"], row["accession_number"]) for row in linked_item_202_filings(args)
    }
    with manifest_path.open(newline="", encoding="utf-8") as handle:
        manifest = [
            row for row in csv.DictReader(handle)
            if row["source_kind"] == "primary_8k"
            and (row["cik"], row["accession_number"]) in allowed_accessions
        ]
    requests_rows: dict[tuple[str, str, str], dict[str, str]] = {}
    cue = re.compile(r"(?:ex(?:hibit)?\s*99[._-]?1|99[._-]?1|press\s*release|earnings\s*release)", re.I)
    for row in manifest:
        payload = (ROOT / row["raw_path"]).read_bytes()
        parser = LinkTextParser()
        parser.feed(payload.decode("utf-8", errors="replace"))
        for href, link_text in parser.links:
            parsed = urlparse(href)
            if parsed.scheme and parsed.netloc and "sec.gov" not in parsed.netloc:
                continue
            name = Path(parsed.path).name
            if not name or not cue.search(f"{name} {link_text}"):
                continue
            if Path(name).suffix.lower() not in {".htm", ".html", ".txt"}:
                continue
            url = urljoin(row["url"], href)
            destination = args.source_root / "sec_filing_documents" / row["cik"] / row["accession_number"] / name
            key = (row["cik"], row["accession_number"], name)
            requests_rows[key] = {
                "cik": row["cik"], "accession_number": row["accession_number"],
                "source_kind": "exhibit_99", "document_name": name, "url": url,
                "raw_path": destination.relative_to(ROOT).as_posix(),
                "discovered_from_raw_path": row["raw_path"],
                "link_text": re.sub(r"\s+", " ", link_text).strip()[:300],
            }
    primary_by_accession = {
        (row["cik"], row["accession_number"]): row["document_name"]
        for row in manifest
    }
    with manifest_path.open(newline="", encoding="utf-8") as handle:
        indexes = [
            row for row in csv.DictReader(handle)
            if row["source_kind"] == "filing_index"
            and (row["cik"], row["accession_number"]) in allowed_accessions
        ]
    for row in indexes:
        value = json.loads((ROOT / row["raw_path"]).read_text())
        items = value.get("directory", {}).get("item", [])
        primary_name = primary_by_accession.get((row["cik"], row["accession_number"]), "")
        text_items = []
        for item in items:
            name = str(item.get("name", ""))
            suffix = Path(name).suffix.lower()
            if not name or name == primary_name or suffix not in {".htm", ".html", ".txt"}:
                continue
            if name.lower() in {"filingsummary.xml", "index.html", "index.json"} or re.match(r"^r\d+\.htm$", name, re.I):
                continue
            size = int(item.get("size") or 0)
            score = int(bool(cue.search(name))) * 100000000 + size
            text_items.append((score, name))
        selected = [name for score, name in sorted(text_items, reverse=True) if score >= 100000000]
        if not selected:
            selected = [name for _, name in sorted(text_items, reverse=True)[:2]]
        for name in selected[:3]:
            url = urljoin(row["url"], name)
            destination = args.source_root / "sec_filing_documents" / row["cik"] / row["accession_number"] / name
            key = (row["cik"], row["accession_number"], name)
            requests_rows[key] = {
                "cik": row["cik"], "accession_number": row["accession_number"],
                "source_kind": "exhibit_99", "document_name": name, "url": url,
                "raw_path": destination.relative_to(ROOT).as_posix(),
                "discovered_from_raw_path": row["raw_path"],
                "link_text": "selected from SEC filing directory",
            }
    values = sorted(requests_rows.values(), key=lambda row: (row["cik"], row["accession_number"], row["document_name"]))
    path = args.output_root / "exhibit_requests.csv"
    if values:
        write_csv(path, list(values[0]), values)
    else:
        write_csv(path, ["cik", "accession_number", "source_kind", "document_name", "url", "raw_path", "discovered_from_raw_path", "link_text"], [])
    print(json.dumps({"primary_documents": len(manifest), "discovered_exhibits": len(values)}, indent=2))


def capture_exhibits(args: argparse.Namespace) -> None:
    user_agent = os.environ.get("SEC_USER_AGENT")
    if not user_agent:
        raise RuntimeError("SEC_USER_AGENT is not present in this process")
    with (args.output_root / "exhibit_requests.csv").open(newline="", encoding="utf-8") as handle:
        tasks = list(csv.DictReader(handle))
    fetch_documents(
        tasks, manifest_path=args.source_root / "filing_document_manifest.csv",
        user_agent=user_agent, max_rps=args.sec_requests_per_second,
        workers=args.sec_workers, attempts=args.max_attempts, timeout=args.timeout,
    )


MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|November|December|"
    "Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
    "Sep(?:tember)?|Sept(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
)
DATE_RE = re.compile(rf"\b({MONTHS})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?[,]?\s+(20\d{{2}})\b", re.I)
CALL_CUE_RE = re.compile(r"conference call|earnings call|investor call|results call|webcast", re.I)


def visible_text(payload: bytes) -> str:
    decoded = payload.decode("utf-8", errors="replace")
    decoded = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", decoded, flags=re.I | re.S)
    decoded = re.sub(r"<!--.*?-->", " ", decoded, flags=re.S)
    text = html.unescape(re.sub(r"<[^>]+>", " ", decoded))
    return re.sub(r"\s+", " ", text).strip()


def explicit_call_dates(text: str) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    for cue in CALL_CUE_RE.finditer(text):
        context_start = max(0, cue.start() - 180)
        context = text[context_start: cue.end() + 420]
        cue_position = cue.start() - context_start
        for match in DATE_RE.finditer(context):
            if match.start() >= cue_position:
                lead = context[max(cue_position, match.start() - 55):match.start()].lower()
                plausible = match.start() - cue_position <= 90 or bool(
                    re.search(r"\b(on|for|scheduled|beginning|starts?|commencing)\b", lead)
                )
            else:
                bridge = context[match.end():cue_position].lower()
                plausible = "." not in bridge and bool(
                    re.search(r"\b(will|plans? to|scheduled to|host|hold)\b", bridge)
                )
            if not plausible:
                continue
            month, day, year = match.group(1).rstrip(".")[:3], match.group(2), match.group(3)
            try:
                value = datetime.strptime(f"{month} {day} {year}", "%b %d %Y").date().isoformat()
            except ValueError:
                continue
            excerpt = context[max(0, match.start() - 180): match.end() + 180]
            pair = (value, re.sub(r"\s+", " ", excerpt).strip()[:700])
            if pair not in results:
                results.append(pair)
    return results


def fiscal_period_match(text: str, quarter_label: str) -> bool:
    year = re.escape(quarter_label[:4])
    q = int(quarter_label[-1])
    ordinal = {1: "first|1st", 2: "second|2nd", 3: "third|3rd", 4: "fourth|4th"}[q]
    patterns = (
        rf"(?:q\s*{q}|{ordinal})\s+(?:fiscal\s+)?quarter[^.]{{0,80}}\b{year}\b",
        rf"\b{year}\b[^.]{{0,80}}(?:q\s*{q}|{ordinal})\s+(?:fiscal\s+)?quarter",
        rf"(?:q\s*{q}|{ordinal})\s+quarter\s+(?:of\s+)?(?:fiscal\s+)?{year}",
        rf"fiscal\s+(?:year\s+)?{year}[^.]{{0,80}}(?:q\s*{q}|{ordinal})\s+quarter",
        rf"fiscal\s+(?:q\s*{q}|{ordinal})\s+quarter[^.]{{0,80}}\b{year}\b",
    )
    return any(re.search(pattern, text, re.I) for pattern in patterns)


def extract_evidence(args: argparse.Namespace) -> None:
    with (args.output_root / "transcript_8k_candidate_links.csv").open(newline="", encoding="utf-8") as handle:
        links = list(csv.DictReader(handle))
    allowed_accessions = {(row["cik"], row["accession_number"]) for row in links}
    quarters_by_accession: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in links:
        quarters_by_accession[(row["cik"], row["accession_number"])].add(row["quarter_label"])
    with (args.source_root / "filing_document_manifest.csv").open(newline="", encoding="utf-8") as handle:
        document_by_path = {
            row["raw_path"]: row for row in csv.DictReader(handle)
            if (row["cik"], row["accession_number"]) in allowed_accessions
            and row["classification"].startswith("valid_sec_filing_document")
            and row["source_kind"] in {"primary_8k", "exhibit_99"}
        }
    documents = list(document_by_path.values())
    by_accession: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    document_dates: dict[str, list[tuple[str, str]]] = {}
    document_period_matches: dict[str, set[str]] = {}
    for document_index, row in enumerate(documents, start=1):
        path = ROOT / row["raw_path"]
        payload = path.read_bytes()
        if sha256_bytes(payload) != row["sha256"]:
            raise RuntimeError(f"filing-document checksum mismatch: {path}")
        decoded = payload.decode("utf-8", errors="replace")
        if CALL_CUE_RE.search(decoded) and DATE_RE.search(decoded):
            text = visible_text(payload)
            dates = explicit_call_dates(text)
        else:
            text = ""
            dates = []
        document_dates[row["raw_path"]] = dates
        document_period_matches[row["raw_path"]] = (
            {
                quarter for quarter in quarters_by_accession[(row["cik"], row["accession_number"])]
                if fiscal_period_match(text, quarter)
            }
            if dates else set()
        )
        by_accession[(row["cik"], row["accession_number"])].append(row)
        if document_index % 1000 == 0 or document_index == len(documents):
            print(f"extracted source evidence {document_index:,}/{len(documents):,}", flush=True)

    links_by_transcript: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in links:
        links_by_transcript[(row["ticker"], row["quarter_label"])].append(row)
    with (args.output_root / "call_date_mapping.csv").open(newline="", encoding="utf-8") as handle:
        mapping = list(csv.DictReader(handle))

    evidence_rows: list[dict[str, object]] = []
    transcript_evidence_rows: list[dict[str, object]] = []
    for row in mapping:
        transcript_path = ROOT / row["transcript_raw_path"]
        transcript_payload = transcript_path.read_bytes()
        if sha256_bytes(transcript_payload) != row["transcript_sha256"]:
            raise RuntimeError(f"transcript checksum mismatch: {transcript_path}")
        wrapper = json.loads(transcript_payload)
        provider_payload = wrapper.get("payload", wrapper)
        segments = provider_payload.get("transcript", []) if isinstance(provider_payload, dict) else []
        opening = " ".join(
            str(segment.get("content") or "")
            for segment in segments[:5] if isinstance(segment, dict)
        )[:15000]
        transcript_dates = [
            (value, excerpt) for value, excerpt in explicit_call_dates(opening)
            if "2010-01-01" <= value <= "2019-12-31"
        ]
        transcript_unique_dates = sorted({value for value, _ in transcript_dates})
        row["transcript_explicit_call_date"] = ";".join(transcript_unique_dates)
        row["transcript_date_evidence_excerpt"] = " | ".join(
            excerpt for _, excerpt in transcript_dates
        )[:1400]
        for value, excerpt in transcript_dates:
            transcript_evidence_rows.append({
                "ticker": row["ticker"], "quarter_label": row["quarter_label"],
                "transcript_raw_path": row["transcript_raw_path"],
                "transcript_sha256": row["transcript_sha256"],
                "explicit_call_date": value, "evidence_excerpt": excerpt,
            })
        candidates: list[dict[str, object]] = []
        for link in links_by_transcript.get((row["ticker"], row["quarter_label"]), []):
            for document in by_accession.get((row["cik"], link["accession_number"]), []):
                dates = document_dates[document["raw_path"]]
                period_match = row["quarter_label"] in document_period_matches[document["raw_path"]]
                for value, excerpt in dates:
                    if not ("2010-01-01" <= value <= "2019-12-31"):
                        continue
                    evidence = {
                        "ticker": row["ticker"], "quarter_label": row["quarter_label"],
                        "cik": row["cik"], "accession_number": link["accession_number"],
                        "source_kind": document["source_kind"], "source_url": document["url"],
                        "source_raw_path": document["raw_path"], "source_sha256": document["sha256"],
                        "explicit_call_date": value, "fiscal_period_match": period_match,
                        "evidence_excerpt": excerpt,
                    }
                    candidates.append(evidence)
                    evidence_rows.append(evidence)
        high = [candidate for candidate in candidates if candidate["fiscal_period_match"]]
        high_dates = sorted({str(candidate["explicit_call_date"]) for candidate in high})
        all_dates = sorted({str(candidate["explicit_call_date"]) for candidate in candidates})
        if len(high_dates) == 1 and transcript_unique_dates and high_dates[0] not in transcript_unique_dates:
            row.update({
                "candidate_call_date": ";".join(sorted(set(high_dates + transcript_unique_dates))),
                "confidence": "unresolved", "mapping_status": "transcript_independent_source_conflict",
                "validation_reason": "explicit transcript-opening and independent SEC dates conflict",
            })
        elif len(high_dates) == 1:
            selected = next(candidate for candidate in high if candidate["explicit_call_date"] == high_dates[0])
            row.update({
                "earnings_call_date": high_dates[0], "candidate_call_date": high_dates[0],
                "call_date_source_type": selected["source_kind"],
                "call_date_source_url": selected["source_url"],
                "call_date_source_raw_path": selected["source_raw_path"],
                "call_date_source_sha256": selected["source_sha256"],
                "evidence_excerpt": selected["evidence_excerpt"],
                "independent_source_count": len({str(candidate["accession_number"]) for candidate in high}),
                "confidence": "high", "mapping_status": "explicit_independent_date",
                "validation_reason": "one explicit call date with matching issuer and fiscal-quarter evidence",
            })
        elif len(high_dates) > 1:
            row.update({
                "candidate_call_date": ";".join(high_dates), "confidence": "unresolved",
                "mapping_status": "conflicting_explicit_dates",
                "validation_reason": "multiple explicit call dates matched the fiscal quarter",
            })
        elif len(all_dates) == 1:
            selected = next(candidate for candidate in candidates if candidate["explicit_call_date"] == all_dates[0])
            row.update({
                "candidate_call_date": all_dates[0], "call_date_source_type": selected["source_kind"],
                "call_date_source_url": selected["source_url"],
                "call_date_source_raw_path": selected["source_raw_path"],
                "call_date_source_sha256": selected["source_sha256"],
                "evidence_excerpt": selected["evidence_excerpt"],
                "independent_source_count": len({str(candidate["accession_number"]) for candidate in candidates}),
                "confidence": "medium", "mapping_status": "explicit_date_fiscal_period_unconfirmed",
                "validation_reason": "explicit call date found, but fiscal-quarter match was not explicit",
            })
        elif all_dates:
            row.update({
                "candidate_call_date": ";".join(all_dates), "confidence": "unresolved",
                "mapping_status": "ambiguous_explicit_dates",
                "validation_reason": "multiple explicit call dates without a unique fiscal-period match",
            })
        elif row["cik"]:
            row.update({
                "confidence": "unresolved", "mapping_status": "no_explicit_date_in_sec_evidence",
                "validation_reason": "no explicit call date found in captured SEC 8-K evidence",
            })
    write_csv(args.output_root / "call_date_mapping.csv", MAPPING_FIELDS, mapping)
    write_csv(
        args.output_root / "transcript_date_evidence.csv",
        ["ticker", "quarter_label", "transcript_raw_path", "transcript_sha256", "explicit_call_date", "evidence_excerpt"],
        transcript_evidence_rows,
    )
    evidence_fields = [
        "ticker", "quarter_label", "cik", "accession_number", "source_kind", "source_url",
        "source_raw_path", "source_sha256", "explicit_call_date", "fiscal_period_match",
        "evidence_excerpt",
    ]
    write_csv(args.output_root / "source_evidence.csv", evidence_fields, evidence_rows)
    unresolved = [row for row in mapping if row["confidence"] != "high"]
    write_csv(args.output_root / "unresolved.csv", MAPPING_FIELDS, unresolved)
    counts = defaultdict(int)
    for row in mapping:
        counts[row["confidence"]] += 1
    report = {
        "valid_transcript_rows": len(mapping), "evidence_rows": len(evidence_rows),
        "resolved_identity_rows": sum(bool(row["cik"]) for row in mapping),
        "high_confidence_call_dates": counts["high"],
        "medium_confidence_candidates": counts["medium"],
        "unresolved": counts["unresolved"],
        "primary_car_eligible_if_frozen": counts["high"],
        "car_construction_performed": False,
    }
    (args.output_root / "coverage_report.json").write_text(json.dumps(report, indent=2) + "\n")
    (args.output_root / "COVERAGE_REPORT.md").write_text(
        "# Independent call-date coverage\n\n"
        f"Valid transcript rows: {len(mapping):,}\n\n"
        f"High-confidence explicit call dates: {counts['high']:,}\n\n"
        f"Medium-confidence date candidates: {counts['medium']:,}\n\n"
        f"Unresolved: {counts['unresolved']:,}\n\n"
        "Dates are assigned only when an SEC-filed issuer document explicitly states "
        "a call date and the text explicitly matches the requested fiscal quarter. "
        "Filing dates, report dates, fiscal-period ends, and quarter labels are never "
        "substituted for call dates. Medium-confidence candidates remain excluded from "
        "the primary CAR input. No CAR construction was performed in this stage.\n"
    )
    source_rows: list[dict[str, object]] = []
    for path in (
        args.source_root / "source_manifest.csv",
        args.source_root / "filing_document_manifest.csv",
    ):
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8") as handle:
            for source in csv.DictReader(handle):
                if path.name == "filing_document_manifest.csv" and (
                    source.get("cik", ""), source.get("accession_number", "")
                ) not in allowed_accessions:
                    continue
                source_rows.append({"manifest": path.name, **source})
    if source_rows:
        source_fields = sorted({key for source in source_rows for key in source})
        write_csv(args.output_root / "source_manifest.csv", source_fields, source_rows)
    manifest_path = args.output_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    manifest.update({
        "completed_at_utc": utc_now(),
        "assigned_call_dates": counts["high"],
        "medium_confidence_candidates": counts["medium"],
        "unresolved_call_dates": counts["unresolved"],
        "primary_car_input_frozen": False,
        "car_construction_performed": False,
    })
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(report, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "stage",
        choices=(
            "initialize", "capture-submissions", "build-candidates",
            "capture-primary", "capture-indexes", "discover-exhibits", "capture-exhibits", "extract-evidence",
        ),
    )
    parser.add_argument("--universe-root", type=Path, default=UNIVERSE_ROOT)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--source-root", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--sec-requests-per-second", type=float, default=8.0)
    parser.add_argument("--sec-workers", type=int, default=32)
    parser.add_argument("--max-attempts", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()
    if not 0 < args.sec_requests_per_second <= 9:
        parser.error("--sec-requests-per-second must be in (0, 9]")
    return args


def main() -> None:
    args = parse_args()
    if args.stage == "initialize":
        initialize_mapping(args)
    elif args.stage == "capture-submissions":
        capture_submissions(args)
    elif args.stage == "build-candidates":
        build_candidates(args)
    elif args.stage == "capture-primary":
        capture_primary_documents(args)
    elif args.stage == "capture-indexes":
        capture_filing_indexes(args)
    elif args.stage == "discover-exhibits":
        discover_exhibits(args)
    elif args.stage == "capture-exhibits":
        capture_exhibits(args)
    else:
        extract_evidence(args)


if __name__ == "__main__":
    main()
