"""Audit and remove post-2019 observations from active study data.

The default mode is audit-only. ``--apply`` moves mixed-period originals and
post-2019 raw responses into a gitignored archive, then writes filtered
2010-2019 consolidated CSVs. It never edits a raw provider response.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import sys
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from collection.study_period import STUDY_END, STUDY_START, row_quarter, validate_study_quarter

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "artifacts" / "earnings_call_responses"
MIXED_OUTPUT_DIR = ROOT / "artifacts" / "earnings_call_supply_chain"
CONSOLIDATED = [
    ROOT / "data/provisional/earnings_call_transcripts.csv",
    ROOT / "data/provisional/earnings_call_transcript_segments.csv",
]
PROVENANCE_DIR = ROOT / "provenance" / "post_2019_removal_20260916"
ARCHIVE_DIR = ROOT / ".archive" / "post_2019_removed_20260916"
PRIOR_AUDIT = (
    ROOT / "review" / "alpha_vantage_transcript_audit_20260916" / "response_manifest.csv"
)
CSV_LIMIT = sys.maxsize

OBSERVATION_FIELDS = [
    "source_path", "source_size_bytes", "source_sha256", "observation_type",
    "row_number", "ticker", "quarter", "raw_path", "raw_size_bytes",
    "raw_sha256", "classification", "verified_outside_study_period", "action",
]
FILE_FIELDS = [
    "source_path", "size_bytes", "sha256", "classification", "post_2019_observations",
    "action", "archive_path",
]


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_prior_audit() -> dict[tuple[str, str], dict[str, str]]:
    if not PRIOR_AUDIT.exists():
        return {}
    with PRIOR_AUDIT.open(newline="", encoding="utf-8") as handle:
        return {
            (row["ticker"].strip().upper(), row["quarter_label"].strip().upper()): row
            for row in csv.DictReader(handle)
        }


def post_2019(quarter: str) -> bool:
    normalized = quarter.strip().upper()
    try:
        validate_study_quarter(normalized)
    except ValueError as exc:
        if normalized > STUDY_END:
            return True
        raise RuntimeError(f"refusing to remove pre-study observation {normalized}") from exc
    return False


def raw_metadata(
    ticker: str, quarter: str, audit: dict[tuple[str, str], dict[str, str]]
) -> tuple[str, str, str, str]:
    row = audit.get((ticker, quarter), {})
    raw = RAW_DIR / f"{ticker}_{quarter}.json"
    raw_path = row.get("raw_file_path") or (relative(raw) if raw.exists() else "")
    size = row.get("raw_file_size_bytes") or (str(raw.stat().st_size) if raw.exists() else "")
    digest = row.get("raw_file_sha256") or (sha256(raw) if raw.exists() else "")
    classification = row.get("response_classification") or row.get("provider_status") or "unknown"
    return raw_path, size, digest, classification


def iter_analysis_csvs() -> list[Path]:
    paths = [path for path in CONSOLIDATED if path.exists()]
    if MIXED_OUTPUT_DIR.exists():
        paths.extend(sorted(MIXED_OUTPUT_DIR.rglob("*.csv")))
    return paths


def audit() -> dict[str, Any]:
    csv.field_size_limit(CSV_LIMIT)
    PROVENANCE_DIR.mkdir(parents=True, exist_ok=True)
    audit_index = load_prior_audit()
    observations_path = PROVENANCE_DIR / "post_2019_observations.csv"
    files_path = PROVENANCE_DIR / "affected_files.csv"
    counts: Counter[str] = Counter()
    unique_calls: set[tuple[str, str]] = set()
    file_rows: list[dict[str, str]] = []

    with observations_path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=OBSERVATION_FIELDS)
        writer.writeheader()

        for raw in sorted(RAW_DIR.glob("*.json")) if RAW_DIR.exists() else []:
            try:
                payload = json.loads(raw.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"cannot verify raw response {raw}: {exc}") from exc
            ticker = str(payload.get("ticker") or "").strip().upper()
            quarter = str(payload.get("quarter_label") or "").strip().upper()
            if not ticker or not quarter:
                raise RuntimeError(f"raw response lacks ticker/quarter: {raw}")
            if not post_2019(quarter):
                continue
            raw_path, size, digest, classification = raw_metadata(ticker, quarter, audit_index)
            writer.writerow({
                "source_path": relative(raw), "source_size_bytes": size,
                "source_sha256": digest, "observation_type": "raw_call",
                "row_number": "", "ticker": ticker, "quarter": quarter,
                "raw_path": raw_path, "raw_size_bytes": size, "raw_sha256": digest,
                "classification": classification, "verified_outside_study_period": "yes",
                "action": "move raw response to gitignored archive",
            })
            counts["raw_files"] += 1
            counts["raw_bytes"] += int(size)
            unique_calls.add((ticker, quarter))
            file_rows.append({
                "source_path": relative(raw), "size_bytes": size, "sha256": digest,
                "classification": classification, "post_2019_observations": "1",
                "action": "move raw response", "archive_path": relative(ARCHIVE_DIR / relative(raw)),
            })

        for path in iter_analysis_csvs():
            source_size = path.stat().st_size
            source_digest = sha256(path)
            post_rows = 0
            with path.open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                fields = set(reader.fieldnames or [])
                if "quarter_label" not in fields and not {"year", "quarter"}.issubset(fields):
                    continue
                is_segment = "segment_number" in fields
                for row_number, row in enumerate(reader, start=2):
                    quarter = row_quarter(row)
                    if not quarter or not post_2019(quarter):
                        continue
                    ticker = (row.get("ticker") or row.get("symbol") or "").strip().upper()
                    raw_path, raw_size, raw_digest, classification = raw_metadata(
                        ticker, quarter, audit_index
                    )
                    writer.writerow({
                        "source_path": relative(path), "source_size_bytes": source_size,
                        "source_sha256": source_digest,
                        "observation_type": "segment" if is_segment else "call",
                        "row_number": row_number, "ticker": ticker, "quarter": quarter,
                        "raw_path": raw_path, "raw_size_bytes": raw_size,
                        "raw_sha256": raw_digest, "classification": classification,
                        "verified_outside_study_period": "yes",
                        "action": (
                            "filter consolidated CSV; archive mixed original"
                            if path in CONSOLIDATED else "archive mixed-period generated output"
                        ),
                    })
                    post_rows += 1
                    counts["segments" if is_segment else "call_rows"] += 1
                    unique_calls.add((ticker, quarter))
            if post_rows:
                destination = ARCHIVE_DIR / relative(path)
                file_rows.append({
                    "source_path": relative(path), "size_bytes": source_size,
                    "sha256": source_digest,
                    "classification": "mixed-period consolidated input" if path in CONSOLIDATED else "mixed-period generated output",
                    "post_2019_observations": post_rows,
                    "action": "filter and archive original" if path in CONSOLIDATED else "archive whole generated tree",
                    "archive_path": relative(destination),
                })

    # Include non-CSV files that leave the active tree with an invalidated output directory.
    if MIXED_OUTPUT_DIR.exists():
        listed = {row["source_path"] for row in file_rows}
        for path in sorted(item for item in MIXED_OUTPUT_DIR.rglob("*") if item.is_file()):
            if relative(path) in listed:
                continue
            file_rows.append({
                "source_path": relative(path), "size_bytes": path.stat().st_size,
                "sha256": sha256(path), "classification": "mixed-period generated output dependency",
                "post_2019_observations": "not row-addressable",
                "action": "archive whole generated tree",
                "archive_path": relative(ARCHIVE_DIR / relative(path)),
            })

    with files_path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=FILE_FIELDS)
        writer.writeheader()
        writer.writerows(file_rows)

    counts["unique_post_2019_calls"] = len(unique_calls)
    counts["affected_files"] = len(file_rows)
    counts["affected_file_bytes"] = sum(int(row["size_bytes"]) for row in file_rows)
    summary = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "study_period": {"start": STUDY_START, "end": STUDY_END},
        "verification": "every listed quarter was parsed and verified later than 2019Q4",
        "counts_before_removal": dict(counts),
        "archive": relative(ARCHIVE_DIR),
        "active_pipeline_archive_exclusion": "archive is outside all default scan paths",
    }
    (PROVENANCE_DIR / "pre_removal_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def move(path: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise RuntimeError(f"archive destination already exists: {destination}")
    shutil.move(str(path), str(destination))


def filtered_copy(source: Path, destination: Path) -> tuple[int, int]:
    csv.field_size_limit(CSV_LIMIT)
    kept = removed = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open(newline="", encoding="utf-8") as input_handle, destination.open(
        "w", newline="", encoding="utf-8"
    ) as output_handle:
        reader = csv.DictReader(input_handle)
        writer = csv.DictWriter(output_handle, fieldnames=reader.fieldnames or [])
        writer.writeheader()
        for row in reader:
            quarter = row_quarter(row)
            if quarter and post_2019(quarter):
                removed += 1
                continue
            if quarter:
                validate_study_quarter(quarter)
            writer.writerow(row)
            kept += 1
    return kept, removed


def apply_cleanup(pre_summary: dict[str, Any]) -> dict[str, Any]:
    if ARCHIVE_DIR.exists():
        raise RuntimeError(f"refusing to reuse existing archive {ARCHIVE_DIR}")
    ARCHIVE_DIR.mkdir(parents=True)

    filtered: dict[str, dict[str, int]] = {}
    for source in CONSOLIDATED:
        if not source.exists():
            continue
        archive_source = ARCHIVE_DIR / relative(source)
        move(source, archive_source)
        with tempfile.NamedTemporaryFile(dir=source.parent, delete=False) as handle:
            temporary = Path(handle.name)
        try:
            kept, removed = filtered_copy(archive_source, temporary)
            os.replace(temporary, source)
        finally:
            temporary.unlink(missing_ok=True)
        filtered[relative(source)] = {"kept": kept, "removed": removed}

    moved_raw = 0
    for raw in sorted(RAW_DIR.glob("*.json")) if RAW_DIR.exists() else []:
        payload = json.loads(raw.read_text(encoding="utf-8"))
        quarter = str(payload.get("quarter_label") or "").strip().upper()
        if quarter and post_2019(quarter):
            move(raw, ARCHIVE_DIR / relative(raw))
            moved_raw += 1

    if MIXED_OUTPUT_DIR.exists():
        move(MIXED_OUTPUT_DIR, ARCHIVE_DIR / relative(MIXED_OUTPUT_DIR))

    outputs_generated = ROOT / "outputs" / "sector_scrisk_rankings_vocab_v2"
    if outputs_generated.exists():
        move(outputs_generated, ARCHIVE_DIR / relative(outputs_generated))

    report = {
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "pre_removal": pre_summary,
        "raw_files_moved": moved_raw,
        "consolidated_csvs": filtered,
        "generated_output_tree_archived": not MIXED_OUTPUT_DIR.exists(),
        "archive_path": relative(ARCHIVE_DIR),
    }
    (PROVENANCE_DIR / "post_removal_verification.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="perform the verified archival/filtering")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if ARCHIVE_DIR.exists():
        raise SystemExit(
            f"Cleanup was already applied to {ARCHIVE_DIR}. "
            "Run collection/verify_active_study_period.py for the active-data check."
        )
    summary = audit()
    print(json.dumps(summary, indent=2))
    if args.apply:
        print(json.dumps(apply_cleanup(summary), indent=2))
    else:
        print("Audit only; no active data was changed. Re-run with --apply after review.")


if __name__ == "__main__":
    main()
