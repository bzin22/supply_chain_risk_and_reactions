"""Unblind the manual review and turn judgements into per-arm precision.

Also writes review_status back into each arm's supply_chain_terms.jsonl, so the
required review_status field carries a real value for reviewed terms.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
from pathlib import Path

VALID = {"relevant", "borderline", "not_relevant"}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sheet", type=Path, required=True)
    p.add_argument("--key", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--write-back", action="store_true")
    p.add_argument("--candidate-dirs", type=Path, nargs="*", default=[])
    a = p.parse_args()

    judged: dict[str, str] = {}
    notes: dict[str, str] = {}
    for r in csv.DictReader(a.sheet.open()):
        j = (r["judgement"] or "").strip()
        if not j:
            continue
        if j not in VALID:
            raise SystemExit(f"{r['review_id']}: bad judgement {j!r}; use {sorted(VALID)}")
        judged[r["term"]] = j
        notes[r["term"]] = r.get("note", "")
    print(f"judged {len(judged)} terms")

    by_method: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for r in csv.DictReader(a.key.open()):
        j = judged.get(r["term"])
        if j:
            by_method[r["method_label"]][j] += 1

    rows = []
    for m, c in sorted(by_method.items()):
        n = sum(c.values())
        rows.append({
            "method_label": m,
            "reviewed": n,
            "relevant": c["relevant"],
            "borderline": c["borderline"],
            "not_relevant": c["not_relevant"],
            # Strict precision counts only clear hits; lenient gives borderline credit.
            "precision_strict": round(c["relevant"] / n, 4) if n else 0.0,
            "precision_lenient": round((c["relevant"] + c["borderline"]) / n, 4) if n else 0.0,
        })
    with a.output.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    for r in rows:
        print(f"  {r['method_label']:<34} n={r['reviewed']:>3}  strict={r['precision_strict']:.3f}  "
              f"lenient={r['precision_lenient']:.3f}")

    if a.write_back:
        for d in a.candidate_dirs:
            f = d / "supply_chain_terms.jsonl"
            terms = [json.loads(l) for l in f.open()]
            n = 0
            for t in terms:
                j = judged.get(t["term"])
                if j:
                    t["review_status"] = j
                    if notes.get(t["term"]):
                        t["review_note"] = notes[t["term"]]
                    n += 1
            with f.open("w") as fh:
                for t in terms:
                    fh.write(json.dumps(t) + "\n")
            print(f"  wrote {n} judgements into {f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
