import numpy as np

from analysis.charts.fractional import fractional_tie_memberships


def test_fractional_tie_block_spans_multiple_quintiles_equally():
    allocation = fractional_tie_memberships([0, 0, 0, 1, 2])
    assert np.allclose(allocation[:3, :3], np.full((3, 3), 1 / 3))
    assert np.allclose(allocation[:3, 3:], 0)
    assert np.allclose(allocation[3], [0, 0, 0, 1, 0])
    assert np.allclose(allocation[4], [0, 0, 0, 0, 1])
    assert np.allclose(allocation.sum(axis=0), 1)


def test_fractional_nested_base_weights_are_preserved():
    allocation = fractional_tie_memberships([0, 0, 1], [.5, .5, 1])
    assert np.allclose(allocation.sum(axis=1), [.5, .5, 1])
    assert np.allclose(allocation.sum(axis=0), .4)
    assert np.allclose(allocation[0] / .5, allocation[1] / .5)
