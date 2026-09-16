#!/usr/bin/env python3
"""Corpus-wide transcript content-integrity scan (read-only)."""
import csv, json, sys
import os
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]  # repository root
sys.path.insert(0, str(ROOT))
import calculate_supply_chain_transcript_scores as S
S.configure_csv_field_size_limit()

RUN = Path(os.environ.get('SCRISK_AUDIT_RUN', str(
    ROOT / 'artifacts/earnings_call_supply_chain/ppmi_svd_full_20260910')))
OUT = Path(os.environ.get('SCRISK_AUDIT_OUT', str(ROOT / 'outputs/scrisk_zero_audit')))

# Taken from the scoring pipeline, not restated here, so the audit and the
# transcript-integrity filter are the same rule by construction.
MARKERS = dict(S.TRANSCRIPT_INTEGRITY_MARKERS)

zero_keys, pos_keys = set(), set()
with (RUN / 'earnings_call_event_returns.csv').open(newline='', encoding='utf-8') as h:
    for r in csv.DictReader(h):
        if r['event_status'] != 'ok':
            continue
        (zero_keys if float(r['SCRisk'] or 0) == 0 else pos_keys).add((r['ticker'], r['quarter_label']))

rows = []
with (RUN / 'earnings_call_transcripts_scored.csv').open(newline='', encoding='utf-8') as h:
    for r in csv.DictReader(h):
        key = (r['ticker'], r['quarter_label'])
        group = 'zero' if key in zero_keys else ('positive' if key in pos_keys else 'not_analysable')
        text = r.get('transcript_text') or ''
        low = text.lower()
        toks = S.tokenize(text)
        flags = {name: int(marker in low) for name, marker in MARKERS.items()}
        ratio = len(set(toks)) / len(toks) if toks else ''
        pipeline_status, pipeline_flags = S.assess_transcript_integrity(text)
        rows.append(dict(ticker=r['ticker'], quarter_label=r['quarter_label'],
                         company_name=r['company_name'], sector=r['sector'], year=r['year'],
                         status=r['status'], group=group, tokens=len(toks),
                         distinct_token_ratio=round(ratio, 4) if toks else '',
                         degenerate_repetition=int(bool(toks) and ratio < S.DEGENERATE_DISTINCT_TOKEN_RATIO),
                         very_short_under_1000_tokens=int(0 < len(toks) < S.MINIMUM_SPOKEN_TOKENS),
                         pipeline_integrity_status=pipeline_status,
                         pipeline_integrity_flags=';'.join(pipeline_flags), **flags))

with (OUT / 'transcript_content_integrity.csv').open('w', newline='', encoding='utf-8') as h:
    w = csv.DictWriter(h, fieldnames=list(rows[0].keys()))
    w.writeheader(); w.writerows(rows)

flagcols = ['degenerate_repetition', 'very_short_under_1000_tokens', *MARKERS]
summary = {}
for g in ('zero', 'positive', 'not_analysable'):
    sub = [r for r in rows if r['group'] == g]
    summary[g] = {'calls': len(sub),
                  **{c: sum(r[c] for r in sub) for c in flagcols},
                  'any_flag': sum(1 for r in sub if any(r[c] for c in flagcols))}
summary['total_rows'] = len(rows)
summary['markers'] = MARKERS
(OUT / 'transcript_content_integrity_summary.json').write_text(json.dumps(summary, indent=2))
print(json.dumps(summary, indent=2))
bad = [r for r in rows if r['group'] in ('zero', 'positive') and
       (r['degenerate_repetition'] or r['redacted_spoken_content'] or r['provider_copyright_boilerplate'])]
print(f"\ncontent-absent analysable calls: {len(bad)}")
for r in sorted(bad, key=lambda r: r['tokens'])[:25]:
    print(f"  {r['ticker']:6s} {r['quarter_label']}  group={r['group']:8s} tokens={r['tokens']:6d} "
          f"ratio={r['distinct_token_ratio']} "
          f"flags={[c for c in flagcols if r[c]]}")
