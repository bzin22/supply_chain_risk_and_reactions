#!/usr/bin/env python3
"""Tests for the one-figure-per-sector CAR-against-quintile charts.

Covers the table behind each figure, the shared y-axis, the filenames, and
that every PNG is actually rendered rather than blank. Real-data expectations
come from ``outputs/scrisk_car_quintile_charts_by_sector/summary.json``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scrisk_vocabulary_fix"))

import per_group_quintile_charts as C  # noqa: E402
import within_industry_quintiles as W  # noqa: E402

OUT = ROOT / "outputs/scrisk_car_quintile_charts_by_sector"
SECTORS = ["Consumer Goods", "Energy", "Financial Services", "Healthcare", "Industrials",
           "Real Estate", "Retail", "Semiconductors", "Technology"]
requires_output = pytest.mark.skipif(
    not (OUT / "summary.json").exists(),
    reason="run scrisk_vocabulary_fix/per_group_quintile_charts.py first",
)


def synthetic(groups: int = 3, positives: int = 60, zeros: int = 40) -> pd.DataFrame:
    rng = np.random.default_rng(3)
    rows = []
    for index in range(groups):
        for call in range(positives + zeros):
            is_zero = call >= positives
            rows.append({
                "ticker": f"T{index:02d}{call:04d}",
                "quarter_label": "2022Q1",
                "industry": f"group{index:02d}",
                "sector": f"group{index:02d}",
                "SCRisk": 0.0 if is_zero else (10.0 ** index) * (call + 1),
                "CAR_0_1": rng.normal(0, 0.01),
                "event_status": "ok",
            })
    return pd.DataFrame(rows)


@pytest.mark.parametrize("name,expected", [
    ("Consumer Goods", "consumer_goods"),
    ("Financial Services", "financial_services"),
    ("REIT - Office", "reit_office"),
    ("Oil & Gas E&P", "oil_gas_e_p"),
])
def test_slug_is_filename_safe(name, expected):
    assert C.slug(name) == expected


def test_group_table_has_a_zero_row_and_five_quintiles():
    frame = synthetic()
    usable, _ = W.build(frame, "positives_only", min_positives=25)
    zeros = frame[frame["SCRisk"] == 0.0]
    rng = np.random.default_rng(1)
    table = C.group_table(usable, zeros, "group01", rng)
    assert list(table["group"]) == ["Score = 0", "Q1", "Q2", "Q3", "Q4", "Q5"]
    # 60 positives split five ways, plus that group's 40 zeros.
    assert table.loc[table.group == "Score = 0", "events"].iloc[0] == 40
    assert table.loc[table.group != "Score = 0", "events"].tolist() == [12, 12, 12, 12, 12]
    assert table["events"].sum() == 100
    assert (table["group_name"] == "group01").all()


def test_group_table_uses_only_that_groups_calls():
    frame = synthetic()
    usable, _ = W.build(frame, "positives_only", min_positives=25)
    zeros = frame[frame["SCRisk"] == 0.0]
    rng = np.random.default_rng(1)
    one = C.group_table(usable, zeros, "group00", rng)
    # group00's scores are 1..60; group01's are 10..600. If the wrong calls
    # leaked in, the quintile score ranges would exceed 60.
    assert one["max_scrisk"].max() <= 60


def test_shared_limits_cover_every_groups_interval():
    frame = synthetic()
    usable, _ = W.build(frame, "positives_only", min_positives=25)
    zeros = frame[frame["SCRisk"] == 0.0]
    rng = np.random.default_rng(1)
    tables = {g: C.group_table(usable, zeros, g, rng) for g in sorted(set(usable["industry"]))}
    floor, ceiling = C.shared_limits(tables, "mean")
    for table in tables.values():
        assert floor <= table["mean_ci_low_bp"].min() / 10_000
        assert ceiling >= table["mean_ci_high_bp"].max() / 10_000


# --- end to end through the CLI -----------------------------------------

def test_cli_writes_one_figure_per_group_per_statistic(tmp_path):
    source = tmp_path / "events.csv"
    frame = synthetic(groups=3)
    frame.to_csv(source, index=False)
    output = tmp_path / "charts"
    subprocess.run(
        [sys.executable, str(ROOT / "scrisk_vocabulary_fix/per_group_quintile_charts.py"),
         "--input", str(source), "--output", str(output), "--group-column", "sector"],
        check=True, capture_output=True, text=True, cwd=ROOT,
        env={**__import__("os").environ, "MPLCONFIGDIR": str(ROOT / "work/matplotlib_config")},
    )
    pngs = sorted(output.glob("*.png"))
    assert len(pngs) == 6  # 3 groups x mean and median
    for png in pngs:
        assert png.stat().st_size > 10_000, f"{png.name} looks blank"
    summary = json.loads((output / "summary.json").read_text())
    assert summary["groups"] == 3
    assert summary["shared_y_axis"] is True


# --- the real output ------------------------------------------------------

@requires_output
def test_real_output_has_one_figure_per_sector_per_statistic():
    summary = json.loads((OUT / "summary.json").read_text())
    assert summary["group_column"] == "sector"
    assert summary["groups"] == 9
    assert summary["groups_excluded"] == 0
    assert summary["positive_calls_ranked"] == 10_155
    assert len(summary["figures"]) == 18
    for statistic in ("mean", "median"):
        found = sorted(OUT.glob(f"*_{statistic}_car_by_scrisk_quintile.png"))
        assert len(found) == 9, f"expected 9 {statistic} figures, found {len(found)}"
        for png in found:
            assert png.stat().st_size > 30_000, f"{png.name} looks blank"


@requires_output
def test_real_output_covers_every_sector_exactly_once():
    table = pd.read_csv(OUT / "car_quintiles_by_sector.csv")
    assert sorted(table["sector"].unique()) == SECTORS
    assert len(table) == 9 * 6
    # Each sector's six rows must add up to its analysable call count.
    totals = table.groupby("sector")["events"].sum().to_dict()
    assert totals["Semiconductors"] == 2371
    assert totals["Healthcare"] == 2291
    assert sum(totals.values()) == 17_833


@requires_output
def test_real_output_quintiles_are_balanced_inside_each_sector():
    table = pd.read_csv(OUT / "car_quintiles_by_sector.csv")
    quintiles = table[table["group"] != "Score = 0"]
    spread = quintiles.groupby("sector")["events"].agg(lambda s: s.max() - s.min())
    # Equal-count split, so a sector's five cells differ by at most the
    # remainder it leaves when divided by five.
    assert spread.max() <= 1


@requires_output
def test_real_output_spreads_match_the_plotted_table():
    summary = json.loads((OUT / "summary.json").read_text())
    table = pd.read_csv(OUT / "car_quintiles_by_sector.csv").set_index(["sector", "group"])
    for sector, spread in summary["q5_minus_q1_mean_bp"].items():
        computed = (table.loc[(sector, "Q5"), "mean_car_0_1_bp"]
                    - table.loc[(sector, "Q1"), "mean_car_0_1_bp"])
        assert round(float(computed), 2) == pytest.approx(spread, abs=0.01)
    # Measured: Semiconductors -1.21 bp, Healthcare -146.21, Consumer Goods +91.88.
    assert summary["q5_minus_q1_mean_bp"]["Semiconductors"] == pytest.approx(-1.21, abs=0.01)
    assert summary["q5_minus_q1_mean_bp"]["Healthcare"] == pytest.approx(-146.21, abs=0.01)
    assert summary["q5_minus_q1_mean_bp"]["Consumer Goods"] == pytest.approx(91.88, abs=0.01)
