#!/usr/bin/env python3
"""Create the four requested SCRisk, Resolution, and CAR(0,1) charts."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import PercentFormatter


# Defaults are the original run, so running this with no arguments reproduces
# the first set of charts.  --input and --output point it at another run.
INPUT = Path("artifacts/earnings_call_supply_chain/ppmi_svd_full_20260910/earnings_call_event_returns.csv")
OUTPUT = Path("outputs/scrisk_car_event_charts")
TITLE_SUFFIX = ""
ZERO_COLOR = "#7A7A7A"
QUINTILE_COLORS = ["#DCE7F5", "#B8D0EA", "#82B4D4", "#4D92BD", "#176C98"]
LINE_COLOR = "#B23A48"


def load_events() -> list[dict[str, float]]:
    """Load only observations with a successfully estimated CAR(0,1)."""
    events: list[dict[str, float]] = []
    with INPUT.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["event_status"] != "ok" or not row["CAR_0_1"]:
                continue
            if not row["SCRisk"] or not row["Resolution"]:
                continue
            scrisk = float(row["SCRisk"])
            resolution = float(row["Resolution"])
            car = float(row["CAR_0_1"])
            if all(math.isfinite(value) for value in (scrisk, resolution, car)):
                events.append({"scrisk": scrisk, "resolution": resolution, "car": car})
    if not events:
        raise ValueError("No valid CAR(0,1) observations were found.")
    return events


def quintile_groups(events: list[dict[str, float]], score_key: str) -> list[np.ndarray]:
    """Return zero-score CARs followed by five nonzero-score quantile groups."""
    zero = np.array([event["car"] for event in events if event[score_key] == 0.0])
    nonzero = sorted((event for event in events if event[score_key] > 0.0), key=lambda event: event[score_key])
    if len(nonzero) < 5:
        raise ValueError(f"Fewer than five positive {score_key} observations are available.")
    scores = np.array([event[score_key] for event in nonzero])
    boundaries = np.quantile(scores, [0.2, 0.4, 0.6, 0.8])
    groups: list[list[float]] = [[] for _ in range(5)]
    for event in nonzero:
        index = int(np.searchsorted(boundaries, event[score_key], side="right"))
        groups[index].append(event["car"])
    return [zero, *(np.array(group) for group in groups)]


def mean_ci(values: np.ndarray) -> tuple[float, float]:
    mean = float(np.mean(values))
    ci = 1.96 * float(np.std(values, ddof=1)) / math.sqrt(len(values)) if len(values) > 1 else 0.0
    return mean, ci


def median_ci(values: np.ndarray, rng: np.random.Generator, samples: int = 2_000) -> tuple[float, float, float]:
    median = float(np.median(values))
    boot = np.median(rng.choice(values, size=(samples, len(values)), replace=True), axis=1)
    lower, upper = np.quantile(boot, [0.025, 0.975])
    return median, float(lower), float(upper)


def style_axis(axis: plt.Axes) -> None:
    axis.axhline(0, color="#3B3B3B", linewidth=0.8, zorder=1)
    axis.grid(axis="y", color="#E5E5E5", linewidth=0.8, zorder=0)
    axis.spines[["top", "right"]].set_visible(False)
    axis.set_ylabel("CAR(0, 1) (%)")
    axis.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=1))


def add_note(figure: plt.Figure, text: str) -> None:
    figure.text(0.5, 0.01, text, ha="center", va="bottom", color="#4D4D4D", fontsize=8.5)


def plot_summary(events: list[dict[str, float]], score_key: str, statistic: str, filename: str) -> None:
    groups = quintile_groups(events, score_key)
    labels = ["Score = 0", "Q1", "Q2", "Q3", "Q4", "Q5"]
    score_label = "SCRisk" if score_key == "scrisk" else "Resolution"
    if statistic == "mean":
        values_and_errors = [mean_ci(group) for group in groups]
        estimates = np.array([item[0] for item in values_and_errors])
        errors = np.array([item[1] for item in values_and_errors])
        title = f"Mean CAR(0, 1) by {score_label} quintile{TITLE_SUFFIX}"
        note = "Whiskers show 95% confidence intervals. Quintiles are calculated among nonzero scores."
    else:
        rng = np.random.default_rng(20260915)
        values_and_errors = [median_ci(group, rng) for group in groups]
        estimates = np.array([item[0] for item in values_and_errors])
        errors = np.array([[item[0] - item[1] for item in values_and_errors], [item[2] - item[0] for item in values_and_errors]])
        title = f"Median CAR(0, 1) by SCRisk quintile{TITLE_SUFFIX}"
        note = "Whiskers show bootstrap 95% confidence intervals. Quintiles are calculated among nonzero SCRisk scores."

    figure, axis = plt.subplots(figsize=(8.6, 5.5))
    x = np.arange(len(labels))
    axis.bar(x, estimates, yerr=errors, capsize=3, color=[ZERO_COLOR, *QUINTILE_COLORS], edgecolor="none", zorder=2)
    axis.set_xticks(x, labels)
    axis.set_xlabel("Score group")
    axis.set_title(title, pad=12, weight="bold")
    style_axis(axis)
    for x_position, estimate, group in zip(x, estimates, groups):
        offset = 7 if estimate >= 0 else -12
        axis.annotate(f"n={len(group):,}", (x_position, estimate), xytext=(0, offset), textcoords="offset points", ha="center", va="bottom" if estimate >= 0 else "top", fontsize=8)
    add_note(figure, note)
    figure.tight_layout(rect=(0, 0.05, 1, 0.95))
    figure.savefig(OUTPUT / filename, dpi=240, bbox_inches="tight")
    plt.close(figure)


def plot_scrisk_scatter(events: list[dict[str, float]]) -> None:
    score = np.array([event["scrisk"] for event in events])
    car = np.array([event["car"] for event in events])
    transformed_score = np.log1p(score)
    positive_order = np.argsort(score[score > 0])
    positive_x = transformed_score[score > 0][positive_order]
    positive_car = car[score > 0][positive_order]
    bin_count = min(100, len(positive_x))
    bin_x, bin_y = [], []
    for index in range(bin_count):
        start = index * len(positive_x) // bin_count
        stop = (index + 1) * len(positive_x) // bin_count
        bin_x.append(float(np.mean(positive_x[start:stop])))
        bin_y.append(float(np.mean(positive_car[start:stop])))

    figure, axis = plt.subplots(figsize=(9.0, 5.7))
    axis.scatter(transformed_score, car, s=9, color="#8FA6B7", alpha=0.16, edgecolors="none", label="Individual calls", zorder=1)
    axis.plot(bin_x, bin_y, color=LINE_COLOR, linewidth=1.8, label="Mean CAR in 100 equal-count positive-SCRisk bins", zorder=3)
    axis.scatter(bin_x, bin_y, s=18, color=LINE_COLOR, edgecolors="white", linewidths=0.4, zorder=4)
    zero_car = car[score == 0]
    axis.scatter([0], [float(np.mean(zero_car))], s=55, color=ZERO_COLOR, edgecolors="white", linewidths=0.7, label="Mean CAR for zero SCRisk", zorder=5)
    axis.set_title(f"SCRisk and CAR(0, 1){TITLE_SUFFIX}", pad=12, weight="bold")
    axis.set_xlabel("log(1 + SCRisk)")
    style_axis(axis)
    axis.legend(frameon=False, loc="best", fontsize=8)
    add_note(figure, "The binned series summarizes positive SCRisk observations; raw points include zero-SCRisk calls.")
    figure.tight_layout(rect=(0, 0.05, 1, 0.95))
    figure.savefig(OUTPUT / "04_scrisk_car_scatter_binned.png", dpi=240, bbox_inches="tight")
    plt.close(figure)


def main() -> None:
    global INPUT, OUTPUT, TITLE_SUFFIX
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT, help="event returns CSV")
    parser.add_argument("--output", type=Path, default=OUTPUT, help="directory for the four PNGs")
    parser.add_argument("--title-suffix", default="", help="appended to every chart title")
    args = parser.parse_args()
    INPUT, OUTPUT, TITLE_SUFFIX = args.input, args.output, args.title_suffix
    OUTPUT.mkdir(parents=True, exist_ok=True)
    events = load_events()
    plot_summary(events, "scrisk", "mean", "01_mean_car_by_scrisk_quintile.png")
    plot_summary(events, "scrisk", "median", "02_median_car_by_scrisk_quintile.png")
    plot_summary(events, "resolution", "mean", "03_mean_car_by_resolution_quintile.png")
    plot_scrisk_scatter(events)
    print(f"Created 4 charts from {len(events):,} valid CAR observations in {OUTPUT}")


if __name__ == "__main__":
    main()
