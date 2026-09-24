"""Combine the five finalized portfolio charts into one landscape PDF."""
from pathlib import Path
import csv

import matplotlib
matplotlib.use("Agg")
import matplotlib.image as mpimg
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.ticker import FuncFormatter


ROOT = Path(__file__).resolve().parents[1]
CHART_DIR = ROOT / "outputs/primary_event_study_2010_2019_release_dates_v1/full"
OUTPUT = ROOT / "outputs/primary_event_study_2010_2019_release_dates_v1/portfolio_charts.pdf"
CHARTS = [
    "01_car_0_1_by_scrisk.png",
    "02_car_0_1_by_resolution.png",
    "03_car_0_1_heatmap.png",
    "04_car_2_60_by_scrisk.png",
    "05_car_2_60_heatmap.png",
]


def resolution_figure():
    """Re-render the Resolution panel because the archived PNG clips its counts."""
    table = CHART_DIR / "02_car_0_1_by_resolution.csv"
    with table.open() as source:
        rows = list(csv.DictReader(source))
    mean = [float(row["mean"]) * 100 for row in rows]
    low = [float(row["ci_low"]) * 100 for row in rows]
    high = [float(row["ci_high"]) * 100 for row in rows]
    counts = [int(row["n"]) for row in rows]

    plt.rcParams.update({
        "font.family": "DejaVu Serif",
        "font.size": 13,
        "axes.spines.top": False,
        "axes.spines.right": False,
    })
    figure = plt.figure(figsize=(11, 8.5), facecolor="white")
    axis = figure.add_axes([0.12, 0.26, 0.84, 0.59])
    axis.bar(range(1, 6), mean, color="#9eb4c4", edgecolor="#2b4557", linewidth=.8, width=.62, zorder=3)
    axis.errorbar(
        range(1, 6), mean,
        yerr=[[m - lo for m, lo in zip(mean, low)], [hi - m for hi, m in zip(high, mean)]],
        fmt="none", color="#202020", capsize=5, lw=1.4, zorder=4,
        label="95% interval, clustered by firm",
    )
    axis.axhline(0, color="#333333", lw=.9)
    axis.grid(axis="y", alpha=.18, zorder=0)
    axis.set_xticks(range(1, 6))
    axis.set_xticklabels([f"Q{i}\nn={count:,}" for i, count in enumerate(counts, 1)])
    axis.set_xlabel("Resolution quintile (low to high)", labelpad=11)
    axis.set_ylabel("Mean CAR(0,1) (%)")
    axis.yaxis.set_major_formatter(FuncFormatter(lambda value, position: f"{value:.2f}"))
    axis.set_title("Mean CAR(0,1) by Resolution quintile", pad=19, fontsize=18)
    axis.legend(loc="upper left", frameon=False, fontsize=11)
    figure.text(.12, .115, "Release-date event sample: 52,533 calls, 2,026 firms. Variables winsorized at 1% and 99%.", fontsize=10)
    figure.text(.12, .077, "All zero scores included. Equal-call weights; deterministic ties; common sample across panels.", fontsize=10)
    return figure


def main() -> None:
    with PdfPages(
        OUTPUT,
        metadata={
            "Title": "2010-2019 portfolio charts",
            "Subject": "Release-date event-study portfolio charts",
            "Creator": "Matplotlib",
        },
    ) as output:
        for filename in CHARTS:
            if filename.startswith("02_"):
                figure = resolution_figure()
            else:
                image = mpimg.imread(CHART_DIR / filename)
                figure = plt.figure(figsize=(11, 8.5), facecolor="white")
                axis = figure.add_axes([0.025, 0.025, 0.95, 0.95])
                axis.imshow(image)
                axis.set_axis_off()
            output.savefig(figure, facecolor="white")
            plt.close(figure)


if __name__ == "__main__":
    main()
