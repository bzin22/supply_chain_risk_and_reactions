"""PPMI + truncated SVD arm. Runs in dap-env.

Symmetric sliding window, positive pointwise mutual information with context
distribution smoothing, then randomized truncated SVD. This is the classic
count-based counterpart to word2vec and the closest public analogue to a
"cluster terms by relative co-occurrence" description like metaHeuristica's.
"""
from __future__ import annotations

import argparse
import collections
import gzip
import json
import platform
import sys
import time
from pathlib import Path

import numpy as np
import scipy.sparse as sp
import sklearn
from sklearn.utils.extmath import randomized_svd

sys.path.insert(0, str(Path(__file__).parent))
from vector_space import save


def count_vocab(corpus: Path, min_count: int, min_df: int):
    tf: collections.Counter = collections.Counter()
    df: collections.Counter = collections.Counter()
    docs = tokens = 0
    with gzip.open(corpus, "rt") as fh:
        for line in fh:
            t = line.split()
            docs += 1
            tokens += len(t)
            tf.update(t)
            df.update(set(t))
            if docs % 5000 == 0:
                print(f"  vocab pass {docs:,} docs {tokens/1e6:.0f}M tokens", flush=True)
    keep = {w for w, c in tf.items() if c >= min_count and df[w] >= min_df}
    return tf, df, keep, docs, tokens


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--corpus", type=Path, required=True)
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--window", type=int, default=5)
    p.add_argument("--min-count", type=int, default=25)
    p.add_argument("--min-df", type=int, default=10)
    p.add_argument("--dim", type=int, default=300)
    p.add_argument("--cds", type=float, default=0.75, help="context distribution smoothing")
    p.add_argument("--shift", type=float, default=1.0, help="k in log(p/(pxpy)) - log k; 1.0 = plain PPMI")
    p.add_argument("--eig-weight", type=float, default=0.5, help="U * S**eig_weight")
    # Separate target and context vocabularies. A square 100k x 100k matrix would
    # reach billions of nonzeros on a 1.4B-token corpus; restricting contexts to the
    # frequent head bounds memory while still covering every Table 2 term as a target
    # (the rarest, 'eprocurement', is corpus rank 94,672).
    p.add_argument("--max-vocab", type=int, default=100_000, help="target vocabulary")
    p.add_argument("--context-vocab", type=int, default=20_000)
    p.add_argument("--seed", type=int, required=True)
    a = p.parse_args()

    t0 = time.time()
    tf, df, keep, docs, tokens = count_vocab(a.corpus, a.min_count, a.min_df)
    ordered = sorted(keep, key=lambda w: (-tf[w], w))
    vocab = ordered[: a.max_vocab]
    ctx_vocab = ordered[: a.context_vocab]
    idx = {w: i for i, w in enumerate(vocab)}
    cidx = {w: i for i, w in enumerate(ctx_vocab)}
    V, Cn = len(vocab), len(ctx_vocab)
    print(f"target_vocab={V:,} context_vocab={Cn:,} docs={docs:,} tokens={tokens:,}", flush=True)

    # Accumulate the symmetric co-occurrence matrix in COO batches.
    M = sp.csr_matrix((V, Cn), dtype=np.float32)
    br, bc, bv = [], [], []
    pairs = 0
    buffered = 0

    def flush():
        nonlocal M, br, bc, bv, buffered
        if not br:
            return
        M = (M + sp.coo_matrix(
            (np.concatenate(bv), (np.concatenate(br), np.concatenate(bc))),
            shape=(V, Cn), dtype=np.float32).tocsr())
        br, bc, bv = [], [], []
        buffered = 0

    with gzip.open(a.corpus, "rt") as fh:
        for n, line in enumerate(fh, 1):
            toks = line.split()
            # Token stream keeps positions aligned: -1 marks a token outside the
            # target vocabulary so it still occupies a slot in the window.
            t_ids = np.fromiter((idx.get(w, -1) for w in toks), dtype=np.int32, count=len(toks))
            c_ids = np.fromiter((cidx.get(w, -1) for w in toks), dtype=np.int32, count=len(toks))
            if t_ids.size < 2:
                continue
            for d in range(1, a.window + 1):
                if t_ids.size <= d:
                    break
                # Harmonic weighting: nearer context words count for more, matching
                # word2vec's expected window-size sampling.
                wgt = np.float32(1.0 / d)
                for tgt, ctx in ((t_ids[:-d], c_ids[d:]), (t_ids[d:], c_ids[:-d])):
                    m = (tgt >= 0) & (ctx >= 0)
                    if not m.any():
                        continue
                    tt, cc = tgt[m], ctx[m]
                    br.append(tt); bc.append(cc)
                    bv.append(np.full(tt.size, wgt, dtype=np.float32))
                    pairs += tt.size
                    buffered += tt.size
            if buffered > 40_000_000:
                flush()
                print(f"  cooc {n:,} docs nnz={M.nnz:,}", flush=True)
    flush()
    print(f"cooccurrence nnz={M.nnz:,} weighted_pairs={pairs:,}", flush=True)

    # PPMI with context distribution smoothing.
    M = M.tocsr()
    total = M.sum()
    row_sum = np.asarray(M.sum(axis=1)).ravel()
    col_sum = np.asarray(M.sum(axis=0)).ravel() ** a.cds
    col_total = col_sum.sum()

    M = M.tocoo()
    with np.errstate(divide="ignore", invalid="ignore"):
        pmi = (np.log(M.data) + np.log(total) + np.log(col_total)
               - np.log(row_sum[M.row]) - np.log(total)
               - np.log(col_sum[M.col]) - np.log(a.shift))
    pmi[~np.isfinite(pmi)] = 0.0
    pmi[pmi < 0] = 0.0
    P = sp.coo_matrix((pmi, (M.row, M.col)), shape=(V, Cn)).tocsr()
    P.eliminate_zeros()
    print(f"ppmi nnz={P.nnz:,}", flush=True)

    U, S, _ = randomized_svd(P, n_components=a.dim, random_state=a.seed)
    vectors = U * (S ** a.eig_weight)
    elapsed = time.time() - t0

    save(a.run_dir, vocab, vectors, {
        "method": "ppmi_svd",
        "library": f"scikit-learn {sklearn.__version__}, scipy/numpy",
        "python": platform.python_version(),
        "env": "dap-env",
        "corpus": str(a.corpus),
        "window": a.window, "weighting": "harmonic 1/d", "min_count": a.min_count,
        "min_df": a.min_df, "dim": a.dim, "cds": a.cds, "shift_k": a.shift,
        "eig_weight": a.eig_weight, "max_vocab": a.max_vocab,
        "context_vocab": a.context_vocab, "random_seed": a.seed,
        "bit_reproducible": True,
        "corpus_tokens": int(tokens), "documents": int(docs),
        "cooccurrence_nnz": int(M.nnz), "ppmi_nnz": int(P.nnz),
        "singular_value_sum": float(S.sum()),
        "train_seconds": round(elapsed, 1),
    })
    print(f"ppmi_svd: target={V:,} context={Cn:,} {elapsed/60:.1f}m -> {a.run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
