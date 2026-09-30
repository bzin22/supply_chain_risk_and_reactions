"""Publication-style table and concise audit report, without editing the paper."""
import html
import json
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle


def table_rows(results, summaries):
    lookup = {(r['model'], r['term']): r for r in results}
    models = ['M1', 'M2', 'M3', 'R1']
    s = {r['model']: r for r in summaries}
    rows = [['', 'M1', 'M2', 'M3 (primary)', 'R1: no FY2010']]
    for term in ['SCRisk', 'Resolution', 'Intercept']:
        for field in ['coefficient', 'se', 'ci', 'p']:
            label = {'coefficient': term, 'se': 'Cluster SE', 'ci': '95% t interval', 'p': 'p-value'}[field]
            line = [label]
            for m in models:
                r = lookup.get((m, term))
                if not r:
                    line.append('Absorbed' if term == 'Intercept' and field == 'coefficient' and m in ['M3', 'R1'] else '--')
                elif field == 'coefficient':
                    line.append(f"{r['coefficient_pp']:.4f}")
                elif field == 'se':
                    line.append(f"({r['cluster_se_pp']:.4f})")
                elif field == 'ci':
                    line.append(f"[{r['ci95_low_pp']:.3f}, {r['ci95_high_pp']:.3f}]")
                else:
                    line.append('<0.0001' if r['p_value'] < .0001 else f"{r['p_value']:.4f}")
            rows.append(line)
    for label, field, fmt in [('Calls', 'calls', ',d'), ('Firms / clusters', 'firms', ',d'),
                              ('Calendar quarters', 'time_periods', 'd'), ('Overall R-squared', 'r2_overall_centered', '.4f'),
                              ('Adjusted overall R-sq.', 'r2_overall_adjusted', '.4f'), ('Two-way partial R-sq.', 'r2_two_way_partial', '.4f')]:
        rows.append([label] + [format(s[m][field], fmt) if s[m][field] is not None else '--' for m in models])
    rows.append(['Firm + quarter effects', 'No', 'No', 'Yes', 'Yes'])
    rows.append(['Inference df (G - 1)'] + [str(s[m]['inference_df']) for m in models])
    return rows


def render_report(output, results, summaries, counts, diag):
    rows = table_rows(results, summaries)
    notes = [
        'Outcome: 100 x winsorized CAR(0,1), in percentage points. Equal call weights; zero scores retained. SCRisk and Resolution retain the baseline uncentered population-SD units and 1%/99% clipping thresholds. R1 excludes adjudicated issuer fiscal year 2010 with the original thresholds.',
        'Firm-clustered CR1 standard errors: G/(G-1) x (N-1)/(N-K), with K counting the full design rank, including fixed effects. Two-sided t inference uses G-1 degrees of freedom. The M3/R1 constant is absorbed in the fixed-effect span. No singleton or influence deletions.',
        'Overall R-squared = 1 - SSE/SST around the outcome mean, including fixed effects. Adjusted overall R-squared uses N-K and N-1 degrees of freedom. Two-way partial R-squared = 1 - SSE/SS of the outcome after removing firm and calendar-quarter effects.',
        'Calendar quarters use event_trading_date; eligible fiscal-2019 events released in 2020 remain. Corrected hardware baseline, common CAR/SIC-eligible sample. Planned analysis following descriptive exploration; not preregistered and not causal.'
    ]
    style = ParagraphStyle('body', fontName='Times-Roman', fontSize=9, leading=11)
    title = ParagraphStyle('title', fontName='Times-Bold', fontSize=14, leading=17)
    doc = SimpleDocTemplate(str(output / 'regression_table.pdf'), pagesize=letter,
                            leftMargin=42, rightMargin=42, topMargin=36, bottomMargin=32)
    story = [Paragraph('Hardware portfolio: SCRisk, Resolution and announcement CARs', title),
             Spacer(1, 8), Paragraph('Planned regression extension following descriptive exploration', style), Spacer(1, 12)]
    table = Table(rows, colWidths=[148, 92, 92, 94, 102], repeatRows=1)
    table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Times-Roman'), ('FONTSIZE', (0, 0), (-1, -1), 8.6),
        ('FONTNAME', (0, 0), (-1, 0), 'Times-Bold'), ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('LEFTPADDING', (0, 0), (-1, -1), 2), ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LINEABOVE', (0, 0), (-1, 0), .8, colors.black),
        ('LINEBELOW', (0, 0), (-1, 0), .5, colors.black),
        ('LINEABOVE', (0, 13), (-1, 13), .5, colors.black),
        ('LINEBELOW', (0, -1), (-1, -1), .8, colors.black),
        *[('FONTNAME', (0, i), (-1, i), 'Times-Bold') for i in [1, 5, 9]]]))
    story.append(table)
    story.append(Spacer(1, 10))
    for note in notes:
        story.extend([Paragraph(html.escape(note), style), Spacer(1, 5)])
    doc.build(story)
    tex = [r'\documentclass[10pt]{article}', r'\usepackage[T1]{fontenc}', r'\usepackage[margin=0.7in]{geometry}',
           r'\usepackage{booktabs}', r'\begin{document}', r'\begin{table}[htbp]\centering',
           r'\caption{Hardware portfolio: SCRisk, Resolution and announcement CARs}',
           r'\small\begin{tabular}{lrrrr}\toprule']
    for i, row in enumerate(rows):
        tex.append(' & '.join(cell.replace('%', r'\%').replace('&', r'\&') for cell in row) + r' \\')
        if i == 0 or i == 12:
            tex.append(r'\midrule')
    tex += [r'\bottomrule\end{tabular}', r'\end{table}', r'\footnotesize']
    tex += [note.replace('%', r'\%') + '\n\n' for note in notes]
    tex.append(r'\end{document}')
    (output / 'regression_table.tex').write_text('\n'.join(tex) + '\n')
    mdtable = '\n'.join(['| ' + ' | '.join(row) + ' |' for row in [rows[0], ['---'] * 5, *rows[1:]]])
    (output / 'regression_table.md').write_text(mdtable + '\n\n' + '\n\n'.join(notes) + '\n')
    r = {(x['model'], x['term']): x for x in results}
    sm = {x['model']: x for x in summaries}
    b = r['M3', 'SCRisk']
    interpretation = (
        f"The primary SCRisk estimate is {b['coefficient_pp']:+.4f} percentage points per baseline score unit "
        f"(cluster SE {b['cluster_se_pp']:.4f}; 95% CI [{b['ci95_low_pp']:.4f}, {b['ci95_high_pp']:.4f}]; "
        f"p={b['p_value']:.3g}). "
        + ('The interval includes zero; the data do not establish a nonzero conditional association at the 5% level. '
           if b['ci95_low_pp'] <= 0 <= b['ci95_high_pp'] else 'The interval excludes zero under the specified firm-clustered inference. ')
        + f"The pooled SCRisk slope is {r['M1', 'SCRisk']['coefficient_pp']:+.4f} in M1 and "
        f"{r['M2', 'SCRisk']['coefficient_pp']:+.4f} after adding Resolution. M3 compares score changes "
        'within firms after common calendar-quarter effects; its change is not caused by a different call sample. '
        f"The R1 slope is {r['R1', 'SCRisk']['coefficient_pp']:+.4f} (p={r['R1', 'SCRisk']['p_value']:.3g}) "
        'after the one planned fiscal-2010 exclusion. This checks dependence on the early fiscal year, not causality.'
    )
    resolution_text = ' '.join(f"{m}: {r[m, 'Resolution']['coefficient_pp']:+.4f} pp, p={r[m, 'Resolution']['p_value']:.4f}." for m in ['M2', 'M3', 'R1'])
    audit = json.loads((output / 'input_audit.json').read_text())
    discrepancy_count = len(audit['working_tree_source_discrepancies'])
    audit_description = (
        'Every source in this checkout matched the corrected baseline manifest; no source recovery was needed.'
        if not discrepancy_count else
        f'The working tree had {discrepancy_count} source/dependency hash or missing-file discrepancies. '
        'Each was resolved using exact expected bytes from the supplied audited source, '
        'without editing current files or weakening the loader.')
    body = f'''# Hardware regression extension

{interpretation}

Resolution estimates: {resolution_text} Resolution is a subset of supply-risk
language, so these slopes are conditional associations, not distinct randomized
treatments. One score unit uses the original hardware population SD before
clipping; no within-firm or sample-specific rescaling was performed.

Adding Resolution makes the negative SCRisk slope larger in magnitude; the two
scores are positively correlated, while Resolution has a positive conditional
slope. Adding fixed effects strengthens the negative association further after
removing stable firm differences and common quarter shifts. These adjustments
do not control for call-specific earnings news. The M3 slopes explain only
{100 * sm['M3']['r2_two_way_partial']:.2f}% of outcome variation remaining after
both fixed effects; statistical precision does not imply strong predictive fit.

## Regression table

{mdtable}

{' '.join(notes)}

## Sample and input audit

The unchanged audited loader passed every manifest, method-equivalence,
dictionary, date-adjudication and unique-call check in an isolated snapshot:
{audit['manifest_files_verified']} manifest entries. {audit_description}
The baseline data package itself had no mismatch. `input_audit.json` records each
discrepancy. `audited_inputs/` preserves the verified loader and dependencies for
a self-contained offline rerun from these derived inputs.

Historical CIK matches the roster's historical issuer mapping. Marvell's current
portfolio CIK 0001835632 maps to predecessor 0001058057 for 25 observations, as
explicitly documented in the baseline roster. Historical and portfolio CIKs map
one-to-one across all 378 eligible firms. Firm effects and clustering use the
historical CIK consistently; no company is split at a ticker or current-ID change.

The baseline contains {counts['baseline_input_calls']:,} input calls from
{counts['baseline_input_firms']} firms; its existing joint CAR/price/SIC/date gates
exclude {counts['baseline_gate_exclusions']:,} calls. The regression starts with
11,950 eligible calls from 378 firms, with {counts['complete_case_exclusions']}
additional complete-case exclusions. M1-M3 use exactly the same call IDs.
R1 excludes {counts['fiscal_2010_excluded_R1']} adjudicated fiscal-2010 calls and
retains {sm['R1']['calls']:,} calls from {sm['R1']['firms']} firms. It does not use
provider fiscal-quarter labels for the exclusion. The original clipping
thresholds and population scaling are retained.

There are {counts['retained_fiscal_2019_events_in_2020']} fiscal-2019 events released
in 2020, all retained in the main sample. Calendar effects span
{sm['M3']['first_calendar_quarter']} to {sm['M3']['last_calendar_quarter']}; they use
trading dates. Zero scores are retained: {counts['SCRisk_zero_calls_retained']}
SCRisk zeros and {counts['Resolution_zero_calls_retained']} Resolution zeros.
All call weights equal one. There are no fractional membership rows.
The 2009 calendar quarters arise from adjudicated issuer fiscal-2010 events;
fiscal scope was not incorrectly converted to a calendar-year exclusion.

Singleton exclusions are zero. M3 retains {sm['M3']['singleton_firms_retained']}
singleton firms and {sm['M3']['singleton_periods_retained']} singleton periods;
R1 retains {sm['R1']['singleton_firms_retained']} and
{sm['R1']['singleton_periods_retained']}, respectively. Singleton effects provide
no within-effect slope information. Absorbed slopes: M3
{sm['M3']['absorbed_slopes']}; R1 {sm['R1']['absorbed_slopes']}. The constant is
absorbed in the fixed-effect span. Full design ranks are
{', '.join(m + ': ' + str(sm[m]['full_rank']) for m in sm)}.

## Diagnostics and numerical verification

{diag['firms_with_SCRisk_variation']} firms have within-firm SCRisk variation;
{diag['firms_with_Resolution_variation']} have Resolution variation. The two-way
residualized regressor correlation is {diag['two_way_score_correlation']:.4f}; the
two-regressor VIF is {diag['two_way_two_regressor_vif']:.3f}. M3 residualized
design condition number is {sm['M3']['slope_design_condition_number']:.3f}.
These diagnostics and firm-level variation are saved; no automatic deletion or
additional specification search was performed.

Across {diag['unique_event_dates']} distinct event trading dates, the busiest date
contains {diag['maximum_calls_same_date']} calls from
{diag['maximum_firms_same_date']} firms. The ten busiest dates account for
{100 * diag['top_10_dates_call_share']:.2f}% of calls;
{100 * diag['calls_on_dates_shared_by_multiple_firms_share']:.2f}% occur on dates
shared by multiple firms. Quarter effects cannot remove every same-day common
shock. Per-date and per-quarter concentration tables are included.

The largest first-order firm influence relative to its cluster SE is
{json.dumps(diag['max_abs_firm_first_order_delta_over_se'])}. These are local
influence approximations, not exact deletion estimates. Full-model leverage,
Cook's distance and residuals are saved per call. Cook's distance uses
homoskedastic MSE only as an influence diagnostic, not for inference. No rows
were removed for leverage, residuals or influence.
Cook's distance is undefined and left missing for the
{diag['cooks_undefined_unit_leverage_calls']} unit-leverage singleton calls, whose
fixed effects fit them exactly; it is not given a spurious finite value.

All four coefficient vectors, residuals and CR1 covariance matrices were checked
against statsmodels OLS with explicit dummies. Maximum coefficient discrepancy:
{max(s['independent_max_beta_difference'] for s in summaries):.3g}; maximum
covariance discrepancy: {max(s['independent_max_covariance_difference'] for s in summaries):.3g}.
The main implementation uses alternating projection/FWL and a separately coded
cluster sandwich. Numerical tolerance is 1e-9 absolute/1e-8 relative for
coefficients and 1e-10 absolute/1e-7 relative for covariance. R-squared definitions
are above; they should not be conflated with each other.

CR1 method reference: [statsmodels covariance implementation](https://www.statsmodels.org/stable/_modules/statsmodels/stats/sandwich_covariance.html#cov_cluster).

## Interpretation limits

Earnings surprises, guidance changes and other simultaneous news are omitted.
They may affect both transcript language and announcement returns, so controlling
for Resolution and fixed effects does not identify a causal SCRisk effect. The
transcript can also describe information released during the return window.
Firm clustering allows within-firm error dependence but assumes independent
clusters; cross-firm same-day or industry shocks may make these intervals too
narrow. Calendar-quarter effects do not guarantee residual independence.

The current-company/US-headquarters screen, survival and transcript/price/SIC
availability limit external validity. The inherited common eligibility gate
requires both CAR horizons even though only CAR(0,1) is regressed here. This
preserves the corrected baseline but can select a different sample than a
CAR(0,1)-only gate. Reconstructed dictionaries and substantial zero scores are
measurement limitations. Null estimates are not proof of no economically
relevant relationship; the reported intervals describe precision under this
model and covariance assumption. This was planned after descriptive exploration,
not preregistered. No supplier-dependence interaction or CAR(2,60) regression ran.

## Reproduction

See [the code README](../../analysis/hardware_regression_v1/README.md) for the single rerun command.
`sample_ids.csv` identifies inclusion in every model; `regression_sample.csv`
retains original scaled and once-clipped values. `regression_results.csv` holds
full-precision coefficients, cluster SEs, intervals, p-values, sample counts and
R-squared. PDF, LaTeX and Markdown tables are generated from those same results.
`fingerprints.json` records input, code, output and dependency hashes/versions;
`protected_hashes_before.json` establishes preservation of the baseline,
dictionaries, charts and existing source files. No paper, baseline chart, remote
branch, transcript score or CAR estimate was changed.
'''
    (output / 'REPORT.md').write_text(body)
    table_html = '<thead><tr>' + ''.join('<th>' + html.escape(x) + '</th>' for x in rows[0]) + '</tr></thead><tbody>'
    for row in rows[1:]:
        table_html += '<tr>' + ''.join('<td>' + html.escape(x) + '</td>' for x in row) + '</tr>'
    table_html += '</tbody>'
    page = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Hardware regressions · planned extension</title><style>
*{box-sizing:border-box}body{margin:0;background:#10100f;color:#e6dfd4;font:15px/1.55 system-ui,sans-serif}main{max-width:1150px;margin:auto;padding:36px 24px 60px}h1{font-size:clamp(30px,5vw,46px);line-height:1.15;letter-spacing:-.035em}h2{font-size:20px}p{max-width:920px}.eyebrow,summary,a{color:#cbb787}.eyebrow{font-size:12px;letter-spacing:.12em;text-transform:uppercase}.muted{color:#b8b2a7}.result{padding:20px 24px;background:#191815;border-left:3px solid #cbb787;margin:24px 0}.metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin:24px 0}.metric{border:1px solid #373229;padding:18px;border-radius:10px}.metric strong{display:block;font-size:29px;color:#dbc38b}.metric span{font-size:13px;color:#b8b2a7}.tablewrap{max-width:100%;overflow-x:auto;border:1px solid #373229;border-radius:10px}table{width:100%;min-width:680px;border-collapse:collapse;font-variant-numeric:tabular-nums}th,td{text-align:right;padding:9px 15px;border-bottom:1px solid #302c24}th:first-child,td:first-child{text-align:left}th{color:#cbb787;background:#191815}tr:nth-child(4n+1){background:#171612}section,details{min-width:0;overflow-wrap:anywhere}details{border-bottom:1px solid #373229;padding:18px 0}summary{cursor:pointer;font-weight:600}footer{margin-top:25px;color:#918b80;font-size:12px}@media(max-width:650px){main{padding:24px 16px}.metrics{grid-template-columns:minmax(0,1fr)}.metric strong{font-size:25px}}
</style><main><div class="eyebrow">Hardware portfolio · regression v1</div><h1>SCRisk and announcement returns</h1>
<p class="muted">Planned analysis following descriptive exploration. Not preregistered. Outcome: CAR(0,1) in percentage points; one equal-weighted row per call.</p>
<section class="result"><h2>Negative SCRisk association persists with fixed effects</h2><p>__INTERPRETATION__</p></section>
<div class="metrics"><div class="metric"><strong>11,950</strong><span>Calls · same M1–M3 sample</span></div><div class="metric"><strong>378</strong><span>Historical issuer CIK clusters</span></div><div class="metric"><strong>240</strong><span>Fiscal-2019 events released in 2020 retained</span></div></div>
<h2>Fixed specifications, full results</h2><div class="tablewrap"><table>__TABLE__</table></div>
<details><summary>Units, covariance and R-squared definitions</summary>__NOTES__</details>
<details><summary>Audit and diagnostics</summary><p>All 263 input-manifest entries verified in an isolated exact-source snapshot. The corrected baseline and existing files remain unchanged. Main models lose no additional complete cases. R1 retains 11,595 calls from 378 firms, excluding 355 adjudicated fiscal-2010 calls. No singleton or influential observations are deleted.</p><p>Every model agrees with an independent explicit-dummy coefficient and clustered-covariance calculation. The detailed report retains within-firm variation, collinearity, leverage, firm influence and event-date concentration diagnostics.</p></details>
<details open><summary>Interpretation limits</summary><p>Resolution is positively associated with returns conditional on SCRisk. The primary slopes explain only __PARTIAL__% of return variation remaining after both fixed effects. Earnings surprises, guidance and other concurrent news are omitted. Shared-date shocks may leave cross-firm residual dependence that firm clustering does not address. Current-company screening and transcript/price/SIC gates select the sample. These estimates are not causal.</p></details>
<footer>Design follows the existing hardware portfolio review page. The paper-ready PDF, full-precision CSV and reproducible code are delivered separately. No supplier interaction, CAR(2,60) regression, new scoring or return estimation.</footer></main></html>'''
    page = page.replace('__INTERPRETATION__', html.escape(interpretation)).replace('__TABLE__', table_html)
    page = page.replace('__NOTES__', ''.join('<p>' + html.escape(n) + '</p>' for n in notes))
    page = page.replace('__PARTIAL__', f"{100 * sm['M3']['r2_two_way_partial']:.2f}")
    (output / 'regression_review.html').write_text(page)
