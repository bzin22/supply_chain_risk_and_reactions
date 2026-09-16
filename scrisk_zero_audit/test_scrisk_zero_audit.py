#!/usr/bin/env python3
"""Tests for the SCRisk-zero audit.

Scope: only the audit code added here, plus assertions that pin the two
scoring-input defects the audit found.  The scoring pipeline itself is not
modified and its unrelated behaviour is not re-verified.

Run:  conda run -n dap-env python -m pytest scrisk_zero_audit -q
"""
from __future__ import annotations

import csv
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import calculate_supply_chain_transcript_scores as S  # noqa: E402
import scan as A  # noqa: E402

# Follow whichever run scan.py was configured to audit, so the consistency
# tests validate the audit that was actually just produced.
OUT = A.OUT
PER_CALL = OUT / "zero_audit_per_call.csv"

# The original audit of ppmi_svd_full_20260910 and the numbers its report
# quotes.  These stay pinned to that directory whatever run is being audited
# now, so the report cannot drift away from the data behind it.
V1_OUT = ROOT / "outputs/scrisk_zero_audit"
V1_PER_CALL = V1_OUT / "zero_audit_per_call.csv"
requires_v1 = pytest.mark.skipif(
    not V1_PER_CALL.exists(), reason="the original v1 audit output is not present"
)


def per_call_rows(path: Path) -> list[dict[str, str]]:
    assert path.exists(), f"run scrisk_zero_audit/scan.py first: {path} missing"
    return list(csv.DictReader(path.open(newline="", encoding="utf-8")))
LIBRARY = A.LIBRARY


@pytest.fixture(scope="module")
def weights() -> dict[str, float]:
    return S.load_supply_chain_library(LIBRARY)


@pytest.fixture(scope="module")
def risk_words() -> list[str]:
    return [" ".join(S.normalize_term(t)) for t in S.STARTER_RISK_WORDS]


# --------------------------------------------------------------------------
# 1. The audit's distance helper must agree with the pipeline's window rule.
# --------------------------------------------------------------------------

def test_min_span_distance_matches_brute_force():
    rng = random.Random(7)
    for _ in range(200):
        left = [S.Occurrence("a", s, s + rng.randint(0, 3))
                for s in sorted(rng.sample(range(300), 15))]
        right = [S.Occurrence("b", s, s + rng.randint(0, 3))
                 for s in sorted(rng.sample(range(300), 11))]
        brute = min(
            0 if not (a.end < b.start or b.end < a.start)
            else (b.start - a.end if a.end < b.start else a.start - b.end)
            for a in left for b in right
        )
        assert A.min_span_distance(left, right) == brute


def test_min_span_distance_agrees_with_pipeline_spans_within():
    """distance <= WINDOW must mean exactly what spans_within means."""
    rng = random.Random(11)
    for _ in range(200):
        left = [S.Occurrence("a", s, s + rng.randint(0, 2))
                for s in sorted(rng.sample(range(80), 6))]
        right = [S.Occurrence("b", s, s + rng.randint(0, 2))
                 for s in sorted(rng.sample(range(80), 6))]
        any_pair = any(S.spans_within(a, b, S.WINDOW) for a in left for b in right)
        assert (A.min_span_distance(left, right) <= S.WINDOW) is any_pair


def test_min_span_distance_is_none_when_a_vocabulary_is_absent():
    one = [S.Occurrence("a", 3, 3)]
    assert A.min_span_distance(one, []) is None
    assert A.min_span_distance([], one) is None


# --------------------------------------------------------------------------
# 2. The audit must reproduce what the scorer actually wrote.
# --------------------------------------------------------------------------

def test_audit_reproduces_pipeline_counts_for_every_zero_call():
    """Recomputed counts must equal the scored CSV's counts on every zero row."""
    rows = per_call_rows(PER_CALL)
    assert rows, "the audited run has no zero-score calls at all"
    for row in rows:
        key = f"{row['ticker']} {row['quarter_label']}"
        assert row["recomputed_word_count"] == row["score_word_count"], key
        assert (row["supply_chain_occurrences_recomputed"]
                == row["supply_chain_occurrences_csv"]), key
        assert row["risk_occurrences_recomputed"] == row["risk_occurrences_csv"], key
        # The scorer recorded a zero score, so it must have found no pair.
        assert int(row["supply_chain_risk_pairs_csv"]) == 0, key
        assert float(row["SCRisk_weight_sum_csv"]) == 0.0, key


@requires_v1
def test_original_audit_population_is_the_reported_9750_calls():
    """The first audit's headline population, pinned to the run it describes."""
    assert len(per_call_rows(V1_PER_CALL)) == 9750


def test_every_zero_call_lands_in_an_explained_bucket():
    rows = per_call_rows(PER_CALL)
    buckets = {r["bucket"] for r in rows}
    assert "UNEXPECTED_pair_within_window" not in buckets, (
        "a zero-score call had a pair inside the window; the audit and the "
        "scorer disagree")
    assert buckets <= {
        "empty_transcript", "no_supply_chain_vocab", "supply_chain_but_no_risk_vocab",
        "no_supply_chain_and_no_risk_vocab", "both_present_never_within_window",
    }


# --------------------------------------------------------------------------
# 3. Casing and whitespace are ruled out as false-zero mechanisms.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "SUPPLY CHAIN DISRUPTION hit our COMPONENT inventory",
    "Supply  Chain\tDisruption hit our\ncomponent inventory",
])
def test_tokenizer_is_case_and_whitespace_invariant(text):
    baseline = S.tokenize("supply chain disruption hit our component inventory")
    assert S.tokenize(text) == baseline


def test_curly_apostrophe_does_not_split_a_token():
    assert S.tokenize("supplier’s risk") == ["supplier’s", "risk"]


# --------------------------------------------------------------------------
# 4. Pin the two scoring-input defects the audit found.
# --------------------------------------------------------------------------

def test_scoring_library_omits_all_sixteen_seed_phrases(weights):
    """Defect: SUPPLY_CHAIN_SEEDS is defined but never added to the library.

    Evidence: terms.jsonl for run ppmi_svd_full_20260910 holds 118 expansion
    terms and none of the 16 seeds.  This test documents the defect; change it
    only when the library is rebuilt to include the seeds.
    """
    seeds = [" ".join(S.normalize_term(s)) for s in S.SUPPLY_CHAIN_SEEDS]
    assert len(weights) == 118
    assert [s for s in seeds if s in weights] == []


def test_supply_chain_disruption_phrase_scores_zero_without_the_seeds(weights, risk_words):
    """Cirrus Logic 2022Q2 case: the phrase itself earns nothing.

    'supply chain disruption' contains a supply-chain seed adjacent to a risk
    term, yet scores 0 because 'supply', 'supply chain' and 'chain' are all
    outside the 118-term library.
    """
    sentence = ("the supply chain disruption created opportunistic situations "
                "where that could occur")
    current = S.calculate_raw_scores(sentence, weights, risk_words, [])
    assert current.risk_occurrences >= 1          # 'disruption' is a risk term
    assert current.supply_chain_occurrences == 0  # nothing supply-chain matches
    assert current.scrisk_raw == 0.0

    seeded = dict(weights)
    for seed in S.SUPPLY_CHAIN_SEEDS:
        seeded[" ".join(S.normalize_term(seed))] = 0.9
    restored = S.calculate_raw_scores(sentence, seeded, risk_words, [])
    assert restored.risk_pairs > 0
    assert restored.scrisk_raw > 0.0


def test_library_and_risk_dictionary_share_the_term_shortages(weights, risk_words):
    """Defect: 'shortages' is in both dictionaries, so it pairs with itself.

    Distance from a span to itself is 0, which is inside the window, so any
    call containing 'shortages' scores non-zero on that word alone.  The
    singular 'shortage' is a risk term only, so it cannot.  345 of the 9,750
    zero calls flip on this inflection difference.
    """
    assert "shortages" in weights
    assert "shortages" in risk_words
    assert "shortage" not in weights

    plural = S.calculate_raw_scores(
        "we navigated labor shortages during the period", weights, risk_words, [])
    singular = S.calculate_raw_scores(
        "we navigated a labor shortage during the period", weights, risk_words, [])
    assert plural.scrisk_raw > 0.0
    assert singular.scrisk_raw == 0.0


# --------------------------------------------------------------------------
# 5. Probe direction: a probe may only ever turn a zero non-zero.
# --------------------------------------------------------------------------

def test_wider_window_probes_are_monotone():
    rows = list(csv.DictReader(PER_CALL.open(newline="", encoding="utf-8")))
    for row in rows:
        if row["probe_window_25_becomes_nonzero"] == "1":
            assert row["probe_window_50_becomes_nonzero"] == "1", (
                f"{row['ticker']} {row['quarter_label']}")


def test_hyphen_splitting_can_push_a_pair_back_out_of_the_window():
    """The combined probe is not a superset of the seeds probe, and that is real.

    Splitting hyphenated tokens lengthens the token stream, so a pair sitting
    at exactly the window edge moves outside it.  Every call the combined
    probe loses must have been at distance exactly 10 and must be a call whose
    tokens hyphen splitting changed.
    """
    rows = per_call_rows(PER_CALL)
    lost = [r for r in rows
            if r["probe_seeds_becomes_nonzero"] == "1"
            and r["probe_combined_becomes_nonzero"] == "0"]
    for row in lost:
        assert int(float(row["probe_seeds_min_distance"])) == S.WINDOW
        assert row["probe_hyphen_split_changed_tokens"] == "1"
        assert int(float(row["probe_combined_min_distance"])) > S.WINDOW


@requires_v1
def test_original_audit_lost_twenty_six_pairs_to_hyphen_splitting():
    """Measured on the original run: 26 of the 1,815 seed-probe flips are lost.

    ARKR 2024Q3 goes from 3,594 to 3,748 tokens and its nearest pair from 10
    to 13.  A run whose vocabulary already holds the seeds flips nothing on
    the seeds probe and so loses nothing here, which is why the count is
    pinned to the run it was measured on.
    """
    rows = per_call_rows(V1_PER_CALL)
    lost = [r for r in rows
            if r["probe_seeds_becomes_nonzero"] == "1"
            and r["probe_combined_becomes_nonzero"] == "0"]
    assert len(lost) == 26


def test_every_transcript_contains_intra_word_punctuation():
    """Why the hyphen probe cannot be isolated on real transcripts.

    Every zero transcript contains at least one token with an internal
    hyphen, apostrophe or period ("forward-looking", "we'll", "ti.com"), so
    there is no call on which the hyphen probe is a no-op.
    """
    rows = per_call_rows(PER_CALL)
    unchanged = [r for r in rows if r["probe_hyphen_split_changed_tokens"] == "0"]
    assert unchanged == []


def test_adding_vocabulary_can_only_add_pairs_when_tokenization_is_fixed(weights, risk_words):
    """Monotonicity holds for vocabulary alone; it is tokenization that breaks it."""
    text = "our supply chain saw a disruption and the factory paused production"
    base = S.calculate_raw_scores(text, weights, risk_words, [])
    seeded = dict(weights)
    for seed in S.SUPPLY_CHAIN_SEEDS:
        seeded[" ".join(S.normalize_term(seed))] = 0.9
    grown = S.calculate_raw_scores(text, seeded, risk_words, [])
    assert grown.risk_pairs >= base.risk_pairs
    assert grown.scrisk_weight_sum >= base.scrisk_weight_sum
    assert grown.word_count == base.word_count


def test_splitting_a_hyphen_can_break_a_pair_at_the_window_edge(weights, risk_words):
    """The ARKR 2024Q3 mechanism, reduced to one sentence.

    A pair sitting exactly WINDOW tokens apart is lost when a hyphenated token
    between the two terms becomes two tokens.
    """
    # 'component' and 'risk' exactly WINDOW apart, one hyphenated token between.
    text = "component was quite steady across our well-known and very large risk"
    tokens = S.tokenize(text)
    split = [m.group(0).lower() for m in A.WORD_ONLY_RE.finditer(text)]
    assert len(split) == len(tokens) + 1, "the sentence must gain exactly one token"
    sc_index = S.build_phrase_index(weights)
    risk_index = S.build_phrase_index(risk_words)
    before = A.min_span_distance(S.find_indexed_occurrences(tokens, sc_index),
                                 S.find_indexed_occurrences(tokens, risk_index))
    after = A.min_span_distance(S.find_indexed_occurrences(split, sc_index),
                                S.find_indexed_occurrences(split, risk_index))
    assert before == S.WINDOW and after == S.WINDOW + 1


def test_window_probes_agree_with_the_recorded_distance():
    rows = per_call_rows(PER_CALL)
    checked = 0
    for row in rows:
        raw = row["min_supply_chain_risk_token_distance"]
        if not raw:
            continue
        distance = int(raw)
        assert distance > S.WINDOW, "a zero call cannot have a pair in the window"
        assert (row["probe_window_25_becomes_nonzero"] == "1") == (distance <= 25)
        assert (row["probe_window_50_becomes_nonzero"] == "1") == (distance <= 50)
        checked += 1
    # A recorded distance exists exactly when both vocabularies were present,
    # which is the same population as the window-miss bucket.
    assert checked == sum(1 for r in rows if r["bucket"] == "both_present_never_within_window")


# --------------------------------------------------------------------------
# 6. The inflection probe must not truncate stems the way the stemmer does.
# --------------------------------------------------------------------------

def test_inflection_probe_never_produces_a_truncated_stem():
    """`inflect` must not yield 'stock' from 'stocking' or 'track' from 'tracking'."""
    from probe_inflection import inflect
    assert "stock" not in inflect("stocking")
    assert "track" not in inflect("tracking")
    assert "materials" in inflect("material") and "material" in inflect("materials")
    assert inflect("inventories") == {"inventories", "inventory"}


def test_crude_stemmer_is_known_to_over_truncate():
    """Documents why the stemming probe's 32% is an upper bound, not a finding."""
    assert A.stem("stocking") == "stock"
    assert A.stem("tracking") == "track"
    assert A.stem("finished") == "finish"
