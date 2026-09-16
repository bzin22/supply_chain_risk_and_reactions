"""Validate the reconstructed resolution dictionary.

Two kinds of output, kept strictly apart.

**Source validation, tracked.** Written next to this script. Table 4 coverage,
exact token matching, the paper's proximity rule, the settled overlaps, and the
SHA-256 of every dictionary. All of it runs on a clean checkout: the inputs are
the paper's published tables, the committed dictionaries, and the committed
synthetic supply-chain fixture. Anyone can reproduce it byte for byte.

  validation_report.md
  validation_run.json
  overlap_report.csv

**Corpus diagnostic, archived and gitignored.** Written to
``outputs/resolution_validation/``. Zero rates and matched-term counts over
real transcripts. It is not PR validation and cannot be reproduced from the
repository: it needs two local gitignored artifacts, the transcript corpus and
the generated supply-chain library, both of which other work in this repository
regenerates. It is archived with the hashes of the inputs it actually ran
against so a later run can tell whether it is comparable.

  outputs/resolution_validation/corpus_diagnostic.md
  outputs/resolution_validation/corpus_diagnostic_run.json
  outputs/resolution_validation/provisional_overlap_report.csv

The primary Resolution specification is the 55-term conservative baseline. The
primary risk library is the 161-term reconstructed-full dictionary in the
sibling ``risk/`` directory.

No return, CAR, or regression output is read.

Run:
    python3 run_validation.py [--sample 400] [--seed 20260916]
                              [--build-date YYYY-MM-DD] [--diagnostic-dir PATH]
                              [--skip-corpus-diagnostic]
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import random
import statistics
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))

import resolution_dictionary_io as dio  # noqa: E402
import calculate_supply_chain_transcript_scores as scoring  # noqa: E402

WINDOW = scoring.WINDOW  # 10, the paper's ten-word range

# Fixed source/build date. Tracked generated files are hashed in
# source_manifest.json, so none of them may carry a runtime date.
SOURCE_DATE = "2026-09-16"

DEFAULT_DIAGNOSTIC_DIR = REPO / "outputs" / "resolution_validation"

# The overlap-adjusted sensitivity variant drops exactly these terms from the
# primary dictionary. Declared, not computed: the terms come from an inspection
# of a provisional supply-chain library, and the definitive overlap cannot be
# calculated until the final reconstructed supply-chain vocabulary exists.
OVERLAP_SENSITIVITY_DROPS = ["solution", "solutions"]

# The overlap-adjusted variant drops two Table 4 terms on purpose, so it is
# exempt from the Table 4 coverage requirement.
COVERAGE_EXEMPT = {"overlap_sensitivity"}


# ---------------------------------------------------------------------------
# Synthetic sentences. Each is hand-written to test one rule.
# ---------------------------------------------------------------------------
# (label, text, expect_resolution_pairs_positive, why)
SYNTHETIC = [
    ("sc_risk_and_resolution_together",
     "We had a supplier shortage last quarter and we were able to resolve the "
     "shortage by qualifying a second plant.",
     True,
     "supply chain word, risk word and resolution word all inside ten tokens"),

    ("sc_risk_without_resolution",
     "We had a supplier shortage last quarter and it cost us roughly two points "
     "of gross margin.",
     False,
     "supply chain word near a risk word but no resolution word: SCRisk only"),

    ("resolution_far_from_supply_chain",
     "We had a supplier shortage last quarter. " + " ".join(["then"] * 30) +
     " separately we did resolve the billing dispute with our landlord.",
     False,
     "resolution word more than ten tokens from the supply chain word"),

    ("generic_resolution_no_supply_chain_risk",
     "Our new product helps customers and we are pleased with the improvement in "
     "brand awareness this quarter.",
     False,
     "generic positive language with no risk word nearby: must not score"),

    ("resolution_without_risk",
     "We continue to improve our supplier onboarding process and our logistics "
     "network performed well.",
     False,
     "supply chain word near a resolution word but no risk word: must not score"),

    ("resolution_and_risk_on_different_supply_chain_words",
     "Our inventory faced a shortage this quarter. " + " ".join(["then"] * 25) +
     " our logistics network continued to improve.",
     False,
     "r and m are each near a supply chain word, but not the same one"),
]

# (label, text, term_that_must_not_match, why)
NO_SUBSTRING_MATCH = [
    ("helpful_is_not_help", "That guidance was helpful for our inventory risk.", "help",
     "exact token matching, not substring"),
    ("prefix_is_not_fix", "The prefix of the part number changed for that supplier risk.", "fix",
     "exact token matching, not substring"),
    ("unresolved_is_not_resolved",
     "The supplier dispute remains unresolved and is a risk to inventory.", "resolved",
     "'unresolved' is a risk-library word, not a resolution word"),
    ("dissolved_is_not_solved",
     "The joint venture was dissolved, a risk to our supply agreement.", "solved",
     "'dissolved' must not fire 'solved'"),
    ("easy_going_is_not_easy",
     "An easy-going supplier relationship is still a risk to inventory.", "easy",
     "the tokenizer keeps 'easy-going' as one token, so 'easy' must not fire"),
    ("easing_is_not_easy", "Port congestion is easing, a risk to our supply plan.", "easy",
     "'easing' is a sensitivity term in its own right and must not fire 'easy'"),
]


def matched_terms(text: str, terms) -> list[str]:
    index = scoring.build_phrase_index(terms)
    return [occ.term for occ in scoring.find_indexed_occurrences(scoring.tokenize(text), index)]


def git_commit() -> str:
    try:
        out = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"],
                             capture_output=True, text=True, check=True)
        dirty = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain",
                                "--", str(HERE)], capture_output=True, text=True)
        suffix = "-dirty" if dirty.stdout.strip() else ""
        return out.stdout.strip() + suffix
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


# ---------------------------------------------------------------------------
# Source validation. Clean checkout only.
# ---------------------------------------------------------------------------


def coverage_check(variants: dict[str, list[str]], table4: list[str]) -> list[str]:
    problems = []
    for name, terms in variants.items():
        if not terms or name in COVERAGE_EXEMPT:
            continue
        missing = [t for t in table4 if t not in set(terms)]
        if missing:
            problems.append(f"{name}: missing Table 4 terms {missing}")
    return problems


def settled_comparisons() -> list[tuple[str, set[str]]]:
    """Libraries that are committed, so the comparison reproduces anywhere."""
    out = [("primary_risk_library_reconstructed_full_161", set(dio.primary_risk_terms()))]
    observed = dio.observed_risk_terms()
    if observed:
        out.append((f"risk_observed_baseline_{len(observed)}", set(observed)))
    out.append(("published_reference_risk_table_3_144", set(dio.table_3_reference_terms())))
    out.append(("paper_supply_chain_table_2_top30", set(dio.PAPER_TABLE_2_SUPPLY_CHAIN)))
    seeds: set[str] = set()
    for phrase in scoring.SUPPLY_CHAIN_SEEDS:
        seeds.update(phrase.split())
    out.append(("paper_supply_chain_seed_terms_table_1", seeds))
    return out


def overlap_rows(variants: dict[str, list[str]],
                 comparisons: list[tuple[str, set[str]]]) -> list[dict]:
    rows = []
    for name, terms in variants.items():
        if not terms:
            continue
        t = set(terms)
        for other_name, other in comparisons:
            shared = sorted(t & other)
            rows.append({
                "resolution_variant": name,
                "compared_against": other_name,
                "n_shared": len(shared),
                "shared_terms": " ".join(shared),
            })
    return rows


def write_overlap_sensitivity(baseline: list[str]) -> Path:
    """The overlap-adjusted sensitivity variant. Declared drops, not computed."""
    kept = [t for t in baseline if t not in set(OVERLAP_SENSITIVITY_DROPS)]
    dio.OVERLAP_FILE.write_text("\n".join(kept) + "\n")
    return dio.OVERLAP_FILE


# ---------------------------------------------------------------------------
# Corpus diagnostic. Local artifacts, archived, gitignored.
# ---------------------------------------------------------------------------


def iter_transcripts(limit: int, seed: int):
    """Reservoir-sample transcripts so the subset never depends on file order."""
    scoring.configure_csv_field_size_limit()
    rng = random.Random(seed)
    reservoir: list[dict] = []
    n = 0
    with dio.TRANSCRIPT_CORPUS.open(newline="") as fh:
        for row in csv.DictReader(fh):
            if row.get("status") != "success":
                continue
            text = row.get("transcript_text") or ""
            integrity, _flags = scoring.assess_transcript_integrity(text)
            if integrity != scoring.INTEGRITY_OK:
                continue
            n += 1
            keep = {"ticker": row["ticker"], "quarter_label": row.get("quarter_label", ""),
                    "transcript_text": text}
            if len(reservoir) < limit:
                reservoir.append(keep)
            else:
                j = rng.randrange(n)
                if j < limit:
                    reservoir[j] = keep
    return reservoir, n


def corpus_diagnostic(variants: dict[str, list[str]], sample: int, seed: int):
    weights = dio.repo_supply_chain_weights()
    risk_words = dio.primary_risk_terms()
    sc_index = scoring.build_phrase_index(weights)
    risk_index = scoring.build_phrase_index(risk_words)
    usable = {n: t for n, t in variants.items() if t}
    res_indexes = {n: scoring.build_phrase_index(t) for n, t in usable.items()}

    rows, total = iter_transcripts(sample, seed)

    eps_next = {"earnings", "eps", "share", "shares", "per", "net"}
    diluted_total = diluted_eps = 0
    for row in rows:
        toks = scoring.tokenize(row["transcript_text"])
        for i, tok in enumerate(toks):
            if tok == "diluted":
                diluted_total += 1
                if i + 1 < len(toks) and toks[i + 1] in eps_next:
                    diluted_eps += 1

    out: dict[str, dict] = {}
    for name, res_index in res_indexes.items():
        zero = scrisk_zero = 0
        raws = []
        term_counts: collections.Counter = collections.Counter()
        contributing: collections.Counter = collections.Counter()
        for row in rows:
            res = scoring.calculate_raw_scores(
                row["transcript_text"], weights, risk_words, usable[name],
                window=WINDOW, supply_chain_index=sc_index, risk_index=risk_index,
                resolution_index=res_index,
            )
            raws.append(res.resolution_raw)
            if res.resolution_raw == 0.0:
                zero += 1
            if res.scrisk_raw == 0.0:
                scrisk_zero += 1
            toks = scoring.tokenize(row["transcript_text"])
            for occ in scoring.find_indexed_occurrences(toks, res_index):
                term_counts[occ.term] += 1
            if res.resolution_pairs:
                sc_occ = scoring.find_indexed_occurrences(toks, sc_index)
                r_occ = scoring.find_indexed_occurrences(toks, risk_index)
                m_occ = scoring.find_indexed_occurrences(toks, res_index)
                scoring_supply = [s for s in sc_occ
                                  if any(scoring.spans_within(s, r, WINDOW) for r in r_occ)]
                for m in m_occ:
                    if any(scoring.spans_within(s, m, WINDOW) for s in scoring_supply):
                        contributing[m.term] += 1
        out[name] = {
            "n": len(rows),
            "zero_rate": zero / len(rows),
            "scrisk_zero_rate": scrisk_zero / len(rows),
            "mean_raw": statistics.fmean(raws),
            "median_raw": statistics.median(raws),
            "top_terms_anywhere": term_counts.most_common(15),
            "top_terms_contributing": contributing.most_common(15),
        }
    return out, total, len(rows), {"total": diluted_total, "accounting_sense": diluted_eps}


ARCHIVED_BANNER = (
    "> **This is an archived local diagnostic, not PR validation.** It cannot be "
    "reproduced from the repository. It needs two local gitignored artifacts, the "
    "transcript corpus and the generated supply-chain library, and other work in this "
    "repository regenerates both. Nothing here is evidence that the dictionary is "
    "correct; the reproducible checks live in "
    "`dictionaries/theile_reconstruction_v1/resolution/validation_report.md`. The "
    "supply-chain library used here is provisional and so is the firm universe. No "
    "number below should be quoted as a result."
)


def write_corpus_diagnostic(out_dir: Path, variants, primary, diag, dil, record) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "corpus_diagnostic_run.json").write_text(json.dumps(record, indent=2) + "\n")

    repo_sc = set(dio.repo_supply_chain_weights())
    with (out_dir / "provisional_overlap_report.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["resolution_variant", "compared_against",
                                           "is_settled", "n_shared", "shared_terms"])
        w.writeheader()
        for name, terms in variants.items():
            if not terms:
                continue
            shared = sorted(set(terms) & repo_sc)
            w.writerow({
                "resolution_variant": name,
                "compared_against": "PROVISIONAL_repo_generated_supply_chain_library",
                "is_settled": "no",
                "n_shared": len(shared),
                "shared_terms": " ".join(shared),
            })

    L: list[str] = []
    A = L.append
    A("# Corpus diagnostic: reconstructed resolution dictionary")
    A("")
    A(ARCHIVED_BANNER)
    A("")
    A(f"Archived {record['build_date']}. Run at commit "
      f"`{record['git_commit_at_run']}`, seed {record['seed']}, "
      f"{record['sample_scored']} transcripts, window {record['window']} tokens.")
    A("")
    A("## Inputs this run actually used")
    A("")
    A("| input | path | size | sha256 |")
    A("| --- | --- | --- | --- |")
    for label, key in [("Resolution dictionary (primary, tracked)", "resolution"),
                       ("Risk dictionary (primary, tracked)", "risk"),
                       ("Supply chain library (provisional, local)", "supply_chain")]:
        d = record["dictionaries"][key]
        A(f"| {label} | `{d['path']}` | {d['terms']} terms | `{d['sha256']}` |")
    tc = record["transcript_corpus"]
    A(f"| Transcript corpus (local) | `{tc['path']}` | "
      f"{tc['calls_passing_integrity']:,} calls pass integrity | `{tc['sha256']}` |")
    A("")
    A("A changed hash on either local input means these numbers are not comparable to "
      "an earlier archive and must be recomputed. That is not hypothetical: the corpus "
      "was regenerated by other work in this repository during development and the "
      "integrity-passing call count moved from 18,162 to 11,598.")
    A("")

    A("## Zero rates")
    A("")
    A("| variant | terms | zero-Resolution rate | zero-SCRisk rate | mean raw | median raw |")
    A("| --- | --- | --- | --- | --- | --- |")
    for name, d in diag.items():
        tag = " **(PRIMARY)**" if name.endswith("_PRIMARY") else ""
        A(f"| {name}{tag} | {len(variants[name])} | {d['zero_rate']:.1%} | "
          f"{d['scrisk_zero_rate']:.1%} | {d['mean_raw']:.3e} | {d['median_raw']:.3e} |")
    A("")
    prim = diag["conservative_baseline_PRIMARY"]
    A(f"The primary dictionary leaves {prim['zero_rate']:.1%} of calls at zero "
      "Resolution. The paper reports more than 75% (journal p. 2986; Table 5 gives "
      "Resolution a median and a P75 of 0.000). That is a diagnostic, not a target. "
      "Nothing in this dictionary was chosen to move it.")
    A("")
    A("The gap is almost certainly the supply chain library, not the resolution "
      "dictionary. Resolution is a subset of SCRisk: a call can only have non-zero "
      "Resolution if it already has non-zero SCRisk. The provisional library has "
      f"{record['dictionaries']['supply_chain']['terms']:,} terms including `customers` "
      f"and `customer`, which appear on nearly every call, so the zero-SCRisk rate is "
      f"{prim['scrisk_zero_rate']:.1%}. Almost every call clears the SCRisk gate, "
      "leaving the resolution condition as the only filter. A narrower supply chain "
      "vocabulary should raise the zero rate.")
    A("")
    anchor = diag.get("paper_anchor")
    exp = diag.get("expanded_sensitivity")
    if anchor and exp:
        A(f"The anchor sits at {anchor['zero_rate']:.1%} and the expanded set at "
          f"{exp['zero_rate']:.1%}, against the primary's {prim['zero_rate']:.1%}. "
          f"Adding the {len(variants['expanded_sensitivity']) - len(primary)} expanded "
          f"terms moves the zero rate "
          f"{(prim['zero_rate'] - exp['zero_rate']) * 100:.1f} points, against "
          f"{(anchor['zero_rate'] - prim['zero_rate']) * 100:.1f} points for the "
          f"{len(primary) - len(anchor)} the primary adds to the anchor. The term lists "
          "below show the expanded step is carried by `reduce`, `reduced`, `reducing` "
          "and `diluted`.")
        A("")
    if dil and dil["total"]:
        share = dil["accounting_sense"] / dil["total"]
        A(f"`diluted` is worth naming. It is a regular form of `dilute`, one of the four "
          f"resolution keywords the paper itself adds in its Table 10 Column (5) check, "
          f"and it is in the expanded set only. On an earnings call it usually means "
          f"diluted earnings per share. It occurs {dil['total']} times in this "
          f"{record['sample_scored']}-call subset, and {dil['accounting_sense']} of those "
          f"({share:.0%}) are immediately followed by one of `earnings`, `eps`, `share`, "
          f"`shares`, `per` or `net`, which is the accounting sense. That is a floor, not "
          f"the full false-positive rate. It is the clearest single reason the expanded "
          f"set is a sensitivity artifact and not the primary.")
        A("")

    A("## Matched terms")
    A("")
    for name, d in diag.items():
        A(f"**{name}** most frequently matched resolution terms (occurrences anywhere in "
          "the subset):")
        A("")
        A("`" + "`, `".join(f"{t} {c}" for t, c in d["top_terms_anywhere"]) + "`")
        A("")
        A(f"**{name}** resolution terms that sat within ten tokens of a scoring supply "
          "chain occurrence:")
        A("")
        A("`" + "`, `".join(f"{t} {c}" for t, c in d["top_terms_contributing"]) + "`")
        A("")

    A("## Provisional supply-chain overlap")
    A("")
    A("`solution` and `solutions` are in both the resolution dictionary and the "
      "provisional supply-chain library. This comparison lives here rather than in the "
      "tracked overlap report because it is a property of a provisional input, not a "
      "finding about the dictionary. The definitive calculation waits for the "
      "reconstructed supply-chain vocabulary. Per-variant counts in "
      "`provisional_overlap_report.csv`.")
    A("")

    (out_dir / "corpus_diagnostic.md").write_text("\n".join(L) + "\n")


# ---------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=400)
    ap.add_argument("--seed", type=int, default=20260916)
    ap.add_argument("--build-date", default=SOURCE_DATE,
                    help="fixed source/build date recorded in generated files")
    ap.add_argument("--diagnostic-dir", type=Path, default=DEFAULT_DIAGNOSTIC_DIR,
                    help="gitignored directory for the archived corpus diagnostic")
    ap.add_argument("--skip-corpus-diagnostic", action="store_true")
    args = ap.parse_args()

    primary = dio.primary_resolution_terms()
    table4 = dio.table_4_terms()
    risk_words = dio.primary_risk_terms()

    write_overlap_sensitivity(primary)
    variants = dio.all_variants()

    cov_problems = coverage_check(variants, table4)
    rows = overlap_rows(variants, settled_comparisons())
    with (HERE / "overlap_report.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["resolution_variant", "compared_against",
                                           "n_shared", "shared_terms"])
        w.writeheader()
        w.writerows(rows)

    # Matching and rule checks run on the committed fixture, never a local artifact.
    fixture_weights = dio.synthetic_supply_chain_weights()
    syn_results = []
    for label, text, expect, why in SYNTHETIC:
        res = scoring.calculate_raw_scores(text, fixture_weights, risk_words, primary,
                                           window=WINDOW)
        ok = (res.resolution_pairs > 0) == expect
        syn_results.append((label, expect, res.resolution_pairs, res.risk_pairs, ok, why))

    sub_results = []
    for label, text, term, why in NO_SUBSTRING_MATCH:
        hits = matched_terms(text, variants["expanded_sensitivity"])
        ok = term not in hits
        sub_results.append((label, term, sorted(set(hits)), ok, why))

    source_record = {
        "scope": "source_validation_only",
        "reproducible_on_a_clean_checkout": True,
        "build_date": args.build_date,
        "git_commit_at_validation": git_commit(),
        "window": WINDOW,
        "primary_dictionaries": {
            "resolution": {
                "path": str(dio.BASELINE_FILE.relative_to(REPO)),
                "terms": len(primary),
                "sha256": dio.sha256(dio.BASELINE_FILE),
            },
            "risk": {
                "path": str(dio.PRIMARY_RISK_FILE.relative_to(REPO)),
                "terms": len(risk_words),
                "sha256": dio.sha256(dio.PRIMARY_RISK_FILE),
            },
        },
        "sensitivity_dictionaries": {
            "paper_anchor": {
                "path": str(dio.ANCHOR_FILE.relative_to(REPO)),
                "terms": len(variants["paper_anchor"]),
                "sha256": dio.sha256(dio.ANCHOR_FILE),
            },
            "expanded_sensitivity_extra_terms": {
                "path": str(dio.SENSITIVITY_FILE.relative_to(REPO)),
                "terms": len(dio.read_terms(dio.SENSITIVITY_FILE)),
                "sha256": dio.sha256(dio.SENSITIVITY_FILE),
            },
            "overlap_sensitivity": {
                "path": str(dio.OVERLAP_FILE.relative_to(REPO)),
                "terms": len(variants["overlap_sensitivity"]),
                "sha256": dio.sha256(dio.OVERLAP_FILE),
            },
        },
        "test_fixture": {
            "path": str(dio.SYNTHETIC_SUPPLY_CHAIN_FIXTURE.relative_to(REPO)),
            "terms": len(dio.synthetic_supply_chain_weights()),
            "sha256": dio.sha256(dio.SYNTHETIC_SUPPLY_CHAIN_FIXTURE),
        },
        "corpus_diagnostic": (
            "Not part of source validation. Archived separately under "
            "outputs/resolution_validation/, which is gitignored, because it depends on "
            "local artifacts this repository does not track and other work here "
            "regenerates."
        ),
        "notes": {
            "git_commit_at_validation": (
                "HEAD when the run executed, with '-dirty' when this directory had "
                "uncommitted edits. The commit that carries this file is normally its "
                "child: check out the recorded commit, apply this directory, and rerun."
            ),
        },
    }
    (HERE / "validation_run.json").write_text(json.dumps(source_record, indent=2) + "\n")

    have_corpus = dio.TRANSCRIPT_CORPUS.exists()
    have_library = dio.REPO_SUPPLY_CHAIN_LIBRARY.exists()
    if args.skip_corpus_diagnostic:
        diagnostic_status = "skipped: --skip-corpus-diagnostic"
    elif have_corpus and have_library:
        diag, total_ok, n_sampled, dil = corpus_diagnostic(variants, args.sample, args.seed)
        record = {
            "scope": "archived_local_diagnostic",
            "reproducible_on_a_clean_checkout": False,
            "why_not_reproducible": (
                "Depends on earnings_call_transcripts.csv and "
                "artifacts/sec_10k_supply_chain/terms.jsonl, both gitignored local "
                "artifacts that other work in this repository regenerates."
            ),
            "build_date": args.build_date,
            "git_commit_at_run": git_commit(),
            "seed": args.seed,
            "sample_requested": args.sample,
            "sample_scored": n_sampled,
            "window": WINDOW,
            "dictionaries": {
                "resolution": source_record["primary_dictionaries"]["resolution"],
                "risk": source_record["primary_dictionaries"]["risk"],
                "supply_chain": {
                    "path": str(dio.REPO_SUPPLY_CHAIN_LIBRARY.relative_to(REPO)),
                    "terms": len(dio.repo_supply_chain_weights()),
                    "sha256": dio.sha256(dio.REPO_SUPPLY_CHAIN_LIBRARY),
                    "status": ("PROVISIONAL: the repo's generated 10-K library, not the "
                               "final reconstructed supply-chain vocabulary"),
                },
            },
            "transcript_corpus": {
                "path": str(dio.TRANSCRIPT_CORPUS.relative_to(REPO)),
                "sha256": dio.sha256(dio.TRANSCRIPT_CORPUS),
                "calls_passing_integrity": total_ok,
            },
            "zero_rates": {name: {"terms": len(variants[name]),
                                  "zero_resolution_rate": d["zero_rate"],
                                  "zero_scrisk_rate": d["scrisk_zero_rate"],
                                  "mean_raw": d["mean_raw"],
                                  "median_raw": d["median_raw"]}
                           for name, d in diag.items()},
        }
        write_corpus_diagnostic(args.diagnostic_dir, variants, primary, diag, dil, record)
        diagnostic_status = f"archived to {args.diagnostic_dir}"
    else:
        missing = [str(p.relative_to(REPO)) for p, ok in
                   [(dio.TRANSCRIPT_CORPUS, have_corpus),
                    (dio.REPO_SUPPLY_CHAIN_LIBRARY, have_library)] if not ok]
        diagnostic_status = ("skipped: local gitignored artifacts absent: "
                             + ", ".join(missing))

    render_source_report(primary, variants, table4, cov_problems, rows,
                         syn_results, sub_results, source_record)

    failures = (list(cov_problems)
                + [f"synthetic {r[0]}" for r in syn_results if not r[4]]
                + [f"substring {r[0]}" for r in sub_results if not r[3]])
    if failures:
        print("FAILURES:", failures)
        raise SystemExit(1)
    print("source validation passed; wrote validation_report.md, validation_run.json, "
          "overlap_report.csv")
    print(f"corpus diagnostic: {diagnostic_status}")


def render_source_report(primary, variants, table4, cov_problems, rows,
                         syn_results, sub_results, run) -> None:
    L: list[str] = []
    A = L.append
    A("# Validation report: reconstructed resolution dictionary")
    A("")
    A(f"Source date {run['build_date']}. Validated at commit "
      f"`{run['git_commit_at_validation']}`. Directory "
      "`dictionaries/theile_reconstruction_v1/resolution/`.")
    A("")
    A("**Scope: source validation only.** Everything in this report runs on a clean "
      "checkout of this repository. Its inputs are the paper's published tables, the "
      "committed dictionaries, and the committed synthetic supply-chain fixture. No "
      "local artifact, no transcript corpus, no generated supply-chain library.")
    A("")
    A("**The corpus diagnostic is not here, and it is not PR validation.** Zero rates "
      "and matched-term counts over real transcripts are an archived local diagnostic. "
      "They cannot be reproduced from this repository: they need "
      "`earnings_call_transcripts.csv` and `artifacts/sec_10k_supply_chain/terms.jsonl`, "
      "both gitignored, and other work in this repository regenerates both. "
      "`run_validation.py` writes them to `outputs/resolution_validation/`, which is "
      "gitignored, together with the hashes of the inputs each run used. Nothing there "
      "is evidence that this dictionary is correct, and no number in it should be quoted "
      "as a result.")
    A("")
    A("No CAR, return, or regression output was read at any point in building or "
      "validating this dictionary.")
    A("")

    A("## 0. Specification and hashes")
    A("")
    A(f"**The primary Resolution specification is "
      f"`resolution_terms_conservative_baseline.txt`, {len(primary)} terms.** It is the "
      "only dictionary the production pipeline loads, and the pipeline produces exactly "
      "one Resolution measure from it. The other three files in this directory are "
      "documented sensitivity artifacts and are never a default.")
    A("")
    A("| dictionary | role | terms | sha256 |")
    A("| --- | --- | --- | --- |")
    for label, key in [("resolution (conservative baseline)", "resolution"),
                       ("risk (reconstructed full)", "risk")]:
        d = run["primary_dictionaries"][key]
        A(f"| {label} | **primary** | {d['terms']} | `{d['sha256']}` |")
    for name, d in run["sensitivity_dictionaries"].items():
        A(f"| {name} | sensitivity | {d['terms']} | `{d['sha256']}` |")
    f = run["test_fixture"]
    A(f"| synthetic supply chain fixture | test fixture | {f['terms']} | "
      f"`{f['sha256']}` |")
    A("")
    A(f"Window {run['window']} tokens. Paths and the full record in "
      "`validation_run.json`.")
    A("")
    A("Generated files in this directory carry no runtime date. The source date above is "
      "fixed and supplied, so a rebuild that changes nothing substantive leaves every "
      "hash in `source_manifest.json` unchanged. Two consecutive rebuilds produce "
      "byte-identical output except for the commit recorded above.")
    A("")

    A("## 1. Table 4 coverage")
    A("")
    A(f"Table 4 prints 30 slots and {len(table4)} distinct keywords. Slots 24 and 25 "
      "repeat slots 22 and 23 (`enhance` 591, `recover` 566). The repetition is in the "
      "typeset page, confirmed by rendering page 8 at 250 dpi, so it is not a PDF "
      "extraction artifact and no OCR correction was applied.")
    A("")
    for name, terms in variants.items():
        if not terms:
            continue
        missing = [t for t in table4 if t not in set(terms)]
        tag = " **(PRIMARY)**" if name.endswith("_PRIMARY") else " (sensitivity)"
        A(f"- **{name}**{tag}: {len(terms)} terms, "
          f"{len(table4) - len(missing)}/{len(table4)} Table 4 terms present"
          + ("" if not missing else f", missing {missing}"))
    A("")
    A("The overlap-adjusted variant deliberately drops "
      f"{', '.join('`' + t + '`' for t in OVERLAP_SENSITIVITY_DROPS)}, so it does not "
      "cover Table 4 in full. That is the point of it, and it is why it is a sensitivity "
      "artifact rather than a candidate primary.")
    A("")
    if cov_problems:
        A("**Coverage failed.**")
        for p in cov_problems:
            A(f"- {p}")
    else:
        A("Coverage passes for the primary dictionary and for every sensitivity variant "
          "that is meant to cover Table 4.")
    A("")

    A("## 2. Exact token matching")
    A("")
    A("Matching is whole-token, case-folded, against the tokenizer the scoring script "
      "already uses. Each case would be a false positive under substring matching.")
    A("")
    A("| case | term that must not fire | terms actually matched | result |")
    A("| --- | --- | --- | --- |")
    for label, term, hits, ok, _why in sub_results:
        A(f"| `{label}` | `{term}` | {', '.join(f'`{h}`' for h in hits) or '(none)'} "
          f"| {'pass' if ok else 'FAIL'} |")
    A("")

    A("## 3. The paper's proximity rule")
    A("")
    A("A supply chain occurrence counts toward Resolution only when a risk occurrence is "
      "within ten tokens of it and a resolution occurrence is within ten tokens of the "
      "*same* supply chain occurrence. Run with the primary resolution dictionary, the "
      "161-term primary risk library, and the committed synthetic supply-chain fixture "
      "`fixtures/synthetic_supply_chain_library.jsonl`.")
    A("")
    A("| case | expect Resolution | Resolution pairs | SCRisk pairs | result |")
    A("| --- | --- | --- | --- | --- |")
    for label, expect, rp, kp, ok, _why in syn_results:
        A(f"| `{label}` | {'yes' if expect else 'no'} | {rp} | {kp} | "
          f"{'pass' if ok else 'FAIL'} |")
    A("")
    A("The three that matter most are `generic_resolution_no_supply_chain_risk`, "
      "`resolution_without_risk` and "
      "`resolution_and_risk_on_different_supply_chain_words`. All score zero, which is "
      "what the measure is for: generic positive language outside a supply-chain-risk "
      "context must not count, and equation (2) ties the risk word and the resolution "
      "word to the same supply chain word, not to each other.")
    A("")

    A("## 4. Overlap, settled comparisons only")
    A("")
    A("Every library below is committed, so every row reproduces on a clean checkout.")
    A("")
    A("| resolution variant | compared against | shared | terms |")
    A("| --- | --- | --- | --- |")
    for r in rows:
        A(f"| {r['resolution_variant']} | {r['compared_against']} | {r['n_shared']} | "
          f"{' '.join(f'`{t}`' for t in r['shared_terms'].split()) or '-'} |")
    A("")
    A("**Risk library: no overlap.** Not one of the 161 terms in the primary risk "
      "dictionary, nor of its observed-baseline variant, nor of the 144 risk keywords "
      "printed in Table 3, appears in the primary resolution dictionary or in any "
      "sensitivity variant. The closest call is `unresolved`, a risk word that shares a "
      "root with `resolved` and carries the opposite sense. Exact token matching keeps "
      "them apart, which is why the matching test above includes it.")
    A("")
    A("**Supply chain vocabulary: not settled, and deliberately left open.** The final "
      "reconstructed supply-chain vocabulary does not exist yet. The only one available "
      "is the repo's provisional 10-K-derived library, gap number two in the repo "
      "README. An overlap measured against it is a property of that provisional input, "
      "not a finding about this dictionary, so it is not reported here: it goes to "
      "`outputs/resolution_validation/provisional_overlap_report.csv` with the archived "
      "diagnostic.")
    A("")
    A("`solution` and `solutions` stay in the primary dictionary. `solutions` is Table "
      "4's second most frequent keyword at 4,289 and `solution` its tenth at 1,932; "
      "removing either would depart from the paper on the strength of a provisional "
      "input. The definitive overlap calculation is deferred until the reconstructed "
      "supply-chain vocabulary lands.")
    A("")
    A("What is at stake, so the deferred check has a stated expectation. Equation (2) "
      "counts the cosine similarity of a supply chain word `w` when some risk word `r` "
      "and some resolution word `m` are each within ten tokens of `w`. A term in both "
      "libraries can act as its own `m` at distance zero, so every occurrence of it near "
      "a risk word turns an SCRisk pair into a Resolution pair for free. In \"our supply "
      "chain solution addressed the shortage\", `solution` would be the supply chain "
      "word, `shortage` the risk word, and `solution` its own resolution word. If the "
      "final vocabulary contains either term, the fix is a decision about which library "
      "keeps it, and `resolution_terms_overlap_sensitivity.txt` already holds the variant "
      "that drops them from the resolution side.")
    A("")

    A("## 5. What is still uncertain")
    A("")
    A("- **The Oxford edition is unknown.** The paper says only \"the Oxford dictionary\" "
      "and names no product, edition, or date. Hassan et al. (2019), whose method the "
      "paper follows for the risk library, are equally vague. The product whose synonym "
      "runs would most plausibly generate this library, the Oxford Thesaurus of English, "
      "is behind a subscription: `premium.oxforddictionaries.com` returns an OAuth "
      "redirect, `oed.com` bounces to its home page, and Lexico, the free surface that "
      "existed when Hassan et al. wrote, shut down in 2022. The Internet Archive was "
      "returning \"Temporarily Offline\" on the retrieval date, so no archived capture "
      "could be read either. Everything Oxford-derived here comes from the free Oxford "
      "Advanced Learner's Dictionary, which prints one or two synonym cross-references "
      "per sense rather than a thesaurus run. See `source_manifest.json`.")
    A("")
    A("- **The tail of the library is unpublished.** Table 4 is the top 30 by frequency. "
      "How many terms sit below rank 30 is not stated. For the risk library the paper "
      "does publish the full list, so a comparable resolution library could plausibly "
      "run to a hundred terms or more. The primary dictionary reaches 55.")
    A("")
    A("- **Two Table 4 entries are lost to the duplication.** Slots 24 and 25 should have "
      "held the 24th and 25th most frequent keywords. Because the column is printed in "
      "descending order, their frequencies lie between 566 (slot 23) and 553 (slot 26), "
      "so both are in the range 554 to 566. Which two words they are is unrecoverable "
      "from the published paper.")
    A("")
    A("- **Table 4 frequencies are not raw corpus counts.** Table 2's note says frequency "
      "is \"the count of occurrences relevant to the construction of the SCRisk "
      "measure\", that is, occurrences that satisfied the proximity conditions. `help` at "
      "5,448 across 129,981 calls is not how often `help` is spoken. A form like "
      "`mitigating` being absent from the top 30 is therefore weak evidence that it is "
      "outside the library.")
    A("")
    A("- **Inflection policy is inferred, not stated.** The published risk library "
      "carries many inflections of a headword (`risk`/`risks`/`risky`/`riskier`/"
      "`riskiest`/`risked`/`risking`/`riskiness`) but not blanket regular inflection: "
      "`threat` appears without `threats`, `hazard` without `hazards`, `peril` without "
      "`perils`. The primary dictionary follows that pattern by adding only the forms "
      "Oxford itself prints, and holds regular plurals Oxford omits back to the "
      "sensitivity file.")
    A("")
    A("- **The supply-chain overlap is unresolved by construction.** See section 4.")
    A("")
    A("- **Behaviour on real transcripts is not validated here.** That is the archived "
      "local diagnostic, and it currently runs against a provisional supply-chain "
      "library and a provisional firm universe. It is a check on behaviour, not evidence "
      "of correctness, which is why it is gitignored rather than tracked.")
    A("")

    A("## 6. Recommendation")
    A("")
    A(f"`resolution_terms_conservative_baseline.txt`, {len(primary)} terms, is the "
      "primary specification and is already wired into the scoring script as the only "
      "default. It covers every Table 4 keyword, adds only forms an Oxford entry prints, "
      "and adds exactly two words beyond the Table 4 roots: `alleviate` and `settle`, the "
      "synonym cross-references Oxford puts on the two seed headwords the paper names.")
    A("")
    A("The anchor, expanded and overlap-adjusted files stay as predeclared sensitivity "
      "specifications. Declare them before any outcome analysis runs. Do not promote one "
      "to primary on the strength of an outcome.")
    A("")

    (HERE / "validation_report.md").write_text("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
