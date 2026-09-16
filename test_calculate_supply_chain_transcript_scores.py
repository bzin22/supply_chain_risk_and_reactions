#!/usr/bin/env python3
"""Tests for calculate_supply_chain_transcript_scores.py.

Covers vocabulary assembly, weight resolution, the two pairing properties the
zero-score audit flagged, the transcript-integrity classifier, and the CLI.
The window, the tokenizer, the pairing rule and the resolution dictionary are
unchanged, so they are covered here only by the assertions that prove they did
not move.

Expected values come from the module's own dictionaries and from the term
library itself, never from intuition and never from a generated result. Two
tests need local artifacts that are not committed (the term library and a
500-row scored sample); both skip when the artifact is absent.

Provisional: the risk and resolution dictionaries under test are this
repository's starter lists, not the paper's. These tests pin the code's
current behaviour; they do not establish paper equivalence.
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import calculate_supply_chain_transcript_scores as S  # noqa: E402

LIBRARY = ROOT / "artifacts/sec_10k_supply_chain/experiments/ppmi_svd_full_20260910/terms.jsonl"
SMOKE_500 = (
    ROOT
    / "artifacts/earnings_call_supply_chain/ppmi_svd_full_20260910"
    / "earnings_call_transcripts_scored_smoke_500.csv"
)
requires_library = pytest.mark.skipif(
    not LIBRARY.exists(), reason=f"term library is not present: {LIBRARY}"
)
requires_smoke_500 = pytest.mark.skipif(
    not SMOKE_500.exists(), reason=f"local scored sample is not present: {SMOKE_500}"
)

# The 14 score columns the original pipeline wrote, in the original format.
V1_SCORE_COLUMNS = (
    "SCRisk_weight_sum", "SCRisk_raw", "SCRisk_sd", "SCRisk",
    "Resolution_weight_sum", "Resolution_raw", "Resolution_sd", "Resolution",
    "score_word_count", "supply_chain_occurrences", "risk_occurrences",
    "resolution_occurrences", "supply_chain_risk_pairs", "supply_chain_resolution_pairs",
)


@pytest.fixture(scope="module")
def library() -> dict[str, float]:
    if not LIBRARY.exists():
        pytest.skip(f"term library is not present: {LIBRARY}")
    return S.load_supply_chain_library(LIBRARY)


@pytest.fixture(scope="module")
def v1(library) -> dict[str, float]:
    return S.build_supply_chain_vocabulary(library, "v1_library_only")


@pytest.fixture(scope="module")
def v2(library) -> dict[str, float]:
    return S.build_supply_chain_vocabulary(library, "v2_seeds_inflections")


def distinct_filler(count: int) -> str:
    """Return ``count`` distinct alphabetic tokens.

    ``WORD_RE`` drops every numeric character, so "word1 word2" tokenizes to
    "word word" and trips the degenerate-repetition check.  Filler has to be
    alphabetic to stand in for a real transcript.
    """

    letters = "abcdefghijklmnopqrstuvwxyz"
    if count > len(letters) ** 3:
        raise ValueError("distinct_filler supports at most 17,576 tokens")
    return " ".join(
        f"z{letters[index // 676]}{letters[index // 26 % 26]}{letters[index % 26]}"
        for index in range(count)
    )


def score(text: str, vocabulary: dict[str, float], risk_version: str, **kwargs) -> S.ScoreResult:
    return S.calculate_raw_scores(
        text,
        vocabulary,
        S.build_risk_vocabulary(S.STARTER_RISK_WORDS, risk_version),
        S.STARTER_RESOLUTION_WORDS,
        **kwargs,
    )


# --- inflection rules -------------------------------------------------------

@pytest.mark.parametrize(
    "word,expected",
    [
        # Regular plural both directions.
        ("inventories", {"inventories", "inventory"}),
        ("supplier", {"supplier", "suppliers"}),
        ("logistics", {"logistics", "logistic"}),
        ("warehouse", {"warehouse", "warehouses"}),
        # The audit's four stemmer casualties.  A stemmer turns these into
        # stock, track, finish and shipp, which drags "stock" and "on track"
        # into the vocabulary.  The inflector must leave them alone.
        ("stocking", {"stocking", "stockings"}),
        ("tracking", {"tracking", "trackings"}),
        ("finished", {"finished", "finisheds"}),
        ("shipping", {"shipping", "shippings"}),
    ],
)
def test_regular_inflections_never_truncate_a_stem(word, expected):
    assert S.regular_inflections(word) == expected


def test_phrase_inflection_moves_only_the_head_word():
    assert S.phrase_inflections("supply chain") == {"supply chain", "supply chains"}
    assert S.phrase_inflections("channel partners") == {"channel partners", "channel partner"}


# --- vocabulary assembly ----------------------------------------------------

def test_v1_is_the_library_alone_and_omits_every_seed(library, v1):
    assert v1 == library
    seeds = {" ".join(S.normalize_term(seed)) for seed in S.SUPPLY_CHAIN_SEEDS}
    # This is the audit's headline defect: none of the 16 seeds were scored.
    assert seeds & set(v1) == set()


def test_v2_scores_all_sixteen_seeds_at_weight_one(v2):
    seeds = [" ".join(S.normalize_term(seed)) for seed in S.SUPPLY_CHAIN_SEEDS]
    assert len(seeds) == 16
    assert all(v2[seed] == pytest.approx(1.0) for seed in seeds)


def test_v2_keeps_every_v1_term_and_only_grows(v1, v2):
    # The audit's defensible probe is "complete the vocabulary's inflections
    # and restore the 16 seeds", so v2 is a strict superset of v1.  The sizes
    # themselves depend on whichever term library is loaded, so only the
    # relation is asserted.
    assert set(v1) <= set(v2)
    assert len(v2) > len(v1)


def test_risk_vocabulary_sizes_are_fixed_by_the_starter_dictionary():
    # Derived from STARTER_RISK_WORDS in the module under test, not from a run.
    assert len(S.build_risk_vocabulary(S.STARTER_RISK_WORDS, "v1_library_only")) == 94
    assert len(S.build_risk_vocabulary(S.STARTER_RISK_WORDS, "v2_seeds_inflections")) == 147


def test_v2_resolves_a_shared_form_to_the_larger_weight(library, v2):
    # "customer" is a 0.9155 library term and an inflection of the seed
    # "customers", so it takes the seed weight.  "clients" is reachable only
    # from the library, so it keeps its own.
    assert library["customer"] == pytest.approx(0.91550493)
    assert v2["customer"] == pytest.approx(1.0)
    assert v2["clients"] == pytest.approx(library["clients"])


def test_unknown_vocabulary_version_is_rejected(library):
    with pytest.raises(ValueError, match="Unknown vocabulary version"):
        S.build_supply_chain_vocabulary(library, "v3")


# --- behaviour on the audit's named false zeros ------------------------------

def test_cirrus_logic_sentence_flips_from_zero_to_positive(v1, v2):
    # CRUS 2022Q2, quoted verbatim in the audit.  "supply" sits inside
    # "supply chain disruption" at distance 0 and scored nothing.
    text = (
        "the once the supply chain disruption created opportunistic situations "
        "where that could occur"
    )
    assert score(text, v1, "v1_library_only").scrisk_raw == 0.0
    assert score(text, v2, "v2_seeds_inflections").scrisk_raw > 0.0


def test_schlumberger_sentence_flips_from_zero_to_positive(v1, v2):
    # SLB 2021Q3.  "logistics" to "disruptions" is one token apart.
    text = "results were affected by temporary supply and logistics disruptions"
    assert score(text, v1, "v1_library_only").scrisk_raw == 0.0
    assert score(text, v2, "v2_seeds_inflections").scrisk_raw > 0.0


@pytest.mark.parametrize("gap,expected_pairs", [(9, 1), (10, 0)])
def test_the_window_is_still_ten_tokens(v2, gap, expected_pairs):
    # Nine filler tokens leaves the two spans exactly 10 apart, which pairs.
    # Ten leaves them 11 apart, which does not.  The fix must not widen this.
    text = "inventory " + " ".join(["quarter"] * gap) + " uncertainty"
    assert score(text, v2, "v2_seeds_inflections").risk_pairs == expected_pairs


# --- the two properties left in place on purpose ----------------------------

def test_shortages_pairs_with_itself_in_both_versions(v1, v2):
    text = "we saw shortages " + " ".join(["quarter"] * 60)
    v1_result = score(text, v1, "v1_library_only")
    v2_result = score(text, v2, "v2_seeds_inflections")
    # One word, no second word anywhere nearby, yet a non-zero score.
    assert v1_result.risk_pairs == 1
    assert v1_result.identical_span_pairs == 1
    assert v1_result.identical_span_weight_sum == pytest.approx(0.69290245)
    assert v1_result.scrisk_weight_sum == pytest.approx(v1_result.identical_span_weight_sum)
    # v2 inflection completion extends the same behaviour to the singular.
    singular = "we saw a shortage " + " ".join(["quarter"] * 60)
    assert score(singular, v1, "v1_library_only").risk_pairs == 0
    assert score(singular, v2, "v2_seeds_inflections").identical_span_pairs == 1
    assert v2_result.identical_span_pairs == 1


def test_forbidding_identical_span_pairs_removes_the_self_pair(v2):
    text = "we saw shortages " + " ".join(["quarter"] * 60)
    result = score(
        text, v2, "v2_seeds_inflections", forbid_identical_span_pairs=True
    )
    assert result.scrisk_raw == 0.0
    assert result.identical_span_pairs == 0


def test_excluding_the_customer_family_removes_the_customer_flip(library):
    # TMO 2022Q2, quoted in the audit: "customers" and "concerns" five tokens
    # apart, on biotech funding rather than supply chain.
    text = "funding concerns pressuring those mid-cap biotech customers"
    kept = S.build_supply_chain_vocabulary(library, "v2_seeds_inflections")
    dropped = S.build_supply_chain_vocabulary(
        library, "v2_seeds_inflections", excluded_terms=("customers", "customer")
    )
    assert score(text, kept, "v2_seeds_inflections").scrisk_raw > 0.0
    assert score(text, dropped, "v2_seeds_inflections").scrisk_raw == 0.0
    assert "customers" not in dropped and "customer" not in dropped


def test_exclusions_cannot_empty_the_vocabulary(library):
    with pytest.raises(ValueError, match="empty after exclusions"):
        S.build_supply_chain_vocabulary(library, "v1_library_only", excluded_terms=list(library))


# --- transcript integrity ---------------------------------------------------

def test_integrity_flags_the_three_audited_failures():
    # F 2012Q4: every utterance is the literal placeholder.
    status, flags = S.assess_transcript_integrity("Operator: (full spoken content)")
    assert status == S.INTEGRITY_CONTENT_ABSENT
    assert "redacted_spoken_content" in flags
    # ETN 2012Q4: 4,506 tokens, 147 distinct, the copyright notice repeated.
    notice = "Copyright policy: All transcripts on this site are the copyright of the provider. "
    status, flags = S.assess_transcript_integrity(notice * 80)
    assert status == S.INTEGRITY_CONTENT_ABSENT
    assert {"provider_copyright_boilerplate", "degenerate_repetition"} <= set(flags)
    # OHI 2021Q3: 22 tokens, the operator's greeting only.
    status, flags = S.assess_transcript_integrity(
        "Operator: Good morning and welcome to the Omega Healthcare Investors "
        "Third Quarter earnings conference call. Please stand by."
    )
    assert status == S.INTEGRITY_CONTENT_ABSENT
    assert flags == ["under_1000_tokens"]


def test_integrity_passes_a_normal_length_transcript():
    assert S.assess_transcript_integrity(distinct_filler(4000)) == (S.INTEGRITY_OK, [])


def test_integrity_separates_no_text_from_content_absent():
    # A row that was never a call is not the same failure as a call whose
    # transcript arrived empty of speech, and it stays in the SD population.
    assert S.assess_transcript_integrity("") == (S.INTEGRITY_NO_TEXT, [])
    assert S.assess_transcript_integrity("   \n  123 456 ") == (S.INTEGRITY_NO_TEXT, [])


# --- standardization population --------------------------------------------

def test_excluded_rows_leave_the_sd_population_and_get_a_blank_score():
    raw = [0.0, 1.0, 2.0, 99.0]
    scaled, sd = S.normalize_raw_scores(raw, [True, True, True, False])
    assert sd == pytest.approx(0.816496580927726)  # pstdev([0, 1, 2])
    assert scaled[3] is None
    assert scaled[2] == pytest.approx(2.0 / sd)


def test_normalization_without_a_mask_is_unchanged():
    raw = [0.0, 1.0, 2.0]
    assert S.normalize_raw_scores(raw)[1] == pytest.approx(S.normalize_raw_scores(raw, None)[1])


# --- end to end through the CLI ---------------------------------------------

def run_cli(tmp_path: Path, rows: list[dict[str, str]], *extra: str) -> list[dict[str, str]]:
    source = tmp_path / "input.csv"
    with source.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["ticker", "quarter_label", "transcript_text"])
        writer.writeheader()
        writer.writerows(rows)
    output = tmp_path / "scored.csv"
    subprocess.run(
        [sys.executable, str(ROOT / "calculate_supply_chain_transcript_scores.py"),
         "--input", str(source), "--output", str(output), "--library", str(LIBRARY), *extra],
        check=True, capture_output=True, text=True, cwd=ROOT,
    )
    csv.field_size_limit(2 ** 31 - 1)
    with output.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle)), output


@requires_library
def test_cli_scores_happy_path_empty_and_junk_rows(tmp_path):
    body = distinct_filler(4000)
    rows = [
        {"ticker": "AAA", "quarter_label": "2022Q1",
         "transcript_text": body + " our supply chain faces real uncertainty today"},
        {"ticker": "BBB", "quarter_label": "2022Q1", "transcript_text": ""},
        {"ticker": "CCC", "quarter_label": "2022Q1", "transcript_text": "]]] 42 ### ’’"},
        {"ticker": "DDD", "quarter_label": "2022Q1", "transcript_text": "Operator: (full spoken content)"},
    ]
    scored, output = run_cli(tmp_path, rows)
    by_ticker = {row["ticker"]: row for row in scored}
    assert len(scored) == 4

    assert float(by_ticker["AAA"]["SCRisk"]) > 0.0
    assert by_ticker["AAA"]["transcript_integrity_status"] == "ok"
    assert by_ticker["AAA"]["in_standardization_population"] == "1"
    assert by_ticker["AAA"]["vocabulary_version"] == "v2_seeds_inflections"

    for ticker in ("BBB", "CCC"):
        assert by_ticker[ticker]["transcript_integrity_status"] == "no_transcript_text"
        assert float(by_ticker[ticker]["SCRisk_raw"]) == 0.0
        assert by_ticker[ticker]["in_standardization_population"] == "1"

    assert by_ticker["DDD"]["SCRisk"] == ""
    assert by_ticker["DDD"]["Resolution"] == ""
    assert by_ticker["DDD"]["in_standardization_population"] == "0"
    assert by_ticker["DDD"]["transcript_integrity_status"] == "content_absent"

    manifest = json.loads(
        (output.parent / (output.name + ".scoring_manifest.json")).read_text(encoding="utf-8")
    )
    assert manifest["rows_content_absent"] == 1
    assert manifest["rows_in_standardization_population"] == 3
    assert manifest["window"] == 10
    assert manifest["terms_in_both_supply_chain_and_risk"] == ["shortage", "shortages"]


@requires_library
def test_cli_without_the_integrity_filter_standardizes_every_row(tmp_path):
    rows = [
        {"ticker": "AAA", "quarter_label": "2022Q1",
         "transcript_text": distinct_filler(4000) + " supply chain uncertainty"},
        {"ticker": "DDD", "quarter_label": "2022Q1", "transcript_text": "Operator: (full spoken content)"},
    ]
    scored, _ = run_cli(tmp_path, rows, "--no-transcript-integrity-filter")
    flagged = next(row for row in scored if row["ticker"] == "DDD")
    assert flagged["transcript_integrity_status"] == "content_absent"
    assert flagged["SCRisk"] != ""
    assert flagged["in_standardization_population"] == "1"


@requires_smoke_500
def test_v1_reproduces_the_original_scores_on_the_local_smoke_run(tmp_path):
    """The regression guard: v1 plus no integrity filter must be bit-identical.

    Reads a 500-row scored sample under artifacts/, which is local and not
    committed, so this skips when the sample is absent.
    """
    csv.field_size_limit(sys.maxsize)
    with SMOKE_500.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        source_fields = [f for f in reader.fieldnames if f not in V1_SCORE_COLUMNS]
        original = list(reader)
    assert len(original) == 500

    source = tmp_path / "unscored.csv"
    with source.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=source_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(original)
    output = tmp_path / "rescored.csv"
    subprocess.run(
        [sys.executable, str(ROOT / "calculate_supply_chain_transcript_scores.py"),
         "--input", str(source), "--output", str(output), "--library", str(LIBRARY),
         "--vocabulary-version", "v1_library_only", "--no-transcript-integrity-filter"],
        check=True, capture_output=True, text=True, cwd=ROOT,
    )
    with output.open(newline="", encoding="utf-8") as handle:
        rescored = list(csv.DictReader(handle))

    assert len(rescored) == 500
    for before, after in zip(original, rescored):
        assert (before["ticker"], before["quarter_label"]) == (after["ticker"], after["quarter_label"])
        for column in V1_SCORE_COLUMNS:
            assert before[column] == after[column], (before["ticker"], column)
