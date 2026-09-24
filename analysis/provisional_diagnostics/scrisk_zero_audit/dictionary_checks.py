import json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]  # repository root
sys.path.insert(0, str(ROOT))
from scoring import calculate_supply_chain_transcript_scores as S

LIB = Path(os.environ.get(
    'SCRISK_AUDIT_LIBRARY',
    str(ROOT / 'artifacts/sec_10k_supply_chain/experiments/ppmi_svd_full_20260910/terms.jsonl')))
OUT = Path(os.environ.get('SCRISK_AUDIT_OUT', str(ROOT / 'outputs/scrisk_zero_audit')))
VERSION = os.environ.get('SCRISK_AUDIT_VOCABULARY', 'v1_library_only')

lib = S.load_supply_chain_library(LIB)
seeds = [" ".join(S.normalize_term(s)) for s in S.SUPPLY_CHAIN_SEEDS]
res = sorted({" ".join(S.normalize_term(t)) for t in S.load_primary_resolution_dictionary()})


def describe(version: str) -> dict:
    """Report one vocabulary version against the same library and dictionaries."""
    sc = S.build_supply_chain_vocabulary(lib, version)
    risk = sorted(S.build_risk_vocabulary(S.load_primary_risk_dictionary()))
    weights = sorted(sc.values())
    overlap = sorted(set(sc) & set(risk))
    return {
        "vocabulary_version": version,
        "supply_chain_terms": len(sc),
        "risk_terms": len(risk),
        "seeds_scored": [s for s in seeds if s in sc],
        "seeds_not_scored": [s for s in seeds if s not in sc],
        "weight_min": weights[0],
        "weight_max": weights[-1],
        "non_positive_weights": sum(1 for x in weights if x <= 0),
        # A term in both vocabularies pairs with its own occurrence at
        # distance 0, so one word is enough to make a call non-zero.
        "terms_in_both_supply_chain_and_risk": overlap,
        "weight_of_terms_in_both": {t: sc[t] for t in overlap},
        "supply_chain_resolution_overlap": sorted(set(sc) & set(res)),
        "multiword_supply_chain_terms": sorted(t for t in sc if " " in t),
        "multiword_risk_terms": sorted(t for t in risk if " " in t),
        "supply_chain_terms_unreachable_by_tokenizer": sorted(
            t for t in sc if tuple(t.split()) != S.normalize_term(t)),
        "risk_terms_unreachable_by_tokenizer": sorted(
            t for t in risk if tuple(t.split()) != S.normalize_term(t)),
    }


v1, v2 = describe('v1_library_only'), describe('v2_seeds_inflections')
v1_sc = set(S.build_supply_chain_vocabulary(lib, 'v1_library_only'))
v2_sc = S.build_supply_chain_vocabulary(lib, 'v2_seeds_inflections')
out = {
    "library_path": str(LIB),
    "library_terms": len(lib),
    "audited_vocabulary_version": VERSION,
    "resolution_terms": len(res),
    "v1_library_only": v1,
    "v2_seeds_inflections": v2,
    "terms_added_by_v2": sorted(set(v2_sc) - v1_sc),
    "terms_reweighted_by_v2": {
        t: {"v1": lib[t], "v2": v2_sc[t]} for t in sorted(v1_sc) if v2_sc[t] != lib[t]},
}
OUT.mkdir(parents=True, exist_ok=True)
(OUT / 'dictionary_checks.json').write_text(json.dumps(out, indent=2))
for k, v in out.items():
    print(k, "=", v if not isinstance(v, (list, dict)) or len(v) <= 12
          else f"{len(v)} items: {list(v)[:12]} ...")
