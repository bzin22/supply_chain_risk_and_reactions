"""Build the reviewed chart gallery and a concise artifact report."""
from __future__ import annotations

import csv
import base64
import hashlib
import html
import json
import importlib.metadata
import argparse
import shutil
from pathlib import Path


ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'outputs/primary_event_study_2010_2019_v1'
OUT=BASE/'full'
VIEW=ROOT/'.lavish/primary_event_study_2010_2019_v1.html'
ASSETS=VIEW.parent/'primary_event_study_2010_2019_v1_assets'


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(2**20),b''): h.update(block)
    return h.hexdigest()


def records(name): return list(csv.DictReader((OUT/name).open()))
def esc(value): return html.escape(str(value))
def number(value): return f'{int(value):,}'


def main():
    m=json.loads((OUT/'manifest.json').read_text())
    v=json.loads((OUT/'verification.json').read_text())
    assert v['passed']
    release=m.get('date_policy_key')=='release'
    policy_label='Release dates treated as call dates' if release else 'Confirmed-call subset'
    date_metric='Event dates available' if release else 'Confirmed call dates'
    date_count=m['gate_counts']['event_dates_available' if release else 'confirmed_call_dates']
    date_note=("Per the user instruction, v1 earnings-release dates are treated as call dates for every source row. "
               "Separate confirmed-call evidence and source disagreements are retained for audit, not used as date exclusions. "
               "Market-data, model and SIC failures remain explicit." if release else
               "v1's date field records earnings releases. Only separately supported live conference-call dates qualify for CARs. "
               "These portfolios describe the confirmed subset, not the entire scored corpus or the paper's original sample.")
    # The calculation-stage mode flag describes local reference comparisons.
    # Finalize the delivery manifest with the actual inspected pilot evidence.
    pilot_dir=ROOT/m['pilot_path'] if m.get('pilot_path') else BASE/'pilot_03'
    pilot_path=pilot_dir/'manifest.json'
    pilot=json.loads(pilot_path.read_text())
    assert sha(pilot_path)==m['pilot_manifest_sha256']
    assert pilot['pilot_validation']['passed']
    assert pilot['code_hashes']==m['code_hashes']
    m['full_run_local_reference_scoring_crosschecks']=0
    m['pilot_validation']={**pilot['pilot_validation'],
                           'pilot_manifest_path':str(pilot_path.relative_to(ROOT)),
                           'inspection_path':str((pilot_dir/'INSPECTED.md').relative_to(ROOT)),
                           'inspection_sha256':sha(pilot_dir/'INSPECTED.md')}
    m['final_verification']={'passed':v['passed'],'checks_passed':v['checks_passed'],
                            'path':str((OUT/'verification.json').relative_to(ROOT)),
                            'sha256':sha(OUT/'verification.json')}
    m['manifest_finalization']='Report builder attaches inspected-pilot and final-verification evidence; calculation artifacts unchanged.'
    (OUT/'manifest.json').write_text(json.dumps(m,indent=2,sort_keys=True)+'\n')
    source_root=ROOT/'artifacts/primary_event_study_2010_2019_v1'
    sec_sources=[]
    for source in sorted((source_root/'sec_sub').glob('*/source.json')):
        record=json.loads(source.read_text())
        assert record['status']=='ok'
        for part in record['ranges']:
            assert sha(ROOT/part['path'])==part['sha256']
        assert sha(source.with_name('sub.txt'))==record['sub_sha256']
        sec_sources.append({'quarter':source.parent.name,**record})
    archive=ROOT/'.archive/post_2019_removed_20260916/artifacts/earnings_call_supply_chain/ppmi_svd_full_20260910/event_study_inputs'
    original_collection=json.loads((archive/'collection_manifest.json').read_text())
    provenance={'sec_submission_sources':sec_sources,
                'factor_original_collection_manifest_path':str((archive/'collection_manifest.json').relative_to(ROOT)),
                'factor_original_collection_manifest_sha256':sha(archive/'collection_manifest.json'),
                'factor_original_sources':original_collection['factor_files'],
                'dictionary_resolution_origin_git_commit':'0b4c92f3e79d45296cca10a1d241c5ca1252d276',
                'software_versions':{name:importlib.metadata.version(name) for name in ['numpy','pandas','scipy','matplotlib','requests']},
                'source_documents':{'paper':'source_research_paper/theile-et-al-2026-supply-chain-risk-and-resolution-an-empirical-study-of-stock-market-reactions.pdf',
                                    'portfolio_reference':'Table 8, journal pages 2991-2993'},
                'date_evidence_decisions_path':str((source_root/'call_date_evidence_decisions.csv').relative_to(ROOT)),
                'date_evidence_decisions_sha256':sha(source_root/'call_date_evidence_decisions.csv')}
    if release:
        collection=ROOT/'artifacts/primary_event_study_release_dates_v1/collection_manifest.json'
        provenance['new_price_collection']={'path':str(collection.relative_to(ROOT)), 'sha256':sha(collection),
                                            'manifest':json.loads(collection.read_text())}
        provenance['price_retries']=[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),
                                      'classification':json.loads(p.read_text())['classification']}
                                     for p in sorted((collection.parent/'prices').glob('*.retry01.json'))]
    (OUT/'auxiliary_source_provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    ASSETS.mkdir(parents=True,exist_ok=True)
    for p in OUT.iterdir():
        if p.suffix in ['.png','.svg'] or p.name.startswith(('01_','02_','03_','04_','05_')):
            shutil.copyfile(p,ASSETS/p.name)
    gallery=OUT/'chart_gallery.html'
    if gallery.exists():
        portable=gallery.read_text()
        for asset in sorted(ASSETS.iterdir()):
            mime={'.png':'image/png','.svg':'image/svg+xml','.csv':'text/csv'}.get(asset.suffix)
            if mime:
                target=f'href="{ASSETS.name}/{asset.name}" download'
                embedded=base64.b64encode(asset.read_bytes()).decode('ascii')
                portable=portable.replace(target,f'href="data:{mime};base64,{embedded}" download="{asset.name}"')
        gallery.write_text(portable)
    g=m['gate_counts']; sample=m['portfolios']
    titles=[('01_car_0_1_by_scrisk','Mean CAR(0,1) by SCRisk'),
            ('02_car_0_1_by_resolution','Mean CAR(0,1) by Resolution'),
            ('03_car_0_1_heatmap','CAR(0,1): SCRisk × Resolution'),
            ('04_car_2_60_by_scrisk','Mean CAR(2,60) by SCRisk'),
            ('05_car_2_60_heatmap','CAR(2,60): SCRisk × Resolution')]
    gate_rows=''.join(f'<tr><td>{esc(r["gate"].replace("_"," "))}</td><td class="text-right">{number(r["retained"])}</td><td class="text-right">{number(r["excluded_at_gate"])}</td></tr>' for r in records('gate_counts.csv'))
    coverage=records('sic_division_coverage.csv')
    coverage_rows=''.join(f'<tr><td>{esc(r["sic_division"])}</td><td class="text-right">{number(r["all_source_calls"])}</td><td class="text-right">{number(r["portfolio_calls"])}</td><td class="text-right">{number(r["portfolio_companies"])}</td></tr>' for r in coverage)
    panels=[]
    for i,(stem,title) in enumerate(titles,1):
        panels.append(f'''<article id="panel-{i}" class="card bg-base-100 border border-base-content/10 mt-7">
        <div class="card-body"><p class="text-sm text-primary">Panel {chr(64+i)}</p><h2 class="card-title text-2xl">{esc(title)}</h2>
        <figure class="mt-3 rounded-box bg-white"><img class="w-full" src="{ASSETS.name}/{stem}.png" alt="{esc(title)} with portfolio counts" loading="eager"></figure>
        <div class="flex flex-wrap gap-2 mt-3"><a class="btn btn-sm btn-outline" href="{ASSETS.name}/{stem}.svg" download>Vector SVG</a><a class="btn btn-sm btn-outline" href="{ASSETS.name}/{stem}.png" download>PNG</a><a class="btn btn-sm btn-outline" href="{ASSETS.name}/{stem}.csv" download>Counts and intervals · CSV</a></div></div></article>''')
    nav=''.join(f'<a class="btn btn-sm btn-ghost" href="#panel-{i}">Panel {chr(64+i)}</a>' for i in range(1,6))
    html_text=f'''<!doctype html>
<html lang="en" data-theme="luxury"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>2010–2019 scored event study</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/daisyui@5.5.19/daisyui.css">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/daisyui@5.5.19/themes.css">
<script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4.2.4/dist/index.global.js"></script>
<style>*,*::before,*::after{{box-sizing:border-box}} :where(.grid,.flex)>*{{min-width:0}} :where(p,h1,h2,td,th,code){{overflow-wrap:anywhere}} img{{max-width:100%;height:auto}} html{{scroll-behavior:smooth}} .num{{font-variant-numeric:tabular-nums}} figure{{padding:8px}} @media print{{nav,.btn{{display:none}} article{{break-inside:avoid}}}}</style>
</head><body class="bg-base-200 text-base-content"><main class="mx-auto max-w-6xl px-4 py-8 sm:px-8">
<header class="card bg-base-100"><div class="card-body sm:p-9"><div class="flex flex-wrap gap-2"><span class="badge badge-outline">Fiscal labels 2010–2019</span><span class="badge badge-success badge-soft">v1 source unchanged</span><span class="badge badge-warning badge-soft">{policy_label}</span></div>
<h1 class="text-3xl sm:text-5xl font-bold mt-3">Scored calls and portfolio returns</h1><p class="text-base-content/75 max-w-3xl mt-3">All {number(g['source_calls'])} validated transcripts are scored and retained. The five panels use a common sample of {number(sample['n'])} eligible calls from {number(sample['companies'])} firms.</p></div></header>
<section class="grid grid-cols-2 lg:grid-cols-4 gap-3 mt-5">
<div class="stat rounded-box bg-base-100"><div class="stat-title">Scored calls</div><div class="stat-value text-3xl num">{number(g['source_calls'])}</div></div>
<div class="stat rounded-box bg-base-100"><div class="stat-title">{date_metric}</div><div class="stat-value text-3xl num">{number(date_count)}</div></div>
<div class="stat rounded-box bg-base-100"><div class="stat-title">Historical SIC assigned</div><div class="stat-value text-3xl num">{number(g['point_in_time_sic_assigned'])}</div></div>
<div class="stat rounded-box bg-base-100"><div class="stat-title">Portfolio observations</div><div class="stat-value text-3xl num">{number(sample['n'])}</div></div></section>
<div role="note" class="alert alert-warning mt-5"><p><strong>Event-date policy.</strong> {date_note}</p></div>
<nav aria-label="Chart panels" class="flex flex-wrap gap-2 mt-5">{nav}</nav>
<section class="grid gap-5 lg:grid-cols-2 mt-5"><article class="card bg-base-100"><div class="card-body"><h2 class="card-title">Sample gates</h2><div class="overflow-x-auto"><table class="table table-sm"><thead><tr><th>Gate</th><th>Retained</th><th>Excluded here</th></tr></thead><tbody>{gate_rows}</tbody></table></div></div></article>
<article class="card bg-base-100"><div class="card-body"><h2 class="card-title">Construction</h2><p>254 supply-chain terms, 161 risk terms and 55 conservative Resolution terms. Exact matching, approved 10-token proximity, cosine weights, transcript-length adjustment, population SD scaling without centering.</p><p>Carhart estimation uses exactly 200 trading observations, days −209 through −10. Day 0 is the first trading day on or after the selected event date.</p><p>All zeros enter the within-division SCRisk sort. Resolution is sorted within SIC division and SCRisk quintile. All four analysis variables are winsorized at 1% and 99%.</p><p class="text-sm text-base-content/65">Equal-call-weight means. 95% intervals cluster by CIK. Deterministic ties. No controlled regressions.</p></div></article></section>
{''.join(panels)}
<section class="card bg-base-100 mt-7"><div class="card-body"><h2 class="card-title text-2xl">Coverage across all ten divisions</h2><p class="text-sm text-base-content/70">SIC is selected from filings available by the observed fiscal period end. All {number(g['source_calls']-g['point_in_time_sic_assigned'])} missing or conflicting SIC records have a separate audit row.</p><div class="overflow-x-auto"><table class="table table-zebra table-sm"><thead><tr><th>SIC division</th><th>Source calls</th><th>Portfolio calls</th><th>Firms</th></tr></thead><tbody>{coverage_rows}</tbody></table></div></div></section>
<footer class="mt-7 text-sm text-base-content/70"><p>{number(v['checks_passed'])} final reconciliation checks passed. The inspected pilot verified scoring and both CAR windows; the full source SHA-256 is unchanged.</p><p class="mt-2">Dataset SHA-256: <code class="text-xs">{esc(v['dataset_sha256'])}</code></p><p class="mt-2">The dictionary libraries are reconstructions. Uncertainty intervals do not include common-date dependence across firms or dictionary uncertainty.</p></footer>
</main></body></html>'''
    VIEW.write_text(html_text)
    portable=html_text
    for asset in sorted(ASSETS.iterdir()):
        mime={'.png':'image/png','.svg':'image/svg+xml','.csv':'text/csv'}.get(asset.suffix)
        if mime:
            uri='data:'+mime+';base64,'+base64.b64encode(asset.read_bytes()).decode('ascii')
            portable=portable.replace(f'src="{ASSETS.name}/{asset.name}"',f'src="{uri}"')
            portable=portable.replace(f'href="{ASSETS.name}/{asset.name}" download',f'href="{uri}" download="{asset.name}"')
    gallery.write_text(portable)
    lines=['# Primary 2010–2019 scored event study','',
           f"All **{g['source_calls']:,}** v1 calls are scored and retained. The common portfolio sample contains **{sample['n']:,} calls from {sample['companies']:,} firms**.",'',
           date_note,'',
           '## Deliverables','',
           '- [Portable five-chart gallery](chart_gallery.html)',
           '- [Call-level dataset](call_level_scored_car.csv)',
           '- [Run manifest and hashes](manifest.json)',
           '- [Factor, SEC and software provenance](auxiliary_source_provenance.json)',
           '- [Final verification](verification.json)',
           '- [Every excluded call](excluded_calls.csv)',
           '- [Point-in-time SIC map](sic_point_in_time_map.csv)',
           '- [Missing or unassigned SIC](sic_missing_or_unassigned.csv)',
           '- [Quintile assignments](quintile_assignments.csv)',
           '- [Winsorization thresholds](winsorization_thresholds.csv)',
           '- [SIC division coverage](sic_division_coverage.csv)',
           '- [Match audit, all calls](match_audit.jsonl.gz)','',
           '## Gates','', '| Gate | Retained | Excluded here |','|---|---:|---:|']
    lines += [f"| {r['gate']} | {int(r['retained']):,} | {int(r['excluded_at_gate']):,} |" for r in records('gate_counts.csv')]
    lines += ['', '## Five portfolio panels','']
    for stem,title in titles:
        lines += [f'- {title}: [PNG]({stem}.png), [SVG]({stem}.svg), [table with counts and 95% intervals]({stem}.csv)']
    lines += ['', '## Method and validation','',
              'The dictionary counts are 254 / 161 / 55. Exact matching and the approved pair-based proximity rule are retained. All valid source calls enter population-SD standardization without centering. All raw zeros enter portfolio sorts. No controlled regressions were run.','',
              'SIC is the latest filing classification available by actual fiscal period end. Current classifications are not backfilled. CAR estimation requires exactly 200 observations (-209 to -10), with separate complete 2-day and 59-day event windows. The common portfolio sample requires both CARs and historical SIC. Analysis variables are winsorized at global linear 1st/99th percentiles of that sample.','',
              'Risk quintiles are formed within SIC division; Resolution quintiles within division and risk quintile. Outcome-blind SHA-256 tie breaking retains zeros and produces counts differing by at most one. Small strata may have empty bins. Means are equally weighted by call; 95% intervals use CIK-clustered SEs and t critical values.','',
              f"The inspected pilot passed {pilot['pilot_validation']['reference_scoring_crosschecks']} reference scoring checks. See its INSPECTED.md and independent_review.json for independently reproduced Carhart results and window checks. The final artifact passed {v['checks_passed']} reconciliation checks.",'',
              '## Limits','',
              f"{g['source_calls']-g['point_in_time_sic_assigned']:,} calls lack an assigned point-in-time SIC. Every source row remains available with explicit flags and reasons. The date-policy assumption and selective market/SIC coverage should be considered when interpreting these descriptive portfolio means.",'',
              'The dictionaries reconstruct unpublished author libraries. The approved <=10 pair-sum rule is retained even though the paper displays a <10 indicator formula. Provider ticker histories are not permanent CRSP security identifiers. French factors use the documented September 2026 retrieval vintage; SEC submission data use the reprocessed public datasets. Firm-clustered intervals omit common-date dependence and dictionary uncertainty.','',
              '## Reproducibility','',
              f"Dataset SHA-256: `{v['dataset_sha256']}`",'',
              f"Unchanged v1 SHA-256: `{m['source']['sha256_after']}`",'',
              'See `analysis/primary_event_study/README.md` for the complete specification and reproduction commands. The chart review page matches the existing project review pages (DaisyUI luxury theme); figures use a restrained Matplotlib style.']
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n')
    delivery={'dataset':str((OUT/'call_level_scored_car.csv').relative_to(ROOT)),
              'source_v1_sha256':m['source']['sha256_after'],
              'full_run_files':{p.name:sha(p) for p in sorted(OUT.iterdir()) if p.is_file()},
              'pilot_review_sha256':sha(pilot_dir/'INSPECTED.md'),
              'pilot_files':{p.name:sha(p) for p in sorted(pilot_dir.iterdir()) if p.is_file()},
              'gallery_path':str(VIEW.relative_to(ROOT)),'gallery_sha256':sha(VIEW),
              'verification_script_sha256':sha(ROOT/'analysis/verify_primary_event_study.py'),
              'report_builder_sha256':sha(Path(__file__))}
    (BASE/'delivery_manifest.json').write_text(json.dumps(delivery,indent=2)+'\n')
    print(VIEW)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--base',type=Path)
    args=parser.parse_args()
    if args.base:
        BASE=args.base.resolve(); OUT=BASE/'full'
        VIEW=ROOT/'.lavish'/(BASE.name+'.html')
        ASSETS=VIEW.parent/(BASE.name+'_assets')
    main()
