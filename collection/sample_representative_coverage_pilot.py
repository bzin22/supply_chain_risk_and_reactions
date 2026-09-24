"""Draw the fixed representative firm-quarter transcript-coverage pilot."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

from collection.study_period import validate_study_quarter

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_UNIVERSE = ROOT / "data" / "universe" / "us_operating_companies_v20260916" / "eligible_firm_quarters.csv"
DEFAULT_OUTPUT = ROOT / "data" / "pilot" / "representative_coverage_pilot_v20260916"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def allocate(strata: dict[str, list[dict[str, str]]], sample_size: int, seed: int) -> dict[str, int]:
    population = sum(len(rows) for rows in strata.values())
    quotas = {key: len(rows) * sample_size / population for key, rows in strata.items()}
    allocation = {key: math.floor(value) for key, value in quotas.items()}
    remainder = sample_size - sum(allocation.values())
    rng = random.Random(seed)
    tie_break = {key: rng.random() for key in strata}
    ordered = sorted(
        strata,
        key=lambda key: (-(quotas[key] - allocation[key]), tie_break[key], key),
    )
    for key in ordered[:remainder]:
        allocation[key] += 1
    return allocation


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sample-size", type=int, default=800)
    parser.add_argument("--seed", type=int, default=20260916)
    parser.add_argument("--preserve-sample", type=Path)
    args = parser.parse_args()

    with args.universe.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise SystemExit("universe is empty")
    required = {
        "company_id", "cik", "company_name", "provider_ticker", "quarter_label",
        "exchange", "sic_division",
    }
    missing = required - set(rows[0])
    if missing:
        raise SystemExit(f"universe lacks columns: {sorted(missing)}")
    keys = set()
    for row in rows:
        validate_study_quarter(row["quarter_label"])
        key = (row["company_id"], row["quarter_label"])
        if key in keys:
            raise SystemExit(f"duplicate firm-quarter in universe: {key}")
        keys.add(key)
        if not row["cik"]:
            raise SystemExit(f"unresolved CIK in request universe: {key}")
        row["sampling_stratum"] = "|".join(
            (row["quarter_label"][:4], row["exchange"], row["sic_division"])
        )
    sample_size = min(args.sample_size, len(rows))
    strata: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        strata[row["sampling_stratum"]].append(row)
    allocation = allocate(strata, sample_size, args.seed)
    rng = random.Random(args.seed)
    preserved_by_stratum: dict[str, list[dict[str, str]]] = defaultdict(list)
    if args.preserve_sample:
        universe_by_key = {(row["company_id"], row["quarter_label"]): row for row in rows}
        with args.preserve_sample.open(newline="", encoding="utf-8") as handle:
            for old in csv.DictReader(handle):
                current = universe_by_key.get((old["company_id"], old["quarter_label"]))
                if current:
                    preserved_by_stratum[current["sampling_stratum"]].append(current)
    sampled: list[dict[str, object]] = []
    preserved_count = 0
    summary: list[dict[str, object]] = []
    for stratum, members in sorted(strata.items()):
        draw = allocation[stratum]
        preserved = preserved_by_stratum.get(stratum, [])
        if len(preserved) > draw:
            preserved = rng.sample(preserved, draw)
        preserved_keys = {(row["company_id"], row["quarter_label"]) for row in preserved}
        remaining = [
            row for row in members
            if (row["company_id"], row["quarter_label"]) not in preserved_keys
        ]
        chosen = preserved + (rng.sample(remaining, draw - len(preserved)) if draw > len(preserved) else [])
        preserved_count += len(preserved)
        probability = draw / len(members) if draw else 0.0
        weight = len(members) / draw if draw else ""
        for row in chosen:
            sampled.append({
                **row,
                "stratum_population": len(members),
                "stratum_sample": draw,
                "selection_probability": f"{probability:.10f}",
                "design_weight": f"{weight:.10f}" if weight != "" else "",
                "sample_seed": args.seed,
            })
        year, exchange, sic_division = stratum.split("|", 2)
        summary.append({
            "sampling_stratum": stratum, "year": year, "exchange": exchange,
            "sic_division": sic_division, "population": len(members),
            "sample": draw, "selection_probability": f"{probability:.10f}",
            "design_weight": f"{weight:.10f}" if weight != "" else "",
        })
    sampled.sort(key=lambda row: (str(row["quarter_label"]), str(row["company_id"])))
    if len(sampled) != sample_size:
        raise SystemExit(f"sample size mismatch: {len(sampled)} != {sample_size}")
    output_path = args.output_dir / "eligible_firm_quarters.csv"
    write_csv(output_path, list(sampled[0]), sampled)
    write_csv(args.output_dir / "sampling_frame_summary.csv", list(summary[0]), summary)
    manifest = {
        "version": "v20260916",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "study_period": "2010Q1-2019Q4",
        "sampling_unit": "resolved eligible operating-company firm-quarter",
        "strata": ["year", "exchange", "sic_division"],
        "allocation": "proportional with largest-remainder integer allocation",
        "seed": args.seed,
        "population_firm_quarters": len(rows),
        "sample_firm_quarters": len(sampled),
        "population_unique_companies": len({row["company_id"] for row in rows}),
        "sample_unique_companies": len({str(row["company_id"]) for row in sampled}),
        "universe_path": args.universe.relative_to(ROOT).as_posix(),
        "universe_sha256": sha256(args.universe),
        "sample_sha256": sha256(output_path),
        "preserved_prior_sample_rows": preserved_count,
        "preserve_sample_path": args.preserve_sample.resolve().relative_to(ROOT).as_posix() if args.preserve_sample else "",
        "sample_by_year": dict(sorted(Counter(str(row["quarter_label"])[:4] for row in sampled).items())),
    }
    (args.output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (args.output_dir / "SOURCES.md").write_text(
        "# Representative coverage pilot source\n\n"
        "This deterministic sample is drawn from the versioned point-in-time universe. "
        "It is proportionally allocated across year, exchange, and SIC division and is "
        "not an adversarial edge-case sample. The source path and SHA-256 are recorded "
        "in `manifest.json`.\n"
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
