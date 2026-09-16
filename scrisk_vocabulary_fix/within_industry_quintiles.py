#!/usr/bin/env python3
"""Rebuild the SCRisk quintiles within industry, then pool across industries.

The published quintiles are cut on the pooled distribution, so a call's
quintile depends on how supply-chain-heavy its industry is rather than on how
supply-chain-heavy the call is for its industry.  Semiconductors and Insurance
Brokers do not talk about supply chains at the same rate, so a pooled Q5 is
partly a list of semiconductor calls.

This script ranks each industry's observations on SCRisk, cuts that industry
into five equal-count quintiles, and pools the Q1s together, the Q2s together
and so on.  Each industry then contributes about a fifth of its calls to every
quintile, so industry mix is held roughly constant across the five groups and
the comparison is within-industry by construction.

Default input is the ``no_self_pairs`` sensitivity run: the corrected
vocabulary with the zero-distance self-match of ``shortage`` / ``shortages``
refused.  See ``outputs/scrisk_vocabulary_fix/self_pair_terms.csv``.

Two readings of "divide each industry's observations into five quintiles" are
both produced, because they answer different questions:

``positives_only``   the primary output, and the one comparable with the
                     existing figures.  Zero-score calls are a mass point,
                     43.1% of this run, so they are held out as their own
                     pooled group and the quintiles are cut on the positive
                     scores within each industry.
``all_observations`` every call is ranked, zeros included.  Q1 is then mostly
                     zeros in most industries, and in some it is entirely
                     zeros, which makes the low quintiles a statement about
                     how many zeros an industry has.  Reported for
                     completeness, not recommended.

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

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = (
    ROOT / "artifacts/earnings_call_supply_chain/ppmi_svd_full_20260910_vocab_v2"
    / "sensitivity/no_self_pairs/event_returns.csv"
)
DEFAULT_OUTPUT = ROOT / "outputs/scrisk_within_industry_quintiles"

# An industry needs at least five calls per quintile for a quintile mean to
# mean anything, so 25 is the floor.  Industries below it are reported, not
# silently dropped.
MIN_POSITIVES_PER_INDUSTRY = 25
QUINTILE_COUNT = 5
BOOTSTRAP_SAMPLES = 2_000
BOOTSTRAP_SEED = 20260915

# The event returns CSV carries two grouping columns.  ``sector`` holds the
# study's 9 categories; ``industry`` holds the data provider's 91 finer labels
# ("REIT - Office", "Tobacco").  Both are inherited names.  The grouping
# column is chosen with --group-column and this label follows it through every
# title, note and output column so a figure cannot claim the wrong one.
GROUP_LABEL = "industry"


def plural(word: str) -> str:
    """English plural for the grouping label: industry -> industries, sector -> sectors."""
    if word.endswith("y") and len(word) > 1 and word[-2] not in "aeiou":
        return word[:-1] + "ies"
    return word + "s"

ZERO_COLOR = "#7A7A7A"
QUINTILE_COLORS = ["#DCE7F5", "#B8D0EA", "#82B4D4", "#4D92BD", "#176C98"]
POOLED_COLOR = "#B23A48"


def load_events(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, low_memory=False)
    for column in ("SCRisk", "CAR_0_1"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    analysable = frame[
        (frame["event_status"] == "ok") & frame["CAR_0_1"].notna() & frame["SCRisk"].notna()
    ].copy()
    analysable["industry"] = analysable["industry"].fillna("").str.strip()
    if (analysable["industry"] == "").any():
        raise ValueError("some analysable events have no industry label")
    return analysable


def assign_quintiles_by_rank(frame: pd.DataFrame) -> pd.Series:
    """Rank on SCRisk, then cut the ranks into five equal-count groups.

    Ties are broken by ticker and quarter so the split is reproducible.  In
    this run only 25 of 10,155 positive observations sit in a within-industry
    tie and the largest tie is 3, so the tie rule moves almost nothing; a
    quantile-boundary cut that keeps ties together gives the same answer to
    within a handful of calls.
    """
    ordered = frame.sort_values(["SCRisk", "ticker", "quarter_label"], kind="mergesort")
    position = np.arange(len(ordered))
    quintile = (position * QUINTILE_COUNT) // len(ordered) + 1
    return pd.Series(quintile, index=ordered.index, name="quintile")


def build(frame: pd.DataFrame, mode: str, min_positives: int) -> tuple[pd.DataFrame, dict]:
    """Attach a within-industry quintile to every usable observation."""
    if mode == "positives_only":
        rankable = frame[frame["SCRisk"] > 0]
    elif mode == "all_observations":
        rankable = frame
    else:
        raise ValueError(f"unknown mode {mode!r}")

    counts = rankable.groupby("industry").size()
    kept = set(counts[counts >= min_positives].index)
    dropped = sorted(set(counts.index) - kept)
    # An industry with no rankable observation at all never reaches `counts`.
    absent = sorted(set(frame["industry"].unique()) - set(counts.index))

    usable = rankable[rankable["industry"].isin(kept)].copy()
    # Concatenating per-industry Series keeps the shape unambiguous.
    # groupby().apply() collapses to a DataFrame when only one group survives
    # the threshold, which then cannot be assigned to a single column.
    if usable.empty:
        raise ValueError("no industry has enough observations to cut into quintiles")
    usable["quintile"] = pd.concat(
        [assign_quintiles_by_rank(block) for _, block in usable.groupby("industry")]
    )
    if usable["quintile"].isna().any():
        raise ValueError("a rankable observation was left without a quintile")

    excluded_industries = dropped + absent
    excluded_calls = int(frame[frame["industry"].isin(excluded_industries)].shape[0])
    meta = {
        "mode": mode,
        "min_rankable_per_industry": min_positives,
        "industries_total": int(frame["industry"].nunique()),
        "industries_ranked": len(kept),
        "industries_excluded": len(excluded_industries),
        "excluded_industry_names": excluded_industries,
        "calls_in_excluded_industries": excluded_calls,
        "observations_ranked": int(len(usable)),
    }
    return usable, meta


def mean_ci(values: np.ndarray) -> tuple[float, float]:
    mean = float(np.mean(values))
    if len(values) < 2:
        return mean, 0.0
    return mean, 1.96 * float(np.std(values, ddof=1)) / math.sqrt(len(values))


def median_ci(values: np.ndarray, rng: np.random.Generator) -> tuple[float, float, float]:
    median = float(np.median(values))
    boot = np.median(
        rng.choice(values, size=(BOOTSTRAP_SAMPLES, len(values)), replace=True), axis=1
    )
    lower, upper = np.quantile(boot, [0.025, 0.975])
    return median, float(lower), float(upper)


def group_row(label: str, block: pd.DataFrame, rng: np.random.Generator) -> dict:
    car = block["CAR_0_1"].to_numpy()
    mean, half_width = mean_ci(car)
    median, lower, upper = median_ci(car, rng)
    return {
        "group": label,
        "events": len(block),
        "min_scrisk": float(block["SCRisk"].min()),
        "max_scrisk": float(block["SCRisk"].max()),
        "median_scrisk": float(block["SCRisk"].median()),
        "mean_car_0_1_bp": round(10_000 * mean, 2),
        "mean_ci_low_bp": round(10_000 * (mean - half_width), 2),
        "mean_ci_high_bp": round(10_000 * (mean + half_width), 2),
        "median_car_0_1_bp": round(10_000 * median, 2),
        "median_ci_low_bp": round(10_000 * lower, 2),
        "median_ci_high_bp": round(10_000 * upper, 2),
        "groups": block["industry"].nunique(),
        "largest_group_share_percent": round(
            100 * block["industry"].value_counts().iloc[0] / len(block), 2
        ),
    }


def pooled_table(
    usable: pd.DataFrame, zero_block: pd.DataFrame | None, rng: np.random.Generator
) -> pd.DataFrame:
    rows = []
    if zero_block is not None and len(zero_block):
        rows.append(group_row("Score = 0", zero_block, rng))
    for quintile in range(1, QUINTILE_COUNT + 1):
        rows.append(group_row(f"Q{quintile}", usable[usable["quintile"] == quintile], rng))
    return pd.DataFrame(rows)


def cut_on_pooled_distribution(frame: pd.DataFrame) -> pd.DataFrame:
    """The published construction: one cut on the pooled positive distribution."""
    positive = frame[frame["SCRisk"] > 0.0].copy()
    boundaries = np.quantile(positive["SCRisk"].to_numpy(), [0.2, 0.4, 0.6, 0.8])
    positive["quintile"] = (
        np.searchsorted(boundaries, positive["SCRisk"].to_numpy(), side="right") + 1
    )
    return positive


def unconditional_table(frame: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    zero = frame[frame["SCRisk"] == 0.0]
    return pooled_table(cut_on_pooled_distribution(frame), zero, rng)


def per_industry_table(usable: pd.DataFrame) -> pd.DataFrame:
    grouped = usable.groupby(["industry", "quintile"])
    table = grouped.agg(
        events=("CAR_0_1", "size"),
        min_scrisk=("SCRisk", "min"),
        max_scrisk=("SCRisk", "max"),
        mean_car_0_1_bp=("CAR_0_1", lambda s: round(10_000 * s.mean(), 2)),
        median_car_0_1_bp=("CAR_0_1", lambda s: round(10_000 * s.median(), 2)),
    ).reset_index()
    return table.sort_values(["industry", "quintile"]).rename(columns={"industry": GROUP_LABEL})


def industry_mix(usable: pd.DataFrame) -> pd.DataFrame:
    """Share of each quintile made up of each industry, the balance check."""
    counts = pd.crosstab(usable["industry"], usable["quintile"])
    shares = (100 * counts / counts.sum()).round(3)
    shares.columns = [f"Q{column}_percent" for column in shares.columns]
    shares["max_minus_min_percent"] = (shares.max(axis=1) - shares.min(axis=1)).round(3)
    return shares.reset_index().rename(columns={"industry": GROUP_LABEL})


def plot_groups(table: pd.DataFrame, statistic: str, title: str, note: str, path: Path) -> None:
    labels = table["group"].tolist()
    if statistic == "mean":
        estimates = table["mean_car_0_1_bp"].to_numpy() / 10_000
        lower = (table["mean_car_0_1_bp"] - table["mean_ci_low_bp"]).to_numpy() / 10_000
        upper = (table["mean_ci_high_bp"] - table["mean_car_0_1_bp"]).to_numpy() / 10_000
    else:
        estimates = table["median_car_0_1_bp"].to_numpy() / 10_000
        lower = (table["median_car_0_1_bp"] - table["median_ci_low_bp"]).to_numpy() / 10_000
        upper = (table["median_ci_high_bp"] - table["median_car_0_1_bp"]).to_numpy() / 10_000

    colors = QUINTILE_COLORS[-len(labels):] if labels[0] != "Score = 0" else [
        ZERO_COLOR, *QUINTILE_COLORS
    ]
    figure, axis = plt.subplots(figsize=(8.6, 5.5))
    x = np.arange(len(labels))
    axis.bar(x, estimates, yerr=[lower, upper], capsize=3, color=colors, edgecolor="none", zorder=2)
    axis.set_xticks(x, labels)
    axis.set_xlabel(f"Within-{GROUP_LABEL} SCRisk quintile")
    axis.set_title(title, pad=12, weight="bold")
    axis.axhline(0, color="#3B3B3B", linewidth=0.8, zorder=1)
    axis.grid(axis="y", color="#E5E5E5", linewidth=0.8, zorder=0)
    axis.spines[["top", "right"]].set_visible(False)
    axis.set_ylabel("CAR(0, 1) (%)")
    axis.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=2))
    for position, estimate, events in zip(x, estimates, table["events"]):
        offset = 7 if estimate >= 0 else -12
        axis.annotate(
            f"n={events:,}", (position, estimate), xytext=(0, offset),
            textcoords="offset points", ha="center",
            va="bottom" if estimate >= 0 else "top", fontsize=8,
        )
    figure.text(0.5, 0.01, note, ha="center", va="bottom", color="#4D4D4D", fontsize=8.5)
    figure.tight_layout(rect=(0, 0.05, 1, 0.95))
    figure.savefig(path, dpi=240, bbox_inches="tight")
    plt.close(figure)


def plot_comparison(within: pd.DataFrame, pooled: pd.DataFrame, path: Path) -> None:
    quintiles = [f"Q{index}" for index in range(1, QUINTILE_COUNT + 1)]
    within_means = [
        within.loc[within.group == label, "mean_car_0_1_bp"].iloc[0] / 10_000 for label in quintiles
    ]
    pooled_means = [
        pooled.loc[pooled.group == label, "mean_car_0_1_bp"].iloc[0] / 10_000 for label in quintiles
    ]
    figure, axis = plt.subplots(figsize=(9.0, 5.5))
    x = np.arange(len(quintiles))
    width = 0.38
    axis.bar(x - width / 2, pooled_means, width, label="Pooled cut (published construction)",
             color=POOLED_COLOR, edgecolor="none", zorder=2)
    axis.bar(x + width / 2, within_means, width,
             label=f"Within-{GROUP_LABEL} cut, then pooled",
             color=QUINTILE_COLORS[3], edgecolor="none", zorder=2)
    axis.set_xticks(x, quintiles)
    axis.set_xlabel("SCRisk quintile among positive scores")
    axis.set_title(f"Mean CAR(0, 1): pooled against within-{GROUP_LABEL} quintiles",
                   pad=12, weight="bold")
    axis.axhline(0, color="#3B3B3B", linewidth=0.8, zorder=1)
    axis.grid(axis="y", color="#E5E5E5", linewidth=0.8, zorder=0)
    axis.spines[["top", "right"]].set_visible(False)
    axis.set_ylabel("CAR(0, 1) (%)")
    axis.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=2))
    axis.legend(frameon=False, fontsize=9)
    figure.text(0.5, 0.01,
                "Same no_self_pairs run and the same positive observations. Only the cut differs.",
                ha="center", va="bottom", color="#4D4D4D", fontsize=8.5)
    figure.tight_layout(rect=(0, 0.05, 1, 0.95))
    figure.savefig(path, dpi=240, bbox_inches="tight")
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--min-positives", type=int, default=MIN_POSITIVES_PER_INDUSTRY)
    parser.add_argument("--group-column", default="industry",
                        help="use sector to cut within sector instead; default: industry")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    global GROUP_LABEL
    GROUP_LABEL = args.group_column

    frame = load_events(args.input)
    if args.group_column != "industry":
        frame["industry"] = frame[args.group_column].fillna("").str.strip()
    rng = np.random.default_rng(BOOTSTRAP_SEED)

    usable, meta = build(frame, "positives_only", args.min_positives)
    zero_block = frame[
        (frame["SCRisk"] == 0.0) & frame["industry"].isin(set(usable["industry"]))
    ]
    within = pooled_table(usable, zero_block, rng)
    within.to_csv(args.output / f"within_{GROUP_LABEL}_quintiles.csv", index=False)

    pooled = unconditional_table(frame, np.random.default_rng(BOOTSTRAP_SEED))
    pooled.to_csv(args.output / "pooled_quintiles_same_run.csv", index=False)

    per_industry_table(usable).to_csv(
        args.output / f"within_{GROUP_LABEL}_quintiles_by_{GROUP_LABEL}.csv", index=False)
    mix = industry_mix(usable)
    mix.to_csv(args.output / f"{GROUP_LABEL}_mix_by_quintile.csv", index=False)
    # The same balance check for the pooled cut, on the same industries, so the
    # two constructions are compared on one population rather than two.
    matched = frame[frame["industry"].isin(set(usable["industry"]))]
    pooled_mix = industry_mix(cut_on_pooled_distribution(matched))
    pooled_mix.to_csv(
        args.output / f"{GROUP_LABEL}_mix_by_quintile_pooled.csv", index=False)

    everything, meta_all = build(frame, "all_observations", args.min_positives)
    within_all = pooled_table(everything, None, np.random.default_rng(BOOTSTRAP_SEED))
    within_all.to_csv(
        args.output / f"within_{GROUP_LABEL}_quintiles_all_observations.csv", index=False)
    zero_share = (
        everything.assign(is_zero=everything["SCRisk"] == 0)
        .groupby("quintile")["is_zero"].mean().mul(100).round(2).to_dict()
    )

    counts = frame[frame["SCRisk"] > 0].groupby("industry").size()
    excluded = pd.DataFrame({GROUP_LABEL: meta["excluded_industry_names"]})
    excluded["positive_calls"] = excluded[GROUP_LABEL].map(counts).fillna(0).astype(int)
    excluded["analysable_calls"] = excluded[GROUP_LABEL].map(
        frame.groupby("industry").size()).astype(int)
    excluded.sort_values("analysable_calls", ascending=False).to_csv(
        args.output / f"excluded_{plural(GROUP_LABEL)}.csv", index=False)

    plot_groups(
        within, "mean",
        f"Mean CAR(0, 1) by within-{GROUP_LABEL} SCRisk quintile",
        f"Quintiles cut inside each {GROUP_LABEL} on positive scores, then pooled. "
        "Whiskers show 95% confidence intervals.",
        args.output / "01_mean_car_by_within_industry_scrisk_quintile.png",
    )
    plot_groups(
        within, "median",
        f"Median CAR(0, 1) by within-{GROUP_LABEL} SCRisk quintile",
        f"Quintiles cut inside each {GROUP_LABEL} on positive scores, then pooled. "
        "Whiskers show bootstrap 95% confidence intervals.",
        args.output / "02_median_car_by_within_industry_scrisk_quintile.png",
    )
    plot_comparison(
        within, pooled,
        args.output / f"03_pooled_against_within_{GROUP_LABEL}_quintiles.png")

    summary = {
        "input": str(args.input),
        "group_column": args.group_column,
        "analysable_calls": int(len(frame)),
        "zero_scores": int((frame["SCRisk"] == 0).sum()),
        "positive_scores": int((frame["SCRisk"] > 0).sum()),
        "positives_only": meta,
        "all_observations": {**meta_all, "zero_share_of_quintile_percent": zero_share},
        "largest_group_share_of_a_quintile_percent": {
            f"within_{GROUP_LABEL}": float(within.loc[within.group != "Score = 0",
                                                      "largest_group_share_percent"].max()),
            "pooled": float(pooled.loc[pooled.group != "Score = 0",
                                       "largest_group_share_percent"].max()),
        },
        "group_share_spread_across_quintiles_percent": {
            "within_group_max": float(mix["max_minus_min_percent"].max()),
            "within_group_median": float(mix["max_minus_min_percent"].median()),
            "pooled_max": float(pooled_mix["max_minus_min_percent"].max()),
            "pooled_median": float(pooled_mix["max_minus_min_percent"].median()),
            "worst_balanced_group_within": str(
                mix.loc[mix["max_minus_min_percent"].idxmax(), GROUP_LABEL]),
            "worst_balanced_group_pooled": str(
                pooled_mix.loc[pooled_mix["max_minus_min_percent"].idxmax(), GROUP_LABEL]),
        },
    }
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2))

    print(f"input: {args.input}")
    print(f"ranked {meta['observations_ranked']:,} positive calls across "
          f"{meta['industries_ranked']} {plural(GROUP_LABEL)}; excluded "
          f"{meta['industries_excluded']} {plural(GROUP_LABEL)} holding "
          f"{meta['calls_in_excluded_industries']:,} calls")
    print(f"\n== within-{GROUP_LABEL} quintiles, then pooled ==")
    print(within[["group", "events", "min_scrisk", "max_scrisk",
                  "mean_car_0_1_bp", "median_car_0_1_bp",
                  "largest_group_share_percent"]].to_string(index=False))
    print("\n== pooled cut on the same run, for comparison ==")
    print(pooled[["group", "events", "min_scrisk", "max_scrisk",
                  "mean_car_0_1_bp", "median_car_0_1_bp",
                  "largest_group_share_percent"]].to_string(index=False))
    print("\n== all observations ranked, zeros included ==")
    print(within_all[["group", "events", "max_scrisk", "mean_car_0_1_bp",
                      "median_car_0_1_bp"]].to_string(index=False))
    print("zero share of each quintile (%):", zero_share)
    print(f"\nwrote {args.output}")


if __name__ == "__main__":
    main()
