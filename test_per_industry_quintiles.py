#!/usr/bin/env python3
"""Tests for the per-industry (unpooled) SCRisk quintile analysis.

The headline result is a null: 37 of 78 industries show a positive Q5 minus
Q1 spread against 39 expected by chance. A null is only worth reporting if the
analysis can detect a real effect, so the load-bearing test here plants one and
checks it comes back out.

Real-data expectations come from
``outputs/scrisk_per_industry_quintiles/summary.json`` and are cited inline.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scrisk_vocabulary_fix"))

import per_industry_quintiles as P  # noqa: E402
import within_industry_quintiles as W  # noqa: E402

OUT = ROOT / "outputs/scrisk_per_industry_quintiles"
requires_output = pytest.mark.skipif(
    not (OUT / "summary.json").exists(),
    reason="run scrisk_vocabulary_fix/per_industry_quintiles.py first",
)


def planted(industries: int, calls: int, effect_bp: float, noise_bp: float,
            seed: int = 11) -> pd.DataFrame:
    """A frame where CAR rises linearly with the within-industry quintile.

    ``effect_bp`` is the Q5 minus Q1 gap built into every industry.  Scores are
    scaled per industry so a pooled cut would sort on industry, which is the
    situation the within-industry cut exists for.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for index in range(industries):
        scale = 10.0 ** index
        for call in range(calls):
            quintile = (call * 5) // calls          # 0 to 4
            car = (effect_bp * quintile / 4 + rng.normal(0, noise_bp)) / 10_000
            rows.append({
                "ticker": f"T{index:02d}{call:04d}",
                "quarter_label": "2022Q1",
                "industry": f"industry{index:02d}",
                "sector": "Test",
                "SCRisk": scale * (call + 1),
                "CAR_0_1": car,
                "event_status": "ok",
            })
    return pd.DataFrame(rows)


def analyse(frame: pd.DataFrame):
    usable, _ = W.build(frame, "positives_only", min_positives=25)
    spreads = P.spread_rows(usable)
    return usable, spreads, P.evidence(spreads)


# --- the analysis can see an effect that is there ------------------------

def test_a_planted_effect_is_recovered():
    """300 bp planted in all 40 industries, noise 300 bp, 100 calls each."""
    frame = planted(industries=40, calls=100, effect_bp=300, noise_bp=300)
    _, spreads, summary = analyse(frame)
    assert summary["industries"] == 40
    # Every industry should come out positive, so the sign test is decisive.
    assert summary["positive_q5_minus_q1"] >= 38
    assert summary["binomial_p"] < 0.001
    assert summary["one_sample_t_on_the_group_spreads"]["p"] < 0.001
    # The recovered spread must match what was planted, not just beat zero.
    assert summary["mean_spread_bp"] == pytest.approx(300, abs=40)
    assert summary["mean_spread_ci_low_bp"] > 0


def test_no_planted_effect_gives_a_null():
    frame = planted(industries=40, calls=100, effect_bp=0, noise_bp=300)
    _, _, summary = analyse(frame)
    assert summary["binomial_p"] > 0.05
    assert summary["mean_spread_ci_low_bp"] < 0 < summary["mean_spread_ci_high_bp"]


def test_a_planted_effect_below_the_resolution_is_not_recovered():
    """An effect smaller than the design can resolve stays invisible.

    This is the point of reporting ``smallest_detectable_spread_bp``: a null
    here is not evidence that nothing is happening.
    """
    frame = planted(industries=40, calls=100, effect_bp=20, noise_bp=600)
    _, _, summary = analyse(frame)
    assert summary["smallest_detectable_spread_bp"] > 20
    assert summary["mean_spread_ci_low_bp"] < 0


# --- the pieces ----------------------------------------------------------

def test_spread_is_q5_mean_minus_q1_mean():
    frame = planted(industries=2, calls=100, effect_bp=500, noise_bp=0)
    usable, spreads, _ = analyse(frame)
    for row in spreads.itertuples():
        block = usable[usable.industry == row.industry]
        q1 = block.loc[block.quintile == 1, "CAR_0_1"].mean()
        q5 = block.loc[block.quintile == 5, "CAR_0_1"].mean()
        assert row.q5_minus_q1_mean_bp == pytest.approx(10_000 * (q5 - q1), abs=0.01)
        assert row.q1_mean_car_bp == pytest.approx(10_000 * q1, abs=0.01)
        assert row.direction == "positive"


def test_monotonicity_flags_a_clean_ladder():
    frame = planted(industries=2, calls=100, effect_bp=500, noise_bp=0)
    usable, _, _ = analyse(frame)
    shape = P.monotonicity(P.industry_rows(usable))
    assert shape["monotone_increasing"].all()
    assert not shape["monotone_decreasing"].any()
    assert (shape["spearman_quintile_vs_mean_car"] == 1.0).all()


def test_every_industry_gets_five_quintile_rows():
    frame = planted(industries=3, calls=60, effect_bp=0, noise_bp=100)
    usable, _, _ = analyse(frame)
    rows = P.industry_rows(usable)
    assert len(rows) == 15
    assert set(rows["quintile"]) == {"Q1", "Q2", "Q3", "Q4", "Q5"}
    assert rows["events"].sum() == 180


# --- the real output ------------------------------------------------------

@requires_output
def test_real_output_is_a_null_across_every_test():
    summary = json.loads((OUT / "summary.json").read_text())
    # Measured: 37 of 78 positive against 39 expected, binomial p = 0.7343,
    # one-sample t p = 0.7294, Wilcoxon p = 0.8168.
    assert summary["industries"] == 78
    assert summary["positive_q5_minus_q1"] == 37
    assert summary["binomial_p"] > 0.05
    assert summary["one_sample_t_on_the_group_spreads"]["p"] > 0.05
    assert summary["wilcoxon_signed_rank_p"] > 0.05
    assert summary["mean_spread_ci_low_bp"] < 0 < summary["mean_spread_ci_high_bp"]


@requires_output
def test_real_output_significant_industries_are_no_more_than_chance():
    summary = json.loads((OUT / "summary.json").read_text())
    # 3 industries at Welch p < 0.05 against 3.9 expected from 78 tests.
    assert summary["industries_with_welch_p_below_0_05"] <= summary[
        "expected_false_positives_at_0_05"
    ]


@requires_output
def test_real_output_has_slightly_more_monotone_industries_than_chance():
    """Observed 4 monotone against 1.3 expected, p = 0.0417. It cuts both ways.

    Five quintile means have 120 orderings and 2 are monotone, so each
    industry is monotone either way with probability 1/60. Four of 78 is
    marginally more than that. But two rise and two fall, and 2 rising alone
    carries p = 0.1381, so this is monotone runs in either direction rather
    than evidence of a positive SCRisk relationship.
    """
    summary = json.loads((OUT / "summary.json").read_text())
    increasing = summary["monotone_increasing_groups"]
    decreasing = summary["monotone_decreasing_groups"]
    assert increasing + decreasing == 4
    assert summary["monotone_either_way_binomial_p"] < 0.05
    # The directional test, which is the one that would matter, is a null.
    assert summary["monotone_increasing_binomial_p"] > 0.05
    assert increasing == decreasing


@requires_output
def test_real_output_cells_are_small_enough_to_warrant_the_caveat():
    summary = json.loads((OUT / "summary.json").read_text())
    # Median quintile cell is 18 calls and the smallest is 5, which is why a
    # single industry's panel cannot carry a conclusion.
    assert summary["smallest_quintile_cell"] == 5
    assert summary["median_quintile_cell"] < 25
