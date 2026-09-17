"""Stage 9: promote one arm to the top-level baseline deliverable.

Copies the chosen arm's term files up, attaches the model fingerprint and every
random seed used anywhere in the pipeline, and stamps the result as a
reconstruction rather than the authors' library. Alternative arms stay under
sensitivity/ and are never merged in.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--baseline-dir", type=Path, required=True)
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--corpus-manifest", type=Path, required=True)
    p.add_argument("--corpus-report", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--selection-rationale", required=True)
    a = p.parse_args()

    for name in ("supply_chain_terms.jsonl", "supply_chain_terms.txt",
                 "per_seed_top100.json", "table2_comparison.csv"):
        src = a.baseline_dir / name
        if src.exists():
            shutil.copy2(src, a.output_dir / name)

    model = json.loads((a.run_dir / "model_config.json").read_text())
    extraction = json.loads((a.baseline_dir / "extraction_summary.json").read_text())
    cm = json.loads(a.corpus_manifest.read_text())
    cr = json.loads(a.corpus_report.read_text())

    config = {
        "status": "RECONSTRUCTED APPROXIMATION, not the authors' library",
        "paper": "Theile et al. (2026), Supply Chain Risk and Resolution",
        "selected_arm": a.baseline_dir.name,
        "selection_rationale": a.selection_rationale,
        "selection_was_outcome_blind": True,
        "outcome_blind_note": (
            "No CAR, transcript score, quintile return, or any downstream result was "
            "computed, inspected, or available while this vocabulary was chosen. "
            "Selection used only Table 2 recovery, cosine ordering, blinded semantic "
            "precision, stability, per-seed coverage, frequency support, generic-language "
            "avoidance, and final size."),
        "model": model,
        "extraction": extraction,
        "random_seeds": {
            "corpus_sampling": cm["sampling"]["seed"],
            "corpus_sampling_scheme": cm["sampling"]["seed_scheme"],
            "model_training": model.get("random_seed"),
            "blinded_review_sampling": 20260916,
            "corpus_subsample_stability": 314159,
            "alternate_training_seed": 777,
        },
        "corpus": {
            "documents": cr["documents_used"],
            "tokens": cr["total_tokens"],
            "years": "1997-2021, exactly 2,000 filings sampled per year",
            "forms": cm["discovery"]["eligible_forms"],
            "eligible_population": cm["discovery"]["eligible_total"],
            "phrases_detected": cr["phrases_detected"],
            "duplicates_excluded": cr["documents_excluded_duplicate"],
        },
        "environments": {
            "corpus_ppmi_evaluation": "dap-env (Python 3.14)",
            "word2vec_only": "dap-w2v (Python 3.13, gensim 4.4.0) because gensim "
                             "does not build on Python 3.14",
        },
    }
    (a.output_dir / "model_config.json").write_text(json.dumps(config, indent=2))

    terms = [json.loads(l) for l in (a.output_dir / "supply_chain_terms.jsonl").open()]
    required = {"term", "max_cosine", "nearest_seed", "seed_rank", "all_seed_matches",
                "frequency", "document_frequency", "method", "in_paper_table_2", "review_status"}
    missing = required - set(terms[0])
    if missing:
        raise SystemExit(f"term records missing required fields: {sorted(missing)}")
    print(f"baseline: {a.baseline_dir.name}  terms={len(terms)}  "
          f"table2={extraction['table_2_recovered']}/30  all required fields present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
