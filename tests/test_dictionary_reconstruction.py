"""Tests for the supply chain library reconstruction.

Scoped to the code this reconstruction added: the shared text pipeline, the
candidate-consolidation funnel run through its real entry point, and invariants
on the shipped baseline artifact. Nothing here touches transcripts or returns.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parents[1] / "dictionaries/theile_reconstruction_v1/supply_chain"
sys.path.insert(0, str(HERE / "corpus"))
sys.path.insert(0, str(HERE / "models"))

filing_text = pytest.importorskip("filing_text")
from seeds import SINGLE_WORD_SEEDS, TABLE_2  # noqa: E402
from vector_space import save  # noqa: E402


# ---------------------------------------------------------------- text pipeline

@pytest.mark.parametrize("raw,expected", [
    # Table 2 prints these with hyphens and spaces removed, so the tokenizer must
    # JOIN hyphenated forms rather than split them. Getting this backwards silently
    # loses 5 of the paper's 30 published keywords.
    ("work-in-process", "workinprocess"),
    ("slow-moving", "slowmoving"),
    ("e-procurement", "eprocurement"),
    ("end-customers", "endcustomers"),
    ("supply-chain", "supplychain"),
])
def test_hyphenated_forms_join_to_table_2_orthography(raw, expected):
    assert filing_text.tokenize(raw) == [expected]


def test_numbers_and_punctuation_dropped_stopwords_kept():
    toks = filing_text.tokenize("The 2021 inventory, and 15% of it, was obsolete.")
    assert toks == ["the", "inventory", "and", "of", "it", "was", "obsolete"]
    # Stopwords must survive: both word2vec and PPMI are defined over co-occurrence
    # windows, and deleting stopwords silently moves every context word closer.
    assert "the" in toks and "and" in toks


def test_primary_document_is_the_10k_not_an_exhibit():
    payload = (b"<SEC-HEADER>CONFORMED PERIOD OF REPORT:\t20201231\n</SEC-HEADER>"
               b"<DOCUMENT><TYPE>EX-21.1<TEXT>subsidiary list</TEXT></DOCUMENT>"
               b"<DOCUMENT><TYPE>10-K<TEXT>annual report body</TEXT></DOCUMENT>")
    doc, doc_type = filing_text.find_primary_document(payload)
    assert doc_type == "10-K"
    assert b"annual report body" in doc
    assert b"subsidiary list" not in doc
    assert filing_text.conformed_period(payload) == "20201231"


def test_10k405_counts_as_a_primary_document():
    # 10-K405 is ~32% of annual reports before 2003. Excluding it puts a
    # composition break at the 2002/2003 boundary.
    payload = b"<DOCUMENT><TYPE>10-K405<TEXT>body</TEXT></DOCUMENT>"
    doc, doc_type = filing_text.find_primary_document(payload)
    assert doc_type == "10-K405"


def test_no_primary_document_returns_none():
    payload = b"<DOCUMENT><TYPE>10-Q<TEXT>quarterly</TEXT></DOCUMENT>"
    assert filing_text.find_primary_document(payload) == (None, None)


def test_inline_xbrl_header_is_stripped():
    html = (b"<html><ix:header><ix:hidden>zzz noise tokens</ix:hidden></ix:header>"
            b"<body><p>inventory levels rose</p></body></html>")
    text = filing_text.document_to_text(html)
    assert "inventory levels rose" in text
    assert "zzz" not in text


# ------------------------------------------------------- consolidation funnel

def _toy_space(tmp_path: Path) -> tuple[Path, Path]:
    """A tiny vector space where the expected neighbours are known by construction."""
    vocab = (SINGLE_WORD_SEEDS
             + ["supply_chain", "channel_partners", "demand_management"]
             + ["inventories", "vendors", "inventory_levels", "key_suppliers", "noise"])
    rng = np.random.default_rng(0)
    V = rng.normal(size=(len(vocab), 16))
    idx = {w: i for i, w in enumerate(vocab)}
    # Pin neighbours: 'inventories' and 'inventory_levels' hug 'inventory'.
    V[idx["inventories"]] = V[idx["inventory"]] + 0.01 * rng.normal(size=16)
    V[idx["inventory_levels"]] = V[idx["inventory"]] + 0.02 * rng.normal(size=16)
    V[idx["vendors"]] = V[idx["suppliers"]] + 0.01 * rng.normal(size=16)
    V[idx["key_suppliers"]] = V[idx["suppliers"]] + 0.02 * rng.normal(size=16)

    run = tmp_path / "run"
    save(run, vocab, V, {"method": "toy", "corpus": "toy.txt.gz", "min_count": 1})
    stats = tmp_path / "stats.json.gz"
    import gzip
    with gzip.open(stats, "wt") as fh:
        json.dump({"documents": 10, "tokens": 100,
                   "term_frequency": {w: 50 for w in vocab},
                   "document_frequency": {w: 5 for w in vocab}}, fh)
    return run, stats


def _run_extract(run: Path, stats: Path, out: Path, mode: str) -> dict:
    subprocess.run([sys.executable, str(HERE / "models" / "extract_candidates.py"),
                    "--run-dir", str(run), "--stats", str(stats),
                    "--output-dir", str(out), "--multiword-seed-mode", mode],
                   check=True, capture_output=True)
    return json.loads((out / "extraction_summary.json").read_text())


def test_funnel_removes_multiword_and_pins_seeds_to_one(tmp_path):
    run, stats = _toy_space(tmp_path)
    out = tmp_path / "cand"
    summary = _run_extract(run, stats, out, "phrase")
    terms = [json.loads(l) for l in (out / "supply_chain_terms.jsonl").open()]
    by_term = {t["term"]: t for t in terms}

    # No multiword survives, including the multiword seeds themselves. Only 13 of
    # the paper's 16 seeds appear at cosine 1.00 in Table 2, which is how we know
    # multiword removal was applied to seeds too.
    assert not [t for t in by_term if "_" in t]
    assert summary["multiword_candidates_removed"] > 0
    for seed in SINGLE_WORD_SEEDS:
        assert by_term[seed]["max_cosine"] == 1.0
        assert by_term[seed]["seed_rank"] == 0
    assert set(summary["single_word_seeds_added"]) == set(SINGLE_WORD_SEEDS)


def test_consolidation_keeps_the_maximum_cosine_across_seeds(tmp_path):
    run, stats = _toy_space(tmp_path)
    out = tmp_path / "cand"
    _run_extract(run, stats, out, "phrase")
    for t in (json.loads(l) for l in (out / "supply_chain_terms.jsonl").open()):
        if t["seed_rank"] == 0:
            continue
        best = max(m["cosine"] for m in t["all_seed_matches"])
        assert t["max_cosine"] == pytest.approx(best)
        winner = [m for m in t["all_seed_matches"] if m["cosine"] == best][0]
        assert t["nearest_seed"] == winner["seed"]


def test_expected_neighbours_are_recovered(tmp_path):
    run, stats = _toy_space(tmp_path)
    out = tmp_path / "cand"
    _run_extract(run, stats, out, "phrase")
    found = {json.loads(l)["term"] for l in (out / "supply_chain_terms.jsonl").open()}
    # Constructed to sit next to their seeds, so a broken ranking step shows here.
    assert "inventories" in found
    assert "vendors" in found


def test_every_seed_gets_a_candidate_list(tmp_path):
    run, stats = _toy_space(tmp_path)
    out = tmp_path / "cand"
    _run_extract(run, stats, out, "phrase_fallback")
    per_seed = json.loads((out / "per_seed_top100.json").read_text())
    assert len(per_seed) == 16
    # phrase_fallback exists precisely so a multiword seed whose joined token is
    # missing still contributes via its component average.
    assert all(rows for rows in per_seed.values())


# -------------------------------------------------- shipped baseline artifact

BASELINE = HERE / "supply_chain_terms.jsonl"
requires_baseline = pytest.mark.skipif(
    not BASELINE.exists(), reason="baseline library not built in this checkout")


@requires_baseline
def test_baseline_records_carry_every_required_field():
    required = {"term", "max_cosine", "nearest_seed", "seed_rank", "all_seed_matches",
                "frequency", "document_frequency", "method", "in_paper_table_2",
                "review_status"}
    for line in BASELINE.open():
        assert required <= set(json.loads(line))


@requires_baseline
def test_baseline_is_single_word_lowercase_and_deduplicated():
    terms = [json.loads(l)["term"] for l in BASELINE.open()]
    assert len(terms) == len(set(terms))
    assert all(t == t.lower() and " " not in t and "_" not in t for t in terms)


@requires_baseline
def test_baseline_seeds_carry_cosine_one_and_cosines_are_bounded():
    terms = {json.loads(l)["term"]: json.loads(l) for l in BASELINE.open()}
    present = [s for s in SINGLE_WORD_SEEDS if s in terms]
    assert len(present) == 13, "all 13 single-word seeds should be in the library"
    assert all(terms[s]["max_cosine"] == 1.0 for s in present)
    assert all(0.0 <= t["max_cosine"] <= 1.0 for t in terms.values())


@requires_baseline
def test_baseline_txt_and_jsonl_agree():
    jsonl = [json.loads(l)["term"] for l in BASELINE.open()]
    txt = (HERE / "supply_chain_terms.txt").read_text().split()
    assert jsonl == txt


@requires_baseline
def test_table_2_flag_matches_the_published_table():
    for line in BASELINE.open():
        t = json.loads(line)
        assert t["in_paper_table_2"] == (t["term"] in TABLE_2)


@requires_baseline
def test_baseline_recovers_most_of_table_2():
    found = {json.loads(l)["term"] for l in BASELINE.open()}
    recovered = len(found & set(TABLE_2))
    # The committed PPMI baseline recovers 27 of 30. Guard against a regression
    # without pinning the exact number, which legitimately moves with the corpus.
    assert recovered >= 25, f"Table 2 recovery fell to {recovered}/30"
