#!/usr/bin/env python3
"""Tests for the within-industry SCRisk quintile construction.

Scope is the new construction only. Two kinds of test: unit tests on the rank
split using a synthetic frame, and assertions against the real output that
check the property the construction exists for, namely that industry mix is
held constant across the five quintiles.

Real-data expectations are taken from
``outputs/scrisk_within_industry_quintiles/summary.json`` and cited inline.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scrisk_vocabulary_fix"))

import within_industry_quintiles as W  # noqa: E402

OUT = ROOT / "outputs/scrisk_within_industry_quintiles"
requires_output = pytest.mark.skipif(
    not (OUT / "within_industry_quintiles.csv").exists(),
    reason="run scrisk_vocabulary_fix/within_industry_quintiles.py first",
)


def synthetic(industry_sizes: dict[str, int]) -> pd.DataFrame:
    rows = []
    for industry, size in industry_sizes.items():
        for index in range(size):
            rows.append({
                "ticker": f"{industry[:3].upper()}{index:03d}",
                "quarter_label": "2022Q1",
                "industry": industry,
                "sector": "Test",
                # Scores rise with index, and differ in level between
                # industries so a pooled cut and a within-industry cut
                # disagree.
                "SCRisk": (index + 1) * (10.0 if industry == "heavy" else 0.1),
                "CAR_0_1": 0.001 * ((index % 7) - 3),
                "event_status": "ok",
            })
    return pd.DataFrame(rows)


# --- the rank split -------------------------------------------------------

@pytest.mark.parametrize("size", [25, 100, 101, 103, 1000])
def test_rank_split_gives_equal_counts_within_one(size):
    frame = synthetic({"light": size})
    quintile = W.assign_quintiles_by_rank(frame)
    counts = quintile.value_counts().sort_index()
    assert set(counts.index) == {1, 2, 3, 4, 5}
    assert counts.max() - counts.min() <= 1
    assert counts.sum() == size


def test_rank_split_is_monotone_in_scrisk():
    frame = synthetic({"light": 200})
    frame["quintile"] = W.assign_quintiles_by_rank(frame)
    peak = frame.groupby("quintile")["SCRisk"].max()
    floor = frame.groupby("quintile")["SCRisk"].min()
    for quintile in range(1, 5):
        assert peak[quintile] <= floor[quintile + 1]


def test_rank_split_breaks_ties_deterministically():
    frame = synthetic({"light": 50})
    frame["SCRisk"] = 1.0  # every score identical
    first = W.assign_quintiles_by_rank(frame)
    second = W.assign_quintiles_by_rank(frame.sample(frac=1.0, random_state=7))
    assert first.sort_index().equals(second.sort_index())


# --- the construction ----------------------------------------------------

def test_every_industry_contributes_to_every_quintile():
    frame = synthetic({"light": 100, "heavy": 60, "middling": 35})
    usable, meta = W.build(frame, "positives_only", min_positives=25)
    counts = pd.crosstab(usable["industry"], usable["quintile"])
    assert list(counts.columns) == [1, 2, 3, 4, 5]
    assert (counts > 0).all().all()
    assert meta["industries_ranked"] == 3
    assert meta["industries_excluded"] == 0


def test_industries_below_the_threshold_are_excluded_and_named():
    frame = synthetic({"light": 100, "tiny": 9})
    usable, meta = W.build(frame, "positives_only", min_positives=25)
    assert meta["excluded_industry_names"] == ["tiny"]
    assert meta["calls_in_excluded_industries"] == 9
    assert "tiny" not in set(usable["industry"])
    # No observation from a kept industry may be left unassigned.
    assert len(usable) == 100


def test_a_within_industry_cut_beats_a_pooled_cut_on_industry_balance():
    """The reason the construction exists, on data built to make it visible.

    "heavy" scores are 100x "light" scores, so a pooled cut puts every heavy
    call in the top quintile and none in the bottom. A within-industry cut
    splits each industry across all five.
    """
    frame = synthetic({"light": 100, "heavy": 100})
    usable, _ = W.build(frame, "positives_only", min_positives=25)
    within = pd.crosstab(usable["industry"], usable["quintile"], normalize="columns")
    assert within.loc["heavy"].min() == pytest.approx(0.5)
    assert within.loc["heavy"].max() == pytest.approx(0.5)

    pooled = frame.sort_values("SCRisk").copy()
    pooled["quintile"] = W.assign_quintiles_by_rank(pooled)
    pooled_shares = pd.crosstab(pooled["industry"], pooled["quintile"], normalize="columns")
    assert pooled_shares.loc["heavy", 1] == 0.0
    assert pooled_shares.loc["heavy", 5] == 1.0


# --- the real output ------------------------------------------------------

@requires_output
def test_real_output_holds_industry_mix_constant():
    mix = pd.read_csv(OUT / "industry_mix_by_quintile.csv")
    # Measured: the worst-balanced industry is Semiconductors, which runs
    # from 9.604% of Q1 to 9.862% of Q5, a spread of 0.258 points.
    assert mix["max_minus_min_percent"].max() < 0.5
    assert len(mix) == 78


@requires_output
def test_real_output_removes_the_pooled_cut_industry_gradient():
    """Same 78 industries and same 9,944 calls in both files; only the cut differs."""
    within = pd.read_csv(OUT / "industry_mix_by_quintile.csv").set_index("industry")
    pooled = pd.read_csv(OUT / "industry_mix_by_quintile_pooled.csv").set_index("industry")
    columns = [f"Q{index}_percent" for index in range(1, 6)]
    # Measured: Semiconductors runs 4.376% of pooled Q1 to 15.535% of pooled
    # Q5, a monotone climb spanning 11.159 points.  Under the within-industry
    # cut it runs 9.604% to 9.862%, a spread of 0.258.
    semis_pooled = pooled.loc["Semiconductors", columns]
    assert list(semis_pooled) == sorted(semis_pooled), "the pooled gradient should be monotone"
    assert pooled.loc["Semiconductors", "max_minus_min_percent"] > 10.0
    assert within.loc["Semiconductors", "max_minus_min_percent"] < 0.5
    assert pooled["max_minus_min_percent"].median() > 20 * within["max_minus_min_percent"].median()


@requires_output
def test_real_output_quintile_score_ranges_overlap():
    """A relative cut must produce overlapping score ranges; an absolute one cannot."""
    within = pd.read_csv(OUT / "within_industry_quintiles.csv").set_index("group")
    pooled = pd.read_csv(OUT / "pooled_quintiles_same_run.csv").set_index("group")
    assert within.loc["Q1", "max_scrisk"] > within.loc["Q5", "min_scrisk"]
    assert pooled.loc["Q1", "max_scrisk"] < pooled.loc["Q5", "min_scrisk"]


@requires_output
def test_real_output_quintiles_are_balanced_in_size():
    within = pd.read_csv(OUT / "within_industry_quintiles.csv")
    quintiles = within[within.group != "Score = 0"]
    assert len(quintiles) == 5
    # 9,944 positives over 78 industries: sizes differ only by the remainder
    # each industry leaves, so a spread of a few dozen calls is expected.
    assert quintiles["events"].sum() == 9944
    assert quintiles["events"].max() - quintiles["events"].min() < 100


@requires_output
def test_all_observations_mode_is_dominated_by_zeros_in_the_low_quintiles():
    """Why positives_only is the primary output rather than this one."""
    import json
    summary = json.loads((OUT / "summary.json").read_text())
    shares = summary["all_observations"]["zero_share_of_quintile_percent"]
    assert shares["1"] > 95.0
    assert shares["5"] < 1.0


# --- the 9-sector grouping, which is the study's own -----------------------

SECTOR_OUT = ROOT / "outputs/scrisk_within_sector_quintiles"
requires_sector_output = pytest.mark.skipif(
    not (SECTOR_OUT / "within_sector_quintiles.csv").exists(),
    reason="run within_industry_quintiles.py --group-column sector first",
)


@requires_sector_output
def test_sector_run_uses_all_nine_sectors_and_excludes_nothing():
    """All 9 sectors clear the 25-positive floor, unlike 13 of the 91 industries."""
    import json
    summary = json.loads((SECTOR_OUT / "summary.json").read_text())
    assert summary["group_column"] == "sector"
    assert summary["positives_only"]["industries_ranked"] == 9
    assert summary["positives_only"]["industries_excluded"] == 0
    assert summary["positives_only"]["observations_ranked"] == 10_155
    assert summary["positive_scores"] == 10_155


@requires_sector_output
def test_sector_run_holds_sector_mix_constant():
    mix = pd.read_csv(SECTOR_OUT / "sector_mix_by_quintile.csv")
    pooled = pd.read_csv(SECTOR_OUT / "sector_mix_by_quintile_pooled.csv")
    assert len(mix) == 9 and list(mix.columns)[0] == "sector"
    # Measured: Semiconductors runs 6.155% of pooled Q1 to 25.800% of pooled
    # Q5, a spread of 19.645 points; within-sector it runs 16.118% to 16.132%,
    # a spread of 0.032.  Energy runs the other way, 13.589% down to 2.806%.
    semis = pooled.set_index("sector").loc["Semiconductors"]
    assert semis["max_minus_min_percent"] > 19.0
    assert pooled.set_index("sector").loc["Energy", "max_minus_min_percent"] > 10.0
    assert mix["max_minus_min_percent"].max() < 0.1


@requires_sector_output
def test_sector_quintile_cells_are_far_larger_than_industry_cells():
    sector = pd.read_csv(SECTOR_OUT / "within_sector_quintiles_by_sector.csv")
    industry = pd.read_csv(OUT / "within_industry_quintiles_by_industry.csv")
    # Median cell 222 calls against 18, a 12x difference; that is the reason
    # the sector version is the one to quote.
    assert sector["events"].median() > 200
    assert industry["events"].median() < 25
    assert sector["events"].min() > industry["events"].median()
