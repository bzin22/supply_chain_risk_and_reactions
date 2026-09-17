"""Stage 4: audit the retrieved corpus and emit the gate report.

Training must not start until this reports zero shortfall against 2,000/year and
an acceptable duplicate/failure profile.
"""
from __future__ import annotations

import argparse
import collections
import json
import statistics
from pathlib import Path


def pct(n, d):
    return f"{(100.0 * n / d):.2f}%" if d else "n/a"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sample", type=Path, required=True)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--discovery-report", type=Path, required=True)
    p.add_argument("--sampling-report", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--per-year", type=int, default=2000)
    a = p.parse_args()

    sample_rows = [json.loads(l) for l in a.sample.open()]
    selected = {r["accession"]: r for r in sample_rows}
    # Last record wins, so a resumed retry supersedes its earlier failure.
    man: dict[str, dict] = {}
    for line in a.manifest.open():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        man[r["accession"]] = r
    # Drop manifest rows for accessions no longer in the sample (2001-2002 redraw).
    stale = [k for k in man if k not in selected]
    for k in stale:
        del man[k]

    usable = {k: v for k, v in man.items() if v.get("parser_status") == "ok"}

    # Duplicate audits.
    dup_acc = [k for k, v in collections.Counter(r["accession"] for r in sample_rows).items() if v > 1]
    period_key = collections.Counter(
        (v["cik"], v.get("conformed_period")) for v in usable.values() if v.get("conformed_period"))
    dup_cik_period = {f"{c}|{p}": n for (c, p), n in period_key.items() if n > 1}
    hash_key = collections.Counter(v["sha256_primary_document"] for v in usable.values())
    dup_hash = {h: n for h, n in hash_key.items() if n > 1}

    years = sorted({v["filed_year"] for v in selected.values()})
    rows = []
    for y in years:
        sel_y = [v for v in selected.values() if v["filed_year"] == y]
        man_y = [v for v in man.values() if v["filed_year"] == y]
        ok_y = [v for v in usable.values() if v["filed_year"] == y]
        toks = [v["token_count"] for v in ok_y]
        sizes = [v["bytes_primary_document"] for v in ok_y]
        st = collections.Counter(v.get("parser_status") for v in man_y)
        rows.append({
            "year": y,
            "selected": len(sel_y),
            "retrieved": len(man_y),
            "usable": len(ok_y),
            "shortfall": a.per_year - len(ok_y),
            "download_failed": st.get("download_failed", 0),
            "no_primary_document": st.get("no_primary_document", 0),
            "too_few_tokens": st.get("too_few_tokens", 0),
            "by_form": dict(collections.Counter(v["form"] for v in ok_y)),
            "by_source": dict(collections.Counter(v["source"] for v in ok_y)),
            "tokens_total": sum(toks),
            "tokens_median": int(statistics.median(toks)) if toks else 0,
            "doc_mb_median": round(statistics.median(sizes) / 1e6, 3) if sizes else 0,
        })

    total_tokens = sum(r["tokens_total"] for r in rows)
    summary = {
        "documents_selected": len(selected),
        "documents_retrieved": len(man),
        "documents_usable": len(usable),
        "total_tokens": total_tokens,
        "stale_manifest_rows_ignored": len(stale),
        "duplicate_accessions_in_sample": len(dup_acc),
        "duplicate_cik_report_period_pairs": len(dup_cik_period),
        "duplicate_content_hashes": len(dup_hash),
        "parser_status_counts": dict(collections.Counter(v.get("parser_status") for v in man.values())),
        "by_year": rows,
    }
    (a.output_dir / "corpus_manifest.json").write_text(json.dumps({
        "discovery": json.loads(a.discovery_report.read_text()),
        "sampling": json.loads(a.sampling_report.read_text()),
        "coverage": summary,
    }, indent=2))

    gate_pass = (
        all(r["shortfall"] <= 0 for r in rows)
        and summary["duplicate_accessions_in_sample"] == 0
    )

    L = []
    L.append("# Corpus coverage report\n")
    L.append(f"Gate: **{'PASS' if gate_pass else 'FAIL'}**. "
             f"{len(usable):,} usable documents, {total_tokens:,} tokens, "
             f"{len(years)} years, target {a.per_year:,}/year.\n")
    L.append("## Per year\n")
    L.append("| year | selected | usable | short | dl fail | no doc | thin | 10-K | 10-K405 | cached | dl | tokens | med tok | med MB |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        L.append(
            f"| {r['year']} | {r['selected']:,} | {r['usable']:,} | {r['shortfall']} | "
            f"{r['download_failed']} | {r['no_primary_document']} | {r['too_few_tokens']} | "
            f"{r['by_form'].get('10-K',0):,} | {r['by_form'].get('10-K405',0):,} | "
            f"{r['by_source'].get('cached',0):,} | {r['by_source'].get('download',0):,} | "
            f"{r['tokens_total']:,} | {r['tokens_median']:,} | {r['doc_mb_median']} |")
    L.append(f"\n## Duplicates\n")
    L.append(f"- Duplicate accession numbers in the sample: **{len(dup_acc)}**")
    L.append(f"- Same CIK and conformed report period appearing twice: **{len(dup_cik_period)}** "
             f"(an amended-style refiling or a genuine transition-period overlap; excluded from training)")
    L.append(f"- Byte-identical primary documents: **{len(dup_hash)}**")
    L.append(f"\n## Retrieval failures\n")
    for k, v in sorted(summary["parser_status_counts"].items(), key=lambda kv: -kv[1]):
        L.append(f"- `{k}`: {v:,} ({pct(v, len(man))})")
    (a.output_dir / "coverage_report.md").write_text("\n".join(L) + "\n")

    print("\n".join(L[:6]))
    print(f"\nusable={len(usable):,} tokens={total_tokens:,} gate={'PASS' if gate_pass else 'FAIL'}")
    return 0 if gate_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
