"""Write a document-level random subsample of a training corpus, for the
corpus-stability leg of the method comparison."""
from __future__ import annotations

import argparse
import gzip
import json
import random
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--corpus", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--fraction", type=float, required=True)
    p.add_argument("--seed", type=int, required=True)
    a = p.parse_args()

    rng = random.Random(a.seed)
    kept = total = tokens = 0
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(a.corpus, "rt") as fin, gzip.open(a.output, "wt", compresslevel=4) as fout:
        for line in fin:
            total += 1
            if rng.random() < a.fraction:
                fout.write(line)
                kept += 1
                tokens += line.count(" ") + 1
    meta = {"source": str(a.corpus), "fraction": a.fraction, "seed": a.seed,
            "documents_in": total, "documents_kept": kept, "tokens_kept": tokens}
    a.output.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
