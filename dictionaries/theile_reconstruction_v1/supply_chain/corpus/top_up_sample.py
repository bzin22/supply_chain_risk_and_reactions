"""Stage 3b: restore each year to exactly 2,000 usable documents.

A few filings per year fail to parse, carry no primary document, or turn out to
be byte-identical repeats. Left alone, the corpus lands at 1,99x for some years
and the exactly-2,000 design is quietly broken. This draws replacements from the
same year's eligible pool, continuing the same seeded RNG stream, and never
reuses an accession already selected.

Writes an extended selected_sample.jsonl plus topup_report.json. Run the fetcher
again afterwards; it is resumable and will only pull the new accessions.
"""
from __future__ import annotations

import argparse
import collections
import json
import random
from pathlib import Path


def usable_by_year(manifest: Path, selected: dict) -> tuple[collections.Counter, set]:
    rows: dict[str, dict] = {}
    for line in manifest.open():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r["accession"] in selected:
            rows[r["accession"]] = r
    ok = [r for r in rows.values() if r.get("parser_status") == "ok"]
    ok.sort(key=lambda r: (r["filed"], r["accession"]))
    seen_hash, seen_period = set(), set()
    good = set()
    for r in ok:
        h = r.get("sha256_primary_document")
        pk = (r["cik"], r.get("conformed_period"))
        if h in seen_hash:
            continue
        if r.get("conformed_period") and pk in seen_period:
            continue
        seen_hash.add(h)
        if r.get("conformed_period"):
            seen_period.add(pk)
        good.add(r["accession"])
    attempted = set(rows)
    return collections.Counter(selected[a]["filed_year"] for a in good), attempted


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--population", type=Path, required=True)
    p.add_argument("--sample", type=Path, required=True)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--cached-manifest", type=Path, required=True)
    p.add_argument("--cached-raw", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--per-year", type=int, default=2000)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--round", type=int, required=True, help="top-up round, keeps draws distinct")
    a = p.parse_args()

    from select_sample import load_cached_index, CACHED_POOL_YEARS
    population = [json.loads(l) for l in a.population.open()]
    selected = {json.loads(l)["accession"]: json.loads(l) for l in a.sample.open()}
    cached = load_cached_index(a.cached_manifest, a.cached_raw)

    good_by_year, attempted = usable_by_year(a.manifest, selected)
    by_year: dict[int, list[dict]] = collections.defaultdict(list)
    for r in population:
        by_year[r["filed_year"]].append(r)

    added, report = [], []
    for year in sorted(by_year):
        have = good_by_year.get(year, 0)
        need = a.per_year - have
        if need <= 0:
            report.append({"year": year, "usable": have, "needed": 0, "added": 0})
            continue
        pool_all = sorted(by_year[year], key=lambda r: r["accession"])
        if year in CACHED_POOL_YEARS:
            pool_all = [r for r in pool_all if r["accession"] in cached]
        pool = [r for r in pool_all if r["accession"] not in selected]
        rng = random.Random(f"{a.seed}:{year}:topup{a.round}")
        draw = rng.sample(pool, min(need, len(pool)))
        for r in draw:
            rec = dict(r)
            hit = cached.get(r["accession"])
            rec["source"] = "cached" if hit else "download"
            rec["cached_path"] = str(hit) if hit else None
            rec["topup_round"] = a.round
            added.append(rec)
        report.append({"year": year, "usable": have, "needed": need, "added": len(draw),
                       "pool_remaining": len(pool) - len(draw)})
        print(f"  {year}: usable={have:,} need={need} added={len(draw)}")

    out = list(selected.values()) + added
    out.sort(key=lambda r: (r["filed_year"], r["accession"]))
    with (a.output_dir / "selected_sample.jsonl").open("w") as fh:
        for r in out:
            fh.write(json.dumps(r) + "\n")

    path = a.output_dir / "topup_report.json"
    hist = json.loads(path.read_text()) if path.exists() else []
    hist.append({"round": a.round, "seed": a.seed, "added_total": len(added), "by_year": report})
    path.write_text(json.dumps(hist, indent=2))
    print(f"round {a.round}: added {len(added)}; sample now {len(out):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
