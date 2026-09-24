"""Firm-clustered joint uncertainty for fixed fractional memberships.

Each column uses its own finite-cluster correction, preserving the original
marginal standard errors. Cross-products of aligned CIK influences retain
covariance from shared calls AND distinct calls of the same firm.
"""
from itertools import combinations

import numpy as np
import pandas as pd
from scipy.stats import t


def joint_inference(values, memberships, firms):
    values = np.asarray(values, dtype=float)
    weights = np.asarray(memberships, dtype=float)
    firms = np.asarray(firms, dtype=str)
    if (weights.ndim != 2 or values.ndim != 1 or
            weights.shape[0] != len(values) or len(firms) != len(values) or
            not np.isfinite(weights).all() or (weights < 0).any() or
            not np.isfinite(values).all()):
        raise ValueError("Finite outcomes and aligned nonnegative membership weights required")
    masses = weights.sum(axis=0)
    if (masses <= 0).any():
        raise ValueError("Every portfolio must have positive mass")
    means = (weights.T @ values) / masses
    unique_firms, cluster_ids = np.unique(firms, return_inverse=True)
    influence = np.zeros((len(unique_firms), weights.shape[1]))
    present = np.zeros_like(influence)
    np.add.at(influence, cluster_ids, weights * (values[:, None] - means) / masses)
    np.add.at(present, cluster_ids, weights > 0)
    cluster_counts = (present > 0).sum(axis=0)
    if (cluster_counts < 2).any():
        raise ValueError("Clustered inference needs at least two firms per portfolio")
    influence *= np.sqrt(cluster_counts / (cluster_counts - 1))
    covariance = influence.T @ influence
    return means, covariance, influence, cluster_counts


def pairwise_comparisons(values, weights, firms, labels):
    means, covariance, influence, counts = joint_inference(values, weights, firms)
    rows = []
    for a, b in combinations(range(len(labels)), 2):
        difference = means[b] - means[a]
        # Difference of cluster influences avoids cancellation for identical groups.
        se = float(np.linalg.norm(influence[:, b] - influence[:, a]))
        df = int(min(counts[a], counts[b]) - 1)
        margin = float(t.ppf(.975, df) * se)
        shared = (weights[:, a] > 0) & (weights[:, b] > 0)
        rows.append({
            "left": labels[a], "right": labels[b], "difference_right_minus_left": difference,
            "se_firm_clustered": se, "ci_low": difference - margin,
            "ci_high": difference + margin, "df": df,
            "covariance": covariance[a, b],
            "se_if_covariance_ignored": float(np.sqrt(covariance[a, a] + covariance[b, b])),
            "left_firms": int(counts[a]), "right_firms": int(counts[b]),
            "shared_unique_calls": int(shared.sum()),
            "shared_call_firms": int(len(np.unique(np.asarray(firms)[shared]))),
            "shared_firms": int(len(set(np.asarray(firms)[weights[:, a] > 0]) &
                                    set(np.asarray(firms)[weights[:, b] > 0]))),
        })
    return pd.DataFrame(rows), pd.DataFrame(covariance, index=labels, columns=labels)
