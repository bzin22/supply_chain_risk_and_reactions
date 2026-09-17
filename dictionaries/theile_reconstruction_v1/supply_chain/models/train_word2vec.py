"""Word2Vec arms (skip-gram and CBOW). Runs in the dap-w2v sidecar env.

gensim will not build on dap-env's Python 3.14 (the Cython noexcept failure), so
these two arms run in dap-w2v (Python 3.13, gensim 4.4.0, compiled C loop active).
Every other stage stays in dap-env.
"""
from __future__ import annotations

import argparse
import gzip
import json
import logging
import platform
import sys
import time
from pathlib import Path

import gensim
import numpy as np
from gensim.models import Word2Vec
from gensim.models.word2vec import FAST_VERSION

sys.path.insert(0, str(Path(__file__).parent))
from vector_space import save


class Corpus:
    def __init__(self, path: Path) -> None:
        self.path = path

    def __iter__(self):
        with gzip.open(self.path, "rt") as fh:
            for line in fh:
                yield line.split()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--corpus", type=Path, required=True)
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--sg", type=int, choices=[0, 1], required=True, help="1=skip-gram, 0=CBOW")
    p.add_argument("--dim", type=int, default=300)
    p.add_argument("--window", type=int, default=5)
    p.add_argument("--min-count", type=int, default=25)
    p.add_argument("--negative", type=int, default=10)
    p.add_argument("--sample", type=float, default=1e-4)
    p.add_argument("--epochs", type=int, default=5)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--seed", type=int, required=True)
    a = p.parse_args()

    # gensim reports epoch progress through logging; without this the job looks
    # dead for hours because the script itself only prints on completion.
    logging.basicConfig(format="%(asctime)s %(message)s", level=logging.INFO, stream=sys.stdout)
    logging.getLogger("gensim.models.word2vec").setLevel(logging.INFO)

    if FAST_VERSION < 0:
        raise SystemExit("gensim is running the slow pure-Python loop; refusing to train")

    t0 = time.time()
    # workers>1 makes training order nondeterministic even with a fixed seed.
    # Recorded honestly rather than claimed as bit-reproducible.
    model = Word2Vec(
        sentences=Corpus(a.corpus), vector_size=a.dim, window=a.window,
        min_count=a.min_count, sg=a.sg, negative=a.negative, sample=a.sample,
        epochs=a.epochs, workers=a.workers, seed=a.seed, sorted_vocab=1,
    )
    elapsed = time.time() - t0

    vocab = list(model.wv.index_to_key)
    vectors = np.array([model.wv[w] for w in vocab], dtype=np.float32)
    save(a.run_dir, vocab, vectors, {
        "method": "word2vec_skipgram" if a.sg else "word2vec_cbow",
        "library": f"gensim {gensim.__version__}",
        "fast_version": FAST_VERSION,
        "python": platform.python_version(),
        "env": "dap-w2v",
        "corpus": str(a.corpus),
        "dim": a.dim, "window": a.window, "min_count": a.min_count,
        "negative": a.negative, "sample": a.sample, "epochs": a.epochs,
        "workers": a.workers, "random_seed": a.seed,
        "bit_reproducible": a.workers == 1,
        "reproducibility_note": (
            "gensim with workers>1 schedules sentences nondeterministically, so "
            "vectors vary slightly between runs at identical seed. Stability is "
            "measured explicitly by the multi-seed stability check rather than assumed."),
        "corpus_tokens": int(model.corpus_total_words),
        "train_seconds": round(elapsed, 1),
    })
    print(f"{'sg' if a.sg else 'cbow'}: vocab={len(vocab):,} tokens={model.corpus_total_words:,} "
          f"{elapsed/60:.1f}m -> {a.run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
