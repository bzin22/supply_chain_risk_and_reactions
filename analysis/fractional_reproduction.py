"""Regenerate the final fractional figures/tables without private raw inputs."""
import argparse
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

from analysis import build_modified_portfolio_chart_pdfs as legacy
from analysis.export_fractional_dataset import BOOLEAN_COLUMNS, COLUMNS, STRING_COLUMNS
from analysis.fractional_covariance import pairwise_comparisons
from analysis.verify_historical_code import verify_historical_code

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "reproduction/fractional_v1"
PANELS = ["car_0_1_by_scrisk", "car_0_1_by_resolution", "car_0_1_heatmap",
          "car_2_60_by_scrisk", "car_2_60_heatmap"]


def check_hash(path, expected):
    if not path.is_file() or legacy.sha256(path) != expected:
        raise ValueError(f"Missing file or SHA-256 mismatch: {path}")


def load_package(package=PACKAGE):
    manifest = json.loads((package / "manifest.json").read_text())
    for name, item in manifest["files"].items():
        check_hash(package / name, item["sha256"])
    verify_historical_code(ROOT, manifest["historical_code"])
    for item in manifest["dictionaries"].values():
        check_hash(ROOT / item["path"], item["sha256"])
    strings = {c: str for c in STRING_COLUMNS if c not in BOOLEAN_COLUMNS}
    # Historical plotting used pandas' default float parser. Changing to
    # round_trip would change the last bits; retain the actual plotting choice.
    data = pd.read_csv(package / "analysis.csv.gz", dtype=strings, low_memory=False)
    if data.columns.tolist() != COLUMNS or len(data) != manifest["source_rows"] or not data.call_id.is_unique:
        raise ValueError("Unexpected schema, row count or duplicate call IDs")
    for col in BOOLEAN_COLUMNS:
        if data[col].dtype != bool:
            raise ValueError(f"Non-boolean or missing flag: {col}")
    if not data.quarter_label.str.match(r"201[0-9]Q[1-4]$").all():
        raise ValueError("Calls outside 2010Q1-2019Q4")
    if not data.event_date_policy.eq("release").all():
        raise ValueError("Event date policy changed")
    sample = data.loc[data.portfolio_eligible].copy().reset_index(drop=True)
    if len(sample) != manifest["eligible_calls"] or sample.cik.nunique() != manifest["eligible_firms"]:
        raise ValueError("Eligible population changed")
    if not np.isfinite(sample[legacy.VARIABLES].to_numpy(float)).all() or sample.sic_division.isna().any():
        raise ValueError("Missing eligible scores, returns or industry")
    return data, sample, manifest


def matrices(frame, risk, joint):
    n = len(frame)
    risk_w = np.zeros((n, 5))
    risk_w[risk.row_id, risk.SCRisk_quintile - 1] = risk.risk_weight
    joint_w = np.zeros((n, 25))
    joint_w[joint.row_id, (joint.SCRisk_quintile - 1) * 5 + joint.Resolution_quintile - 1] = joint.weight
    resolution_w = joint_w.reshape(n, 5, 5).sum(axis=1)
    np.testing.assert_allclose(joint_w.reshape(n, 5, 5).sum(axis=2), risk_w, atol=1e-11, rtol=0)
    for w in [risk_w, joint_w, resolution_w]:
        np.testing.assert_allclose(w.sum(axis=1), 1, atol=1e-10, rtol=0)
    for _, idx in frame.groupby("sic_division").groups.items():
        for w in [risk_w, joint_w, resolution_w]:
            np.testing.assert_allclose(w[idx].sum(axis=0), len(idx) / w.shape[1], atol=1e-8, rtol=0)
    return risk_w, resolution_w, joint_w


def reproduce(package, output):
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite {output}; choose a new --output")
    _, eligible, _ = load_package(package)
    frame, thresholds = legacy.winsorize(eligible)
    expected_thresholds = pd.read_csv(package / "historical/winsorization_thresholds.csv")
    for row in thresholds:
        old = expected_thresholds.set_index("variable").loc[row["variable"]]
        np.testing.assert_allclose([row["lower_threshold"], row["upper_threshold"]],
                                   [old.lower_threshold, old.upper_threshold], atol=1e-14, rtol=1e-12)
    risk, joint, _ = legacy.fractional_assignments(frame)
    risk_w, resolution_w, joint_w = matrices(frame, risk, joint)
    tables = legacy.fractional_tables(frame, risk, joint)
    output.mkdir(parents=True)
    comparisons = []
    for number, panel in enumerate(PANELS, 1):
        rows = tables[panel]
        table = pd.DataFrame(rows)
        for field in ["mean", "se_firm_clustered", "ci_low", "ci_high"]:
            table[field + "_percent"] = table[field] * 100
        old = pd.read_csv(package / "historical" / f"{number:02d}_{panel}.csv")
        # Compare EVERY historical table field before correcting count semantics.
        if table.columns.tolist() != old.columns.tolist():
            raise ValueError(f"Historical table schema changed: {panel}")
        # The published CSVs have ten decimal places, including percent fields.
        np.testing.assert_allclose(table.to_numpy(float), old.to_numpy(float), rtol=1e-14, atol=5.1e-11)
        if "heatmap" in panel:
            weights = joint_w
            labels = [f"S{s}R{r}" for s in range(1, 6) for r in range(1, 6)]
        else:
            weights = resolution_w if "resolution" in panel else risk_w
            labels = [f"Q{q}" for q in range(1, 6)]
        table["membership_rows"] = table.contributing_calls
        table["contributing_calls"] = (weights > 0).sum(axis=0)
        table["fractional_mass"] = table.effective_n
        # Update counts only, preserving the exact historical mean/CI computation.
        tables[panel] = table.to_dict("records")
        table.to_csv(output / f"{number:02d}_{panel}.csv", index=False, float_format="%.17g")
        variable = "CAR_2_60_winsor" if "2_60" in panel else "CAR_0_1_winsor"
        contrast, covariance = pairwise_comparisons(frame[variable].to_numpy(), weights, frame.cik.to_numpy(), labels)
        np.testing.assert_allclose(np.sqrt(np.diag(covariance)), table.se_firm_clustered, rtol=1e-12, atol=1e-14)
        contrast.insert(0, "panel", panel)
        comparisons.append(contrast)
    pd.concat(comparisons, ignore_index=True).to_csv(output / "portfolio_comparisons.csv", index=False, float_format="%.17g")
    legacy.PAGE_CACHE = output / "pages"
    pdf = output / "portfolio_charts_fractional_ties.pdf"
    legacy.render_pdf(pdf, tables, "Modification 2 - fractional allocation of tied scores",
                      f"Full eligible sample: {len(frame):,} calls, {frame.cik.nunique():,} firms. Variables winsorized at 1% and 99%.",
                      "Tied score groups receive equal proportional membership; masses are equal within each SIC division and nested sort.", True)
    for number, panel in enumerate(PANELS, 1):
        shutil.copyfile(legacy.PAGE_CACHE / f"{pdf.stem}_page_{number}.png", output / f"{number:02d}_{panel}.png")
    print(json.dumps({"output": str(output), "historical_panels_verified": 5,
                      "eligible_calls": len(frame), "eligible_firms": int(frame.cik.nunique())}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=PACKAGE)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/fractional_reproduction_v1")
    args = parser.parse_args()
    reproduce(args.package.resolve(), args.output.resolve())
