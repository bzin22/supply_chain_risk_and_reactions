"""Run the four fixed specifications offline; refuse all output overwrites."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess

import numpy as np
import pandas as pd

from .estimate import fit, residualize
from .inputs import ROOT, load_audited, prepare_sample, protected_hashes, sha


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def diagnostics(frame, call_diag, firm_diag, output):
    variation = frame.groupby('cik').agg(
        calls=('call_id', 'size'), SCRisk_unique=('SCRisk_winsor', 'nunique'),
        Resolution_unique=('Resolution_winsor', 'nunique'),
        SCRisk_sd_within=('SCRisk_winsor', lambda s: float(s.std(ddof=0))),
        Resolution_sd_within=('Resolution_winsor', lambda s: float(s.std(ddof=0))))
    variation.to_csv(output / 'within_firm_variation.csv')
    dates = frame.groupby('event_trading_date').agg(calls=('call_id', 'size'), firms=('cik', 'nunique'))
    dates.sort_values('calls', ascending=False).to_csv(output / 'event_date_concentration.csv')
    times = frame.groupby('event_calendar_quarter').agg(calls=('call_id', 'size'), firms=('cik', 'nunique'))
    times.to_csv(output / 'event_quarter_counts.csv')
    pooled = frame[['SCRisk_winsor', 'Resolution_winsor']].to_numpy(float)
    within, _ = residualize(pooled, [frame.cik])
    twoway, _ = residualize(pooled, [frame.cik, frame.event_calendar_quarter])
    correlation = float(np.corrcoef(twoway.T)[0, 1])
    summary = {
        'firms_with_SCRisk_variation': int(variation.SCRisk_unique.gt(1).sum()),
        'firms_with_Resolution_variation': int(variation.Resolution_unique.gt(1).sum()),
        'firms_without_SCRisk_variation': int(variation.SCRisk_unique.eq(1).sum()),
        'firms_without_Resolution_variation': int(variation.Resolution_unique.eq(1).sum()),
        'pooled_score_sd_ddof0': np.std(pooled, axis=0).tolist(),
        'within_firm_score_rms': np.sqrt(np.mean(within ** 2, axis=0)).tolist(),
        'two_way_residualized_score_rms': np.sqrt(np.mean(twoway ** 2, axis=0)).tolist(),
        'pooled_score_correlation': float(np.corrcoef(pooled.T)[0, 1]),
        'two_way_score_correlation': correlation, 'two_way_two_regressor_vif': 1 / (1 - correlation ** 2),
        'unique_event_dates': len(dates), 'maximum_calls_same_date': int(dates.calls.max()),
        'maximum_firms_same_date': int(dates.firms.max()),
        'top_10_dates_call_share': float(dates.calls.nlargest(10).sum() / len(frame)),
        'calls_on_dates_shared_by_multiple_firms_share': float(dates.loc[dates.firms.gt(1), 'calls'].sum() / len(frame)),
        'largest_calendar_quarter_calls': int(times.calls.max()),
        'top_leverage_calls': call_diag.nlargest(5, 'leverage_full_model').astype(object).where(pd.notna(call_diag), None).to_dict('records'),
        'top_cooks_calls': call_diag.nlargest(5, 'cooks_distance_homoskedastic_diagnostic').to_dict('records'),
        'max_abs_firm_first_order_delta_over_se': {v: float(firm_diag[v].abs().max()) for v in firm_diag if v.endswith('_over_cluster_se')},
        'influence_deletions': 0, 'cooks_undefined_unit_leverage_calls': int((~call_diag.cooks_defined).sum()),
        'influence_definition': 'First-order coefficient change proxy (Xtilde Xtilde)^-1 Xtilde_g u_g, divided by CR1 SE; not exact leave-one-firm-out estimates. Cook distance uses homoskedastic MSE for diagnosis only.'}
    write_json(output / 'diagnostics.json', summary)
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, default=ROOT / 'outputs/hardware_regression_v1')
    p.add_argument('--audited-source', type=Path, default=ROOT)
    a = p.parse_args()
    output = a.output.resolve()
    if output.exists():
        raise FileExistsError(f'Refusing to overwrite {output}; choose a new output directory')
    output.mkdir(parents=True)
    protected = protected_hashes()
    write_json(output / 'protected_hashes_before.json', protected)
    plan = Path(__file__).with_name('PLAN.md')
    shutil.copyfile(plan, output / 'PLAN.md')
    initial_lock = json.loads(plan.with_name('initial_specification_lock.json').read_text())
    assert sha(plan) == initial_lock['plan_sha256'], 'Prespecified plan has changed'
    write_json(output / 'specification_lock.json', {
        'initial_pre_estimation_lock': initial_lock,
        'this_execution_started_at_utc': datetime.now(timezone.utc).isoformat(),
        'execution_is_reproduction_of_locked_specifications': True})
    data, eligible, config, snapshot = load_audited(output, a.audited_source.resolve())
    frame, thresholds, exclusions = prepare_sample(eligible, config)
    if len(frame) != len(eligible):
        exclusions.to_csv(output / 'complete_case_exclusions.csv', index=False)
        raise ValueError('Unexpected complete-case attrition; investigate before estimation')
    keep = ['call_id', 'cik', 'portfolio_cik', 'current_ticker', 'issuer_fiscal_period_label',
            'issuer_fiscal_year', 'provider_quarter_label', 'event_trading_date', 'event_calendar_quarter',
            'call_date', 'date_audit_status', 'SCRisk', 'Resolution', 'SCRisk_winsor',
            'Resolution_winsor', 'CAR_0_1', 'CAR_0_1_winsor', 'CAR_0_1_pp']
    frame = frame[keep].copy()
    frame['call_weight'] = 1.0
    frame['included_M1_M2_M3'] = True
    frame['included_R1'] = frame.issuer_fiscal_year.ne(2010)
    frame.to_csv(output / 'regression_sample.csv', index=False, float_format='%.17g')
    frame[['call_id', 'cik', 'issuer_fiscal_period_label', 'event_trading_date', 'event_calendar_quarter',
           'included_M1_M2_M3', 'included_R1']].to_csv(output / 'sample_ids.csv', index=False)
    exclusions.to_csv(output / 'complete_case_exclusions.csv', index=False)
    pd.DataFrame(thresholds).to_csv(output / 'baseline_winsorization_thresholds.csv', index=False, float_format='%.17g')
    pd.DataFrame([{'variable': k, 'population_sd': v, 'population_calls': int(data.score_valid.sum()),
                   'centered': False, 'ddof': 0} for k, v in config['expected_scaling_sd'].items()]).to_csv(output / 'baseline_scaling.csv', index=False, float_format='%.17g')
    counts = {'baseline_input_calls': len(data), 'baseline_input_firms': int(data.cik.nunique()),
              'baseline_eligible_calls': len(eligible), 'baseline_eligible_firms': int(eligible.cik.nunique()),
              'baseline_gate_exclusions': len(data) - len(eligible),
              'complete_case_exclusions': len(exclusions), 'common_model_calls': len(frame),
              'retained_fiscal_2019_events_in_2020': int((frame.issuer_fiscal_year.eq(2019) & frame.event_trading_date.str.startswith('2020')).sum()),
              'SCRisk_zero_calls_retained': int(frame.SCRisk_winsor.eq(0).sum()),
              'Resolution_zero_calls_retained': int(frame.Resolution_winsor.eq(0).sum()),
              'fiscal_2010_excluded_R1': int(frame.issuer_fiscal_year.eq(2010).sum())}
    write_json(output / 'sample_counts_before_estimation.json', counts)
    print(json.dumps(counts), flush=True)
    specs = [('M1', frame, False, False), ('M2', frame, False, True),
             ('M3', frame, True, True), ('R1', frame.loc[frame.included_R1].copy(), True, True)]
    results, summaries = [], []
    for name, sub, fe, resolution in specs:
        print('Estimating and independently verifying', name, flush=True)
        rows, summary, covariance, call_diag, firm_diag = fit(sub, name, fe, resolution)
        results.extend(rows)
        summaries.append(summary)
        covariance.to_csv(output / (name + '_cluster_covariance.csv'), float_format='%.17g')
        if name == 'M3':
            call_diag.to_csv(output / 'M3_call_diagnostics.csv', index=False, float_format='%.17g')
            firm_diag.to_csv(output / 'M3_firm_influence.csv', index=False, float_format='%.17g')
            diag = diagnostics(frame, call_diag, firm_diag, output)
    result_table = pd.DataFrame(results).merge(pd.DataFrame(summaries).drop(columns='absorbed_slopes'), on='model', validate='many_to_one')
    result_table.to_csv(output / 'regression_results.csv', index=False, float_format='%.17g')
    write_json(output / 'model_summaries.json', summaries)
    write_json(output / 'results.json', results)
    # No source/input/chart changes are tolerated, including the initially discrepant files.
    after = protected_hashes()
    assert protected == after, 'Protected working-tree files changed'
    current_plan_hash = sha(plan)
    assert current_plan_hash == sha(output / 'PLAN.md')
    fingerprint = {'completed_at_utc': datetime.now(timezone.utc).isoformat(),
        'python': platform.python_version(), 'platform': platform.platform(),
        'dependencies': {dist.metadata['Name']: dist.version for dist in importlib.metadata.distributions()},
        'git_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'git_worktree_clean': False, 'baseline_preserved': True, 'protected_files_verified': len(protected),
        'input_manifest_sha256': sha(snapshot / 'reproduction/hardware_baseline_v1/manifest.json'),
        'sample_ids_sha256': sha(output / 'sample_ids.csv'),
        'code_sha256': {str(f.relative_to(ROOT)): sha(f) for f in
            sorted([*Path(__file__).parent.glob('*'), ROOT / 'tests/test_hardware_regression.py',
                    ROOT / 'scripts/run_hardware_regression.sh', ROOT / 'analysis/charts/fractional.py']) if f.is_file()},
        'thread_environment': {k: os.environ.get(k) for k in ['OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS']},
        'independent_implementation': 'statsmodels OLS explicit dummies + cov_cluster CR1',
        'raw_scoring_or_CAR_estimation': False, 'new_data_collection': False}
    from .report import render_report
    render_report(output, results, summaries, counts, diag)
    fingerprint['output_sha256'] = {f.name: sha(f) for f in sorted(output.iterdir()) if f.is_file() and f.name != 'fingerprints.json'}
    write_json(output / 'fingerprints.json', fingerprint)
    print(result_table[['model', 'term', 'coefficient_pp', 'cluster_se_pp', 'p_value']].to_string(index=False), flush=True)
    print('Complete:', output, flush=True)


if __name__ == '__main__':
    main()
