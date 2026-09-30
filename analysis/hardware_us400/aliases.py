"""Collect only uncovered issuer-quarters under evidenced historical aliases."""

from collections import Counter
from .data import Client, content_validation, records
from .inventory import ART, OUT, read
from analysis.primary_event_study import core


def plan():
    """Aliases are queried only for quarters still uncovered after main collection."""
    companies = {x['portfolio_cik']:x for x in read(ART / 'company_manifest.csv')}
    pairs = read(ART / 'pair_manifest_reviewed.csv')
    covered = {(x['portfolio_cik'],x['quarter_label']) for x in pairs if x['call_id']}
    for name in ['collection_pilot.csv','collection_full.csv']:
        if (ART/name).exists():
            covered.update((x['portfolio_cik'],x['quarter_label']) for x in read(ART/name) if x['new_call_id'])
    previous = {(r['params'].get('symbol'),r['params'].get('quarter')) for r in records()
                if r['params']['function']=='EARNINGS_CALL_TRANSCRIPT' and r['status'] in ['ok','no_transcript']}
    # Prior local, identity-matched empties are also reusable findings.
    import json
    for r in read(ART/'local_cache_validation.csv'):
        if r['status']=='no_transcript':
            d=json.loads((core.ROOT/r['path']).read_text());p=d.get('payload',d)
            previous.add((p.get('symbol'),p.get('quarter')))
    links={}
    for r in read(ART/'security_history.csv'):
        links.setdefault(r['ticker'],set()).add(r['cik'])
    planned=[];audit=[]
    for p in pairs:
        if (p['portfolio_cik'],p['quarter_label']) in covered or p['decision'] in ['not_applicable','unresolved_identity']:
            continue
        c=companies[p['portfolio_cik']]
        for alias in c['aliases'].split(';'):
            if alias == p['request_symbols']:
                continue
            reason='request_missing_alias'
            if (alias,p['quarter_label']) in previous:
                reason='reuse_prior_alias_response'
            elif links.get(alias,set()) - {c['historical_cik']}:
                reason='hold_recycled_ticker_identity'
            elif alias in ['BIO-B','BELFA','IARTV','GEF-B','HEI-A','IFF-WI','WSO-B']:
                reason='same_issuer_alternate_share_class_or_when_issued_security; no separate call required'
            row={**p,'provider_alias':alias,'identity_evidence_url':c.get('additional_alias_evidence') or c['identity_evidence'],'alias_decision':reason}
            audit.append(row)
            if reason=='request_missing_alias':planned.append(row)
    core.write_csv(ART/'alias_review.csv',audit)
    core.write_csv(ART/'alias_missing_pairs.csv',planned)
    print('Alias plan',len(planned),dict(Counter(x['provider_alias'] for x in planned)),flush=True)


def collect_aliases():
    assert (OUT / "pilot/INSPECTED.md").is_file()
    plan = read(ART / "alias_missing_pairs.csv")
    companies = {x["portfolio_cik"]: x for x in read(ART / "company_manifest.csv")}
    reused = {
        (x["portfolio_cik"], x["quarter_label"])
        for x in read(ART / "pair_manifest_reviewed.csv")
        if x["call_id"]
    }
    client = Client()
    results = []
    for pair in plan:
        assert (pair["portfolio_cik"], pair["quarter_label"]) not in reused
        company = dict(companies[pair["portfolio_cik"]])
        company["aliases"] += ";" + pair["provider_alias"]
        path, payload, status = client.fetch(
            {
                "function": "EARNINGS_CALL_TRANSCRIPT",
                "symbol": pair["provider_alias"],
                "quarter": pair["quarter_label"],
            }
        )
        row, validation = (
            content_validation(path, company, pair["quarter_label"])
            if status == "ok"
            else (None, status)
        )
        results.append(
            {
                **pair,
                "collection_status": status,
                "validation_status": validation,
                "new_call_id": row["call_id"] if row else "",
                "new_raw_path": core.relative(path),
                "new_raw_sha256": core.sha256(path),
            }
        )
    core.write_csv(ART / "alias_collection.csv", results)
    print(
        "Alias results",
        dict(Counter(x["validation_status"] for x in results)),
        flush=True,
    )


if __name__ == "__main__":
    plan()
    collect_aliases()
