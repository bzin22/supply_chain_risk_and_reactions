#!/usr/bin/env python3
"""One full-size CAR-against-quintile chart per sector, not a combined figure.

``within_industry_quintiles.py`` pools the corresponding quintiles across
groups into one chart.  ``per_industry_quintiles.py`` puts every group in a
small-multiple grid.  This script writes a separate, full-size figure for each
group, styled like the study's existing
``outputs/scrisk_car_event_charts/01_mean_car_by_scrisk_quintile.png``: that
group's zero-score calls, then its own Q1 to Q5, with confidence intervals and
counts.

Quintiles are cut inside the group on its positive scores, so Q5 means "high
SCRisk for this sector" rather than "high SCRisk in the corpus".  A sector's Q1
can hold higher raw scores than another sector's Q5.

The nine figures share one y-axis by default so they can be read against each
other; ``--autoscale`` gives each figure its own range instead.

Default input is the ``no_self_pairs`` sensitivity run.  Nothing is rescored.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import PercentFormatter

import within_industry_quintiles as W

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "outputs/scrisk_car_quintile_charts_by_sector"
ZERO_COLOR = W.ZERO_COLOR
QUINTILE_COLORS = W.QUINTILE_COLORS
LABELS = ["Score = 0", "Q1", "Q2", "Q3", "Q4", "Q5"]


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def group_table(
    usable: pd.DataFrame, zeros: pd.DataFrame, group: str, rng: np.random.Generator
) -> pd.DataFrame:
    """The six rows behind one group's figure: its zero group and its quintiles."""
    rows = [W.group_row("Score = 0", zeros[zeros["industry"] == group], rng)]
    block = usable[usable["industry"] == group]
    for quintile in range(1, W.QUINTILE_COUNT + 1):
        rows.append(W.group_row(f"Q{quintile}", block[block["quintile"] == quintile], rng))
    table = pd.DataFrame(rows)
    table.insert(0, "group_name", group)
    return table


def plot_group(
    table: pd.DataFrame, group: str, statistic: str, limits: tuple[float, float] | None,
    path: Path, label: str,
) -> None:
    if statistic == "mean":
        estimates = table["mean_car_0_1_bp"].to_numpy() / 10_000
        lower = (table["mean_car_0_1_bp"] - table["mean_ci_low_bp"]).to_numpy() / 10_000
        upper = (table["mean_ci_high_bp"] - table["mean_car_0_1_bp"]).to_numpy() / 10_000
        title = f"{group}: mean CAR(0, 1) by SCRisk quintile"
        note = (f"Quintiles cut inside {group} on its positive SCRisk scores. "
                f"Whiskers show 95% confidence intervals.")
    else:
        estimates = table["median_car_0_1_bp"].to_numpy() / 10_000
        lower = (table["median_car_0_1_bp"] - table["median_ci_low_bp"]).to_numpy() / 10_000
        upper = (table["median_ci_high_bp"] - table["median_car_0_1_bp"]).to_numpy() / 10_000
        title = f"{group}: median CAR(0, 1) by SCRisk quintile"
        note = (f"Quintiles cut inside {group} on its positive SCRisk scores. "
                f"Whiskers show bootstrap 95% confidence intervals.")

    figure, axis = plt.subplots(figsize=(8.6, 5.5))
    x = np.arange(len(LABELS))
    axis.bar(x, estimates, yerr=[lower, upper], capsize=3,
             color=[ZERO_COLOR, *QUINTILE_COLORS], edgecolor="none", zorder=2)
    axis.set_xticks(x, LABELS)
    axis.set_xlabel(f"SCRisk group within {label}")
    axis.set_title(title, pad=12, weight="bold")
    axis.axhline(0, color="#3B3B3B", linewidth=0.8, zorder=1)
    axis.grid(axis="y", color="#E5E5E5", linewidth=0.8, zorder=0)
    axis.spines[["top", "right"]].set_visible(False)
    axis.set_ylabel("CAR(0, 1) (%)")
    axis.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=2))
    if limits is not None:
        axis.set_ylim(*limits)
    # Counts sit in one row just below the top of the axes.  Tracking the bar
    # puts the label under the axis whenever a negative bar has a long
    # whisker, which clipped Healthcare's Q5, and a fixed row is easier to
    # read across the nine figures anyway.
    floor, ceiling = axis.get_ylim()
    label_y = ceiling - 0.04 * (ceiling - floor)
    for position, events in zip(x, table["events"]):
        axis.annotate(f"n={events:,}", (position, label_y), ha="center", va="top",
                      fontsize=8, color="#4D4D4D")
    total = int(table["events"].sum())
    positives = total - int(table.loc[table.group == "Score = 0", "events"].iloc[0])
    figure.text(0.5, 0.055, f"{total:,} analysable calls, {positives:,} with a positive score.",
                ha="center", va="bottom", color="#4D4D4D", fontsize=8.5)
    figure.text(0.5, 0.01, note, ha="center", va="bottom", color="#4D4D4D", fontsize=8.5)
    figure.tight_layout(rect=(0, 0.075, 1, 0.95))
    figure.savefig(path, dpi=240, bbox_inches="tight")
    plt.close(figure)


def shared_limits(tables: dict[str, pd.DataFrame], statistic: str) -> tuple[float, float]:
    """One y-range wide enough for every group's estimates and whiskers."""
    low, high = [], []
    for table in tables.values():
        if statistic == "mean":
            low.append(table["mean_ci_low_bp"].min())
            high.append(table["mean_ci_high_bp"].max())
        else:
            low.append(table["median_ci_low_bp"].min())
            high.append(table["median_ci_high_bp"].max())
    floor, ceiling = min(low) / 10_000, max(high) / 10_000
    pad = 0.08 * (ceiling - floor)
    return floor - pad, ceiling + pad


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=W.DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--group-column", default="sector",
                        help="sector for the study's 9 categories, industry for the "
                             "provider's 91 finer labels; default: sector")
    parser.add_argument("--min-positives", type=int, default=W.MIN_POSITIVES_PER_INDUSTRY)
    parser.add_argument("--autoscale", action="store_true",
                        help="give each figure its own y-range instead of one shared range")
    parser.add_argument("--statistic", choices=("mean", "median", "both"), default="both")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    W.GROUP_LABEL = args.group_column

    frame = W.load_events(args.input)
    if args.group_column != "industry":
        frame["industry"] = frame[args.group_column].fillna("").str.strip()
    usable, meta = W.build(frame, "positives_only", args.min_positives)
    kept = sorted(set(usable["industry"]))
    zeros = frame[(frame["SCRisk"] == 0.0) & frame["industry"].isin(set(kept))]

    rng = np.random.default_rng(W.BOOTSTRAP_SEED)
    tables = {group: group_table(usable, zeros, group, rng) for group in kept}
    # Order the files by size so 01 is the largest group.
    order = sorted(kept, key=lambda g: -int(tables[g]["events"].sum()))

    statistics = ("mean", "median") if args.statistic == "both" else (args.statistic,)
    written = []
    for statistic in statistics:
        limits = None if args.autoscale else shared_limits(tables, statistic)
        for index, group in enumerate(order, start=1):
            path = args.output / f"{index:02d}_{slug(group)}_{statistic}_car_by_scrisk_quintile.png"
            plot_group(tables[group], group, statistic, limits, path, args.group_column)
            written.append(path.name)

    combined = pd.concat([tables[group] for group in order], ignore_index=True)
    combined = combined.rename(columns={"group_name": args.group_column})
    combined.to_csv(args.output / f"car_quintiles_by_{args.group_column}.csv", index=False)

    summary = {
        "input": str(args.input),
        "group_column": args.group_column,
        "groups": len(kept),
        "groups_excluded": meta["industries_excluded"],
        "excluded_group_names": meta["excluded_industry_names"],
        "positive_calls_ranked": meta["observations_ranked"],
        "zero_calls": int(len(zeros)),
        "shared_y_axis": not args.autoscale,
        "figures": written,
        "quintile_cell_range": [int(combined.loc[combined.group != "Score = 0", "events"].min()),
                                int(combined.loc[combined.group != "Score = 0", "events"].max())],
        "q5_minus_q1_mean_bp": {
            group: round(
                float(tables[group].loc[tables[group].group == "Q5", "mean_car_0_1_bp"].iloc[0]
                      - tables[group].loc[tables[group].group == "Q1", "mean_car_0_1_bp"].iloc[0]),
                2)
            for group in order
        },
    }
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2))

    print(f"input: {args.input}")
    print(f"{len(kept)} {W.plural(args.group_column)}, one figure each per statistic "
          f"({len(written)} PNGs), shared y-axis: {not args.autoscale}")
    for group in order:
        table = tables[group]
        means = table.loc[table.group != "Score = 0", "mean_car_0_1_bp"].tolist()
        zero = table.loc[table.group == "Score = 0", "mean_car_0_1_bp"].iloc[0]
        print(f"  {group:<20s} zero={zero:>8.2f}  Q1..Q5="
              f"{' '.join(f'{value:>8.2f}' for value in means)}  "
              f"Q5-Q1={summary['q5_minus_q1_mean_bp'][group]:>8.2f}")
    print(f"\nwrote {args.output}")


if __name__ == "__main__":
    main()
