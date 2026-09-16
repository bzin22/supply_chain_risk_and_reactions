#!/usr/bin/env python3
"""Report the SCRisk quintile pattern inside each industry, without pooling.

The pooled version of this is in ``within_industry_quintiles.py``: cut each
industry into five quintiles, then pool the Q1s, Q2s and so on.  Pooling hides
whether the pattern is shared.  A flat pooled line is produced both by 78
industries that each have no relationship and by 39 with a strong positive
relationship cancelling 39 with a strong negative one.

This script stops before the pooling step.  It reports every industry's own
Q1 to Q5 table, the Q5 minus Q1 spread with a confidence interval, and then
asks one question of the 78 spreads: do more industries show a positive spread
than chance would give?  Under no relationship each industry is a coin flip,
so the expectation is 39 of 78.

Same cut as the pooled version: the ``no_self_pairs`` sensitivity run, zero
scores held out, positive scores ranked inside each industry and split into
five equal-count groups, industries with fewer than 25 positives excluded.

Nothing here rescores anything.  It reads one event-returns CSV.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import PercentFormatter
from scipy import stats

import within_industry_quintiles as W

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "outputs/scrisk_per_industry_quintiles"

# 6 across suits 78 panels; 3 across suits 9.  Set with --grid-columns.
GRID_COLUMNS = 6
# Panels share one y-axis so the industries are comparable at a glance.  A
# quintile mean built on five calls can run to several percent, which would
# flatten every other panel, so the axis is clipped and clipped bars are
# marked rather than silently cut off.
GRID_Y_LIMIT = 0.02
QUINTILE_COLORS = W.QUINTILE_COLORS
POSITIVE_COLOR = "#176C98"
NEGATIVE_COLOR = "#B23A48"


def industry_rows(usable: pd.DataFrame) -> pd.DataFrame:
    """One row per group-quintile: counts, score range and CAR with a CI."""
    rows = []
    rng = np.random.default_rng(W.BOOTSTRAP_SEED)
    for industry, block in usable.groupby("industry"):
        for quintile in range(1, W.QUINTILE_COUNT + 1):
            cell = block[block["quintile"] == quintile]
            car = cell["CAR_0_1"].to_numpy()
            mean, half_width = W.mean_ci(car)
            median, lower, upper = W.median_ci(car, rng)
            rows.append({
                W.GROUP_LABEL: industry,
                "quintile": f"Q{quintile}",
                "events": len(cell),
                "min_scrisk": float(cell["SCRisk"].min()),
                "median_scrisk": float(cell["SCRisk"].median()),
                "max_scrisk": float(cell["SCRisk"].max()),
                "mean_car_0_1_bp": round(10_000 * mean, 2),
                "mean_ci_low_bp": round(10_000 * (mean - half_width), 2),
                "mean_ci_high_bp": round(10_000 * (mean + half_width), 2),
                "median_car_0_1_bp": round(10_000 * median, 2),
                "median_ci_low_bp": round(10_000 * lower, 2),
                "median_ci_high_bp": round(10_000 * upper, 2),
            })
    return pd.DataFrame(rows)


def spread_rows(usable: pd.DataFrame) -> pd.DataFrame:
    """Q5 minus Q1 per industry, with a Welch interval on the mean difference."""
    rows = []
    for industry, block in usable.groupby("industry"):
        low = block.loc[block["quintile"] == 1, "CAR_0_1"].to_numpy()
        high = block.loc[block["quintile"] == 5, "CAR_0_1"].to_numpy()
        difference = float(high.mean() - low.mean())
        # Welch, because the two quintiles have no reason to share a variance.
        test = stats.ttest_ind(high, low, equal_var=False)
        standard_error = math.sqrt(
            high.var(ddof=1) / len(high) + low.var(ddof=1) / len(low)
        )
        rows.append({
            W.GROUP_LABEL: industry,
            "positive_calls": len(block),
            "q1_events": len(low),
            "q5_events": len(high),
            "q1_mean_car_bp": round(10_000 * float(low.mean()), 2),
            "q5_mean_car_bp": round(10_000 * float(high.mean()), 2),
            "q5_minus_q1_mean_bp": round(10_000 * difference, 2),
            "q5_minus_q1_ci_low_bp": round(10_000 * (difference - 1.96 * standard_error), 2),
            "q5_minus_q1_ci_high_bp": round(10_000 * (difference + 1.96 * standard_error), 2),
            "welch_p": round(float(test.pvalue), 4),
            "q5_minus_q1_median_bp": round(
                10_000 * float(np.median(high) - np.median(low)), 2),
            "direction": "positive" if difference > 0 else "negative",
        })
    return pd.DataFrame(rows).sort_values("q5_minus_q1_mean_bp", ascending=False)


def monotonicity(per_industry: pd.DataFrame) -> pd.DataFrame:
    """Spearman correlation between quintile number and mean CAR, per group."""
    rows = []
    for industry, block in per_industry.groupby(W.GROUP_LABEL):
        ordered = block.sort_values("quintile")
        means = ordered["mean_car_0_1_bp"].to_numpy()
        correlation, pvalue = stats.spearmanr(np.arange(1, 6), means)
        rows.append({
            W.GROUP_LABEL: industry,
            "spearman_quintile_vs_mean_car": round(float(correlation), 4),
            "spearman_p": round(float(pvalue), 4),
            "monotone_increasing": bool(np.all(np.diff(means) > 0)),
            "monotone_decreasing": bool(np.all(np.diff(means) < 0)),
        })
    return pd.DataFrame(rows)


def evidence(spreads: pd.DataFrame) -> dict:
    """Does the count of positive spreads beat a coin flip across industries?"""
    industries = len(spreads)
    positive = int((spreads["q5_minus_q1_mean_bp"] > 0).sum())
    binomial = stats.binomtest(positive, industries, 0.5)
    differences = spreads["q5_minus_q1_mean_bp"].to_numpy()
    one_sample = stats.ttest_1samp(differences, 0.0)
    signed_rank = stats.wilcoxon(differences)
    significant = spreads[spreads["welch_p"] < 0.05]
    # What size of effect this design could have detected.  The spreads are
    # one observation per industry, so their SD over sqrt(n) is the standard
    # error of the pooled answer, and 1.96 of those is the width the data can
    # resolve.  Anything smaller than that is invisible here whether or not it
    # is real.
    standard_error = float(differences.std(ddof=1)) / math.sqrt(industries)
    return {
        "industries": industries,
        "positive_q5_minus_q1": positive,
        "negative_q5_minus_q1": industries - positive,
        "expected_positive_under_no_relationship": industries / 2,
        "binomial_p": round(float(binomial.pvalue), 4),
        "mean_spread_bp": round(float(differences.mean()), 2),
        "median_spread_bp": round(float(np.median(differences)), 2),
        "sd_of_spreads_bp": round(float(differences.std(ddof=1)), 2),
        "one_sample_t_on_the_group_spreads": {
            "t": round(float(one_sample.statistic), 4),
            "p": round(float(one_sample.pvalue), 4),
        },
        "wilcoxon_signed_rank_p": round(float(signed_rank.pvalue), 4),
        "standard_error_of_mean_spread_bp": round(standard_error, 2),
        "mean_spread_ci_low_bp": round(float(differences.mean()) - 1.96 * standard_error, 2),
        "mean_spread_ci_high_bp": round(float(differences.mean()) + 1.96 * standard_error, 2),
        "smallest_detectable_spread_bp": round(1.96 * standard_error, 2),
        "industries_with_welch_p_below_0_05": int(len(significant)),
        "expected_false_positives_at_0_05": round(0.05 * industries, 2),
        "significant_groups": significant[
            [W.GROUP_LABEL, "q5_minus_q1_mean_bp", "welch_p", "q1_events", "q5_events"]
        ].to_dict("records"),
    }


def plot_grid(per_industry: pd.DataFrame, spreads: pd.DataFrame, path: Path) -> None:
    order = spreads.sort_values(
        "positive_calls", ascending=False)[W.GROUP_LABEL].tolist()
    rows = math.ceil(len(order) / GRID_COLUMNS)
    figure, axes = plt.subplots(
        rows, GRID_COLUMNS, figsize=(2.5 * GRID_COLUMNS, 1.85 * rows), sharey=True
    )
    flat = axes.ravel()
    clipped = 0
    for axis, industry in zip(flat, order):
        block = per_industry[
            per_industry[W.GROUP_LABEL] == industry].sort_values("quintile")
        values = block["mean_car_0_1_bp"].to_numpy() / 10_000
        drawn = np.clip(values, -GRID_Y_LIMIT, GRID_Y_LIMIT)
        clipped += int(np.sum(np.abs(values) > GRID_Y_LIMIT))
        axis.bar(np.arange(5), drawn, color=QUINTILE_COLORS, edgecolor="none", zorder=2)
        for index, (value, shown) in enumerate(zip(values, drawn)):
            if abs(value) > GRID_Y_LIMIT:
                axis.annotate("^" if value > 0 else "v", (index, shown),
                              xytext=(0, 1 if value > 0 else -7), textcoords="offset points",
                              ha="center", fontsize=6, color="#B23A48")
        axis.axhline(0, color="#3B3B3B", linewidth=0.6, zorder=1)
        axis.set_xticks([])
        axis.set_ylim(-GRID_Y_LIMIT, GRID_Y_LIMIT)
        axis.spines[["top", "right"]].set_visible(False)
        label = industry if len(industry) <= 26 else industry[:24] + ".."
        total = int(spreads.loc[
            spreads[W.GROUP_LABEL] == industry, "positive_calls"].iloc[0])
        axis.set_title(f"{label}\nn={total}", fontsize=6.5, pad=3)
        axis.tick_params(labelsize=6)
        axis.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    for axis in flat[len(order):]:
        axis.set_visible(False)
    figure.suptitle(
        f"Mean CAR(0, 1) by SCRisk quintile, inside each {W.GROUP_LABEL}",
        y=1.0, fontsize=13, weight="bold",
    )
    figure.text(
        0.5, -0.004,
        f"Bars are Q1 to Q5 left to right, cut inside that {W.GROUP_LABEL} on positive "
        f"SCRisk. Panels ordered by positive-call count and share one axis clipped at "
        f"+/-{GRID_Y_LIMIT:.0%}; {clipped} bars exceed it and are marked.",
        ha="center", va="top", color="#4D4D4D", fontsize=8.5,
    )
    figure.tight_layout(rect=(0, 0.004, 1, 0.985))
    figure.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(figure)


def plot_spread_histogram(spreads: pd.DataFrame, summary: dict, path: Path) -> None:
    values = spreads["q5_minus_q1_mean_bp"].to_numpy()
    figure, axis = plt.subplots(figsize=(9.0, 5.4))
    limit = float(np.percentile(np.abs(values), 97.5))
    bins = np.linspace(-limit, limit, 31)
    axis.hist(np.clip(values, -limit, limit), bins=bins, color=QUINTILE_COLORS[2],
              edgecolor="white", linewidth=0.5, zorder=2)
    axis.axvline(0, color="#3B3B3B", linewidth=1.0, zorder=3)
    axis.axvline(values.mean(), color=NEGATIVE_COLOR, linewidth=1.6, zorder=4,
                 label=f"mean {values.mean():.0f} bp")
    axis.axvline(np.median(values), color=POSITIVE_COLOR, linewidth=1.6, linestyle="--",
                 zorder=4, label=f"median {np.median(values):.0f} bp")
    axis.set_title(
        f"Q5 minus Q1 mean CAR(0, 1), one observation per {W.GROUP_LABEL}",
        pad=12, weight="bold")
    axis.set_xlabel("Q5 mean CAR minus Q1 mean CAR (basis points)")
    axis.set_ylabel(W.plural(W.GROUP_LABEL).title())
    axis.grid(axis="y", color="#E5E5E5", linewidth=0.8, zorder=0)
    axis.spines[["top", "right"]].set_visible(False)
    axis.legend(frameon=False, fontsize=9)
    figure.text(
        0.5, 0.01,
        f"{summary['positive_q5_minus_q1']} of {summary['industries']} "
        f"{W.plural(W.GROUP_LABEL)} are "
        f"positive against {summary['expected_positive_under_no_relationship']:.0f} expected "
        f"under no relationship, binomial p = {summary['binomial_p']}. "
        f"Values clipped at the 97.5th percentile of absolute spread.",
        ha="center", va="bottom", color="#4D4D4D", fontsize=8.5,
    )
    figure.tight_layout(rect=(0, 0.05, 1, 0.95))
    figure.savefig(path, dpi=240, bbox_inches="tight")
    plt.close(figure)


def main() -> None:
    global GRID_COLUMNS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=W.DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--min-positives", type=int, default=W.MIN_POSITIVES_PER_INDUSTRY)
    parser.add_argument("--group-column", default="industry",
                        help="sector for the study's 9 categories, industry for the "
                             "provider's 91 finer labels; default: industry")
    parser.add_argument("--grid-columns", type=int, default=GRID_COLUMNS,
                        help="panels across in the small-multiple grid; use 3 for sectors")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    GRID_COLUMNS = args.grid_columns
    W.GROUP_LABEL = args.group_column

    frame = W.load_events(args.input)
    if args.group_column != "industry":
        frame["industry"] = frame[args.group_column].fillna("").str.strip()
    usable, meta = W.build(frame, "positives_only", args.min_positives)

    per_industry = industry_rows(usable)
    label = args.group_column
    per_industry.to_csv(args.output / f"per_{label}_quintiles.csv", index=False)
    spreads = spread_rows(usable)
    spreads.to_csv(args.output / f"per_{label}_q5_minus_q1.csv", index=False)
    shape = monotonicity(per_industry)
    shape.to_csv(args.output / f"per_{label}_monotonicity.csv", index=False)

    summary = evidence(spreads)
    summary["input"] = str(args.input)
    summary["group_column"] = args.group_column
    summary["positive_calls_ranked"] = meta["observations_ranked"]
    summary["industries_excluded"] = meta["industries_excluded"]
    summary["calls_in_excluded_industries"] = meta["calls_in_excluded_industries"]
    increasing = int(shape["monotone_increasing"].sum())
    decreasing = int(shape["monotone_decreasing"].sum())
    # Five quintile means have 120 orderings and 2 of them are monotone, so
    # under exchangeable means each industry is monotone either way with
    # probability 1/60 and one direction with probability 1/120.
    summary["monotone_increasing_groups"] = increasing
    summary["monotone_decreasing_groups"] = decreasing
    summary["expected_monotone_either_way_under_no_relationship"] = round(
        2 * len(shape) / math.factorial(5), 2)
    summary["monotone_either_way_binomial_p"] = round(float(stats.binomtest(
        increasing + decreasing, len(shape), 2 / math.factorial(5),
        alternative="greater").pvalue), 4)
    summary["monotone_increasing_binomial_p"] = round(float(stats.binomtest(
        increasing, len(shape), 1 / math.factorial(5),
        alternative="greater").pvalue), 4)
    summary["smallest_quintile_cell"] = int(per_industry["events"].min())
    summary["median_quintile_cell"] = float(per_industry["events"].median())
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2))

    plot_grid(per_industry, spreads,
              args.output / f"01_quintile_pattern_by_{label}_grid.png")
    plot_spread_histogram(spreads, summary,
                          args.output / "02_q5_minus_q1_spread_histogram.png")

    print(f"input: {args.input}")
    print(f"{meta['industries_ranked']} {W.plural(label)}, "
          f"{meta['observations_ranked']:,} positive "
          f"calls; quintile cells run {per_industry['events'].min()} to "
          f"{per_industry['events'].max()} calls, median "
          f"{per_industry['events'].median():.0f}")
    print(f"\npositive Q5 minus Q1: {summary['positive_q5_minus_q1']} of "
          f"{summary['industries']} {W.plural(label)} (expected "
          f"{summary['expected_positive_under_no_relationship']:.0f}), "
          f"binomial p = {summary['binomial_p']}")
    print(f"mean spread {summary['mean_spread_bp']} bp, median "
          f"{summary['median_spread_bp']} bp, SD {summary['sd_of_spreads_bp']} bp")
    print(f"one-sample t on the {summary['industries']} spreads: "
          f"t = {summary['one_sample_t_on_the_group_spreads']['t']}, "
          f"p = {summary['one_sample_t_on_the_group_spreads']['p']}")
    print(f"Wilcoxon signed-rank p = {summary['wilcoxon_signed_rank_p']}")
    print(f"mean spread 95% CI: {summary['mean_spread_ci_low_bp']} to "
          f"{summary['mean_spread_ci_high_bp']} bp; this design can only resolve a spread "
          f"bigger than {summary['smallest_detectable_spread_bp']} bp")
    print(f"{W.plural(label)} with Welch p < 0.05: "
          f"{summary['industries_with_welch_p_below_0_05']} "
          f"(expected {summary['expected_false_positives_at_0_05']} by chance)")
    print(f"monotone increasing: {summary['monotone_increasing_groups']} "
          f"(p = {summary['monotone_increasing_binomial_p']}), "
          f"decreasing: {summary['monotone_decreasing_groups']}; "
          f"either way expected "
          f"{summary['expected_monotone_either_way_under_no_relationship']}, "
          f"observed p = {summary['monotone_either_way_binomial_p']}")
    print("\ntop 6 and bottom 6 by Q5 minus Q1:")
    columns = [label, "positive_calls", "q1_mean_car_bp", "q5_mean_car_bp",
               "q5_minus_q1_mean_bp", "welch_p"]
    # head(6) + tail(6) would print the same rows twice when there are only
    # 9 groups, so show every row once whenever the list is short.
    shown = spreads if len(spreads) <= 14 else pd.concat([spreads.head(6), spreads.tail(6)])
    print(shown[columns].to_string(index=False))
    print(f"\nwrote {args.output}")


if __name__ == "__main__":
    main()
