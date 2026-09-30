"""Construct a byte-verified audited snapshot without repairing the working tree."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def protected_hashes():
    files = set()
    for directory in ['reproduction', 'dictionaries', 'docs', 'analysis', 'collection', 'scoring', 'tests', 'scripts']:
        for p in (ROOT / directory).rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts and 'hardware_regression_v1' not in p.parts:
                files.add(p)
    for p in (ROOT / 'outputs').rglob('*'):
        if p.is_file() and p.suffix.lower() in {'.png', '.pdf', '.svg'} and not any('hardware_regression' in s for s in p.parts):
            files.add(p)
    return {str(p.relative_to(ROOT)): sha(p) for p in sorted(files)}


def load_audited(output, audited_source):
    package = ROOT / 'reproduction/hardware_baseline_v1'
    manifest = json.loads((package / 'manifest.json').read_text())
    snapshot = output / 'audited_inputs'
    mismatches = []
    for name, expected in manifest['files'].items():
        current = ROOT / name
        actual = sha(current) if current.is_file() else None
        source = current
        if actual != expected:
            # Never substitute different baseline data, only an exact original source.
            if name.startswith('reproduction/hardware_baseline_v1/'):
                raise ValueError(f'Baseline package changed: {name}')
            source = audited_source / name
            if not source.is_file() or sha(source) != expected:
                raise ValueError(f'No exact audited source available for {name}')
            mismatches.append({'path': name, 'working_sha256': actual,
                               'audited_sha256': expected, 'recovered_from': str(source)})
        target = snapshot / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        assert sha(target) == expected
    shutil.copyfile(package / 'manifest.json', snapshot / 'reproduction/hardware_baseline_v1/manifest.json')
    # A fresh process imports the unmodified loader and its exact audited dependencies.
    loader = """from analysis.hardware_reproduction import load_package
from pathlib import Path
import json
data, sample, config = load_package()
data.to_pickle('_loaded_all.pkl')
sample.to_pickle('_loaded_sample.pkl')
Path('_loaded_config.json').write_text(json.dumps(config))
print('Audited loader passed:', len(sample), 'eligible calls;', sample.cik.nunique(), 'firms', flush=True)
"""
    subprocess.run([sys.executable, '-c', loader], cwd=snapshot, check=True)
    data = pd.read_pickle(snapshot / '_loaded_all.pkl')
    sample = pd.read_pickle(snapshot / '_loaded_sample.pkl')
    config = json.loads((snapshot / '_loaded_config.json').read_text())
    for name in ['_loaded_all.pkl', '_loaded_sample.pkl', '_loaded_config.json']:
        (snapshot / name).unlink()
    if len(sample) != 11950 or sample.cik.nunique() != 378 or not sample.call_id.is_unique:
        raise ValueError('Unexpected eligible call/firm count or duplicate call ID')
    roster = pd.read_csv(snapshot / 'reproduction/hardware_baseline_v1/roster_379.csv',
                         dtype=str, keep_default_na=False).set_index('portfolio_cik')
    expected_historical = sample.portfolio_cik.map(roster.historical_cik)
    if not sample.cik.eq(expected_historical).all():
        raise ValueError('Stable historical CIK differs from adjudicated roster mapping')
    if sample.groupby('portfolio_cik').cik.nunique().max() != 1 or sample.groupby('cik').portfolio_cik.nunique().max() != 1:
        raise ValueError('Non-bijective historical issuer mapping requires review')
    report = {'manifest_files_verified': len(manifest['files']),
              'working_tree_source_discrepancies': mismatches,
              'resolution': 'Exact manifest-matching source snapshot; original working tree unchanged',
              'loader_path': 'audited_inputs/analysis/hardware_reproduction.py',
              'loader_sha256': sha(snapshot / 'analysis/hardware_reproduction.py'),
              'baseline_manifest_sha256': sha(package / 'manifest.json'),
              'eligible_calls': len(sample), 'eligible_firms': int(sample.cik.nunique()),
              'historical_cik_mapping_verified': True,
              'successor_mappings': sample.loc[sample.cik.ne(sample.portfolio_cik),
                  ['portfolio_cik', 'cik', 'current_ticker']].drop_duplicates().to_dict('records'),
              'date_adjudications_verified': True, 'unique_call_ids': True,
              'input_fingerprint': sha(package / 'calls.csv.gz')}
    (output / 'input_audit.json').write_text(json.dumps(report, indent=2) + '\n')
    return data, sample, config, snapshot


def prepare_sample(sample, config):
    """Exactly the baseline linear clipping rule, validated against frozen thresholds."""
    # Import the shared helper only for clipping, not portfolio allocation or render.
    from analysis.charts.fractional import winsorize
    if any(c.endswith('_winsor') for c in sample.columns):
        raise ValueError('Input already winsorized; refusing a second application')
    frame, thresholds = winsorize(sample)
    for observed, expected in zip(thresholds, config['expected_winsorization_thresholds']):
        if observed['variable'] != expected['variable']:
            raise ValueError('Winsorization variable order changed')
        for key in ['lower_threshold', 'upper_threshold']:
            if abs(observed[key] - float(expected[key])) > 1e-12:
                raise ValueError(f'Baseline clipping threshold mismatch: {key}')
        for key in ['n', 'clipped_below', 'clipped_above']:
            assert observed[key] == int(expected[key])
    frame['CAR_0_1_pp'] = 100 * frame.CAR_0_1_winsor
    frame['event_calendar_quarter'] = pd.to_datetime(frame.event_trading_date, errors='raise').dt.to_period('Q').astype(str)
    fiscal = frame.issuer_fiscal_period_label
    if not fiscal.str.fullmatch(r'201[0-9](Q[1-4]|T)').all():
        raise ValueError('Adjudicated fiscal periods missing or unsupported')
    frame['issuer_fiscal_year'] = fiscal.str[:4].astype(int)
    import numpy as np
    valid = np.isfinite(frame[['CAR_0_1_pp', 'SCRisk_winsor', 'Resolution_winsor']]).all(axis=1)
    valid &= frame.cik.str.fullmatch(r'\d{10}') & frame.event_calendar_quarter.ne('NaT')
    excluded = frame.loc[~valid, ['call_id', 'cik']].assign(reason='missing regression field')
    return frame.loc[valid].reset_index(drop=True), thresholds, excluded
