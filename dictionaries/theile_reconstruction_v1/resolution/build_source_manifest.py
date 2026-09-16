"""Write source_manifest.json and oxford_evidence.json.

Records what was retrieved, when, from where, and what could not be retrieved.
The Oxford Thesaurus of English is the product that would settle the
reconstruction and it is paywalled, so the manifest records the failed attempts
as first-class evidence.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
# Fixed source/build date. Generated files in this directory are hashed in
# source_manifest.json, so none of them may carry a runtime date.
SOURCE_DATE = "2026-09-16"
RETRIEVED = SOURCE_DATE

PDF = REPO / "source_research_paper" / (
    "theile-et-al-2026-supply-chain-risk-and-resolution-"
    "an-empirical-study-of-stock-market-reactions.pdf"
)

OALD_BASE = "https://www.oxfordlearnersdictionaries.com/definition/english/"

# Verbatim extracts from the Oxford Advanced Learner's Dictionary entries,
# retrieved 2026-09-16.  Only the fields the reconstruction relies on.
OXFORD_EVIDENCE = {
    "mitigate": {
        "url": OALD_BASE + "mitigate",
        "part_of_speech": "verb",
        "definitions": ["to make something less harmful, serious, etc."],
        "synonym_cross_references": ["alleviate"],
        "printed_inflected_forms": ["mitigate", "mitigates", "mitigated", "mitigating"],
    },
    "resolve": {
        "url": OALD_BASE + "resolve",
        "part_of_speech": "verb",
        "definitions": [
            "to find an acceptable solution to a problem or difficulty",
            "to make a definite decision to do something",
            "(of a committee, meeting, etc.) to reach a decision by means of a formal vote",
        ],
        "synonym_cross_references": ["settle"],
        "printed_inflected_forms": ["resolve", "resolves", "resolved", "resolving"],
    },
    "alleviate": {
        "url": OALD_BASE + "alleviate",
        "part_of_speech": "verb",
        "definitions": ["to make something less severe"],
        "synonym_cross_references": ["ease"],
        "printed_inflected_forms": ["alleviate", "alleviates", "alleviated", "alleviating"],
    },
    "settle": {
        "url": OALD_BASE + "settle",
        "part_of_speech": "verb",
        "definitions": ["to put an end to an argument or a disagreement",
                        "to decide or arrange something finally"],
        "synonym_cross_references": [],
        "printed_inflected_forms": ["settle", "settles", "settled", "settling"],
    },
    "ease (verb)": {
        "url": OALD_BASE + "ease_2",
        "part_of_speech": "verb",
        "definitions": [
            "to become less unpleasant, painful or severe; to make something less unpleasant, etc.",
            "to make something easier",
        ],
        "synonym_cross_references": ["alleviate", "relax", "reduce"],
        "printed_inflected_forms": ["ease", "eases", "eased", "easing"],
    },
    "resolution": {
        "url": OALD_BASE + "resolution",
        "part_of_speech": "noun",
        "definitions": ["a definite decision to do or not to do something",
                        "the act of solving or settling a problem, argument, etc."],
        "synonym_cross_references": ["resolve", "settlement"],
        "printed_inflected_forms": ["resolution"],
    },
    "mitigation": {
        "url": OALD_BASE + "mitigation",
        "part_of_speech": "noun",
        "definitions": ["a reduction in how unpleasant, serious, etc. something is"],
        "synonym_cross_references": [],
        "printed_inflected_forms": ["mitigation"],
    },
    "help": {
        "url": OALD_BASE + "help",
        "part_of_speech": "verb",
        "definitions": [
            "to make it easier or possible for somebody to do something by doing something "
            "for them or by giving them something that they need",
            "to improve a situation; to make it easier for something to happen",
        ],
        "synonym_cross_references": [],
        "printed_inflected_forms": ["help", "helps", "helped", "helping"],
    },
    "solve": {
        "url": OALD_BASE + "solve",
        "part_of_speech": "verb",
        "definitions": ["to find a way of dealing with a problem or difficult situation",
                        "to find the correct answer or explanation for something"],
        "synonym_cross_references": [],
        "printed_inflected_forms": ["solve", "solves", "solved", "solving"],
    },
    "solution": {
        "url": OALD_BASE + "solution",
        "part_of_speech": "noun",
        "definitions": ["a way of solving a problem or dealing with a difficult situation"],
        "synonym_cross_references": ["answer"],
        "printed_inflected_forms": ["solution"],
    },
    "improve": {
        "url": OALD_BASE + "improve",
        "part_of_speech": "verb",
        "definitions": ["to become better than before; to make something/somebody better than before"],
        "synonym_cross_references": [],
        "printed_inflected_forms": ["improve", "improves", "improved", "improving"],
    },
    "improvement": {
        "url": OALD_BASE + "improvement",
        "part_of_speech": "noun",
        "definitions": ["the act of making something better; the process of something becoming better"],
        "synonym_cross_references": [],
        "printed_inflected_forms": ["improvement"],
    },
    "fix": {
        "url": OALD_BASE + "fix",
        "part_of_speech": "verb",
        "definitions": ["to repair or correct something",
                        "to decide on a date, a time, an amount, etc. for something"],
        "synonym_cross_references": ["set"],
        "printed_inflected_forms": ["fix", "fixes", "fixed", "fixing"],
    },
    "recover": {
        "url": OALD_BASE + "recover",
        "part_of_speech": "verb",
        "definitions": [
            "to get well again after being ill, hurt, etc.",
            "to return to a normal state after an unpleasant or unusual experience or a "
            "period of difficulty",
        ],
        "synonym_cross_references": ["recoup", "regain"],
        "printed_inflected_forms": ["recover", "recovers", "recovered", "recovering"],
    },
    "recovery": {
        "url": OALD_BASE + "recovery",
        "part_of_speech": "noun",
        "definitions": ["the process of becoming well again after an illness or injury",
                        "the process of improving or becoming stronger again"],
        "synonym_cross_references": [],
        "printed_inflected_forms": ["recovery", "recoveries"],
    },
    "enhance": {
        "url": OALD_BASE + "enhance",
        "part_of_speech": "verb",
        "definitions": ["to increase or further improve the good quality, value or status "
                        "of somebody/something"],
        "synonym_cross_references": [],
        "printed_inflected_forms": ["enhance", "enhances", "enhanced", "enhancing"],
    },
    "overcome": {
        "url": OALD_BASE + "overcome",
        "part_of_speech": "verb",
        "definitions": ["to succeed in dealing with or controlling a problem that has been "
                        "preventing you from achieving something"],
        "synonym_cross_references": ["overwhelm"],
        "printed_inflected_forms": ["overcome", "overcomes", "overcame", "overcoming"],
    },
    "easy": {
        "url": OALD_BASE + "easy_1",
        "part_of_speech": "adjective",
        "definitions": ["not difficult; done or obtained without a lot of effort or problems"],
        "synonym_cross_references": ["easy-going"],
        "printed_inflected_forms": ["easy", "easier", "easiest"],
    },
    "relieve": {
        "url": OALD_BASE + "relieve",
        "part_of_speech": "verb",
        "definitions": ["to remove or reduce an unpleasant feeling or pain"],
        "synonym_cross_references": ["alleviate"],
        "printed_inflected_forms": ["relieve", "relieves", "relieved", "relieving"],
    },
    "reduce": {
        "url": OALD_BASE + "reduce",
        "part_of_speech": "verb",
        "definitions": ["to make something less or smaller in size, quantity, price, etc."],
        "synonym_cross_references": [],
        "printed_inflected_forms": ["reduce", "reduces", "reduced", "reducing"],
    },
    "relax": {
        "url": OALD_BASE + "relax",
        "part_of_speech": "verb",
        "definitions": ["to rest while you are doing something enjoyable",
                        "to make rules, restrictions, etc. less severe"],
        "synonym_cross_references": ["unwind"],
        "printed_inflected_forms": ["relax", "relaxes", "relaxed", "relaxing"],
    },
    "remedy (noun)": {
        "url": OALD_BASE + "remedy",
        "part_of_speech": "noun",
        "definitions": ["a way of dealing with or improving an unpleasant or difficult situation"],
        "synonym_cross_references": ["redress", "solution"],
        "printed_inflected_forms": ["remedy", "remedies"],
    },
    "remedy (verb)": {
        "url": OALD_BASE + "remedy_2",
        "part_of_speech": "verb",
        "definitions": ["to correct or improve something"],
        "synonym_cross_references": ["right"],
        "printed_inflected_forms": ["remedy", "remedies", "remedied", "remedying"],
    },
    "counter (verb)": {
        "url": OALD_BASE + "counter_2",
        "part_of_speech": "verb",
        "definitions": ["to do something to reduce or prevent the bad effects of something"],
        "synonym_cross_references": ["counteract"],
        "printed_inflected_forms": ["counter", "counters", "countered", "countering"],
    },
    "absorb": {
        "url": OALD_BASE + "absorb",
        "part_of_speech": "verb",
        "definitions": ["to take in a liquid, gas or other substance from the surface or space around"],
        "synonym_cross_references": ["engross", "take in"],
        "printed_inflected_forms": ["absorb", "absorbs", "absorbed", "absorbing"],
    },
    "dissolve": {
        "url": OALD_BASE + "dissolve",
        "part_of_speech": "verb",
        "definitions": ["to mix with a liquid and become part of it"],
        "synonym_cross_references": [],
        "printed_inflected_forms": ["dissolve", "dissolves", "dissolved", "dissolving"],
    },
    "dilute": {
        "url": OALD_BASE + "dilute",
        "part_of_speech": "verb",
        "definitions": ["to make a liquid weaker by adding water or another liquid to it"],
        "synonym_cross_references": ["water down"],
        "printed_inflected_forms": ["dilute", "dilutes", "diluted", "diluting"],
    },
    "settlement": {
        "url": OALD_BASE + "settlement",
        "part_of_speech": "noun",
        "definitions": ["an official agreement that ends an argument"],
        "synonym_cross_references": [],
        "printed_inflected_forms": ["settlement"],
    },
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    (HERE / "oxford_evidence.json").write_text(
        json.dumps({"retrieved": RETRIEVED,
                    "product": "Oxford Advanced Learner's Dictionary, 10th edition",
                    "publisher": "Oxford University Press",
                    "site": "oxfordlearnersdictionaries.com",
                    "entries": OXFORD_EVIDENCE}, indent=2) + "\n"
    )

    manifest = {
        "artifact": "dictionaries/theile_reconstruction_v1/resolution",
        "source_date": SOURCE_DATE,
        "purpose": (
            "Reconstruct the resolution library (the paper's 'M library') of "
            "Theile et al. (2026) without author-provided files."
        ),
        "primary_specification": {
            "file": "resolution_terms_conservative_baseline.txt",
            "terms": 55,
            "role": (
                "The single primary Resolution specification. The scoring script "
                "loads it by default and emits exactly one Resolution measure from "
                "it. Overrides are marked non-primary in the run manifest."
            ),
            "sensitivity_artifacts": [
                "resolution_terms_paper_anchor.txt",
                "resolution_terms_expanded_sensitivity.txt",
                "resolution_terms_overlap_sensitivity.txt",
            ],
        },
        "primary_risk_library": {
            "file": "dictionaries/theile_reconstruction_v1/risk/"
                    "risk_terms_reconstructed_full.txt",
            "terms": 161,
            "role": (
                "Used as the risk library in validation and scoring. The 144-term "
                "Table 3 list in table_3_risk_terms_reference.csv is a record of the "
                "published table, not a specification."
            ),
        },
        "validation_scope": {
            "tracked_source_validation": [
                "validation_report.md", "validation_run.json", "overlap_report.csv",
            ],
            "tracked_source_validation_note": (
                "Reproducible on a clean checkout. Inputs are the paper's published "
                "tables, the committed dictionaries, and the committed synthetic "
                "supply-chain fixture."
            ),
            "archived_local_diagnostic": "outputs/resolution_validation/ (gitignored)",
            "archived_local_diagnostic_note": (
                "Zero rates and matched-term counts over real transcripts. Not PR "
                "validation and not reproducible from this repository: it depends on "
                "earnings_call_transcripts.csv and "
                "artifacts/sec_10k_supply_chain/terms.jsonl, both gitignored local "
                "artifacts that other work here regenerates, and on a provisional "
                "supply-chain library and firm universe. No number in it is evidence "
                "that this dictionary is correct."
            ),
        },
        "supply_chain_overlap": (
            "Deferred. The final reconstructed supply-chain vocabulary does not "
            "exist yet, so the overlap between this dictionary and the supply-chain "
            "library cannot be settled. 'solution' and 'solutions' stay in the "
            "primary dictionary; resolution_terms_overlap_sensitivity.txt holds the "
            "variant that drops them, as a predeclared sensitivity run."
        ),
        "outcome_blind": (
            "No CAR, return, or regression output was consulted at any point. "
            "Term selection used Table 4, Oxford dictionary entries, and the "
            "paper's prose only."
        ),

        "primary_source": {
            "citation": (
                "Theile, O., et al. (2026). Supply Chain Risk and Resolution: An "
                "Empirical Study of Stock Market Reactions. Production and Operations "
                "Management, 35(8), 2981-3001."
            ),
            "local_path": str(PDF.relative_to(REPO)),
            "sha256": sha256(PDF) if PDF.exists() else None,
            "pages_used": {
                "Table 1 (supply chain seed terms)": "journal p. 2985, PDF p. 5",
                "Table 2 (top 30 supply chain keywords)": "journal p. 2986, PDF p. 6",
                "Table 3 (risk keywords)": "journal p. 2987, PDF p. 7",
                "Table 4 (top 30 resolution keywords)": "journal p. 2988, PDF p. 8",
                "Table 10 Col (5) (expanded keywords)": "journal p. 2995, PDF p. 15",
            },
            "definition_of_M_library": (
                "'The M library consists of the terms mitigate and resolve as well as "
                "their synonyms from the Oxford dictionary.' (journal p. 2986)"
            ),
            "extraction_method": (
                "pdftotext -layout for the text layer, then pdftoppm -r 200/250 -png "
                "to render page 8 and read Table 4 off the rendered page. Both agree "
                "character for character, including the duplicated slots."
            ),
        },

        "oxford_sources": {
            "retrieved": [
                {
                    "product": "Oxford Advanced Learner's Dictionary, 10th edition",
                    "publisher": "Oxford University Press",
                    "access": "free web edition",
                    "base_url": OALD_BASE,
                    "retrieval_date": RETRIEVED,
                    "entries_retrieved": sorted(OXFORD_EVIDENCE),
                    "fields_extracted": [
                        "definitions",
                        "synonym cross-references printed in the entry ('synonym X')",
                        "inflected forms printed in the Verb Forms table or inflection bracket",
                    ],
                    "limitations": [
                        "OALD is a learner's dictionary. It prints at most one or two "
                        "synonym cross-references per sense, not a thesaurus run.",
                        "It does not print regular noun plurals, so absence of a plural "
                        "here is not evidence the plural is wrong.",
                        "It has no Word Family box on these entries.",
                    ],
                    "local_extract": "oxford_evidence.json",
                },
            ],
            "attempted_and_unavailable": [
                {
                    "product": "Oxford Thesaurus of English / Oxford Dictionary of English "
                               "synonym data (Oxford Dictionaries Premium)",
                    "url": "https://premium.oxforddictionaries.com/thesaurus/english/mitigate",
                    "retrieval_date": RETRIEVED,
                    "result": "HTTP 302 to an OAuth login. Subscription required.",
                    "why_it_matters": (
                        "This is the product whose synonym runs most plausibly generated "
                        "the paper's library. Without it the tail of the M library cannot "
                        "be recovered."
                    ),
                },
                {
                    "product": "Oxford English Dictionary (oed.com) and its Historical Thesaurus",
                    "url": "https://www.oed.com/dictionary/mitigate_v",
                    "retrieval_date": RETRIEVED,
                    "result": "HTTP 200 but redirected to the unauthenticated home page. "
                              "Subscription required.",
                },
                {
                    "product": "Lexico / en.oxforddictionaries.com thesaurus pages, the "
                               "surface Hassan et al. (2019) most likely used",
                    "url": "https://www.lexico.com/synonym/mitigate",
                    "retrieval_date": RETRIEVED,
                    "result": "Site shut down in 2022. DNS/connection failure. Internet "
                              "Archive was returning 'Temporarily Offline' on the same day, "
                              "so no archived capture could be read either.",
                },
                {
                    "product": "Oxford Reference (Concise Oxford Thesaurus etc.)",
                    "url": "https://www.oxfordreference.com/search?q=mitigate",
                    "retrieval_date": RETRIEVED,
                    "result": "HTTP 302, subscription required.",
                },
                {
                    "product": "Apple New Oxford American Dictionary / Oxford American "
                               "Writer's Thesaurus bundled with macOS",
                    "result": "Not installed on this machine; no .dictionary bundle found.",
                },
            ],
            "edition_uncertainty": (
                "The paper says 'the Oxford dictionary' and names no product, edition, "
                "or retrieval date. Hassan et al. (2019), whose approach the paper "
                "follows for the risk library, say only 'the Oxford dictionary' as well. "
                "The reconstruction therefore cannot be edition-exact and does not claim "
                "to be."
            ),
        },

        "corroborating_source": {
            "citation": (
                "Hassan, T.A., Hollander, S., van Lent, L., Tahoun, A. (2019). Firm-Level "
                "Political Risk: Measurement and Effects. Quarterly Journal of Economics, "
                "134(4), 2135-2202. NBER WP 24029 rev1."
            ),
            "url": "https://www.nber.org/system/files/working_papers/w24029/revisions/w24029.rev1.pdf",
            "retrieval_date": RETRIEVED,
            "why_used": (
                "Theile et al. build their risk library from Hassan et al.'s Oxford "
                "synonym list. Hassan's Appendix Table 3 is therefore a worked example of "
                "what 'Oxford dictionary synonyms' produced in practice. It is used here "
                "only to calibrate the authors' inflection policy, never to add a "
                "resolution term."
            ),
            "what_it_shows": [
                "Oxford-derived libraries carry several inflections of a headword "
                "(risk/risks/risky/riskier/riskiest/risked/risking/riskiness) but not "
                "blanket regular inflection: 'threat' appears without 'threats', "
                "'hazard' without 'hazards', 'peril' without 'perils'.",
                "Hassan et al. dropped 'question', 'questions', 'unknown', 'venture' and "
                "'prospect' from the Oxford list because they mean something else on an "
                "earnings call. That is the precedent for holding 'settlement' out of the "
                "baseline here.",
            ],
        },

        "tools": {
            "pdftotext": subprocess.run(["pdftotext", "-v"], capture_output=True,
                                        text=True).stderr.strip().splitlines()[0],
            "pdftoppm": subprocess.run(["pdftoppm", "-v"], capture_output=True,
                                       text=True).stderr.strip().splitlines()[0],
        },

        "table_4_findings": {
            "printed_slots": 30,
            "distinct_keywords": 28,
            "duplicated_slots": {
                "24": "repeats slot 22, 'enhance' 591",
                "25": "repeats slot 23, 'recover' 566",
            },
            "duplication_is_in_the_typeset_page": (
                "Confirmed by rendering PDF page 8 at 250 dpi with pdftoppm and reading "
                "the third column off the image. The text layer and the rendered page "
                "agree. No OCR correction was applied because none was needed."
            ),
            "unrecoverable_entries": (
                "Slots 24 and 25 should have carried the 24th and 25th most frequent "
                "keywords. The column is printed in descending order, so their "
                "frequencies lie between 566 (slot 23) and 553 (slot 26): both are in "
                "the range 554 to 566. The words themselves cannot be recovered from "
                "the published paper."
            ),
            "frequency_semantics": (
                "Table 2's note says frequency is 'the count of occurrences relevant to "
                "the construction of the SCRisk measure', that is, occurrences that "
                "satisfied the proximity conditions. Table 4 frequencies are therefore "
                "window-filtered counts, not raw corpus counts."
            ),
        },

        "variants": {
            "resolution_terms_paper_anchor.txt": "28 terms. Distinct Table 4 keywords only.",
            "resolution_terms_conservative_baseline.txt":
                "55 terms. Anchor plus Oxford-printed inflected forms of each anchor root, "
                "plus 'alleviate' and 'settle' with their Oxford-printed verb forms. "
                "PRIMARY: the only dictionary the production pipeline loads.",
            "resolution_terms_expanded_sensitivity.txt":
                "42 sensitivity-only terms, 97 when combined with the baseline. "
                "Predeclared robustness specification.",
            "resolution_terms_overlap_sensitivity.txt":
                "53 terms. The primary minus 'solution' and 'solutions'. Predeclared "
                "robustness specification held ready for when the reconstructed "
                "supply-chain vocabulary makes the overlap question answerable.",
        },

        "outputs": {},
    }

    for name in ["resolution_terms_paper_anchor.txt",
                 "resolution_terms_conservative_baseline.txt",
                 "resolution_terms_expanded_sensitivity.txt",
                 "resolution_terms.csv",
                 "table_4_extraction.csv",
                 "table_3_risk_terms_reference.csv",
                 "resolution_terms_overlap_sensitivity.txt",
                 "oxford_evidence.json",
                 "validation_report.md",
                 "validation_run.json",
                 "overlap_report.csv",
                 "fixtures/synthetic_supply_chain_library.jsonl"]:
        p = HERE / name
        if p.exists():
            manifest["outputs"][name] = {"sha256": sha256(p), "bytes": p.stat().st_size}

    (HERE / "source_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("wrote source_manifest.json and oxford_evidence.json")


if __name__ == "__main__":
    main()
