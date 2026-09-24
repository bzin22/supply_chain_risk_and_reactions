"""Invariants and independent clustered-uncertainty checks."""
import json
import shutil

import numpy as np
import pandas as pd
import pytest

from analysis.charts.fractional import (
    fractional_assignments, fractional_tie_memberships, weighted_summary, winsorize,
)
from analysis.fractional_covariance import joint_inference, pairwise_comparisons
from analysis.fractional_reproduction import ROOT, load_package, matrices
from analysis.verify_historical_code import verify_historical_code


@pytest.mark.parametrize("corruption", ["current", "naming_snapshot", "layout_snapshot",
                                       "integration_snapshot", "publication_snapshot"])
def test_recorded_revisions_reject_unrecorded_source_changes(tmp_path, corruption):
    naming_file = "provenance/fractional_naming_v1/manifest.json"
    layout_file = "provenance/repository_layout_v1/manifest.json"
    integration_file = "provenance/fractional_main_integration_v1/manifest.json"
    publication_file = "provenance/repository_publication_v1/manifest.json"
    naming = json.loads((ROOT / naming_file).read_text())["code"]
    layout = json.loads((ROOT / layout_file).read_text())["code"]
    integration = json.loads((ROOT / integration_file).read_text())["code"]
    publication = json.loads((ROOT / publication_file).read_text())["code"]
    active_layout = {**layout, **publication}
    hashes = json.loads((ROOT / "reproduction/fractional_v1/manifest.json").read_text())["historical_code"]
    paths = [naming_file, layout_file, integration_file, publication_file]
    paths += [active_layout[name]["current_path"] if name in active_layout else name for name in hashes]
    paths += [c["historical_path"] for c in [*naming.values(), *integration.values()]]
    paths += [c["snapshot_path"] for c in [*layout.values(), *publication.values()]]
    for name in paths:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    verify_historical_code(tmp_path, hashes)
    chart = "analysis/build_modified_portfolio_chart_pdfs.py"
    scorer = "calculate_supply_chain_transcript_scores.py"
    targets = {"current": layout[chart]["current_path"],
               "naming_snapshot": naming[chart]["historical_path"],
               "layout_snapshot": layout[chart]["snapshot_path"],
               "integration_snapshot": integration[scorer]["historical_path"],
               "publication_snapshot": publication[scorer]["snapshot_path"]}
    target = tmp_path / targets[corruption]
    target.write_bytes(target.read_bytes() + b"\n# Unrecorded change\n")
    with pytest.raises(ValueError):
        verify_historical_code(tmp_path, hashes)


@pytest.mark.parametrize("seed", range(5))
def test_ties_conserve_weights_equal_mass_and_ignore_row_order(seed):
    rng = np.random.default_rng(seed)
    values = rng.integers(0, 8, 101)
    weights = rng.uniform(.01, 2, len(values))
    allocation = fractional_tie_memberships(values, weights)
    np.testing.assert_allclose(allocation.sum(axis=1), weights, rtol=0, atol=1e-12)
    np.testing.assert_allclose(allocation.sum(axis=0), weights.sum() / 5, rtol=0, atol=1e-12)
    for v in np.unique(values):
        proportions = allocation[values == v] / weights[values == v, None]
        np.testing.assert_allclose(proportions, np.broadcast_to(proportions[0], proportions.shape), atol=1e-12)
    order = rng.permutation(len(values))
    np.testing.assert_allclose(fractional_tie_memberships(values[order], weights[order]), allocation[order], atol=1e-12)


def test_tiny_stratum_all_tied_still_has_five_equal_masses():
    np.testing.assert_allclose(fractional_tie_memberships([0], [.37]), [[.074] * 5])


@pytest.mark.parametrize("values,weights", [([], None), ([np.nan], None), ([1], [0]), ([1], [-1])])
def test_invalid_memberships_rejected(values, weights):
    with pytest.raises(ValueError):
        fractional_tie_memberships(values, weights)


def test_nested_resolution_preserves_each_parent_allocation():
    frame = pd.DataFrame({"SCRisk_winsor": [0, 0, 0, 1, 2, 4, 4, 4],
                          "Resolution_winsor": [0, 0, 0, .2, 1, 0, 0, 1],
                          "scrisk_zero": [True, True, True, False, False, False, False, False],
                          "sic_division": ["A"] * 5 + ["B"] * 3})
    risk, joint, _ = fractional_assignments(frame)
    risk_w, resolution_w, joint_w = matrices(frame, risk, joint)
    # Independent nested calculation for each parent, including its weights.
    for division, idx in frame.groupby("sic_division").groups.items():
        for s in range(5):
            positive = np.asarray(idx)[risk_w[idx, s] > 0]
            expected = fractional_tie_memberships(frame.loc[positive, "Resolution_winsor"], risk_w[positive, s])
            np.testing.assert_allclose(joint_w[positive, s * 5:(s + 1) * 5], expected, atol=1e-12)
    np.testing.assert_allclose(resolution_w.sum(axis=1), 1)


def test_joint_covariance_matches_independent_cluster_score_formula():
    y = np.array([.02, -.03, .08, .01, -.04, .05])
    firms = np.array(["a", "a", "b", "c", "c", "d"])
    w = np.array([[1, .2], [.5, .1], [0, .8], [.8, 0], [.1, .4], [.2, .7]])
    means, covariance, influence, counts = joint_inference(y, w, firms)
    manual = []
    for k in range(2):
        mu = sum(w[i, k] * y[i] for i in range(6)) / sum(w[:, k])
        g = len(set(firms[w[:, k] > 0]))
        manual.append([sum(w[i, k] * (y[i] - mu) for i in range(6) if firms[i] == firm)
                       / sum(w[:, k]) * np.sqrt(g / (g - 1)) for firm in sorted(set(firms))])
    manual = np.asarray(manual).T
    np.testing.assert_allclose(influence, manual)
    np.testing.assert_allclose(covariance, manual.T @ manual)
    table, _ = pairwise_comparisons(y, w, firms, ["A", "B"])
    assert table.iloc[0].se_firm_clustered == pytest.approx(np.linalg.norm(manual[:, 1] - manual[:, 0]))
    assert table.iloc[0].df == min(counts) - 1
    assert table.iloc[0].difference_right_minus_left == pytest.approx(means[1] - means[0])


def test_identical_shared_portfolios_have_zero_difference_uncertainty():
    rows, cov = pairwise_comparisons(np.array([1., 4., -2., 5.]), np.full((4, 2), .2), np.array(["a", "a", "b", "c"]), ["A", "B"])
    assert rows.iloc[0].se_firm_clustered == 0
    assert rows.iloc[0].difference_right_minus_left == 0
    assert rows.iloc[0].se_if_covariance_ignored > 0
    assert cov.iloc[0, 1] == pytest.approx(cov.iloc[0, 0])


def test_distinct_calls_from_same_firm_also_have_covariance():
    y = np.array([1., 2., 4., 8.])
    w = np.array([[1, 0], [0, 1], [1, 0], [0, 1]])
    rows, _ = pairwise_comparisons(y, w, np.array(["a", "a", "b", "b"]), ["A", "B"])
    assert rows.iloc[0].shared_unique_calls == 0
    assert rows.iloc[0].shared_firms == 2
    assert rows.iloc[0].covariance != 0


def test_covariance_margins_preserve_original_firm_cluster_se():
    frame = pd.DataFrame({"cik": ["a", "a", "b", "c"], "y": [1., 3., 2., 8.],
                          "scrisk_zero": [False] * 4, "resolution_zero": [False] * 4,
                          "sic_division": ["A"] * 4})
    w = np.array([[1., 0], [.5, 1.], [.1, .5], [1, .5]])
    _, cov, _, _ = joint_inference(frame.y, w, frame.cik)
    for k in range(2):
        keep = w[:, k] > 0
        old = weighted_summary(frame, frame.index[keep], w[keep, k], "y")
        assert cov[k, k] == pytest.approx(old["se_firm_clustered"] ** 2)
    assert np.linalg.eigvalsh(cov).min() >= -1e-12


def test_frozen_dataset_counts_flags_scaling_and_full_nested_conservation():
    data, frame, _ = load_package()
    assert len(data) == 58305 and len(frame) == 52533 and frame.cik.nunique() == 2026
    assert frame.scrisk_zero.sum() == 21027
    assert frame.resolution_zero.sum() == 46123
    assert data.loc[~data.portfolio_eligible, "portfolio_exclusion_reasons"].notna().all()
    assert data.supply_chain_resolution_pairs.le(data.supply_chain_risk_pairs).all()
    for label in ["SCRisk", "Resolution"]:
        raw = data[label + "_weight_sum"] / data.transcript_word_count
        np.testing.assert_allclose(raw, data[label + "_raw"], atol=1e-15, rtol=1e-11)
        np.testing.assert_allclose(data[label + "_raw"].std(ddof=0), data[label + "_sd"], atol=1e-15, rtol=1e-11)
    frame, _ = winsorize(frame)
    risk, joint, _ = fractional_assignments(frame)
    risk_w, resolution_w, joint_w = matrices(frame, risk, joint)
    np.testing.assert_allclose(risk_w.sum(axis=0), 10506.6, atol=1e-8)
    np.testing.assert_allclose(joint_w.sum(axis=0), 2101.32, atol=1e-8)
    # Resolution marginal counts must count each call once, even if it has
    # memberships in several SCRisk parents.
    assert (resolution_w > 0).sum(axis=0).max() <= len(frame)
    assert len(joint[joint.Resolution_quintile == 1]) > (resolution_w[:, 0] > 0).sum()
