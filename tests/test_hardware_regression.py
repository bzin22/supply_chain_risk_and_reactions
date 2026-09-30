"""Meaningful contracts for the extension, independent of network/raw research data."""
import json
import gzip
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from analysis.hardware_regression_v1.estimate import fit, residualize
from analysis.hardware_regression_v1.inputs import prepare_sample, sha


def synthetic():
    rng = np.random.default_rng(812)
    n = 80
    f = pd.DataFrame({'call_id': [f'id{i}' for i in range(n)],
        'cik': [str(i // 8).zfill(10) for i in range(n)],
        'event_trading_date': ['2020-01-02' if i % 2 else '2019-12-31' for i in range(n)],
        'issuer_fiscal_period_label': ['2019Q4'] * n,
        'provider_quarter_label': ['2010Q1'] * n,
        'SCRisk': rng.uniform(0, 5, n), 'Resolution': rng.uniform(0, 2, n),
        'CAR_0_1': rng.normal(0, .02, n), 'CAR_2_60': rng.normal(0, .03, n)})
    f.loc[:5, ['SCRisk', 'Resolution']] = 0
    thresholds = []
    for v in ['SCRisk', 'Resolution', 'CAR_0_1', 'CAR_2_60']:
        lo, hi = np.quantile(f[v], [.01, .99], method='linear')
        thresholds.append({'variable': v, 'lower_threshold': lo, 'upper_threshold': hi,
            'n': n, 'clipped_below': int(f[v].lt(lo).sum()), 'clipped_above': int(f[v].gt(hi).sum())})
    return f, {'expected_winsorization_thresholds': thresholds}


def test_units_zero_scores_and_once_only_winsorization():
    f, config = synthetic()
    prepared, _, exclusions = prepare_sample(f, config)
    np.testing.assert_array_equal(prepared.CAR_0_1_pp, 100 * prepared.CAR_0_1_winsor)
    assert prepared.SCRisk_winsor.eq(0).sum() == 6
    assert len(exclusions) == 0
    with pytest.raises(ValueError, match='second application'):
        prepare_sample(prepared, config)


def test_calendar_quarters_and_fiscal_year_ignore_provider_labels():
    f, config = synthetic()
    prepared, _, _ = prepare_sample(f, config)
    assert set(prepared.event_calendar_quarter) == {'2019Q4', '2020Q1'}
    assert prepared.issuer_fiscal_year.eq(2019).all()
    assert len(prepared.loc[prepared.issuer_fiscal_year.ne(2010)]) == len(f)


def test_wrong_thresholds_fail():
    f, config = synthetic()
    config['expected_winsorization_thresholds'][0]['upper_threshold'] = 999
    with pytest.raises(ValueError, match='threshold mismatch'):
        prepare_sample(f, config)


def test_fwl_orthogonal_in_unbalanced_panel():
    f, config = synthetic()
    f = f.drop([1, 2, 3, 20])
    x, _ = residualize(f[['SCRisk', 'Resolution']], [f.cik, f.event_trading_date])
    for groups in [f.cik, f.event_trading_date]:
        assert np.max(np.abs(pd.DataFrame(x).groupby(groups.to_numpy()).mean().to_numpy())) < 1e-10


def test_explicit_dummy_verification_and_outcome_units():
    f, config = synthetic()
    prepared, _, _ = prepare_sample(f, config)
    a, s, cov, _, _ = fit(prepared, 'test', True)
    twice = prepared.copy()
    twice.CAR_0_1_pp *= 100
    b, _, cov2, _, _ = fit(twice, 'test', True)
    np.testing.assert_allclose([r['coefficient_pp'] * 100 for r in a], [r['coefficient_pp'] for r in b])
    np.testing.assert_allclose(cov * 10000, cov2)
    assert s['singleton_exclusions'] == 0
    assert s['inference_df'] == 9


def test_restricted_sample_keeps_baseline_thresholds():
    f, config = synthetic()
    f.loc[:10, 'issuer_fiscal_period_label'] = '2010Q4'
    prepared, _, _ = prepare_sample(f, config)
    sub = prepared.loc[prepared.issuer_fiscal_year.ne(2010)]
    np.testing.assert_array_equal(sub.SCRisk_winsor, prepared.loc[sub.index, 'SCRisk_winsor'])


def test_singletons_retained_with_undefined_cooks_distance():
    f, config = synthetic()
    prepared, _, _ = prepare_sample(f, config)
    prepared = prepared.drop(range(1, 8))
    _, summary, _, calls, _ = fit(prepared, 'singleton', True)
    singleton = calls.loc[calls.cik.eq('0000000000')]
    assert summary['singleton_firms_retained'] == 1
    assert summary['singleton_exclusions'] == 0
    assert singleton.cooks_defined.eq(False).all()
    assert singleton.cooks_distance_homoskedastic_diagnostic.isna().all()


def test_published_reference_hashes_and_sample_contract():
    reference = Path('reproduction/hardware_regression_v1')
    manifest = json.loads((reference / 'manifest.json').read_text())
    assert all(sha(p) == digest for p, digest in manifest['files'].items())
    assert sha('reproduction/hardware_baseline_v1/manifest.json') == manifest['baseline_manifest_sha256']
    f = pd.read_csv(reference / 'regression_sample.csv.gz', dtype={'cik': str})
    ids = pd.read_csv(reference / 'sample_ids.csv.gz', dtype={'cik': str})
    assert f.call_id.is_unique and len(f) == 11950 and f.cik.nunique() == 378
    assert f.call_id.equals(ids.call_id) and f.call_weight.eq(1).all()
    assert f.included_R1.sum() == 11595
    assert f.included_R1.eq(f.issuer_fiscal_year.ne(2010)).all()
    assert f.event_calendar_quarter.equals(pd.to_datetime(f.event_trading_date).dt.to_period('Q').astype(str))
    assert ((f.issuer_fiscal_year == 2019) & f.event_trading_date.str.startswith('2020')).sum() == 240


def test_completed_run_uniqueness_common_sample_and_preservation():
    output = Path('outputs/hardware_regression_v1')
    if not (output / 'fingerprints.json').exists():
        pytest.skip('Integration assertions run after initial authorized estimation')
    f = pd.read_csv(output / 'regression_sample.csv', dtype={'cik': str})
    assert len(f) == 11950 and f.cik.nunique() == 378 and f.call_id.is_unique
    assert f.call_weight.eq(1).all() and f.included_M1_M2_M3.all()
    summaries = json.loads((output / 'model_summaries.json').read_text())
    assert all(s['calls'] == 11950 and s['firms'] == 378 for s in summaries[:3])
    hashes = json.loads((output / 'protected_hashes_before.json').read_text())
    assert all(sha(p) == digest for p, digest in hashes.items())
    assert ((f.issuer_fiscal_year == 2019) & f.event_trading_date.str.startswith('2020')).any()
    manifest = json.loads((output / 'audited_inputs/reproduction/hardware_baseline_v1/manifest.json').read_text())
    assert all(sha(output / 'audited_inputs' / p) == digest for p, digest in manifest['files'].items())
    reference = Path('reproduction/hardware_regression_v1')
    for name in ['regression_sample.csv', 'sample_ids.csv']:
        assert gzip.decompress((reference / (name + '.gz')).read_bytes()) == (output / name).read_bytes()
    actual = pd.read_csv(output / 'regression_results.csv')
    expected = pd.read_csv('docs/hardware_regression_v1/regression_results.csv')
    assert actual[['model', 'term']].equals(expected[['model', 'term']])
    for col in ['coefficient_pp', 'cluster_se_pp', 'ci95_low_pp', 'ci95_high_pp', 'p_value']:
        np.testing.assert_allclose(actual[col], expected[col], rtol=1e-10, atol=1e-12)
