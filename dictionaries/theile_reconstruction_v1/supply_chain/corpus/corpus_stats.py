"""Term frequency and document frequency over a training corpus. Shared by every
arm so frequency support is comparable across methods."""
from __future__ import annotations

import argparse
import collections
import gzip
import json
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--corpus", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--min-count", type=int, default=5)
    a = p.parse_args()

    tf: collections.Counter = collections.Counter()
    df: collections.Counter = collections.Counter()
    docs = tokens = 0
    with gzip.open(a.corpus, "rt") as fh:
        for line in fh:
            t = line.split()
            docs += 1
            tokens += len(t)
            tf.update(t)
            df.update(set(t))
            if docs % 10000 == 0:
                print(f"  {docs:,} docs {tokens/1e6:.0f}M tokens {len(tf):,} types", flush=True)

    tf = {w: c for w, c in tf.items() if c >= a.min_count}
    df = {w: df[w] for w in tf}
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(a.output, "wt") as fh:
        json.dump({"documents": docs, "tokens": tokens, "min_count": a.min_count,
                   "term_frequency": tf, "document_frequency": df}, fh)
    print(f"docs={docs:,} tokens={tokens:,} types_kept={len(tf):,} -> {a.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
