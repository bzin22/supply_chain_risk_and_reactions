"""Build the reconstructed Theile et al. (2026) resolution dictionary.

The paper defines its resolution library (the 𝕄 library) as "the terms mitigate
and resolve as well as their synonyms from the Oxford dictionary".  It never
publishes the library.  It publishes Table 4, the 30 most frequent
resolution-related word forms observed in its 129,981 transcripts.

This script turns that into three dictionaries of increasing reach:

``resolution_terms_paper_anchor.txt``
    The distinct word forms actually printed in Table 4.  Every one of these is
    observed evidence that the form is in the paper's 𝕄 library.

``resolution_terms_conservative_baseline.txt``
    The anchor plus terms an Oxford source directly supports: the inflected
    forms Oxford itself prints for each anchor root, and the synonym
    cross-references Oxford prints on the two seed headwords ``mitigate`` and
    ``resolve``.

``resolution_terms_expanded_sensitivity.txt``
    Predeclared sensitivity terms.  Regular inflections Oxford does not print,
    Oxford synonym-graph neighbours two or three hops out, and the four
    resolution keywords the paper itself names in its Table 10 Column (5)
    expanded-keyword robustness check.

Nothing here is chosen by looking at returns.  Selection uses Table 4, the
Oxford entries recorded in ``source_manifest.json``, and the paper's own prose.

Run:
    python3 build_resolution_dictionary.py
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Fixed source/build date.  Every generated file in this directory is hashed in
# source_manifest.json, so nothing generated may carry a runtime date: the hash
# would change on every rebuild for no substantive reason.
SOURCE_DATE = "2026-09-16"
RETRIEVAL_DATE = SOURCE_DATE

OALD = "Oxford Advanced Learner's Dictionary (10th ed.), oxfordlearnersdictionaries.com"


# ---------------------------------------------------------------------------
# 1. Table 4, read off the rendered PDF page, not off a text-layer dump.
# ---------------------------------------------------------------------------
# Page 8 of the PDF (journal page 2988).  Read column by column, top to bottom.
# Slots 24 and 25 of the printed table repeat slots 22 and 23 verbatim.  That
# repetition is in the typeset page itself, not an extraction artifact, so the
# printed "top 30" carries only 28 distinct keywords.  See table_4_extraction.csv.
TABLE_4_SLOTS: list[tuple[int, str, int]] = [
    # (printed slot, keyword, published frequency)
    (1, "help", 5448),
    (2, "solutions", 4289),
    (3, "solve", 3722),
    (4, "improve", 2688),
    (5, "improved", 2554),
    (6, "mitigate", 2503),
    (7, "resolved", 2150),
    (8, "fixed", 2015),
    (9, "improvement", 1943),
    (10, "solution", 1932),
    (11, "improving", 1842),
    (12, "helping", 1536),
    (13, "recovery", 1376),
    (14, "solving", 1327),
    (15, "resolve", 996),
    (16, "improvements", 953),
    (17, "resolution", 801),
    (18, "helps", 768),
    (19, "helped", 744),
    (20, "mitigation", 622),
    (21, "solved", 612),
    (22, "enhance", 591),
    (23, "recover", 566),
    (24, "enhance", 591),   # duplicate of slot 22 as printed
    (25, "recover", 566),   # duplicate of slot 23 as printed
    (26, "fix", 553),
    (27, "easy", 541),
    (28, "easier", 516),
    (29, "overcome", 475),
    (30, "enhanced", 474),
]

DUPLICATE_SLOTS = {24, 25}


# ---------------------------------------------------------------------------
# 2. Oxford evidence, retrieved 2026-09-16.  Recorded verbatim.
# ---------------------------------------------------------------------------
# Inflected forms Oxford prints in the entry's own "Verb Forms" table or
# inflection bracket.  Oxford does not print regular noun plurals, so a missing
# plural here means "not attested", not "not a word".
OXFORD_LISTED_FORMS: dict[str, list[str]] = {
    "mitigate": ["mitigate", "mitigates", "mitigated", "mitigating"],
    "resolve": ["resolve", "resolves", "resolved", "resolving"],
    "help": ["help", "helps", "helped", "helping"],
    "solve": ["solve", "solves", "solved", "solving"],
    "improve": ["improve", "improves", "improved", "improving"],
    "fix": ["fix", "fixes", "fixed", "fixing"],
    "recover": ["recover", "recovers", "recovered", "recovering"],
    "enhance": ["enhance", "enhances", "enhanced", "enhancing"],
    "overcome": ["overcome", "overcomes", "overcame", "overcoming"],
    "easy": ["easy", "easier", "easiest"],
    "recovery": ["recovery", "recoveries"],
    "alleviate": ["alleviate", "alleviates", "alleviated", "alleviating"],
    "settle": ["settle", "settles", "settled", "settling"],
    "ease": ["ease", "eases", "eased", "easing"],
    "relieve": ["relieve", "relieves", "relieved", "relieving"],
    "reduce": ["reduce", "reduces", "reduced", "reducing"],
    "relax": ["relax", "relaxes", "relaxed", "relaxing"],
    "remedy": ["remedy", "remedies", "remedied", "remedying"],
    "counter": ["counter", "counters", "countered", "countering"],
    "absorb": ["absorb", "absorbs", "absorbed", "absorbing"],
    "dissolve": ["dissolve", "dissolves", "dissolved", "dissolving"],
    "dilute": ["dilute", "dilutes", "diluted", "diluting"],
    # Nouns with no Oxford-printed plural.
    "solution": ["solution"],
    "improvement": ["improvement"],
    "resolution": ["resolution"],
    "mitigation": ["mitigation"],
    "enhancement": ["enhancement"],
    "settlement": ["settlement"],
}

# Synonym cross-references Oxford prints inside the entry ("synonym X").
OXFORD_SYNONYM_XREFS: dict[str, list[str]] = {
    "mitigate": ["alleviate"],
    "resolve": ["settle"],
    "alleviate": ["ease"],
    "ease (verb)": ["alleviate", "relax", "reduce"],
    "relieve": ["alleviate"],
    "resolution": ["resolve", "settlement"],
    "solution": ["answer"],
    "remedy (noun)": ["redress", "solution"],
    "remedy (verb)": ["right"],
    "counter (verb)": ["counteract"],
}

# Oxford definition text used to trace an anchor root back to mitigate/resolve.
OXFORD_DEFS: dict[str, str] = {
    "mitigate": "to make something less harmful, serious, etc.",
    "resolve": "to find an acceptable solution to a problem or difficulty",
    "help": "to improve a situation; to make it easier for something to happen",
    "solve": "to find a way of dealing with a problem or difficult situation",
    "solution": "a way of solving a problem or dealing with a difficult situation",
    "improve": "to become better than before; to make something/somebody better than before",
    "improvement": "the act of making something better; the process of something becoming better",
    "fix": "to repair or correct something",
    "recover": "to return to a normal state after an unpleasant or unusual experience "
               "or a period of difficulty",
    "recovery": "the process of improving or becoming stronger again",
    "enhance": "to increase or further improve the good quality, value or status of "
               "somebody/something",
    "overcome": "to succeed in dealing with or controlling a problem that has been "
                "preventing you from achieving something",
    "resolution": "the act of solving or settling a problem, argument, etc.",
    "mitigation": "a reduction in how unpleasant, serious, etc. something is",
    "easy": "(via ease, verb) to make something easier",
    "ease": "to become less unpleasant, painful or severe; to make something less "
            "unpleasant, etc. / to make something easier",
    "alleviate": "to make something less severe",
    "settle": "to put an end to an argument or a disagreement",
    "remedy": "to correct or improve something",
    "counter": "to do something to reduce or prevent the bad effects of something",
    "settlement": "an official agreement that ends an argument",
}

# Which anchor root each Table 4 form belongs to.
ROOT_OF: dict[str, str] = {}
for _root, _forms in OXFORD_LISTED_FORMS.items():
    for _f in _forms:
        ROOT_OF.setdefault(_f, _root)
ROOT_OF.update({
    "solutions": "solution",
    "improvements": "improvement",
    "resolutions": "resolution",
    "mitigations": "mitigation",
    "enhancements": "enhancement",
    "settlements": "settlement",
})

# How each anchor root connects back to mitigate or resolve.
ROOT_TRACE: dict[str, tuple[str, str, int, str]] = {
    # root -> (root_concept, source_relationship, oxford_hops, confidence)
    "mitigate": ("mitigate", "seed_term_named_in_paper", 0, "high"),
    "mitigation": ("mitigate", "oxford_noun_of_seed_term", 0, "high"),
    "resolve": ("resolve", "seed_term_named_in_paper", 0, "high"),
    "resolution": ("resolve", "oxford_synonym_xref_to_resolve", 1, "high"),
    "solve": ("resolve", "oxford_definition_overlap_with_resolve", 1, "high"),
    "solution": ("resolve", "oxford_definition_of_resolve_names_solution", 1, "high"),
    "overcome": ("resolve", "oxford_definition_overlap_with_solve", 2, "medium"),
    "fix": ("resolve", "oxford_definition_repair_or_correct", 2, "medium"),
    "help": ("mitigate", "oxford_definition_names_improve_and_easier", 2, "medium"),
    "improve": ("mitigate", "oxford_definition_reached_via_help_enhance_recovery", 2, "medium"),
    "improvement": ("mitigate", "oxford_noun_of_improve", 2, "medium"),
    "enhance": ("mitigate", "oxford_definition_names_improve", 3, "medium"),
    "enhancement": ("mitigate", "oxford_noun_of_enhance", 3, "low"),
    "recover": ("mitigate", "oxford_definition_return_to_normal_state", 3, "medium"),
    "recovery": ("mitigate", "oxford_definition_names_improving", 3, "medium"),
    "easy": ("mitigate", "oxford_chain_mitigate_alleviate_ease_easier", 3, "medium"),
    "alleviate": ("mitigate", "oxford_synonym_xref_on_mitigate", 1, "high"),
    "settle": ("resolve", "oxford_synonym_xref_on_resolve", 1, "high"),
    "ease": ("mitigate", "oxford_synonym_xref_on_alleviate", 2, "medium"),
    "relieve": ("mitigate", "oxford_synonym_xref_to_alleviate", 2, "low"),
    "reduce": ("mitigate", "oxford_synonym_xref_on_ease_verb", 3, "low"),
    "relax": ("mitigate", "oxford_synonym_xref_on_ease_verb", 3, "low"),
    "remedy": ("resolve", "oxford_synonym_xref_to_solution", 2, "low"),
    "settlement": ("resolve", "oxford_synonym_xref_on_resolution", 2, "low"),
    "counter": ("paper_sensitivity", "named_in_paper_table_10_column_5", -1, "n/a"),
    "absorb": ("paper_sensitivity", "named_in_paper_table_10_column_5", -1, "n/a"),
    "dissolve": ("paper_sensitivity", "named_in_paper_table_10_column_5", -1, "n/a"),
    "dilute": ("paper_sensitivity", "named_in_paper_table_10_column_5", -1, "n/a"),
}

# Roots whose Oxford-printed forms enter the conservative baseline.
BASELINE_ROOTS = [
    "mitigate", "mitigation", "resolve", "resolution", "help", "solve", "solution",
    "improve", "improvement", "fix", "recover", "recovery", "enhance", "overcome",
    "easy",
    # The two direct Oxford synonym cross-references on the paper's seed terms.
    "alleviate", "settle",
]

# Everything below is sensitivity-only and is never in the baseline.
SENSITIVITY_EXTRA: list[tuple[str, str]] = [
    # (term, note)
    ("resolutions", "regular plural of resolution; Oxford prints no plural, Table 4 does not show it"),
    ("mitigations", "regular plural of mitigation; Oxford prints no plural, Table 4 does not show it"),
    ("enhancement", "regular nominalisation of enhance; neither Oxford-printed nor in Table 4"),
    ("enhancements", "regular plural of enhancement; neither Oxford-printed nor in Table 4"),
    ("ease", "Oxford: mitigate -> alleviate -> ease. Two hops. Makes Table 4 easy/easier explicable"),
    ("eases", "Oxford-printed verb form of ease"),
    ("eased", "Oxford-printed verb form of ease"),
    ("easing", "Oxford-printed verb form of ease"),
    ("relieve", "Oxford: relieve -> alleviate, and alleviate is mitigate's synonym. Two hops"),
    ("relieves", "Oxford-printed verb form of relieve"),
    ("relieved", "Oxford-printed verb form of relieve"),
    ("relieving", "Oxford-printed verb form of relieve"),
    ("reduce", "Oxford: ease (verb) -> reduce. Three hops. Heavy non-resolution use in earnings calls"),
    ("reduces", "Oxford-printed verb form of reduce"),
    ("reduced", "Oxford-printed verb form of reduce"),
    ("reducing", "Oxford-printed verb form of reduce"),
    ("relax", "Oxford: ease (verb) -> relax. Three hops. Rare in a supply chain sense"),
    ("relaxes", "Oxford-printed verb form of relax"),
    ("relaxed", "Oxford-printed verb form of relax"),
    ("relaxing", "Oxford-printed verb form of relax"),
    ("remedy", "Oxford: remedy (noun) -> solution, and solution is a Table 4 term. Two hops"),
    ("remedies", "Oxford-printed form of remedy"),
    ("remedied", "Oxford-printed verb form of remedy"),
    ("remedying", "Oxford-printed verb form of remedy"),
    ("settlement", "Oxford: resolution -> settlement. In earnings calls this is usually a legal "
                   "or cash settlement, the same context problem that made Hassan et al. (2019) "
                   "drop question/unknown/venture/prospect"),
    ("settlements", "regular plural of settlement; same context problem"),
    ("counter", "paper Table 10 Column (5) expanded resolution keyword"),
    ("counters", "Oxford-printed verb form of counter"),
    ("countered", "Oxford-printed verb form of counter"),
    ("countering", "Oxford-printed verb form of counter"),
    ("absorb", "paper Table 10 Column (5) expanded resolution keyword"),
    ("absorbs", "Oxford-printed verb form of absorb"),
    ("absorbed", "Oxford-printed verb form of absorb"),
    ("absorbing", "Oxford-printed verb form of absorb"),
    ("dissolve", "paper Table 10 Column (5) expanded resolution keyword"),
    ("dissolves", "Oxford-printed verb form of dissolve"),
    ("dissolved", "Oxford-printed verb form of dissolve"),
    ("dissolving", "Oxford-printed verb form of dissolve"),
    ("dilute", "paper Table 10 Column (5) expanded resolution keyword"),
    ("dilutes", "Oxford-printed verb form of dilute"),
    ("diluted", "Oxford-printed verb form of dilute"),
    ("diluting", "Oxford-printed verb form of dilute"),
]


def build() -> dict:
    anchor: list[str] = []
    seen = set()
    for _slot, term, _freq in TABLE_4_SLOTS:
        if term not in seen:
            seen.add(term)
            anchor.append(term)

    freq_of = {term: freq for _s, term, freq in TABLE_4_SLOTS}

    baseline = list(anchor)
    for root in BASELINE_ROOTS:
        for form in OXFORD_LISTED_FORMS[root]:
            if form not in seen:
                seen.add(form)
                baseline.append(form)

    baseline_set = set(baseline)
    expanded = []
    for term, _note in SENSITIVITY_EXTRA:
        if term in baseline_set:
            raise SystemExit(f"sensitivity term {term!r} is already in the baseline")
        expanded.append(term)

    sens_note = dict(SENSITIVITY_EXTRA)
    rows = []
    for term in baseline + expanded:
        root = ROOT_OF.get(term, term)
        concept, root_relationship, hops, root_confidence = ROOT_TRACE[root]
        in_anchor = term in anchor
        in_baseline = term in baseline_set
        is_headword = term == root

        note_bits = []
        if in_anchor:
            note_bits.append("printed in Table 4")
            relationship = root_relationship
            confidence = "high"
        elif in_baseline:
            note_bits.append(f"Oxford prints this form in the '{root}' entry")
            relationship = (root_relationship if is_headword
                            else f"oxford_printed_form_of_{root}")
            # An Oxford-printed form is no better supported than its root.
            confidence = root_confidence
        else:
            note_bits.append(sens_note[term])
            relationship = (root_relationship if is_headword
                            else f"unattested_regular_form_of_{root}"
                            if hops >= 0 else root_relationship)
            if hops < 0:
                # counter/absorb/dissolve/dilute come from the paper, not Oxford.
                relationship = root_relationship
                confidence = "n/a_paper_declared_sensitivity"
            else:
                confidence = "low"

        if hops >= 0:
            note_bits.append(f"{hops} Oxford synonym hop(s) from mitigate/resolve")
        else:
            note_bits.append("not traced to an Oxford synonym of mitigate or resolve")

        rows.append({
            "term": term,
            "paper_table_4_frequency": freq_of.get(term, ""),
            "root_concept": concept,
            "oxford_source": OALD,
            "source_relationship": relationship,
            "confidence": confidence,
            "baseline_inclusion": "TRUE" if in_baseline else "FALSE",
            "sensitivity_only": "FALSE" if in_baseline else "TRUE",
            "notes": "; ".join(note_bits),
        })

    return {
        "anchor": anchor,
        "baseline": baseline,
        "expanded": expanded,
        "rows": rows,
        "freq_of": freq_of,
    }


def write_term_file(path: Path, terms: list[str]) -> None:
    """One lowercase term per line, nothing else.

    No comment header and no build date. These files are loaded by a strict
    validator in ``calculate_supply_chain_transcript_scores.py`` and are hashed
    in ``source_manifest.json``, so their bytes must be a pure function of the
    term list. The documentation lives in README.md and resolution_terms.csv.
    """
    path.write_text("\n".join(terms) + "\n")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    built = build()
    anchor, baseline, expanded, rows = (
        built["anchor"], built["baseline"], built["expanded"], built["rows"]
    )

    write_term_file(HERE / "resolution_terms_paper_anchor.txt", anchor)
    write_term_file(HERE / "resolution_terms_conservative_baseline.txt", baseline)
    write_term_file(HERE / "resolution_terms_expanded_sensitivity.txt", expanded)

    # resolution_terms.csv
    fields = ["term", "paper_table_4_frequency", "root_concept", "oxford_source",
              "source_relationship", "confidence", "baseline_inclusion",
              "sensitivity_only", "notes"]
    with (HERE / "resolution_terms.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    # table_4_extraction.csv
    with (HERE / "table_4_extraction.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["printed_slot", "column", "row_in_column", "keyword",
                    "published_frequency", "is_duplicate_of_slot",
                    "visually_verified", "correction_applied"])
        for slot, term, freq in TABLE_4_SLOTS:
            col = (slot - 1) // 10 + 1
            row_in_col = (slot - 1) % 10 + 1
            dup = ""
            if slot in DUPLICATE_SLOTS:
                dup = str(slot - 2)
            w.writerow([slot, col, row_in_col, term, freq, dup, "yes",
                        "none: rendered page matches the text layer character for character"])

    print(f"anchor      {len(anchor)} terms")
    print(f"baseline    {len(baseline)} terms ({len(baseline) - len(anchor)} beyond the anchor)")
    print(f"expanded    {len(baseline) + len(expanded)} terms "
          f"({len(expanded)} sensitivity-only)")
    print(f"rows        {len(rows)}")


if __name__ == "__main__":
    main()
