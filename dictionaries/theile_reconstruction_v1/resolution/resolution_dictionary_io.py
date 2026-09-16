"""Load the reconstructed resolution dictionaries and the reference libraries.

Shared by the test suite and the validation run so both read the same files.

The primary Resolution specification is the 55-term conservative baseline. The
primary risk specification is the 161-term reconstructed-full risk dictionary
in the sibling ``risk/`` directory. The 144-term Table 3 list is kept only as a
published-source reference for the extraction record.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]

# --- resolution dictionaries ------------------------------------------------

BASELINE_FILE = HERE / "resolution_terms_conservative_baseline.txt"   # PRIMARY
ANCHOR_FILE = HERE / "resolution_terms_paper_anchor.txt"              # sensitivity
SENSITIVITY_FILE = HERE / "resolution_terms_expanded_sensitivity.txt"  # sensitivity
OVERLAP_FILE = HERE / "resolution_terms_overlap_sensitivity.txt"       # sensitivity

PRIMARY_RESOLUTION_TERM_COUNT = 55

# --- reference and sibling libraries ---------------------------------------

TABLE_3_FILE = HERE / "table_3_risk_terms_reference.csv"
TABLE_4_FILE = HERE / "table_4_extraction.csv"
RECONSTRUCTED_RISK_DIR = HERE.parent / "risk"
PRIMARY_RISK_FILE = RECONSTRUCTED_RISK_DIR / "risk_terms_reconstructed_full.txt"
OBSERVED_RISK_FILE = RECONSTRUCTED_RISK_DIR / "risk_terms_observed_baseline.txt"
PRIMARY_RISK_TERM_COUNT = 161

# --- supply chain vocabularies ---------------------------------------------

SYNTHETIC_SUPPLY_CHAIN_FIXTURE = HERE / "fixtures" / "synthetic_supply_chain_library.jsonl"
REPO_SUPPLY_CHAIN_LIBRARY = REPO / "artifacts" / "sec_10k_supply_chain" / "terms.jsonl"
TRANSCRIPT_CORPUS = REPO / "earnings_call_transcripts.csv"

# The top 30 supply chain keywords the paper prints in Table 2, journal p. 2986.
# Hyphens and spaces are already removed there, as the table's note says.
PAPER_TABLE_2_SUPPLY_CHAIN = [
    "customers", "supply", "inventory", "manufacturing", "distribution", "suppliers",
    "transportation", "logistics", "purchasing", "sourcing", "procurement",
    "fulfillment", "warehousing", "resellers", "endcustomers", "vars", "pims",
    "inventories", "supplychain", "isvs", "vendors", "warehouse", "workinprocess",
    "integrators", "endcustomer", "workflow", "eprocurement", "slowmoving",
    "customer", "supplier",
]


def read_terms(path: Path) -> list[str]:
    """One term per line. ``#`` comments and blank lines are dropped."""
    return [line.strip() for line in path.read_text().splitlines()
            if line.strip() and not line.startswith("#")]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --- resolution -------------------------------------------------------------


def primary_resolution_terms() -> list[str]:
    """The single primary Resolution specification: 55 terms."""
    terms = read_terms(BASELINE_FILE)
    if len(terms) != PRIMARY_RESOLUTION_TERM_COUNT or len(set(terms)) != len(terms):
        raise ValueError(
            f"{BASELINE_FILE} must hold exactly {PRIMARY_RESOLUTION_TERM_COUNT} "
            f"unique terms; found {len(terms)} ({len(set(terms))} unique)"
        )
    return terms


def sensitivity_variants() -> dict[str, list[str]]:
    """The documented sensitivity dictionaries. Never a production default."""
    baseline = primary_resolution_terms()
    return {
        "paper_anchor": read_terms(ANCHOR_FILE),
        "expanded_sensitivity": baseline + read_terms(SENSITIVITY_FILE),
        "overlap_sensitivity": read_terms(OVERLAP_FILE) if OVERLAP_FILE.exists() else [],
    }


def all_variants() -> dict[str, list[str]]:
    """Primary first, then the sensitivity variants. For reporting only."""
    out = {"conservative_baseline_PRIMARY": primary_resolution_terms()}
    out.update(sensitivity_variants())
    return out


def table_4_terms() -> list[str]:
    """The distinct keywords printed in Table 4, in printed order."""
    seen, out = set(), []
    with TABLE_4_FILE.open() as fh:
        for row in csv.DictReader(fh):
            term = row["keyword"]
            if term not in seen:
                seen.add(term)
                out.append(term)
    return out


# --- risk -------------------------------------------------------------------


def primary_risk_terms() -> list[str]:
    """The 161-term reconstructed-full risk dictionary. The primary risk library."""
    terms = read_terms(PRIMARY_RISK_FILE)
    if len(terms) != PRIMARY_RISK_TERM_COUNT:
        raise ValueError(
            f"{PRIMARY_RISK_FILE} must hold exactly {PRIMARY_RISK_TERM_COUNT} terms; "
            f"found {len(terms)}"
        )
    return terms


def table_3_reference_terms() -> list[str]:
    """The 144 risk keywords printed in Table 3.

    A record of the published table, not a specification. The primary risk
    library is ``primary_risk_terms()``.
    """
    with TABLE_3_FILE.open() as fh:
        return [row["risk_word"] for row in csv.DictReader(fh)]


def observed_risk_terms() -> list[str]:
    """The sibling observed-baseline risk variant, when present."""
    return read_terms(OBSERVED_RISK_FILE) if OBSERVED_RISK_FILE.exists() else []


# --- supply chain -----------------------------------------------------------


def _load_weights(path: Path) -> dict[str, float]:
    weights: dict[str, float] = {}
    with path.open() as fh:
        for line in fh:
            rec = json.loads(line)
            weights[rec["term"]] = float(rec["max_cosine"])
    return weights


def synthetic_supply_chain_weights() -> dict[str, float]:
    """The committed 15-term test fixture. Available on a clean checkout."""
    return _load_weights(SYNTHETIC_SUPPLY_CHAIN_FIXTURE)


def repo_supply_chain_weights() -> dict[str, float]:
    """The repo's generated 10-K library. A local, gitignored artifact.

    This is a provisional input, not the paper's S library and not the final
    reconstructed supply-chain vocabulary. Used only to exercise the proximity
    rule on real transcripts in ``run_validation.py``.
    """
    return _load_weights(REPO_SUPPLY_CHAIN_LIBRARY)
