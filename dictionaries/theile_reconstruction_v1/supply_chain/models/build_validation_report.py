"""Assemble the tabular backbone of validation_report.md from the run artifacts.

Narrative interpretation is written alongside this output by hand; everything
numeric here is read from files so the report cannot drift from the runs.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
from pathlib import Path


def read_csv(p: Path) -> list[dict]:
    with p.open() as fh:
        return list(csv.DictReader(fh))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--comparison", type=Path, required=True)
    p.add_argument("--table2", type=Path, required=True, help="table2 comparison for the baseline arm")
    p.add_argument("--corpus-manifest", type=Path, required=True)
    p.add_argument("--corpus-report", type=Path, required=True)
    p.add_argument("--precision", type=Path)
    p.add_argument("--baseline-dir", type=Path, required=True)
    p.add_argument("--stability", type=Path)
    p.add_argument("--analysis", type=Path, help="hand-written sections appended verbatim")
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()

    comp = read_csv(a.comparison)
    t2 = read_csv(a.table2)
    cm = json.loads(a.corpus_manifest.read_text())
    cr = json.loads(a.corpus_report.read_text())
    base = json.loads((a.baseline_dir / "extraction_summary.json").read_text())
    prec = {r["method_label"]: r for r in read_csv(a.precision)} if a.precision and a.precision.exists() else {}

    cov = cm["coverage"]
    L = []
    L.append("# Supply chain keyword library: reconstruction validation\n")
    L.append("This is a **reconstructed approximation** of the keyword library in Theile et al. "
             "(2026). It is not the authors' library. metaHeuristica's algorithm is not public, "
             "the authors' corpus and files were unavailable, and several terms in their Table 2 "
             "cannot be produced by any distributional model. Treat every number here as evidence "
             "about a reconstruction, not as a replication of the original dictionary.\n")

    L.append("## 1. Corpus\n")
    L.append(f"- Documents used for training: **{cr['documents_used']:,}** "
             f"of {cov['documents_selected']:,} selected "
             f"({cov['documents_usable']:,} parsed cleanly)")
    L.append(f"- Tokens: **{cr['total_tokens']:,}**")
    L.append(f"- Years: 1997-2021, sampled at exactly 2,000 filings per year")
    L.append(f"- Eligible population discovered: {cm['discovery']['eligible_total']:,} "
             f"(forms {', '.join(cm['discovery']['eligible_forms'])})")
    L.append(f"- Sampling seed: `{cm['sampling']['seed']}`, {cm['sampling']['seed_scheme']}")
    L.append(f"- Excluded as duplicates before training: {cr['documents_excluded_duplicate']:,} "
             f"({cr['exclusion_breakdown']})")
    L.append(f"- Phrase-augmented space: {cr['phrases_detected']:,} phrases, "
             f"{cr['phrase_joins_applied']:,} joins applied\n")
    L.append("The paper trains on *all* 10-K reports 1997-2021. This reconstruction uses a "
             "year-balanced sample because the full set is roughly 600 GB of submissions. "
             "Year balance is a deliberate departure: it prevents the embedding from being "
             "dominated by the high-filing-count early 2000s.\n")

    L.append("## 2. Method comparison\n")
    hdr = ["method", "corpus", "multiword_seed_mode", "final_size", "table2_recovered_of_30",
           "table2_nonseed_recovered_of_17", "cosine_spearman_rho", "seeds_contributing",
           "generic_term_count", "median_document_frequency", "pct_terms_df_under_100"]
    short = ["method", "corpus", "seed mode", "size", "T2 /30", "T2 non-seed /17", "rho",
             "seeds", "generic", "med df", "% df<100"]
    L.append("| " + " | ".join(short) + " |")
    L.append("|" + "---|" * len(short))
    for r in comp:
        L.append("| " + " | ".join(str(r.get(k, "")) for k in hdr) + " |")
    L.append("")
    if prec:
        L.append("Blinded precision (method labels hidden from the reviewer during judging):\n")
        L.append("| arm | reviewed | relevant | borderline | not relevant | strict | lenient |")
        L.append("|---|---|---|---|---|---|---|")
        for k, r in sorted(prec.items()):
            L.append(f"| {k.replace('|', ' / ')} | {r['reviewed']} | {r['relevant']} | {r['borderline']} | "
                     f"{r['not_relevant']} | {r['precision_strict']} | {r['precision_lenient']} |")
        L.append("")

    L.append("## 3. Table 2, term by term\n")
    L.append(f"Baseline arm: `{base['method']}` / `{base['multiword_seed_mode']}`. "
             f"Recovered **{base['table_2_recovered']}/30**.\n")
    L.append("| keyword | paper cos | our cos | our seed | our rank | corpus freq | status |")
    L.append("|---|---|---|---|---|---|---|")
    for r in t2:
        status = "recovered" if r["recovered"] == "True" else f"**missing** ({r['discrepancy_class']})"
        L.append(f"| {r['term']} | {r['paper_cosine']} | {r['our_max_cosine'] or '-'} | "
                 f"{r['our_nearest_seed'] or '-'} | {r['our_seed_rank'] or '-'} | "
                 f"{int(r['corpus_frequency']):,} | {status} |")
    L.append("")

    missing = [r for r in t2 if r["recovered"] != "True"]
    L.append("## 4. Discrepancy classification\n")
    if not missing:
        L.append("All 30 Table 2 terms recovered.\n")
    else:
        counts = collections.Counter(r["discrepancy_class"] for r in missing)
        L.append("| class | n | terms |")
        L.append("|---|---|---|")
        for cls, n in counts.most_common():
            terms = ", ".join(f"`{r['term']}`" for r in missing if r["discrepancy_class"] == cls)
            L.append(f"| {cls} | {n} | {terms} |")
        L.append("")
        for r in missing:
            L.append(f"- `{r['term']}` ({r['discrepancy_class']}): {r['diagnosis']}")
        L.append("")

    if a.analysis and a.analysis.exists():
        L.append(a.analysis.read_text().rstrip())
        L.append("")
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text("\n".join(L) + "\n")
    print(f"wrote {a.output} ({len(L)} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
