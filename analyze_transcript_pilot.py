"""Reconcile the bounded transcript pilot and write auditable pilot outputs."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from extract_earnings_call_transcript_data import response_segments
from study_period import validate_study_quarter

ROOT = Path(__file__).resolve().parent
PILOT_DIR = ROOT / "artifacts" / "transcript_pilot_20260916"
UNIVERSE = ROOT / "data" / "pilot" / "pilot_universe_v20260916" / "eligible_firm_quarters.csv"
AUDIT = ROOT / "review" / "alpha_vantage_transcript_audit_20260916" / "response_manifest.csv"
REPORT_DIR = ROOT / "review" / "transcript_pilot_20260916"

MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|November|December|"
    "Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
    "Sep(?:tember)?|Sept(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
)
DATE_RE = re.compile(rf"\b({MONTHS})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?[,]?\s+(20\d{{2}})\b", re.I)

TERMINAL_FIELDS = [
    "company_id", "cik", "company_name", "provider_ticker", "quarter_label",
    "exchange", "sic_2digit", "pilot_category", "terminal_state", "response_source",
    "attempt_count", "raw_path", "raw_sha256", "classification", "validation_reason",
    "normalized_transcript_sha256", "duplicate_group_size", "duplicate_canonical_key",
    "explicit_call_date", "call_date_source", "call_date_confidence", "primary_car_eligible",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def text_from_raw(path: Path) -> str:
    wrapper = json.loads(path.read_text(encoding="utf-8"))
    payload: Any = wrapper.get("payload")
    return "\n\n".join(str(row.get("content") or "") for row in response_segments(payload))


def parse_explicit_date(text: str, quarter: str) -> tuple[str, str]:
    candidates = []
    opening = text[:12000]
    for match in DATE_RE.finditer(opening):
        month, day, year = match.group(1), match.group(2), match.group(3)
        if abs(int(year) - int(quarter[:4])) > 1:
            continue
        context = opening[max(0, match.start() - 120):match.end() + 120].lower()
        if not any(cue in context for cue in ("earnings call", "conference call", "today is", "welcome")):
            continue
        cleaned_month = month.rstrip(".")[:3]
        try:
            value = datetime.strptime(f"{cleaned_month} {day} {year}", "%b %d %Y").date().isoformat()
        except ValueError:
            continue
        if value not in candidates:
            candidates.append(value)
    if len(candidates) == 1:
        return candidates[0], "medium_explicit_opening_unvalidated"
    if len(candidates) > 1:
        return "", "ambiguous_multiple_opening_dates"
    return "", "no_explicit_opening_date"


def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    universe = read_csv(UNIVERSE)
    legacy = {
        (row["ticker"].strip().upper(), row["quarter_label"].strip().upper()): row
        for row in read_csv(AUDIT)
        if int(row["year"]) <= 2019
    }
    attempts = read_csv(PILOT_DIR / "request_manifest.csv")
    live_by_key: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in attempts:
        live_by_key[(row["company_id"], row["provider_ticker"], row["quarter_label"])].append(row)

    terminal = []
    raw_hash_failures = []
    for eligible in universe:
        validate_study_quarter(eligible["quarter_label"])
        key = (eligible["company_id"], eligible["provider_ticker"], eligible["quarter_label"])
        live = live_by_key.get(key, [])
        old = legacy.get((eligible["provider_ticker"], eligible["quarter_label"]))
        if live:
            last = live[-1]
            raw_path = ROOT / last["raw_path"]
            digest = hashlib.sha256(raw_path.read_bytes()).hexdigest()
            if digest != last["raw_sha256"]:
                raw_hash_failures.append(last["raw_path"])
            state = last["terminal_status"]
            classification = last["classification"]
            reason = last["validation_reason"]
            normalized_hash = last["normalized_transcript_sha256"]
            source = "pilot_live"
            attempt_count = len(live) + (1 if old else 0)
            raw_rel = last["raw_path"]
            raw_sha = last["raw_sha256"]
        elif old and old["response_classification"] == "valid full transcript":
            state = "valid"
            classification = "valid"
            reason = old["classification_reasons"]
            normalized_hash = old["normalized_transcript_sha256"]
            source = "legacy_reuse"
            attempt_count = 1
            raw_rel = old["raw_file_path"]
            raw_sha = old["raw_file_sha256"]
            raw_path = ROOT / raw_rel
            if hashlib.sha256(raw_path.read_bytes()).hexdigest() != raw_sha:
                raw_hash_failures.append(raw_rel)
        else:
            raise RuntimeError(f"eligible pair lacks a terminal state: {key}")

        explicit_date = ""
        confidence = "not_applicable"
        date_source = ""
        if state == "valid":
            explicit_date, confidence = parse_explicit_date(text_from_raw(raw_path), eligible["quarter_label"])
            if explicit_date:
                date_source = f"explicit transcript opening; {raw_rel}"
        terminal.append({
            **{field: eligible[field] for field in (
                "company_id", "cik", "company_name", "provider_ticker", "quarter_label",
                "exchange", "sic_2digit", "pilot_category",
            )},
            "terminal_state": state,
            "response_source": source,
            "attempt_count": attempt_count,
            "raw_path": raw_rel,
            "raw_sha256": raw_sha,
            "classification": classification,
            "validation_reason": reason,
            "normalized_transcript_sha256": normalized_hash,
            "duplicate_group_size": "",
            "duplicate_canonical_key": "",
            "explicit_call_date": explicit_date,
            "call_date_source": date_source,
            "call_date_confidence": confidence,
            "primary_car_eligible": "no_independent_date_validation_pending" if explicit_date else "no",
        })

    hash_groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in terminal:
        if row["terminal_state"] == "valid" and row["normalized_transcript_sha256"]:
            hash_groups[row["normalized_transcript_sha256"]].append(row)
    duplicate_groups = 0
    duplicate_noncanonical = 0
    for group in hash_groups.values():
        if len(group) < 2:
            continue
        duplicate_groups += 1
        group.sort(key=lambda row: (row["provider_ticker"], row["quarter_label"]))
        canonical = f"{group[0]['provider_ticker']}|{group[0]['quarter_label']}"
        for index, row in enumerate(group):
            row["duplicate_group_size"] = len(group)
            row["duplicate_canonical_key"] = canonical
            if index:
                duplicate_noncanonical += 1

    terminal_path = REPORT_DIR / "terminal_state_manifest.csv"
    with terminal_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=TERMINAL_FIELDS)
        writer.writeheader()
        writer.writerows(terminal)

    dimensions = {
        "year": lambda row: row["quarter_label"][:4],
        "exchange": lambda row: row["exchange"],
        "sic_2digit": lambda row: row["sic_2digit"],
        "pilot_category": lambda row: row["pilot_category"],
    }
    for name, key_function in dimensions.items():
        counts: Counter[tuple[str, str]] = Counter(
            (key_function(row), row["terminal_state"]) for row in terminal
        )
        categories = sorted({row["terminal_state"] for row in terminal})
        values = sorted({key_function(row) for row in terminal})
        path = REPORT_DIR / f"coverage_by_{name}.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=[name, "eligible"] + categories)
            writer.writeheader()
            for value in values:
                row = {name: value, "eligible": sum(counts[value, state] for state in categories)}
                row.update({state: counts[value, state] for state in categories})
                writer.writerow(row)

    state_counts = Counter(row["terminal_state"] for row in terminal)
    explicit_dates = sum(bool(row["explicit_call_date"]) for row in terminal if row["terminal_state"] == "valid")
    summaries = sorted(PILOT_DIR.glob("pilot_*_summary.json"))
    summary = {
        "eligible_firm_quarters": len(terminal),
        "legacy_valid_reused": sum(row["response_source"] == "legacy_reuse" for row in terminal),
        "new_valid_recovered": sum(row["response_source"] == "pilot_live" and row["terminal_state"] == "valid" for row in terminal),
        "terminal_state_counts": dict(state_counts),
        "live_request_count": len(attempts),
        "live_session_count": len({row["session_id"] for row in attempts}),
        "rate_limit_api_transport_failures": sum(
            row["classification"] in {"provider_or_http_failure", "transport_error"} for row in attempts
        ),
        "exact_duplicate_groups": duplicate_groups,
        "duplicate_noncanonical_observations": duplicate_noncanonical,
        "explicit_opening_call_dates": explicit_dates,
        "independently_validated_call_dates": 0,
        "primary_car_eligible_dates": 0,
        "raw_hash_failures": raw_hash_failures,
        "session_summaries": [path.relative_to(ROOT).as_posix() for path in summaries],
    }
    (REPORT_DIR / "pilot_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
