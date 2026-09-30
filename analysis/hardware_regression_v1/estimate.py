"""OLS/FWL and CR1, checked against an explicit-dummy statsmodels fit."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import linalg, stats
import statsmodels.api as sm
from statsmodels.stats.sandwich_covariance import cov_cluster


def residualize(values, groups, tol=1e-12, max_iter=10000):
    """Orthogonal projection off several categorical effects, including constants."""
    result = np.asarray(values, dtype=float).copy()
    if result.ndim == 1:
        result = result[:, None]
    codes = [pd.factorize(g, sort=True)[0] for g in groups]
    for iteration in range(max_iter):
        previous = result.copy()
        for code in codes:
            sums = np.zeros((code.max() + 1, result.shape[1]))
            np.add.at(sums, code, result)
            result -= (sums / np.bincount(code)[:, None])[code]
        if np.max(np.abs(result - previous)) < tol:
            return result, iteration + 1
    raise RuntimeError('Fixed-effect projection did not converge')


def cluster_covariance(x, residual, firms, full_rank):
    code, labels = pd.factorize(firms, sort=True)
    n, g = len(x), len(labels)
    if g < 2 or n <= full_rank:
        raise ValueError('Insufficient clusters/residual degrees of freedom')
    bread = linalg.inv(x.T @ x)
    scores = np.zeros((g, x.shape[1]))
    np.add.at(scores, code, x * residual[:, None])
    correction = g / (g - 1) * (n - 1) / (n - full_rank)
    cov = correction * bread @ (scores.T @ scores) @ bread
    return cov, correction, scores @ bread, labels


def fit(frame, name, fixed_effects=False, resolution=True):
    y = frame['CAR_0_1_pp'].to_numpy(float)
    terms = ['SCRisk'] + (['Resolution'] if resolution else [])
    x = frame[[s + '_winsor' for s in terms]].to_numpy(float)
    firms = frame.cik.to_numpy()
    periods = frame.event_calendar_quarter.to_numpy()
    absorbed = []
    if fixed_effects:
        z, iterations = residualize(np.column_stack([y, x]), [firms, periods])
        yr, xr = z[:, 0], z[:, 1:]
        keep = np.linalg.norm(xr, axis=0) > 1e-10 * np.maximum(1, np.linalg.norm(x, axis=0))
        absorbed = [t for t, k in zip(terms, keep) if not k]
        terms = [t for t, k in zip(terms, keep) if k]
        x, xr = x[:, keep], xr[:, keep]
        if not terms or np.linalg.matrix_rank(xr) != len(terms):
            raise ValueError('Unidentified slope combination')
        dummies = [pd.get_dummies(firms, drop_first=True, dtype=float).to_numpy(),
                   pd.get_dummies(periods, drop_first=True, dtype=float).to_numpy()]
        full_x = np.column_stack([x, np.ones(len(y)), *dummies])
    else:
        terms = ['Intercept', *terms]
        yr, xr = y, np.column_stack([np.ones(len(y)), x])
        full_x = xr
        iterations = 0
    # QR supplies a full-design rank check and leverage without squaring condition.
    q, r = linalg.qr(full_x, mode='economic')
    rank = int(np.sum(np.abs(np.diag(r)) > np.max(np.abs(np.diag(r))) * 1e-11))
    if rank != full_x.shape[1]:
        raise ValueError('Disconnected or rank-deficient explicit dummy design')
    beta = linalg.lstsq(xr, yr, lapack_driver='gelsd')[0]
    residual = yr - xr @ beta
    cov, correction, influence, labels = cluster_covariance(xr, residual, firms, rank)
    se = np.sqrt(np.diag(cov))
    g = len(labels)
    tvalues = beta / se
    pvalues = 2 * stats.t.sf(np.abs(tvalues), g - 1)
    critical = stats.t.ppf(.975, g - 1)
    # Independent estimation: original y and full dummy design, no residualization.
    independent = sm.OLS(y, full_x, hasconst=True).fit(method='qr')
    independent_cov = cov_cluster(independent, firms, use_correction=True)
    k = len(beta)
    np.testing.assert_allclose(beta, independent.params[:k], rtol=1e-8, atol=1e-9)
    np.testing.assert_allclose(cov, independent_cov[:k, :k], rtol=1e-7, atol=1e-10)
    np.testing.assert_allclose(residual, independent.resid, rtol=1e-7, atol=1e-8)
    sse = float(residual @ residual)
    sst = float(np.sum((y - y.mean()) ** 2))
    leverage = np.clip(np.sum(q ** 2, axis=1), 0, 1)
    mse = sse / (len(y) - rank)
    cooks = np.full(len(y), np.nan)
    defined = leverage < 1 - 1e-10
    cooks[defined] = residual[defined] ** 2 / (rank * mse) * leverage[defined] / (1 - leverage[defined]) ** 2
    coefs = [{'model': name, 'term': term, 'coefficient_pp': float(b), 'cluster_se_pp': float(s),
              'ci95_low_pp': float(b - critical * s), 'ci95_high_pp': float(b + critical * s),
              't_statistic': float(t), 'p_value': float(p), 'df_inference': g - 1}
             for term, b, s, t, p in zip(terms, beta, se, tvalues, pvalues)]
    summary = {'model': name, 'calls': len(y), 'firms': g, 'time_periods': len(set(periods)),
               'first_calendar_quarter': min(periods), 'last_calendar_quarter': max(periods),
               'firm_effects': fixed_effects, 'time_effects': fixed_effects, 'full_rank': rank,
               'residual_df': len(y) - rank, 'inference_df': g - 1, 'cr1_correction': correction,
               'r2_overall_centered': 1 - sse / sst,
               'r2_overall_adjusted': 1 - (sse / (len(y) - rank)) / (sst / (len(y) - 1)),
               'r2_two_way_partial': 1 - sse / float(yr @ yr) if fixed_effects else None,
               'absorbed_slopes': absorbed, 'constant': 'absorbed in fixed-effect span' if fixed_effects else 'estimated',
               'singleton_firms_retained': int(pd.Series(firms).value_counts().eq(1).sum()),
               'singleton_periods_retained': int(pd.Series(periods).value_counts().eq(1).sum()),
               'singleton_exclusions': 0, 'projection_iterations': iterations,
               'slope_design_condition_number': float(np.linalg.cond(xr)),
               'independent_max_beta_difference': float(np.max(np.abs(beta - independent.params[:k]))),
               'independent_max_covariance_difference': float(np.max(np.abs(cov - independent_cov[:k, :k]))),
               'independent_max_residual_difference': float(np.max(np.abs(residual - independent.resid)))}
    call_diagnostics = frame[['call_id', 'cik', 'event_trading_date', 'event_calendar_quarter']].copy()
    call_diagnostics['residual_pp'] = residual
    call_diagnostics['leverage_full_model'] = leverage
    call_diagnostics['cooks_distance_homoskedastic_diagnostic'] = cooks
    call_diagnostics['cooks_defined'] = defined
    firm_diagnostics = pd.DataFrame({'cik': labels})
    for j, term in enumerate(terms):
        firm_diagnostics[term + '_first_order_delta_pp'] = influence[:, j]
        firm_diagnostics[term + '_first_order_delta_over_cluster_se'] = influence[:, j] / se[j]
    return coefs, summary, pd.DataFrame(cov, index=terms, columns=terms), call_diagnostics, firm_diagnostics
