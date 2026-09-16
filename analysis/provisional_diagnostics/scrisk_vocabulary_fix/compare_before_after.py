#!/usr/bin/env python3
"""Compare the original SCRisk run against the corrected-vocabulary run.

Reads two ``earnings_call_event_returns.csv`` files and the sensitivity
variants' compact score CSVs.  Writes only to the output directory.  Nothing
here recomputes a score: every number is read from a run that was produced by
the pipeline itself.

Populations
-----------

The two runs do not have the same analysable population: the transcript
integrity filter excludes some events from the after run that the before run
kept.  Zero rates are reported on each run's own analysable population, and
the flip analysis on the events analysable in both, so no call is counted as
a change when what actually changed was its eligibility.  Both counts are
written to ``before_after_summary.json`` by the run itself; none are hard
coded here.

Provisional
-----------

This is a diagnostic on two of this repository's own scoring runs.  Neither
run is comparable to Theile et al. (2026): see "Known methodological gaps" in
the root README.  Nothing written here is a replication result.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

KEY = ["ticker", "quarter_label"]
QUANTILES = [0.2, 0.4, 0.6, 0.8]


def load_events(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, low_memory=False)
    for column in ("SCRisk", "Resolution", "CAR_0_1", "SCRisk_raw"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["year"] = pd.to_numeric(frame["year"], errors="coerce").astype("Int64")
    return frame


def analysable(frame: pd.DataFrame) -> pd.DataFrame:
    """Events the study uses: an estimated CAR and a defined SCRisk."""
    return frame[
        (frame["event_status"] == "ok") & frame["CAR_0_1"].notna() & frame["SCRisk"].notna()
    ].copy()


def zero_rate(frame: pd.DataFrame) -> dict:
    calls = len(frame)
    zeros = int((frame["SCRisk"] == 0).sum())
    return {
        "analysable_calls": calls,
        "zero_scores": zeros,
        "zero_percent": round(100 * zeros / calls, 2),
        "positive_scores": calls - zeros,
        "positive_percent": round(100 * (calls - zeros) / calls, 2),
    }


def distribution(series: pd.Series) -> dict:
    values = series.dropna()
    percentiles = [1, 5, 10, 25, 50, 75, 90, 95, 99]
    result = {
        "count": int(values.size),
        "mean": float(values.mean()),
        "sd": float(values.std(ddof=0)),
        "min": float(values.min()),
        "max": float(values.max()),
        "share_zero": round(float((values == 0).mean()), 4),
    }
    for percentile, value in zip(percentiles, np.percentile(values, percentiles)):
        result[f"p{percentile}"] = float(value)
    positive = values[values > 0]
    result["positive_mean"] = float(positive.mean())
    result["positive_median"] = float(positive.median())
    return result


def quintile_table(frame: pd.DataFrame, score: str = "SCRisk") -> pd.DataFrame:
    """Zero group then five equal-count groups of the positive scores.

    Provisional and NOT the paper's construction.  The paper sorts the whole
    analysable sample into quintiles; this drops the zero-score calls into
    their own group first and cuts quintiles within the positive scores only,
    because this pipeline's dictionaries leave a large share of calls at
    exactly zero.  The two are not interchangeable, so no number out of this
    table can be compared to a paper quintile.
    """
    zero = frame[frame[score] == 0.0]
    positive = frame[frame[score] > 0.0].sort_values(score)
    boundaries = np.quantile(positive[score].to_numpy(), QUANTILES)
    index = np.searchsorted(boundaries, positive[score].to_numpy(), side="right")
    rows = [{"group": "Score = 0", "events": len(zero),
             "mean_car_0_1": zero["CAR_0_1"].mean(), "median_car_0_1": zero["CAR_0_1"].median(),
             "min_score": 0.0, "max_score": 0.0}]
    for quintile in range(5):
        block = positive[index == quintile]
        rows.append({
            "group": f"Q{quintile + 1}",
            "events": len(block),
            "mean_car_0_1": block["CAR_0_1"].mean(),
            "median_car_0_1": block["CAR_0_1"].median(),
            "min_score": block[score].min(),
            "max_score": block[score].max(),
        })
    table = pd.DataFrame(rows)
    table["mean_car_0_1_bp"] = (table["mean_car_0_1"] * 10_000).round(2)
    table["median_car_0_1_bp"] = (table["median_car_0_1"] * 10_000).round(2)
    return table


def grouped_change(merged: pd.DataFrame, column: str) -> pd.DataFrame:
    """Zero rate and mean SCRisk before and after, within one grouping column."""
    grouped = merged.groupby(column, dropna=False)
    table = pd.DataFrame({
        "analysable_calls": grouped.size(),
        "zeros_before": grouped.apply(lambda g: int((g["SCRisk_before"] == 0).sum()), include_groups=False),
        "zeros_after": grouped.apply(lambda g: int((g["SCRisk_after"] == 0).sum()), include_groups=False),
        "mean_scrisk_before": grouped["SCRisk_before"].mean(),
        "mean_scrisk_after": grouped["SCRisk_after"].mean(),
        "median_scrisk_before": grouped["SCRisk_before"].median(),
        "median_scrisk_after": grouped["SCRisk_after"].median(),
    }).reset_index()
    table["zero_percent_before"] = (100 * table["zeros_before"] / table["analysable_calls"]).round(2)
    table["zero_percent_after"] = (100 * table["zeros_after"] / table["analysable_calls"]).round(2)
    table["zero_percent_change"] = (table["zero_percent_after"] - table["zero_percent_before"]).round(2)
    table["zeros_recovered"] = table["zeros_before"] - table["zeros_after"]
    return table


def sensitivity_table(before: pd.DataFrame, after: pd.DataFrame,
                      sensitivity_dir: Path | None) -> pd.DataFrame:
    """One row per variant, on that variant's own analysable population."""
    rows = [
        {"variant": "before (v1_library_only)", **zero_rate(before),
         "mean_scrisk": before["SCRisk"].mean(), "median_positive_scrisk": before.loc[before.SCRisk > 0, "SCRisk"].median(),
         "scrisk_sd_divisor": before["SCRisk_sd"].iloc[0]},
        {"variant": "after (v2_seeds_inflections)", **zero_rate(after),
         "mean_scrisk": after["SCRisk"].mean(), "median_positive_scrisk": after.loc[after.SCRisk > 0, "SCRisk"].median(),
         "scrisk_sd_divisor": after["SCRisk_sd"].iloc[0]},
    ]
    variants = sorted(p for p in sensitivity_dir.glob("*") if p.is_dir()) if sensitivity_dir else []
    for directory in variants:
        path = directory / "event_returns.csv"
        if not path.exists():
            continue
        frame = analysable(load_events(path))
        manifest = json.loads((directory / "scoring_manifest.json").read_text())
        rows.append({
            "variant": f"sensitivity: {directory.name}",
            **zero_rate(frame),
            "mean_scrisk": frame["SCRisk"].mean(),
            "median_positive_scrisk": frame.loc[frame.SCRisk > 0, "SCRisk"].median(),
            "scrisk_sd_divisor": manifest["SCRisk_sd"],
        })
    table = pd.DataFrame(rows)
    baseline = table.loc[table.variant.str.startswith("after"), "zero_percent"].iloc[0]
    table["zero_percent_vs_corrected"] = (table["zero_percent"] - baseline).round(2)
    return table


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--before", type=Path, required=True,
                        help="earnings_call_event_returns.csv for the baseline run")
    parser.add_argument("--after", type=Path, required=True,
                        help="earnings_call_event_returns.csv for the comparison run")
    parser.add_argument("--sensitivity-dir", type=Path,
                        help="directory of sensitivity variants, each with event_returns.csv "
                             "and scoring_manifest.json; omitted means no variant rows")
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    BEFORE, AFTER, OUT = args.before, args.after, args.output_dir
    for path in (BEFORE, AFTER):
        if not path.exists():
            raise SystemExit(f"missing input: {path}")
    OUT.mkdir(parents=True, exist_ok=True)
    before_all, after_all = load_events(BEFORE), load_events(AFTER)
    before, after = analysable(before_all), analysable(after_all)

    merged = before.merge(after, on=KEY, suffixes=("_before", "_after"))
    merged["scrisk_change"] = merged["SCRisk_after"] - merged["SCRisk_before"]
    merged["flip"] = np.select(
        [
            (merged.SCRisk_before == 0) & (merged.SCRisk_after > 0),
            (merged.SCRisk_before > 0) & (merged.SCRisk_after == 0),
            (merged.SCRisk_before == 0) & (merged.SCRisk_after == 0),
        ],
        ["zero_to_positive", "positive_to_zero", "zero_in_both"],
        default="positive_in_both",
    )

    excluded = after_all[after_all["event_status"] == "excluded_transcript_integrity"]
    summary = {
        "before": {"run": str(BEFORE.parent.name), **zero_rate(before)},
        "after": {"run": str(AFTER.parent.name), **zero_rate(after)},
        "zero_percent_change": round(
            zero_rate(after)["zero_percent"] - zero_rate(before)["zero_percent"], 2),
        "common_population": len(merged),
        "flips": merged["flip"].value_counts().to_dict(),
        "zero_to_positive_percent_of_before_zeros": round(
            100 * int((merged.flip == "zero_to_positive").sum())
            / int((merged.SCRisk_before == 0).sum()), 2),
        "excluded_for_transcript_integrity": {
            "calls": len(excluded),
            "zero_before": int((before.set_index(KEY).reindex(
                pd.MultiIndex.from_frame(excluded[KEY]))["SCRisk"] == 0).sum()),
            "identities": sorted(
                f"{row.ticker} {row.quarter_label} ({row.transcript_integrity_status}"
                f"; SCRisk_before="
                f"{before.set_index(KEY).at[(row.ticker, row.quarter_label), 'SCRisk']:.4f})"
                for row in excluded.itertuples()),
        },
        "scrisk_sd_divisor_before": float(before["SCRisk_sd"].iloc[0]),
        "scrisk_sd_divisor_after": float(after["SCRisk_sd"].iloc[0]),
        "scrisk_distribution_before": distribution(before["SCRisk"]),
        "scrisk_distribution_after": distribution(after["SCRisk"]),
        "scrisk_raw_distribution_before": distribution(before["SCRisk_raw"]),
        "scrisk_raw_distribution_after": distribution(after["SCRisk_raw"]),
        "scrisk_change_on_common_population": distribution(merged["scrisk_change"]),
        "spearman_scrisk_before_after": float(
            merged["SCRisk_before"].corr(merged["SCRisk_after"], method="spearman")),
        "pearson_scrisk_before_after": float(
            merged["SCRisk_before"].corr(merged["SCRisk_after"])),
    }
    (OUT / "before_after_summary.json").write_text(json.dumps(summary, indent=2, default=float))

    quintiles = pd.concat([
        quintile_table(before).assign(run="before"),
        quintile_table(after).assign(run="after"),
    ])[["run", "group", "events", "min_score", "max_score",
        "mean_car_0_1", "median_car_0_1", "mean_car_0_1_bp", "median_car_0_1_bp"]]
    quintiles.to_csv(OUT / "car_quintiles_before_after.csv", index=False)

    resolution_quintiles = pd.concat([
        quintile_table(before, "Resolution").assign(run="before"),
        quintile_table(after, "Resolution").assign(run="after"),
    ])
    resolution_quintiles.to_csv(OUT / "car_quintiles_resolution_before_after.csv", index=False)

    grouped_change(merged, "year_before").rename(
        columns={"year_before": "year"}).to_csv(OUT / "zero_rate_by_year.csv", index=False)
    grouped_change(merged, "sector_before").rename(
        columns={"sector_before": "sector"}).to_csv(OUT / "zero_rate_by_sector.csv", index=False)

    movers_columns = KEY + [
        "company_name_before", "sector_before", "year_before", "SCRisk_before", "SCRisk_after",
        "scrisk_change", "SCRisk_raw_before", "SCRisk_raw_after", "CAR_0_1_before", "flip",
    ]
    movers = merged.sort_values("scrisk_change", ascending=False)
    pd.concat([movers.head(40), movers.tail(40)])[movers_columns].rename(
        columns={"company_name_before": "company_name", "sector_before": "sector",
                 "year_before": "year", "CAR_0_1_before": "CAR_0_1"}
    ).to_csv(OUT / "largest_scrisk_changes.csv", index=False)

    merged[merged.flip == "zero_to_positive"][movers_columns].sort_values(
        "scrisk_change", ascending=False
    ).to_csv(OUT / "zero_to_positive_calls.csv", index=False)

    sensitivity_table(before, after, args.sensitivity_dir).to_csv(
        OUT / "sensitivity_summary.csv", index=False)

    print(json.dumps({k: v for k, v in summary.items() if not isinstance(v, dict)}, indent=2))
    print("\nbefore:", summary["before"])
    print("after: ", summary["after"])
    print("flips: ", summary["flips"])
    print(f"\nwrote 8 files to {OUT}")


if __name__ == "__main__":
    main()
