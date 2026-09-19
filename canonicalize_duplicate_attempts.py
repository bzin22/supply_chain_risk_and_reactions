"""Plan and apply canonicalization of accidental duplicate attempt numbers."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
COLLECTION = ROOT / "artifacts" / "full_transcript_collection_v20260917"
ACTIVE_MANIFEST = COLLECTION / "request_manifest.csv"
PROVENANCE = ROOT / "provenance" / "duplicate_attempt_cleanup_20260918"
ARCHIVE = ROOT / ".archive" / "duplicate_attempts_20260918"
PLAN = PROVENANCE / "duplicate_attempts_manifest.csv"
PRE_REPORT = PROVENANCE / "pre_removal_report.json"
BACKUP_MANIFEST = PROVENANCE / "request_manifest_before_cleanup.csv"

PLAN_FIELDS = [
    "company_id", "ticker", "quarter", "attempt_number", "classification",
    "provider_status", "canonical_session_id", "canonical_raw_path",
    "canonical_size_bytes", "canonical_sha256", "canonical_provider_body_sha256",
    "redundant_session_id", "redundant_raw_path", "redundant_size_bytes",
    "redundant_sha256", "redundant_provider_body_sha256",
    "provider_body_exact_duplicate", "removal_classification", "archive_path",
]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def load_rows() -> tuple[list[dict[str, str]], list[str]]:
    with ACTIVE_MANIFEST.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or [])


def provider_body_sha(path: Path) -> str:
    envelope: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    body = {
        "http_status": envelope.get("http_status"),
        "provider_status": envelope.get("provider_status"),
        "payload": envelope.get("payload"),
        "response_text": envelope.get("response_text"),
    }
    encoded = json.dumps(
        body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256_bytes(encoded)


def duplicate_groups(rows: list[dict[str, str]]) -> list[list[dict[str, str]]]:
    grouped: defaultdict[tuple[str, str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[(
            row["company_id"], row["provider_ticker"], row["quarter_label"],
            row["attempt_number"],
        )].append(row)
    return [group for group in grouped.values() if len(group) > 1]


def plan() -> None:
    if PROVENANCE.exists():
        raise FileExistsError(f"provenance plan already exists: {PROVENANCE}")
    rows, _ = load_rows()
    groups = duplicate_groups(rows)
    planned: list[dict[str, Any]] = []
    for group in groups:
        ordered = sorted(group, key=lambda row: (row["requested_at_utc"], row["raw_path"]))
        canonical = ordered[0]
        canonical_path = ROOT / canonical["raw_path"]
        if sha256_file(canonical_path) != canonical["raw_sha256"]:
            raise ValueError(f"canonical SHA mismatch: {canonical_path}")
        canonical_body_sha = provider_body_sha(canonical_path)
        for redundant in ordered[1:]:
            redundant_path = ROOT / redundant["raw_path"]
            if sha256_file(redundant_path) != redundant["raw_sha256"]:
                raise ValueError(f"redundant SHA mismatch: {redundant_path}")
            redundant_body_sha = provider_body_sha(redundant_path)
            exact = canonical_body_sha == redundant_body_sha
            archive_path = ARCHIVE / redundant["raw_path"]
            planned.append({
                "company_id": redundant["company_id"],
                "ticker": redundant["provider_ticker"],
                "quarter": redundant["quarter_label"],
                "attempt_number": redundant["attempt_number"],
                "classification": redundant["classification"],
                "provider_status": redundant["provider_status"],
                "canonical_session_id": canonical["session_id"],
                "canonical_raw_path": canonical["raw_path"],
                "canonical_size_bytes": canonical["raw_size_bytes"],
                "canonical_sha256": canonical["raw_sha256"],
                "canonical_provider_body_sha256": canonical_body_sha,
                "redundant_session_id": redundant["session_id"],
                "redundant_raw_path": redundant["raw_path"],
                "redundant_size_bytes": redundant["raw_size_bytes"],
                "redundant_sha256": redundant["raw_sha256"],
                "redundant_provider_body_sha256": redundant_body_sha,
                "provider_body_exact_duplicate": str(exact).lower(),
                "removal_classification": (
                    "exact_provider_body_duplicate"
                    if exact else "duplicate_attempt_conflicting_provider_body"
                ),
                "archive_path": archive_path.relative_to(ROOT).as_posix(),
            })

    PROVENANCE.mkdir(parents=True)
    shutil.copy2(ACTIVE_MANIFEST, BACKUP_MANIFEST)
    with PLAN.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=PLAN_FIELDS)
        writer.writeheader()
        writer.writerows(planned)
    report = {
        "operation": "duplicate attempt canonicalization plan",
        "active_manifest": ACTIVE_MANIFEST.relative_to(ROOT).as_posix(),
        "active_manifest_sha256": sha256_file(ACTIVE_MANIFEST),
        "active_manifest_rows_before": len(rows),
        "duplicate_attempt_keys": len(groups),
        "redundant_observations_and_files": len(planned),
        "redundant_bytes": sum(int(row["redundant_size_bytes"]) for row in planned),
        "exact_provider_body_duplicates": sum(
            row["provider_body_exact_duplicate"] == "true" for row in planned
        ),
        "conflicting_provider_bodies": sum(
            row["provider_body_exact_duplicate"] != "true" for row in planned
        ),
        "quarters_outside_2010Q1_2019Q4": sum(
            not (2010 <= int(row["quarter"][:4]) <= 2019) for row in planned
        ),
        "canonical_rule": "earliest requested_at_utc, then lexical raw_path",
        "archive_root": ARCHIVE.relative_to(ROOT).as_posix(),
        "active_files_changed": False,
    }
    PRE_REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


def apply() -> None:
    report = json.loads(PRE_REPORT.read_text(encoding="utf-8"))
    if sha256_file(ACTIVE_MANIFEST) != report["active_manifest_sha256"]:
        raise ValueError("active manifest changed after the cleanup plan was produced")
    with PLAN.open(newline="", encoding="utf-8") as handle:
        planned = list(csv.DictReader(handle))
    redundant_paths = {row["redundant_raw_path"] for row in planned}
    rows, fieldnames = load_rows()
    if len(redundant_paths) != len(planned):
        raise ValueError("cleanup plan contains duplicate redundant paths")
    for row in planned:
        source = ROOT / row["redundant_raw_path"]
        destination = ROOT / row["archive_path"]
        if sha256_file(source) != row["redundant_sha256"]:
            raise ValueError(f"source changed after planning: {source}")
        if destination.exists():
            raise FileExistsError(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.replace(destination)

    retained = [row for row in rows if row["raw_path"] not in redundant_paths]
    temporary = ACTIVE_MANIFEST.with_suffix(".csv.canonicalizing")
    with temporary.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(retained)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, ACTIVE_MANIFEST)

    remaining_groups = duplicate_groups(retained)
    missing = [row["raw_path"] for row in retained if not (ROOT / row["raw_path"]).exists()]
    if remaining_groups or missing:
        raise RuntimeError(
            f"post-cleanup verification failed: duplicates={len(remaining_groups)}, "
            f"missing={len(missing)}"
        )
    post = {
        "operation": "duplicate attempt canonicalization applied",
        "active_manifest_rows_before": len(rows),
        "active_manifest_rows_after": len(retained),
        "archived_files": len(planned),
        "archived_bytes": sum(int(row["redundant_size_bytes"]) for row in planned),
        "remaining_duplicate_attempt_keys": len(remaining_groups),
        "missing_active_raw_files": len(missing),
        "active_manifest_sha256_after": sha256_file(ACTIVE_MANIFEST),
        "recoverable_backup_manifest": BACKUP_MANIFEST.relative_to(ROOT).as_posix(),
        "archive_root": ARCHIVE.relative_to(ROOT).as_posix(),
    }
    (PROVENANCE / "post_removal_verification.json").write_text(
        json.dumps(post, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(post, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("plan", "apply"))
    args = parser.parse_args()
    plan() if args.action == "plan" else apply()


if __name__ == "__main__":
    main()
