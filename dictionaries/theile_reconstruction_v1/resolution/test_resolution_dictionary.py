"""Tests for the reconstructed Theile et al. (2026) resolution dictionary.

Small and high signal. Each test guards a claim the reconstruction makes:
Table 4 coverage, the 55-term primary specification, exact token matching, the
paper's proximity rule, and that the pipeline produces one Resolution measure
from one dictionary.

Everything here runs on a clean checkout. The supply-chain vocabulary comes
from the committed fixture `fixtures/synthetic_supply_chain_library.jsonl`, not
from the gitignored generated library. The two tests that do need local
artifacts are marked and skip.

Run:
    python3 -m pytest dictionaries/theile_reconstruction_v1/resolution -q
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))

import resolution_dictionary_io as dio  # noqa: E402
import calculate_supply_chain_transcript_scores as scoring  # noqa: E402

WINDOW = scoring.WINDOW  # 10

requires_generated_library = pytest.mark.skipif(
    not dio.REPO_SUPPLY_CHAIN_LIBRARY.exists(),
    reason=f"local gitignored artifact absent: {dio.REPO_SUPPLY_CHAIN_LIBRARY}",
)
requires_transcript_corpus = pytest.mark.skipif(
    not dio.TRANSCRIPT_CORPUS.exists(),
    reason=f"local gitignored artifact absent: {dio.TRANSCRIPT_CORPUS}",
)


@pytest.fixture(scope="module")
def primary():
    return dio.primary_resolution_terms()


@pytest.fixture(scope="module")
def variants():
    return dio.all_variants()


@pytest.fixture(scope="module")
def table4():
    return dio.table_4_terms()


@pytest.fixture(scope="module")
def sc_weights():
    """The committed synthetic fixture, so these tests need no local artifact."""
    return dio.synthetic_supply_chain_weights()


@pytest.fixture(scope="module")
def risk_words():
    return dio.primary_risk_terms()


# --- the primary specification ------------------------------------------


def test_primary_dictionary_has_exactly_55_unique_lowercase_whole_tokens(primary):
    """The one production Resolution specification."""
    assert len(primary) == 55
    assert len(set(primary)) == 55
    for term in primary:
        assert term == term.lower(), term
        assert term.isalpha(), term          # single whole token, no spaces or hyphens
        assert term.strip() == term, term


def test_primary_dictionary_file_is_bare_with_no_build_date():
    """Generated files are hashed, so none may carry a runtime date or header."""
    raw = dio.BASELINE_FILE.read_text()
    lines = raw.splitlines()
    assert len(lines) == 55
    assert all(line and not line.startswith("#") for line in lines)
    assert "Built" not in raw and "20260" not in raw


def test_scoring_script_loads_the_55_term_dictionary_as_its_only_default():
    assert scoring.PRIMARY_RESOLUTION_TERM_COUNT == 55
    assert scoring.PRIMARY_RESOLUTION_DICTIONARY_PATH == dio.BASELINE_FILE
    terms = scoring.load_primary_resolution_dictionary()
    assert terms == dio.primary_resolution_terms()
    assert not hasattr(scoring, "STARTER_RESOLUTION_WORDS")


def test_resolution_dictionary_selection_is_primary_by_default():
    selection = scoring.select_resolution_dictionary(None)
    assert selection.is_primary is True
    assert selection.usage == "primary"
    assert len(selection.terms) == 55


def test_resolution_override_is_marked_non_primary(tmp_path):
    override = tmp_path / "development-resolution.txt"
    override.write_text("mitigate\nresolve\n")
    selection = scoring.select_resolution_dictionary(override)
    assert selection.is_primary is False
    assert selection.usage == "override_non_primary"
    assert selection.terms == ["mitigate", "resolve"]


def filler(n: int) -> list[str]:
    """n distinct alphabetic placeholder terms, so only the defect under test fires."""
    alphabet = "abcdefghijklmnopqrstuvwxyz"
    return [f"zz{alphabet[i // 26]}{alphabet[i % 26]}" for i in range(n)]


@pytest.mark.parametrize("contents,message", [
    ("\n".join(["help", "help"] + filler(53)) + "\n", "duplicate"),
    ("help\nsolve\n", "exactly 55"),
    ("\n".join(["Help"] + filler(54)) + "\n", "malformed"),
    ("\n".join(["help "] + filler(54)) + "\n", "malformed"),
    ("\n".join(["help", ""] + filler(53)) + "\n", "non-empty"),
])
def test_malformed_primary_resolution_dictionary_fails_clearly(tmp_path, contents, message):
    bad = tmp_path / "bad-resolution.txt"
    bad.write_text(contents)
    with pytest.raises(ValueError, match=message):
        scoring.load_primary_resolution_dictionary(bad)


def test_missing_primary_resolution_dictionary_fails_clearly(tmp_path):
    with pytest.raises(ValueError, match="missing"):
        scoring.load_primary_resolution_dictionary(tmp_path / "nope.txt")


# --- Table 4 -------------------------------------------------------------


def test_table_4_has_thirty_printed_slots_and_two_duplicates():
    """The printed table has 30 slots but only 28 distinct keywords.

    Slots 24 and 25 repeat slots 22 and 23 (enhance 591, recover 566). Verified
    by rendering PDF page 8 at 250 dpi, not just by the text layer.
    """
    with dio.TABLE_4_FILE.open() as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 30
    dupes = [r for r in rows if r["is_duplicate_of_slot"]]
    assert [r["printed_slot"] for r in dupes] == ["24", "25"]
    assert [(r["keyword"], r["published_frequency"]) for r in dupes] == [
        ("enhance", "591"), ("recover", "566")
    ]
    assert len({r["keyword"] for r in rows}) == 28


def test_table_4_frequencies_descend_within_each_printed_column():
    """The table says it is ordered by frequency. Check that it actually is."""
    with dio.TABLE_4_FILE.open() as fh:
        rows = list(csv.DictReader(fh))
    for col in ("1", "2", "3"):
        in_col = [r for r in rows if r["column"] == col]
        assert len(in_col) == 10
        # Column 3 dips only because slots 24-25 repeat 22-23.
        cleaned = [int(r["published_frequency"]) for r in in_col
                   if not r["is_duplicate_of_slot"]]
        assert cleaned == sorted(cleaned, reverse=True), col


def test_primary_covers_every_table_4_term(primary, table4):
    assert len(table4) == 28
    assert not sorted(set(table4) - set(primary))


def test_sensitivity_variants_cover_table_4_except_the_overlap_variant(variants, table4):
    for name, terms in variants.items():
        if name == "overlap_sensitivity" or not terms:
            continue
        assert not sorted(set(table4) - set(terms)), name


def test_the_paper_high_frequency_words_are_present(primary):
    """The words the task called out by name as must-not-omit."""
    for word in ["help", "solution", "solve", "improve", "fix", "easy", "overcome"]:
        assert word in primary, word


def test_solution_and_solutions_stay_in_the_primary_dictionary(primary):
    """Table 4 rank 2 (4,289) and rank 10 (1,932).

    They also appear in the repo's provisional supply chain library, but the
    final reconstructed supply-chain vocabulary does not exist yet, so the
    overlap is not settled and neither term is removed from the primary.
    """
    assert "solution" in primary
    assert "solutions" in primary


# --- variant structure ---------------------------------------------------


def test_primary_is_nested_between_the_anchor_and_the_expanded_set(primary, variants):
    anchor = set(variants["paper_anchor"])
    baseline = set(primary)
    expanded = set(variants["expanded_sensitivity"])
    assert anchor < baseline < expanded
    assert len(anchor) == 28
    assert len(expanded) == 97


def test_overlap_variant_is_the_primary_minus_two_declared_terms(primary, variants):
    overlap = variants["overlap_sensitivity"]
    assert set(overlap) == set(primary) - {"solution", "solutions"}
    assert len(overlap) == 53


def test_no_duplicate_terms_in_any_variant(variants):
    for name, terms in variants.items():
        assert len(terms) == len(set(terms)), name


def test_every_variant_is_single_lowercase_tokens(variants):
    """These are word lists. Multiword operational strategies do not belong."""
    for name, terms in variants.items():
        for t in terms:
            assert t == t.lower() and t.isalpha(), (name, t)


def test_unsupported_starter_terms_are_excluded(variants):
    """The old starter dictionary carried concepts, not Oxford synonyms.

    Operational strategies (dual sourcing, buffer stock) and words like
    'prevent' and 'address' are not synonyms of mitigate or resolve in any
    Oxford entry retrieved on 2026-09-16. See oxford_evidence.json.
    """
    banned = {"dual", "sourcing", "backup", "buffer", "safety", "stock",
              "alternative", "source", "supplier", "diversify", "diversified",
              "prevent", "prevents", "prevented", "preventing",
              "address", "addresses", "addressed", "addressing",
              "avoid", "avoids", "contain", "contains",
              "remediate", "remediation", "substitute", "substitutes"}
    assert not (set(variants["expanded_sensitivity"]) & banned)


# --- exact token matching ------------------------------------------------


def matched(text: str, terms) -> set[str]:
    index = scoring.build_phrase_index(terms)
    return {occ.term for occ in scoring.find_indexed_occurrences(scoring.tokenize(text), index)}


@pytest.mark.parametrize("text,must_not_match", [
    ("That guidance was helpful for our inventory risk.", "help"),
    ("The prefix of the part number changed.", "fix"),
    ("The supplier dispute remains unresolved.", "resolved"),
    ("The joint venture was dissolved.", "solved"),
    ("An easy-going supplier relationship.", "easy"),
    ("Port congestion is easing.", "easy"),
    ("We improvised a workaround.", "improve"),
    ("The recoverable amount was written down.", "recover"),
])
def test_matching_is_whole_token_not_substring(variants, text, must_not_match):
    assert must_not_match not in matched(text, variants["expanded_sensitivity"])


@pytest.mark.parametrize("text,expected", [
    ("We resolved the shortage.", "resolved"),
    ("Mitigating actions are underway.", "mitigating"),
    ("It was an easier quarter.", "easier"),
    ("They overcame the constraint.", "overcame"),
])
def test_primary_matches_the_forms_it_claims(primary, text, expected):
    assert expected in matched(text, primary)


def test_unresolved_is_a_risk_word_not_a_resolution_word(variants, risk_words):
    """The primary risk library carries 'unresolved'. It must stay on that side."""
    assert "unresolved" in risk_words
    for terms in variants.values():
        assert "unresolved" not in terms


# --- the paper's proximity rule ------------------------------------------


def resolution_pairs(text, sc_weights, risk_words, res_terms) -> int:
    return scoring.calculate_raw_scores(
        text, sc_weights, risk_words, res_terms, window=WINDOW).resolution_pairs


def test_supply_chain_risk_with_nearby_resolution_scores(sc_weights, risk_words, primary):
    text = ("We had a supplier shortage last quarter and we were able to resolve "
            "the shortage by qualifying a second plant.")
    assert resolution_pairs(text, sc_weights, risk_words, primary) > 0


def test_supply_chain_risk_without_resolution_does_not_score(sc_weights, risk_words, primary):
    text = ("We had a supplier shortage last quarter and it cost us roughly two "
            "points of gross margin.")
    res = scoring.calculate_raw_scores(text, sc_weights, risk_words, primary, window=WINDOW)
    assert res.risk_pairs > 0          # it is supply chain risk
    assert res.resolution_pairs == 0   # but not resolution


def test_generic_resolution_language_outside_a_risk_context_does_not_score(
        sc_weights, risk_words, primary):
    """The whole point of the measure. Positive talk with no risk word is zero."""
    text = ("Our new product helps customers and we are pleased with the improvement "
            "in brand awareness this quarter.")
    assert resolution_pairs(text, sc_weights, risk_words, primary) == 0


def test_resolution_beyond_the_ten_word_window_does_not_score(sc_weights, risk_words, primary):
    filler = " ".join(["then"] * 30)
    text = (f"We had a supplier shortage last quarter. {filler} separately we did "
            "resolve the billing dispute with our landlord.")
    assert resolution_pairs(text, sc_weights, risk_words, primary) == 0


def test_resolution_must_be_near_the_same_supply_chain_occurrence(sc_weights, risk_words,
                                                                  primary):
    """Equation (2) ties r and m to the same w, not to each other.

    The risk word sits by one supply chain word and the resolution word by a
    different one, more than ten tokens apart. Neither w satisfies both
    conditions, so Resolution is zero even though all three libraries fire.
    """
    filler = " ".join(["then"] * 25)
    text = (f"Our inventory faced a shortage this quarter. {filler} our logistics "
            "network continued to improve.")
    res = scoring.calculate_raw_scores(text, sc_weights, risk_words, primary, window=WINDOW)
    assert res.risk_pairs > 0
    assert res.resolution_occurrences > 0
    assert res.resolution_pairs == 0


def test_resolution_never_exceeds_scrisk(sc_weights, risk_words, variants):
    """Equation (2) adds a condition to equation (1), so Resolution is a subset."""
    text = ("We saw a supplier shortage and inventory risk. We are mitigating it and "
            "reducing our exposure, which should help the supply constraint.")
    for name, terms in variants.items():
        res = scoring.calculate_raw_scores(text, sc_weights, risk_words, terms, window=WINDOW)
        assert res.resolution_pairs <= res.risk_pairs, name
        assert res.resolution_weight_sum <= res.scrisk_weight_sum, name


def test_each_tier_fires_on_the_term_it_adds(sc_weights, risk_words, variants, primary):
    """One sentence per tier, each carrying only that tier's resolution word.

    'mitigate' is a Table 4 term, 'mitigating' is primary-only (Oxford prints
    it in the Verb Forms table but Table 4 does not show it), 'reducing' is
    sensitivity-only.
    """
    cases = {
        "mitigate": (True, True, True),
        "mitigating": (False, True, True),
        "reducing": (False, False, True),
    }
    tiers = [variants["paper_anchor"], primary, variants["expanded_sensitivity"]]
    for word, expected in cases.items():
        text = f"Our supplier shortage is a real risk and we are {word} it now."
        got = tuple(
            scoring.calculate_raw_scores(text, sc_weights, risk_words, t,
                                         window=WINDOW).resolution_pairs > 0
            for t in tiers
        )
        assert got == expected, (word, got, expected)


# --- one production measure ----------------------------------------------


def score_with_fixture(tmp_path: Path, resolution_path: Path | None = None) -> dict:
    """Run the real pipeline end to end on the committed fixture."""
    library_path = tmp_path / "terms.jsonl"
    library_path.write_text(dio.SYNTHETIC_SUPPLY_CHAIN_FIXTURE.read_text())
    input_path = tmp_path / "input.csv"
    with input_path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["ticker", "quarter_label", "transcript_text"])
        w.writeheader()
        w.writerow({
            "ticker": "TEST",
            "quarter_label": "2018Q1",
            "transcript_text": ("We had a supplier shortage last quarter and we were "
                                "able to resolve the shortage by qualifying a second "
                                "plant. " * 5),
        })
    return scoring.score_csv(
        input_path=input_path,
        output_path=tmp_path / "scored.csv",
        library_path=library_path,
        risk_path=None,
        resolution_path=resolution_path,
        text_column="transcript_text",
        window=WINDOW,
        vocabulary_version="v1_library_only",
        filter_transcript_integrity=False,
    )


def test_pipeline_emits_one_resolution_measure_from_the_primary_dictionary(tmp_path):
    manifest = score_with_fixture(tmp_path)
    assert manifest["resolution_dictionary_is_primary"] is True
    assert manifest["resolution_dictionary_usage"] == "primary"
    assert manifest["resolution_dictionary_total_terms"] == 55
    assert manifest["resolution_dictionary_selected_total_terms"] == 55
    assert manifest["resolution_dictionary_sha256"] == dio.sha256(dio.BASELINE_FILE)
    assert manifest["resolution_dictionary_path"].endswith(
        "resolution_terms_conservative_baseline.txt")

    header = (tmp_path / "scored.csv").read_text().splitlines()[0].split(",")
    resolution_columns = [c for c in header if c.startswith("Resolution")]
    # One measure, plus its raw and sd bookkeeping. No per-variant columns.
    assert resolution_columns == ["Resolution_weight_sum", "Resolution_raw",
                                  "Resolution_sd", "Resolution"]


def test_pipeline_marks_a_resolution_override_non_primary(tmp_path):
    override = tmp_path / "override-resolution.txt"
    override.write_text("mitigate\nresolve\n")
    manifest = score_with_fixture(tmp_path, override)
    assert manifest["resolution_dictionary_is_primary"] is False
    assert manifest["resolution_dictionary_usage"] == "override_non_primary"
    assert manifest["resolution_dictionary_selected_total_terms"] == 2
    # The primary identity is still recorded so the run is auditable.
    assert manifest["resolution_dictionary_total_terms"] == 55


def test_pipeline_uses_the_161_term_risk_dictionary_by_default(tmp_path):
    manifest = score_with_fixture(tmp_path)
    assert manifest["risk_dictionary_is_primary"] is True
    assert manifest["risk_dictionary_total_terms"] == 161
    assert manifest["risk_dictionary_selected_total_terms"] >= 161


# --- overlaps ------------------------------------------------------------


def test_no_overlap_with_the_primary_161_term_risk_dictionary(variants, risk_words):
    assert len(risk_words) == 161
    for name, terms in variants.items():
        assert not (set(terms) & set(risk_words)), name


def test_no_overlap_with_the_published_risk_and_supply_chain_tables(variants):
    published_risk = set(dio.table_3_reference_terms())
    assert len(published_risk) == 144
    published_sc = set(dio.PAPER_TABLE_2_SUPPLY_CHAIN)
    for phrase in scoring.SUPPLY_CHAIN_SEEDS:
        published_sc.update(phrase.split())
    for name, terms in variants.items():
        assert not (set(terms) & published_risk), (name, "risk")
        assert not (set(terms) & published_sc), (name, "supply chain")


def test_the_fixture_avoids_the_unsettled_supply_chain_overlap():
    """The fixture must not prejudge the deferred overlap question."""
    fixture = set(dio.synthetic_supply_chain_weights())
    assert not (fixture & {"solution", "solutions"})


# --- tracked source validation ------------------------------------------


def test_validation_run_record_is_source_only_and_pins_the_dictionaries():
    """The tracked record must reproduce on a clean checkout.

    It carries the commit, the window and the SHA-256 of every dictionary. It
    must not carry the transcript corpus, the generated supply-chain library,
    or any zero rate: those belong to the archived local diagnostic.
    """
    record = json.loads((HERE / "validation_run.json").read_text())
    assert record["scope"] == "source_validation_only"
    assert record["reproducible_on_a_clean_checkout"] is True
    assert record["build_date"] == "2026-09-16"
    assert record["git_commit_at_validation"] != "unknown"
    assert record["window"] == WINDOW

    prim = record["primary_dictionaries"]
    assert prim["resolution"]["terms"] == 55
    assert prim["resolution"]["sha256"] == dio.sha256(dio.BASELINE_FILE)
    assert prim["risk"]["terms"] == 161
    assert prim["risk"]["sha256"] == dio.sha256(dio.PRIMARY_RISK_FILE)
    assert record["sensitivity_dictionaries"]["paper_anchor"]["terms"] == 28
    assert record["sensitivity_dictionaries"]["overlap_sensitivity"]["terms"] == 53
    assert record["test_fixture"]["sha256"] == dio.sha256(
        dio.SYNTHETIC_SUPPLY_CHAIN_FIXTURE)

    for banned in ("transcript_corpus", "zero_rates", "seed", "sample_scored"):
        assert banned not in record, banned
    blob = json.dumps(record)
    assert "earnings_call_transcripts.csv" not in blob
    assert "sec_10k_supply_chain" not in blob


def test_tracked_overlap_report_holds_only_settled_comparisons():
    """No provisional supply-chain row in a tracked file."""
    with (HERE / "overlap_report.csv").open() as fh:
        rows = list(csv.DictReader(fh))
    assert rows
    assert all(not r["compared_against"].startswith("PROVISIONAL") for r in rows)
    assert all("repo_generated" not in r["compared_against"] for r in rows)
    # every settled comparison is a zero-overlap comparison
    assert all(r["n_shared"] == "0" for r in rows)


def test_validation_report_states_the_corpus_diagnostic_is_archived():
    report = (HERE / "validation_report.md").read_text()
    assert "Scope: source validation only" in report
    assert "not PR validation" in report
    assert "outputs/resolution_validation/" in report
    # No corpus numbers leak into the tracked report.
    for banned in ("zero-Resolution rate", "zero-SCRisk", "calls pass integrity"):
        assert banned not in report, banned


def test_source_validation_needs_no_local_artifact():
    """The tracked report's inputs are all committed."""
    for path in (dio.BASELINE_FILE, dio.ANCHOR_FILE, dio.SENSITIVITY_FILE,
                 dio.OVERLAP_FILE, dio.PRIMARY_RISK_FILE, dio.TABLE_3_FILE,
                 dio.TABLE_4_FILE, dio.SYNTHETIC_SUPPLY_CHAIN_FIXTURE):
        assert path.exists(), path
        tracked = subprocess.run(
            ["git", "-C", str(REPO), "ls-files", "--error-unmatch", str(path)],
            capture_output=True, text=True)
        assert tracked.returncode == 0, f"{path} is not tracked"


# --- archived local diagnostic -------------------------------------------


@requires_generated_library
def test_provisional_supply_chain_overlap_exists_and_is_not_acted_on(primary):
    """The overlap is real against a provisional input, and is left alone.

    Recomputing it definitively waits on the reconstructed supply-chain
    vocabulary. This pins what the provisional number is today so a change in
    the generated library does not slip by unnoticed, and it asserts the terms
    stay in the primary dictionary.
    """
    repo_sc = set(dio.repo_supply_chain_weights())
    assert sorted(set(primary) & repo_sc) == ["solution", "solutions"]
    assert "solution" in primary and "solutions" in primary


@requires_transcript_corpus
@requires_generated_library
def test_archived_diagnostic_is_gitignored_and_labels_itself():
    """When the archive exists it must be untracked and say what it is."""
    out_dir = REPO / "outputs" / "resolution_validation"
    if not out_dir.exists():
        pytest.skip("archived diagnostic not generated in this checkout")

    check = subprocess.run(["git", "-C", str(REPO), "check-ignore", "-q", str(out_dir)])
    assert check.returncode == 0, f"{out_dir} must be gitignored"

    report = (out_dir / "corpus_diagnostic.md").read_text()
    assert "archived local diagnostic, not PR validation" in report
    assert "cannot be reproduced from the repository" in report

    record = json.loads((out_dir / "corpus_diagnostic_run.json").read_text())
    assert record["scope"] == "archived_local_diagnostic"
    assert record["reproducible_on_a_clean_checkout"] is False
    assert record["transcript_corpus"]["sha256"]
    assert record["dictionaries"]["supply_chain"]["status"].startswith("PROVISIONAL")
    assert record["dictionaries"]["resolution"]["terms"] == 55
    assert record["dictionaries"]["risk"]["terms"] == 161
