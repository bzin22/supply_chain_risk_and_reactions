"""Stage 1: build the eligible 10-K population for 1997-2021 from EDGAR full-index.

Eligible form types are exactly 10-K and 10-K405. Amendments (10-K/A, 10-K405/A),
small-business forms (10-KSB), and transition reports (10-KT) are excluded by
whitelist, so any unanticipated variant is excluded rather than silently kept.

Writes eligible_population.jsonl and discovery_report.json. Downloads nothing but
quarterly index files.
"""
from __future__ import annotations

import argparse
import collections
import gzip
import json
import sys
import time
from datetime import date
from pathlib import Path

import requests

ELIGIBLE_FORMS = {"10-K", "10-K405"}
# Recorded so the coverage report can state what was seen and dropped, not just what was kept.
TRACKED_EXCLUSIONS = {
    "10-K/A", "10-K405/A", "10-KSB", "10-KSB/A", "10-KT", "10-KT/A",
    "10-KSB405", "10-KSB405/A", "10-K405/A ", "NT 10-K", "10-KT405",
}
START_YEAR, END_YEAR = 1997, 2021
INDEX_URL = "https://www.sec.gov/Archives/edgar/full-index/{year}/QTR{qtr}/master.idx"


def session(user_agent: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"})
    return s


def fetch_index(s: requests.Session, year: int, qtr: int, cache: Path, rps: float) -> bytes:
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"{year}QTR{qtr}.idx.gz"
    if path.exists() and path.stat().st_size > 0:
        return gzip.decompress(path.read_bytes())
    url = INDEX_URL.format(year=year, qtr=qtr)
    for attempt in range(5):
        time.sleep(1.0 / rps)
        r = s.get(url, timeout=120)
        if r.status_code == 200:
            path.write_bytes(gzip.compress(r.content))
            return r.content
        if r.status_code in (403, 429, 500, 502, 503, 504):
            time.sleep(min(2 ** attempt, 30))
            continue
        r.raise_for_status()
    raise RuntimeError(f"failed to fetch {url}")


def parse_index(payload: bytes, year: int) -> tuple[list[dict], collections.Counter]:
    """Return eligible rows plus a census of every annual-report-ish form seen."""
    rows: list[dict] = []
    seen: collections.Counter = collections.Counter()
    lo, hi = date(START_YEAR, 1, 1), date(END_YEAR, 12, 31)
    for line in payload.decode("latin-1", errors="replace").splitlines():
        if line.count("|") != 4:
            continue
        cik, company, form, filed, filename = line.split("|")
        if not form.startswith("10-K") and form != "NT 10-K":
            continue
        seen[form] += 1
        if form not in ELIGIBLE_FORMS:
            continue
        try:
            filed_date = date.fromisoformat(filed)
        except ValueError:
            continue
        if not (lo <= filed_date <= hi):
            continue
        accession = Path(filename).stem
        rows.append({
            "cik": cik.zfill(10),
            "company": company.strip(),
            "form": form,
            "filed": filed,
            "filed_year": filed_date.year,
            "accession": accession,
            "filename": filename,
            "url": f"https://www.sec.gov/Archives/{filename}",
        })
    return rows, seen


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--index-cache", type=Path, required=True)
    p.add_argument("--user-agent", required=True)
    p.add_argument("--rps", type=float, default=8.0)
    a = p.parse_args()

    a.output_dir.mkdir(parents=True, exist_ok=True)
    s = session(a.user_agent)

    all_rows: list[dict] = []
    form_census: dict[int, collections.Counter] = {}
    for year in range(START_YEAR, END_YEAR + 1):
        year_seen: collections.Counter = collections.Counter()
        for qtr in (1, 2, 3, 4):
            payload = fetch_index(s, year, qtr, a.index_cache, a.rps)
            rows, seen = parse_index(payload, year)
            all_rows.extend(rows)
            year_seen.update(seen)
        form_census[year] = year_seen
        print(f"  {year}: {sum(year_seen[f] for f in ELIGIBLE_FORMS & set(year_seen)):>6,} eligible "
              f"of {sum(year_seen.values()):>6,} 10-K-family rows", file=sys.stderr)

    # Deduplicate by accession. A filing can appear in two quarterly indexes.
    by_acc: dict[str, dict] = {}
    dup_accessions = 0
    for r in all_rows:
        if r["accession"] in by_acc:
            dup_accessions += 1
            continue
        by_acc[r["accession"]] = r
    population = sorted(by_acc.values(), key=lambda r: (r["filed"], r["accession"]))

    out = a.output_dir / "eligible_population.jsonl"
    with out.open("w") as fh:
        for r in population:
            fh.write(json.dumps(r) + "\n")

    by_year_form: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for r in population:
        by_year_form[str(r["filed_year"])][r["form"]] += 1

    report = {
        "start_year": START_YEAR,
        "end_year": END_YEAR,
        "eligible_forms": sorted(ELIGIBLE_FORMS),
        "eligible_total": len(population),
        "duplicate_accessions_dropped_at_discovery": dup_accessions,
        "eligible_by_year_form": {y: dict(c) for y, c in sorted(by_year_form.items())},
        "form_census_by_year": {str(y): dict(c) for y, c in sorted(form_census.items())},
    }
    (a.output_dir / "discovery_report.json").write_text(json.dumps(report, indent=2))
    print(f"eligible={len(population):,}  dropped_dupe_accessions={dup_accessions:,}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
