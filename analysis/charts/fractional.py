"""Fractional allocation, weighted summaries, and Matplotlib chart rendering.

Use python -m analysis.fractional_reproduction for the supported CLI.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.colors import TwoSlopeNorm
from matplotlib.ticker import FuncFormatter
import numpy as np
import pandas as pd
from scipy.stats import t


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "outputs/primary_event_study_2010_2019_release_dates_v1/full/call_level_scored_car.csv"
PAGE_CACHE = ROOT / "outputs/fractional_pages"
VARIABLES = ["SCRisk", "Resolution", "CAR_0_1", "CAR_2_60"]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(2**20), b""):
            digest.update(block)
    return digest.hexdigest()


def winsorize(frame: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    frame = frame.copy()
    thresholds = []
    for variable in VARIABLES:
        low, high = np.quantile(frame[variable].to_numpy(float), [.01, .99], method="linear")
        frame[variable + "_winsor"] = frame[variable].clip(low, high)
        thresholds.append({
            "variable": variable,
            "lower_threshold": float(low),
            "upper_threshold": float(high),
            "n": int(len(frame)),
            "clipped_below": int((frame[variable] < low).sum()),
            "clipped_above": int((frame[variable] > high).sum()),
            "quantile_method": "linear",
        })
    return frame, thresholds


def fractional_tie_memberships(values, base_weights=None) -> np.ndarray:
    """Allocate tied score blocks across five equal-mass bins.

    Every member of a tied block receives the same allocation proportions.
    Base weights allow the same rule to be applied to nested Resolution sorts.
    """
    values = np.asarray(values, dtype=float)
    weights = np.ones(len(values), dtype=float) if base_weights is None else np.asarray(base_weights, dtype=float)
    if len(values) == 0 or not np.isfinite(values).all() or not np.isfinite(weights).all() or (weights <= 0).any():
        raise ValueError("fractional allocation requires finite values and positive weights")
    total = float(weights.sum())
    boundaries = np.linspace(0.0, total, 6)
    allocation = np.zeros((len(values), 5), dtype=float)
    cursor = 0.0
    for score in np.unique(values):
        positions = np.flatnonzero(values == score)
        block_mass = float(weights[positions].sum())
        block_end = cursor + block_mass
        for quintile in range(5):
            overlap = max(0.0, min(block_end, boundaries[quintile + 1]) - max(cursor, boundaries[quintile]))
            if overlap:
                allocation[positions, quintile] = weights[positions] * overlap / block_mass
        cursor = block_end
    assert np.allclose(allocation.sum(axis=1), weights, atol=1e-11)
    assert np.allclose(allocation.sum(axis=0), total / 5, atol=1e-9)
    return allocation


def weighted_summary(frame: pd.DataFrame, row_ids, weights, variable: str) -> dict:
    row_ids = np.asarray(row_ids, dtype=int)
    weights = np.asarray(weights, dtype=float)
    selected = frame.loc[row_ids]
    values = selected[variable].to_numpy(float)
    mass = float(weights.sum())
    mean = float(np.sum(weights * values) / mass)
    cluster_scores = pd.Series(weights * (values - mean), index=selected["cik"].to_numpy()).groupby(level=0).sum()
    firms = int(len(cluster_scores))
    if firms >= 2:
        se = float(np.sqrt(firms / (firms - 1) * np.sum(cluster_scores.to_numpy() ** 2)) / mass)
        margin = float(t.ppf(.975, firms - 1) * se)
    else:
        se = margin = None
    return {
        "effective_n": mass,
        "contributing_calls": int(len(selected)),
        "firms": firms,
        "mean": mean,
        "se_firm_clustered": se,
        "ci_low": mean - margin if margin is not None else None,
        "ci_high": mean + margin if margin is not None else None,
        "zero_scrisk_weight": float(np.sum(weights * selected["scrisk_zero"].to_numpy(float))),
        "zero_resolution_weight": float(np.sum(weights * selected["resolution_zero"].to_numpy(float))),
        "sic_divisions": int(selected["sic_division"].nunique()),
    }


def fractional_assignments(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, list[dict]]:
    risk_parts = []
    zero_audit = []
    for division, group in frame.groupby("sic_division", sort=True, observed=True):
        allocation = fractional_tie_memberships(group.SCRisk_winsor.to_numpy(float))
        for q in range(5):
            keep = allocation[:, q] > 1e-14
            risk_parts.append(pd.DataFrame({
                "row_id": group.index.to_numpy()[keep],
                "sic_division": division,
                "SCRisk_quintile": q + 1,
                "risk_weight": allocation[keep, q],
            }))
        zero_positions = np.flatnonzero(group.scrisk_zero.to_numpy(bool))
        if len(zero_positions):
            first = allocation[zero_positions[0]]
            assert np.allclose(allocation[zero_positions], first, atol=1e-12)
            zero_audit.append({
                "sic_division": division,
                "zero_calls": int(len(zero_positions)),
                **{f"Q{q + 1}_membership_per_zero_call": float(first[q]) for q in range(5)},
            })
    risk_long = pd.concat(risk_parts, ignore_index=True)
    risk_mass = risk_long.groupby(["sic_division", "SCRisk_quintile"]).risk_weight.sum()
    division_n = frame.groupby("sic_division").size()
    for (division, _), mass in risk_mass.items():
        assert np.isclose(mass, division_n[division] / 5, atol=1e-8)
    assert np.allclose(risk_long.groupby("row_id").risk_weight.sum().reindex(frame.index), 1.0, atol=1e-10)

    joint_parts = []
    for (division, risk_q), group in risk_long.groupby(["sic_division", "SCRisk_quintile"], sort=True):
        row_ids = group.row_id.to_numpy(int)
        base = group.risk_weight.to_numpy(float)
        values = frame.loc[row_ids, "Resolution_winsor"].to_numpy(float)
        allocation = fractional_tie_memberships(values, base)
        for resolution_q in range(5):
            keep = allocation[:, resolution_q] > 1e-14
            joint_parts.append(pd.DataFrame({
                "row_id": row_ids[keep],
                "sic_division": division,
                "SCRisk_quintile": int(risk_q),
                "Resolution_quintile": resolution_q + 1,
                "weight": allocation[keep, resolution_q],
            }))
    joint_long = pd.concat(joint_parts, ignore_index=True)
    assert np.allclose(joint_long.groupby("row_id").weight.sum().reindex(frame.index), 1.0, atol=1e-10)
    joint_mass = joint_long.groupby(["sic_division", "SCRisk_quintile", "Resolution_quintile"]).weight.sum()
    for (division, _, _), mass in joint_mass.items():
        assert np.isclose(mass, division_n[division] / 25, atol=1e-8)
    return risk_long, joint_long, zero_audit


def fractional_tables(frame: pd.DataFrame, risk_long: pd.DataFrame, joint_long: pd.DataFrame) -> dict[str, list[dict]]:
    tables = {}
    for name, variable in [("car_0_1_by_scrisk", "CAR_0_1_winsor"), ("car_2_60_by_scrisk", "CAR_2_60_winsor")]:
        rows = []
        for q in range(1, 6):
            group = risk_long[risk_long.SCRisk_quintile == q]
            rows.append({"SCRisk_quintile": q, **weighted_summary(frame, group.row_id, group.risk_weight, variable)})
        tables[name] = rows
    rows = []
    for q in range(1, 6):
        group = joint_long[joint_long.Resolution_quintile == q]
        rows.append({"Resolution_quintile": q, **weighted_summary(frame, group.row_id, group.weight, "CAR_0_1_winsor")})
    tables["car_0_1_by_resolution"] = rows
    for name, variable in [("car_0_1_heatmap", "CAR_0_1_winsor"), ("car_2_60_heatmap", "CAR_2_60_winsor")]:
        rows = []
        for risk_q in range(1, 6):
            for resolution_q in range(1, 6):
                group = joint_long[(joint_long.SCRisk_quintile == risk_q) &
                                   (joint_long.Resolution_quintile == resolution_q)]
                rows.append({"SCRisk_quintile": risk_q, "Resolution_quintile": resolution_q,
                             **weighted_summary(frame, group.row_id, group.weight, variable)})
        tables[name] = rows
    return tables


def style() -> None:
    plt.rcParams.update({
        "font.family": "DejaVu Serif",
        "font.size": 12,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "pdf.fonttype": 42,
    })


def save_raster_page(pdf, figure, slug: str, page: int) -> None:
    PAGE_CACHE.mkdir(parents=True, exist_ok=True)
    page_path = PAGE_CACHE / f"{slug}_page_{page}.png"
    figure.savefig(page_path, dpi=180, facecolor="white")
    plt.close(figure)
    image = plt.imread(page_path)
    wrapper = plt.figure(figsize=(11, 8.5), facecolor="white")
    axis = wrapper.add_axes([0, 0, 1, 1])
    axis.imshow(image)
    axis.set_axis_off()
    pdf.savefig(wrapper, facecolor="white")
    plt.close(wrapper)


def bar_page(pdf, rows, title, xlabel, ylabel, variant, sample_caption, method_caption, fractional, page, slug):
    figure = plt.figure(figsize=(11, 8.5), facecolor="white")
    axis = figure.add_axes([.11, .27, .85, .57])
    means = np.array([row["mean"] for row in rows]) * 100
    lows = np.array([row["ci_low"] for row in rows]) * 100
    highs = np.array([row["ci_high"] for row in rows]) * 100
    axis.bar(range(1, 6), means, color="#9eb4c4", edgecolor="#2b4557", linewidth=.8, width=.62, zorder=3)
    axis.errorbar(range(1, 6), means, yerr=np.vstack([means - lows, highs - means]), fmt="none",
                  color="#202020", capsize=5, lw=1.4, zorder=4,
                  label="95% interval, clustered by firm")
    axis.axhline(0, color="#333333", lw=.9)
    axis.grid(axis="y", alpha=.18, zorder=0)
    labels = []
    for i, row in enumerate(rows, 1):
        count = f'mass={row["effective_n"]:,.1f}' if fractional else f'n={row["contributing_calls"]:,}'
        labels.append(f"Q{i}\n{count}")
    axis.set_xlim(.5, 5.5)
    axis.set_xticks(range(1, 6))
    axis.set_xticklabels(labels)
    axis.set_xlabel(xlabel, labelpad=11)
    axis.set_ylabel(ylabel)
    axis.yaxis.set_major_formatter(FuncFormatter(lambda value, position: f"{value:.2f}"))
    axis.set_title(title, pad=19, fontsize=18)
    axis.legend(loc="best", frameon=False, fontsize=10)
    figure.text(.5, .94, variant, ha="center", fontsize=9, color="#555555")
    figure.text(.11, .13, sample_caption, fontsize=9.5)
    figure.text(.11, .09, method_caption, fontsize=9.5)
    figure.text(.955, .035, f"Page {page} of 5", ha="right", fontsize=8, color="#666666")
    save_raster_page(pdf, figure, slug, page)


def heatmap_page(pdf, rows, title, variant, sample_caption, method_caption, fractional, page, slug):
    figure = plt.figure(figsize=(11, 8.5), facecolor="white")
    axis = figure.add_axes([.12, .20, .68, .68])
    means = np.array([row["mean"] for row in rows]).reshape(5, 5) * 100
    bound = max(float(np.nanmax(np.abs(means))), .01)
    image = axis.imshow(means, cmap="RdBu", norm=TwoSlopeNorm(vmin=-bound, vcenter=0, vmax=bound), aspect="equal")
    for index, row in enumerate(rows):
        i, j = divmod(index, 5)
        value = means[i, j]
        count = f'mass={row["effective_n"]:,.1f}' if fractional else f'n={row["contributing_calls"]:,}'
        color = "white" if abs(value) > .62 * bound else "#202020"
        axis.text(j, i, f"{value:+.2f}%\n{count}", ha="center", va="center", color=color, fontsize=9.5)
    axis.set_xlim(-.5, 4.5)
    axis.set_ylim(4.5, -.5)
    axis.set_xticks(range(5))
    axis.set_xticklabels([f"Q{i}" for i in range(1, 6)])
    axis.set_yticks(range(5))
    axis.set_yticklabels([f"Q{i}" for i in range(1, 6)])
    axis.set_xlabel("Resolution quintile (low to high)")
    axis.set_ylabel("SCRisk quintile (low to high)")
    axis.set_title(title, pad=16, fontsize=18)
    color_axis = figure.add_axes([.82, .29, .025, .48])
    colorbar = figure.colorbar(image, cax=color_axis)
    colorbar.set_label("Mean cumulative abnormal return (%)")
    figure.text(.5, .94, variant, ha="center", fontsize=9, color="#555555")
    figure.text(.11, .115, sample_caption, fontsize=9.5)
    figure.text(.11, .078, method_caption, fontsize=9.5)
    figure.text(.11, .043, "Cell intervals omitted for readability; bar panels show firm-clustered 95% intervals.", fontsize=8.5)
    figure.text(.93, .035, f"Page {page} of 5", ha="right", fontsize=8, color="#666666")
    save_raster_page(pdf, figure, slug, page)


def render_pdf(path: Path, tables: dict, variant: str, sample_caption: str, method_caption: str, fractional: bool):
    style()
    slug = path.stem
    with PdfPages(path, metadata={"Title": variant, "Creator": "Matplotlib"}) as pdf:
        bar_page(pdf, tables["car_0_1_by_scrisk"], "Mean CAR(0,1) by SCRisk quintile",
                 "SCRisk quintile (low to high)", "Mean CAR(0,1) (%)", variant,
                 sample_caption, method_caption, fractional, 1, slug)
        bar_page(pdf, tables["car_0_1_by_resolution"], "Mean CAR(0,1) by Resolution quintile",
                 "Resolution quintile (low to high)", "Mean CAR(0,1) (%)", variant,
                 sample_caption, method_caption, fractional, 2, slug)
        heatmap_page(pdf, tables["car_0_1_heatmap"], "Mean CAR(0,1): SCRisk x Resolution",
                     variant, sample_caption, method_caption, fractional, 3, slug)
        bar_page(pdf, tables["car_2_60_by_scrisk"], "Mean CAR(2,60) by SCRisk quintile",
                 "SCRisk quintile (low to high)", "Mean CAR(2,60) (%)", variant,
                 sample_caption, method_caption, fractional, 4, slug)
        heatmap_page(pdf, tables["car_2_60_heatmap"], "Mean CAR(2,60): SCRisk x Resolution",
                     variant, sample_caption, method_caption, fractional, 5, slug)
