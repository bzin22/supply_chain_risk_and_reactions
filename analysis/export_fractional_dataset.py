"""Export an allowlisted, transcript-free snapshot of the documented run.

No numerical rewriting: CSV cells are copied verbatim, including missingness.
Gzip has a fixed header timestamp. Existing packages are never overwritten.
"""
import argparse
import csv
import gzip
import io
import json
import shutil
from pathlib import Path

from analysis.build_modified_portfolio_chart_pdfs import ROOT, SOURCE, sha256
from analysis.verify_historical_code import verify_historical_code

SOURCE_SHA256 = "af88e549cc8b275262eeb1e69af4d4aeb3b554b6197577dc91d5b63cdef7e2a6"
REFERENCE_TABLES = ROOT / "reproduction/fractional_v1/historical"
PANEL_TABLES = ["01_car_0_1_by_scrisk.csv", "02_car_0_1_by_resolution.csv", "03_car_0_1_heatmap.csv",
                "04_car_2_60_by_scrisk.csv", "05_car_2_60_heatmap.csv"]
GROUPS = {
    "identifiers": "call_id company_id security_id cik historical_ticker quarter_label source_row_ordinal",
    "dates": "earnings_call_date confirmed_call_date reported_earnings_date call_date event_date_policy event_date_source_field event_trading_date day_0_calendar_lag date_source_agreement reported_date_source_disagreement call_date_confirmation_status release_date_differs_from_confirmed_call",
    "industry": "sic_4digit sic_2digit sic_division sic_match_status sic_asof_date sic_asof_rule sic_filing_date sic_accession",
    "scores": "transcript_word_count supply_chain_occurrences risk_occurrences resolution_occurrences supply_chain_risk_pairs supply_chain_resolution_pairs SCRisk_weight_sum Resolution_weight_sum SCRisk_raw Resolution_raw SCRisk_sd Resolution_sd SCRisk Resolution scrisk_identical_span_pairs scrisk_identical_span_weight_sum",
    "flags": "validation_status validation_flags transcript_integrity_status transcript_integrity_flags score_valid scrisk_zero resolution_zero zero_reason market_data_status price_identity_status car_model_status car_0_1_status car_2_60_status car_0_1_eligible car_2_60_eligible car_joint_eligible portfolio_eligible car_0_1_exclusion_reasons car_2_60_exclusion_reasons portfolio_exclusion_reasons",
    "returns": "CAR_0_1 CAR_2_60 estimation_observations estimation_rank estimation_start estimation_end car_0_1_observations car_2_60_observations",
}
COLUMNS = [c for group in GROUPS.values() for c in group.split()]
STRING_COLUMNS = GROUPS["identifiers"].split() + GROUPS["dates"].split() + GROUPS["industry"].split()
BOOLEAN_COLUMNS = "reported_date_source_disagreement release_date_differs_from_confirmed_call score_valid scrisk_zero resolution_zero car_0_1_eligible car_2_60_eligible car_joint_eligible portfolio_eligible".split()


def dump(path, obj):
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, allow_nan=False) + "\n")


def export(source, output, reference_tables=REFERENCE_TABLES):
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite {output}")
    if sha256(source) != SOURCE_SHA256:
        raise ValueError("Source does not match the documented scored-CAR snapshot")
    original = json.loads((source.parent / "manifest.json").read_text())
    chart_manifest = ROOT / "reproduction/fractional_v1/historical/chart_manifest.json"
    chart = json.loads(chart_manifest.read_text())
    code = dict(original["code_hashes"])
    code[chart["implementation"]["path"]] = chart["implementation"]["sha256"]
    verify_historical_code(ROOT, code)
    for item in original["dictionaries"].values():
        if sha256(ROOT / item["path"]) != item["sha256"]:
            raise ValueError(f"Canonical dictionary differs: {item['path']}")
    output.mkdir(parents=True)
    (output / "historical").mkdir()
    with source.open(newline="") as inp, (output / "analysis.csv.gz").open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
            with io.TextIOWrapper(zipped, encoding="utf-8", newline="") as out:
                reader = csv.DictReader(inp)
                writer = csv.DictWriter(out, COLUMNS, extrasaction="ignore", lineterminator="\n")
                writer.writeheader()
                count = 0
                for row in reader:
                    writer.writerow(row)
                    count += 1
    if count != 58305:
        raise ValueError("Unexpected source row count")
    for name in ["manifest.json", "verification.json", "winsorization_thresholds.csv", "gate_counts.csv"]:
        shutil.copyfile(source.parent / name, output / "historical" / name)
    shutil.copyfile(chart_manifest, output / "historical/chart_manifest.json")
    for name in PANEL_TABLES:
        shutil.copyfile(reference_tables / name, output / "historical" / name)
    # Input inventory makes external/private requirements concrete. Include every
    # selected price response, even unavailable-provider responses defining gates.
    inputs = dict(original["auxiliary_input_hashes"])
    inputs[original["source"]["path"]] = original["source"]["sha256_before"]
    for kind in ["fama_french", "momentum"]:
        item = original["factors"][kind]
        inputs[item["path"]] = item["sha256"]
    with (source.parent / "market_data_sources.csv").open() as handle:
        for row in csv.DictReader(handle):
            for field in ["price_source", "price_initial_response"]:
                if row.get(field + "_path"):
                    inputs[row[field + "_path"]] = row[field + "_sha256"]
    raw_inputs = [{"path": p, "sha256": h, "redistributed": False} for p, h in sorted(inputs.items())]
    dump(output / "raw_inputs.json", raw_inputs)
    schema = {"format": "UTF-8 CSV, gzip mtime=0; original decimal strings retained",
              "missing": "empty cell; never substituted with zero",
              "string_columns": STRING_COLUMNS, "boolean_columns": BOOLEAN_COLUMNS,
              "units": {"CAR_0_1": "decimal cumulative return, 2 trading days",
                        "CAR_2_60": "decimal cumulative return, 59 trading days",
                        "SCRisk": "raw divided by population SD, no centering",
                        "Resolution": "raw divided by population SD, no centering"},
              "column_groups": {k: v.split() for k, v in GROUPS.items()},
              "privacy": "Strict allowlist; no transcript text, snippets, match text, or raw price series"}
    dump(output / "schema.json", schema)
    files = {str(p.relative_to(output)): {"sha256": sha256(p), "bytes": p.stat().st_size}
             for p in sorted(output.rglob("*")) if p.is_file()}
    dump(output / "manifest.json", {
        "version": "fractional_analysis_v1", "source_path": str(source.relative_to(ROOT)),
        "source_sha256": SOURCE_SHA256, "source_rows": count, "eligible_calls": 52533,
        "eligible_firms": 2026, "date_policy": "release", "files": files,
        "historical_code": code, "dictionaries": original["dictionaries"],
        "exporter_sha256": sha256(Path(__file__)),
        "historical_environment": original["environment"],
        "count_correction": "Historical pooled Resolution contributing_calls counts membership rows; reproduction reports unique call IDs and membership_rows separately. Numerical estimates unchanged.",
    })
    print(json.dumps({"output": str(output), "rows": count, "compressed_bytes": (output / "analysis.csv.gz").stat().st_size}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference-tables", type=Path, default=REFERENCE_TABLES)
    args = parser.parse_args()
    export(args.source.resolve(), args.output.resolve(), args.reference_tables.resolve())
