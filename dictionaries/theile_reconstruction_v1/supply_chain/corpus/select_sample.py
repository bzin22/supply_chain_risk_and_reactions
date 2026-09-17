"""Stage 2: draw a year-balanced sample of exactly N filings per year, 1997-2021.

For 2001-2004 the draw is restricted to filings already cached on disk from the
earlier collection, so those years cost no downloads. Every other year draws from
the full eligible population.

Writes selected_sample.jsonl and sampling_report.json.
"""
from __future__ import annotations

import argparse
import collections
import json
import random
from pathlib import Path

# Years whose sampling pool is restricted to the existing cache, costing no
# downloads. 2001-2002 are deliberately NOT here: the cache was built with an
# exact form=="10-K" filter and so holds no 10-K405, which would put a 32%-to-0%
# form-composition break at the 2000/2001 boundary. Those two years draw from the
# full eligible pool and reuse cached files wherever the draw lands on one.
CACHED_POOL_YEARS = {2003, 2004}


def load_cached_index(cached_manifest: Path, cached_raw: Path) -> dict[str, Path]:
    """Map accession -> on-disk raw path, keeping only files that actually exist."""
    found: dict[str, Path] = {}
    for line in cached_manifest.open():
        r = json.loads(line)
        p = cached_raw / r["cik"] / f"{r['accession']}.txt"
        if not p.exists():
            hits = sorted((cached_raw / r["cik"]).glob(r["accession"] + "*")) if (cached_raw / r["cik"]).is_dir() else []
            if not hits:
                continue
            p = hits[0]
        if p.stat().st_size > 0:
            found[r["accession"]] = p
    return found


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--population", type=Path, required=True)
    p.add_argument("--cached-manifest", type=Path, required=True)
    p.add_argument("--cached-raw", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--per-year", type=int, default=2000)
    p.add_argument("--seed", type=int, required=True)
    a = p.parse_args()

    population = [json.loads(l) for l in a.population.open()]
    cached = load_cached_index(a.cached_manifest, a.cached_raw)
    print(f"cached raw filings usable on disk: {len(cached):,}")

    by_year: dict[int, list[dict]] = collections.defaultdict(list)
    for r in population:
        by_year[r["filed_year"]].append(r)

    selected: list[dict] = []
    report_rows = []
    for year in sorted(by_year):
        pool_all = sorted(by_year[year], key=lambda r: r["accession"])
        if year in CACHED_POOL_YEARS:
            pool = [r for r in pool_all if r["accession"] in cached]
            pool_source = "cached_only"
        else:
            pool = pool_all
            pool_source = "full_eligible"
        # Independent stream per year so changing one year cannot reshuffle another.
        rng = random.Random(f"{a.seed}:{year}")
        if len(pool) < a.per_year:
            raise SystemExit(f"year {year}: pool {len(pool)} < per_year {a.per_year}")
        draw = rng.sample(pool, a.per_year)
        for r in draw:
            rec = dict(r)
            hit = cached.get(r["accession"])
            rec["source"] = "cached" if hit else "download"
            rec["cached_path"] = str(hit) if hit else None
            selected.append(rec)
        forms = collections.Counter(r["form"] for r in draw)
        srcs = collections.Counter("cached" if r["accession"] in cached else "download" for r in draw)
        report_rows.append({
            "year": year,
            "eligible_population": len(pool_all),
            "sampling_pool": len(pool),
            "pool_source": pool_source,
            "selected_by_source": dict(srcs),
            "selected": len(draw),
            "selected_by_form": dict(forms),
            "pool_by_form": dict(collections.Counter(r["form"] for r in pool)),
        })
        print(f"  {year}: pool={len(pool):>6,} ({pool_source})  selected={len(draw):,}  "
              f"{dict(forms)}  {dict(srcs)}")

    selected.sort(key=lambda r: (r["filed_year"], r["accession"]))
    accs = collections.Counter(r["accession"] for r in selected)
    assert not [k for k, v in accs.items() if v > 1], "duplicate accession in sample"

    with (a.output_dir / "selected_sample.jsonl").open("w") as fh:
        for r in selected:
            fh.write(json.dumps(r) + "\n")

    (a.output_dir / "sampling_report.json").write_text(json.dumps({
        "seed": a.seed,
        "seed_scheme": "random.Random(f'{seed}:{year}') per year, sample() over accession-sorted pool",
        "per_year": a.per_year,
        "total_selected": len(selected),
        "cached_pool_years": sorted(CACHED_POOL_YEARS),
        "cached_raw_filings_available": len(cached),
        "by_year": report_rows,
    }, indent=2))
    print(f"total selected: {len(selected):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
