"""Common on-disk format for every method, so candidate extraction is identical.

A run directory holds:
  vocab.json        list of terms, index-aligned to the vector matrix
  vectors.npy       float32 [vocab, dim], L2-normalised at save time
  model_config.json hyperparameters, seeds, fingerprints
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np


def save(run_dir: Path, vocab: list[str], vectors: np.ndarray, config: dict) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    v = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(v, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    v = v / norms
    np.save(run_dir / "vectors.npy", v)
    (run_dir / "vocab.json").write_text(json.dumps(vocab))
    config = dict(config)
    config["vector_sha256"] = hashlib.sha256(v.tobytes()).hexdigest()
    config["vocab_sha256"] = hashlib.sha256("\n".join(vocab).encode()).hexdigest()
    config["vocab_size"] = len(vocab)
    config["dimensions"] = int(v.shape[1])
    (run_dir / "model_config.json").write_text(json.dumps(config, indent=2))


def load(run_dir: Path):
    vocab = json.loads((run_dir / "vocab.json").read_text())
    vectors = np.load(run_dir / "vectors.npy")
    config = json.loads((run_dir / "model_config.json").read_text())
    return vocab, vectors, config
