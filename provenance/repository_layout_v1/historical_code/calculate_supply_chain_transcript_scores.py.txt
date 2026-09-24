#!/usr/bin/env python3
"""Calculate supply-chain risk and resolution scores for earnings calls.

This script is intentionally separate from the transcript collector.  It does
not modify ``earnings_call_transcripts.csv`` or
``earnings_call_transcript_segments.csv`` in place.  It can be reviewed and
run against a copy of the transcript-level CSV before the scores are added to
the study outputs.

Scoring definition
------------------

1. A *supply-chain occurrence* is a term from the supply-chain vocabulary.
   ``--vocabulary-version`` chooses that vocabulary.  ``v1_library_only`` uses
   the generated library exactly as it appears in ``terms.jsonl``, weighting
   each term by its ``max_cosine``.  ``v2_seeds_inflections``, the default,
   adds the 16 ``SUPPLY_CHAIN_SEEDS`` at ``SEED_WEIGHT`` and then completes the
   regular singular/plural inflections of the union, so ``inventory`` reaches
   the library's ``inventories`` and ``suppliers`` reaches its ``supplier``.
   A form reachable from more than one term takes the largest weight, which is
   the rule ``load_supply_chain_library`` already applies to repeated rows.
2. A *risk occurrence* is a term from the risk dictionary, inflected the same
   way under ``v2_seeds_inflections``.  For the starter
   dictionary below, the base vocabulary is a manually curated expansion of
   "risk" and "uncertainty" and the additional vocabulary is drawn from
   official supply-chain-risk sources.  The dictionary is an input, so the
   researcher can replace or revise it without changing scoring code.
3. Every supply-chain/risk occurrence pair whose token spans are no more than
   ``WINDOW`` tokens apart contributes the supply-chain cosine weight to the
   raw SCRisk score.  Thus, one supply-chain occurrence can contribute more
   than once if it is close to multiple risk occurrences.
4. The weighted match sum is divided by the transcript's total tokenized word
   count.  This length-adjusted value is the raw score used for dataset-wide
   standardization.
5. A Resolution contribution uses the same supply-chain/risk pair, but is
   counted only when at least one resolution occurrence is also within
   ``WINDOW`` tokens of the supply-chain occurrence.  This keeps Resolution a
   measure of resolution language in supply-chain-risk contexts, rather than
   a general count of words such as "mitigate" anywhere in a call.
6. Each raw score is divided by the *population* standard deviation of that
   raw score across the complete input dataset.  The mean is deliberately not
   subtracted.  If a dataset's standard deviation is zero, its normalized
   score is written as 0.0 because division would otherwise be undefined.
7. A transcript that holds no spoken content is excluded from the
   standardization population and its standardized score is written blank.
   See ``assess_transcript_integrity``.  ``--no-transcript-integrity-filter``
   restores the original behaviour of standardizing every row.

Two known vocabulary properties, deliberately left in place
-----------------------------------------------------------

Both of these change scores and both are arguable.  They are measured rather
than silently altered, and each has a switch so a sensitivity run can be
compared against the default.

*Terms in both vocabularies.*  ``shortages`` is a supply-chain library term
(weight 0.693) and also a risk term.  A span is zero tokens from itself, so
one occurrence of ``shortages`` forms a valid pair with itself and contributes
0.693 to the score with no second word anywhere nearby.  Under
``v2_seeds_inflections`` the inflection completion puts ``shortage`` in both
vocabularies too, so the same applies to the singular.  Every such pair is
counted in ``scrisk_identical_span_pairs`` and
``scrisk_identical_span_weight_sum`` on each output row, and the full list of
shared terms is written to the run manifest.  ``--forbid-identical-span-pairs``
drops them.

*Broad seeds.*  ``customers`` is a seed, so in ``v2_seeds_inflections`` it
carries the maximum weight of 1.0, and ``customer`` inherits that weight as
its inflection.  It is the most common noun in the corpus that either
vocabulary contains, and it is the weakest of the 16 seeds semantically: a
sentence about customer funding concerns scores as supply-chain risk.
``--exclude-supply-chain-terms customers,customer`` drops it.

The proximity rule uses token positions and supports multiword dictionary
entries.  A distance of 10 means the closest tokens in the two spans are at
most ten positions apart; this is the usual practical interpretation of
"within 10 words" and is explicit here for reproducibility.

Examples
--------

Score a transcript-level CSV, preserving all existing columns::

    python calculate_supply_chain_transcript_scores.py \
        --input earnings_call_transcripts.csv \
        --library artifacts/sec_10k_supply_chain_pilot_concurrent/terms.jsonl \
        --output earnings_call_transcripts_scored.csv

Reproduce the original ppmi_svd_full_20260910 scores exactly::

    python calculate_supply_chain_transcript_scores.py \
        --input earnings_call_transcripts.csv \
        --library artifacts/sec_10k_supply_chain/experiments/ppmi_svd_full_20260910/terms.jsonl \
        --vocabulary-version v1_library_only \
        --no-transcript-integrity-filter \
        --output earnings_call_transcripts_scored_v1.csv

Use reviewed dictionaries instead of the starter dictionaries::

    python calculate_supply_chain_transcript_scores.py \
        --input earnings_call_transcripts.csv \
        --library artifacts/sec_10k_supply_chain_pilot_concurrent/terms.jsonl \
        --risk-words risk_words.txt \
        --resolution-words resolution_words.txt \
        --output earnings_call_transcripts_scored.csv

The input CSV must contain a ``transcript_text`` column.  A dictionary file
can be either one term per line (blank lines and ``#`` comments are ignored),
or JSON containing a list of terms, or an object with a ``terms`` list.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from statistics import pstdev
from typing import Any, Iterable, Sequence


WINDOW = 10

# These are the 16 seed phrases used by build_supply_chain_library.py.  They
# are the intended semantic center of the generated library, so under
# vocabulary version ``v2_seeds_inflections`` they are scored directly at
# SEED_WEIGHT.  Under ``v1_library_only`` they are not scored at all, which
# reproduces the original ppmi_svd_full_20260910 run exactly.
SUPPLY_CHAIN_SEEDS = (
    "channel partners",
    "customers",
    "demand management",
    "distribution",
    "fulfillment",
    "inventory",
    "logistics",
    "manufacturing",
    "procurement",
    "purchasing",
    "sourcing",
    "suppliers",
    "supply",
    "supply chain",
    "transportation",
    "warehousing",
)

# Starter risk vocabulary.  These terms are intentionally visible for review
# and are not presented as a final research dictionary.  The closest synonym
# set is followed by supply-chain-specific exposures, disruptions, and threat
# terms used in official NIST, CISA, and GAO supply-chain-risk material.
STARTER_RISK_WORDS = (
    # Direct/near synonyms and common inflections for risk and uncertainty.
    "risk", "risks", "risky", "uncertain", "uncertainty", "uncertainties",
    "exposure", "exposures", "vulnerability", "vulnerabilities", "threat",
    "threats", "hazard", "hazards", "danger", "dangers", "jeopardy",
    "peril", "perils", "contingency", "contingencies", "volatility",
    "volatile", "downside", "concern", "concerns", "susceptible",
    # Supply-chain disruption, dependency, availability, and concentration.
    "supply disruption", "supply chain disruption", "business disruption",
    "disruption", "disruptions", "shortage", "shortages", "stockout",
    "stockouts", "bottleneck", "bottlenecks", "capacity constraint",
    "capacity constraints", "supplier failure", "supplier dependency",
    "supplier concentration", "single source", "single sourcing",
    "geographic concentration", "foreign dependency", "external dependency",
    "raw material availability", "component availability", "material shortage",
    "labor shortage", "delivery delay", "delivery delays", "shipping delay",
    "transportation delay", "lead time", "lead times", "port congestion",
    # Events and integrity threats identified in supply-chain-risk guidance.
    "counterfeit", "counterfeits", "counterfeiting", "unauthorized production",
    "tampering", "theft", "malicious software", "malicious hardware",
    "poor manufacturing", "manufacturing defect", "manufacturing defects",
    "quality failure", "quality failures", "supplier failure", "cyberattack",
    "cyberattacks", "cyber threat", "ransomware", "natural disaster",
    "natural disasters", "extreme weather", "geopolitical conflict",
    "trade dispute", "trade disputes", "trade restriction", "trade restrictions",
    "tariff", "tariffs", "sanction", "sanctions", "regulatory violation",
    "regulatory violations", "supplier insolvency", "supplier bankruptcy",
    "demand shock", "forecast error",
)

# The starter Resolution dictionary is deliberately narrower than a generic
# positive-language dictionary.  It focuses on actions that can describe
# addressing a risk: mitigation, containment, recovery, and resolution.
STARTER_RESOLUTION_WORDS = (
    "mitigate", "mitigates", "mitigated", "mitigating", "mitigation",
    "mitigations", "resolve", "resolves", "resolved", "resolving",
    "resolution", "resolutions", "address", "addresses", "addressed",
    "addressing", "remediate", "remediates", "remediated", "remediation",
    "reduce", "reduces", "reduced", "reducing", "contain", "contains",
    "contained", "containing", "prevent", "prevents", "prevented",
    "preventing", "avoid", "avoids", "avoided", "avoiding", "recover",
    "recovers", "recovered", "recovering", "recovery", "diversify",
    "diversifies", "diversified", "diversifying", "substitute", "substitutes",
    "substituted", "substituting", "alternative source", "backup supplier",
    "dual source", "dual sourcing", "buffer stock", "safety stock",
)

# Source notes for the starter supply-chain-specific additions.  They are
# comments/data provenance only; the script never downloads or depends on the
# internet at scoring time.  Reviewers can replace STARTER_RISK_WORDS with a
# versioned dictionary and retain these URLs in that file's metadata.
RISK_TERM_SOURCES = (
    "https://csrc.nist.gov/Projects/cyber-supply-chain-risk-management",
    "https://csrc.nist.gov/glossary/term/supply_chain_risk",
    "https://www.cisa.gov/sites/default/files/2024-08/Critical_Manufacturing_Sector_Supply_Chain_Security_and_the_Gray_Market_508c.pdf",
    "https://www.gao.gov/products/gao-22-105923",
)

WORD_RE = re.compile(r"[A-Za-z]+(?:['’.-][A-Za-z]+)*")

# A seed is by construction the centre of its own neighbourhood, so its
# similarity to itself is 1.0.  Giving the seeds that weight keeps them
# strictly above every generated expansion term, whose max_cosine tops out at
# 0.916 in the study library.
SEED_WEIGHT = 1.0

# ``v1_library_only`` scores exactly the terms in terms.jsonl and exactly the
# risk dictionary as written.  ``v2_seeds_inflections`` adds the 16 seeds at
# SEED_WEIGHT and completes the regular singular/plural inflections of both
# vocabularies.  Neither version changes WINDOW, tokenization, the pairing
# rule, or the resolution dictionary.
VOCABULARY_VERSIONS = ("v1_library_only", "v2_seeds_inflections")
DEFAULT_VOCABULARY_VERSION = "v2_seeds_inflections"

# Transcript-integrity markers.  Every string is matched case-insensitively
# against the raw transcript text.  These are the three provider artifacts
# found in the corpus by the SCRisk zero audit, all of which arrive with
# ``status = success`` and therefore reach scoring.
TRANSCRIPT_INTEGRITY_MARKERS = {
    "redacted_spoken_content": "(full spoken content)",
    "provider_copyright_boilerplate": "copyright policy: all transcripts on this site",
    "transcript_unavailable": "transcript is not available",
}

# A real earnings call does not repeat the same 3% of its vocabulary for
# thousands of tokens.  ETN 2012Q4 has 4,506 tokens and 147 distinct ones,
# a ratio of 0.033, because the body is the provider's copyright notice
# repeated.  No genuine call in the corpus falls below 0.10.
DEGENERATE_DISTINCT_TOKEN_RATIO = 0.10

# The shortest genuine full call in the corpus runs a few thousand tokens.
# Everything below 1,000 tokens is a truncated stub: an operator greeting, a
# headline paragraph, or a placeholder.
MINIMUM_SPOKEN_TOKENS = 1000

INTEGRITY_OK = "ok"
INTEGRITY_CONTENT_ABSENT = "content_absent"
INTEGRITY_NO_TEXT = "no_transcript_text"


def configure_csv_field_size_limit() -> None:
    """Accept full earnings-call transcripts that exceed CSV's small default."""

    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


@dataclass(frozen=True)
class Occurrence:
    """A normalized dictionary phrase and its inclusive token span."""

    term: str
    start: int
    end: int


@dataclass(frozen=True)
class ScoreResult:
    """Raw score details for one transcript."""

    word_count: int
    supply_chain_occurrences: int
    risk_occurrences: int
    resolution_occurrences: int
    risk_pairs: int
    resolution_pairs: int
    scrisk_weight_sum: float
    resolution_weight_sum: float
    scrisk_raw: float
    resolution_raw: float
    # A term that sits in both the supply-chain and the risk vocabulary pairs
    # with its own occurrence at distance 0.  ``shortages`` is the only such
    # term in v1.  These two fields report exactly how much of the score comes
    # from that, so it can be measured instead of argued about.
    identical_span_pairs: int = 0
    identical_span_weight_sum: float = 0.0


def normalize_term(term: str) -> tuple[str, ...]:
    """Convert a dictionary entry into the same token representation as text."""

    return tuple(match.group(0).lower() for match in WORD_RE.finditer(term))


def tokenize(text: str) -> list[str]:
    """Tokenize prose while retaining ordinary words and hyphenated terms."""

    return [match.group(0).lower() for match in WORD_RE.finditer(text)]


def _phrase_occurrences(tokens: Sequence[str], term: str) -> list[Occurrence]:
    """Return every exact, non-overlapping-start occurrence of one phrase."""

    phrase = normalize_term(term)
    if not phrase or len(phrase) > len(tokens):
        return []
    occurrences: list[Occurrence] = []
    width = len(phrase)
    for start in range(len(tokens) - width + 1):
        if tuple(tokens[start : start + width]) == phrase:
            occurrences.append(Occurrence(" ".join(phrase), start, start + width - 1))
    return occurrences


PhraseIndex = dict[str, tuple[tuple[tuple[str, ...], str], ...]]


def build_phrase_index(terms: Iterable[str]) -> PhraseIndex:
    """Index normalized phrases by their first token for one-pass matching."""

    indexed: dict[str, list[tuple[tuple[str, ...], str]]] = {}
    seen: set[tuple[str, ...]] = set()
    for term in terms:
        phrase = normalize_term(term)
        if not phrase or phrase in seen:
            continue
        seen.add(phrase)
        indexed.setdefault(phrase[0], []).append((phrase, " ".join(phrase)))
    return {first: tuple(candidates) for first, candidates in indexed.items()}


def find_indexed_occurrences(tokens: Sequence[str], index: PhraseIndex) -> list[Occurrence]:
    """Find every indexed phrase in one pass over the transcript tokens."""

    occurrences: list[Occurrence] = []
    token_count = len(tokens)
    for start, first_token in enumerate(tokens):
        for phrase, term in index.get(first_token, ()):
            width = len(phrase)
            if start + width <= token_count and tuple(tokens[start : start + width]) == phrase:
                occurrences.append(Occurrence(term, start, start + width - 1))
    return occurrences


def find_occurrences(tokens: Sequence[str], terms: Iterable[str]) -> list[Occurrence]:
    """Find all dictionary phrases, including overlapping phrase occurrences."""

    return find_indexed_occurrences(tokens, build_phrase_index(terms))


def spans_within(left: Occurrence, right: Occurrence, window: int = WINDOW) -> bool:
    """Return true when the closest tokens in two spans are <= window apart."""

    if left.end < right.start:
        distance = right.start - left.end
    elif right.end < left.start:
        distance = left.start - right.end
    else:
        distance = 0
    return distance <= window


def load_supply_chain_library(path: Path) -> dict[str, float]:
    """Load ``term`` and ``max_cosine`` from the builder's JSONL output."""

    weights: dict[str, float] = {}
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                term = str(record["term"]).strip()
                weight = float(record["max_cosine"])
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"Invalid supply-chain library row {line_number} in {path}") from exc
            normalized = " ".join(normalize_term(term))
            if not normalized:
                continue
            if not math.isfinite(weight):
                raise ValueError(f"Non-finite cosine weight on row {line_number} in {path}")
            # If a term is repeated, retain the largest supplied weight.  This
            # is conservative with respect to the builder's max_cosine field.
            weights[normalized] = max(weight, weights.get(normalized, -math.inf))
    if not weights:
        raise ValueError(f"No supply-chain terms found in {path}")
    return weights


def load_dictionary(path: Path) -> list[str]:
    """Load terms from plain text or simple JSON and normalize duplicates."""

    if path.suffix.lower() == ".json":
        value: Any = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            value = value.get("terms")
        if not isinstance(value, list):
            raise ValueError(f"JSON dictionary {path} must be a list or an object with a terms list")
        raw_terms = value
    else:
        raw_terms = [
            line.split("#", 1)[0].strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.split("#", 1)[0].strip()
        ]

    terms: list[str] = []
    seen: set[str] = set()
    for raw_term in raw_terms:
        normalized = " ".join(normalize_term(str(raw_term)))
        if normalized and normalized not in seen:
            seen.add(normalized)
            terms.append(normalized)
    if not terms:
        raise ValueError(f"No terms found in dictionary {path}")
    return terms


def regular_inflections(word: str) -> set[str]:
    """Return a word's regular singular and plural forms, never truncating a stem.

    This is deliberately not a stemmer.  A stemmer turns ``stocking`` into
    ``stock`` and ``tracking`` into ``track``, which pulls two of the most
    common words in an earnings call into the supply-chain vocabulary.  This
    function only adds or removes a regular English plural ending, so
    ``inventories`` reaches ``inventory`` and ``supplier`` reaches
    ``suppliers`` while ``finished`` and ``shipping`` are left alone.
    """

    variants = {word}
    if word.endswith("ies") and len(word) > 4:
        variants.add(word[:-3] + "y")
    elif word.endswith(("ses", "xes", "zes", "ches", "shes")):
        variants.add(word[:-2])
    elif word.endswith("s") and not word.endswith("ss"):
        variants.add(word[:-1])
    else:
        variants.add(word + "s")
        if word.endswith("y") and len(word) > 2 and word[-2] not in "aeiou":
            variants.add(word[:-1] + "ies")
        if word.endswith(("s", "x", "z", "ch", "sh")):
            variants.add(word + "es")
    return variants


def phrase_inflections(term: str) -> set[str]:
    """Inflect only a phrase's head word, which in English is its last token."""

    words = term.split()
    if not words:
        return set()
    head = words[-1]
    prefix = words[:-1]
    return {" ".join(prefix + [variant]) for variant in regular_inflections(head)}


def expand_term_inflections(terms: Iterable[str]) -> list[str]:
    """Complete the regular inflections of an unweighted dictionary."""

    expanded: set[str] = set()
    for term in terms:
        expanded.update(phrase_inflections(term))
    return sorted(expanded)


def expand_weighted_inflections(weights: dict[str, float]) -> dict[str, float]:
    """Complete inflections of a weighted vocabulary, keeping the larger weight.

    Taking the maximum matches ``load_supply_chain_library``, which already
    keeps the largest weight when ``terms.jsonl`` repeats a term.  It means a
    form reachable from more than one source term is scored at the strongest
    of them: ``supplier`` is both a 0.897 library term and an inflection of
    the seed ``suppliers``, so it is scored at the seed weight.
    """

    expanded: dict[str, float] = {}
    for term, weight in weights.items():
        for variant in phrase_inflections(term):
            expanded[variant] = max(weight, expanded.get(variant, -math.inf))
    return expanded


def build_supply_chain_vocabulary(
    library_weights: dict[str, float],
    version: str = DEFAULT_VOCABULARY_VERSION,
    seed_weight: float = SEED_WEIGHT,
    excluded_terms: Iterable[str] = (),
) -> dict[str, float]:
    """Assemble the weighted supply-chain vocabulary for one version.

    ``v1_library_only`` returns the library exactly as loaded.
    ``v2_seeds_inflections`` adds the 16 seeds at ``seed_weight`` and then
    completes the regular inflections of the union.  ``excluded_terms`` is
    applied last and exists for sensitivity runs; it is empty by default so
    the version's own definition is never quietly narrowed.
    """

    if version not in VOCABULARY_VERSIONS:
        raise ValueError(f"Unknown vocabulary version {version!r}; expected one of {VOCABULARY_VERSIONS}")
    vocabulary = dict(library_weights)
    if version == "v2_seeds_inflections":
        for seed in SUPPLY_CHAIN_SEEDS:
            normalized = " ".join(normalize_term(seed))
            if normalized:
                vocabulary[normalized] = max(seed_weight, vocabulary.get(normalized, -math.inf))
        vocabulary = expand_weighted_inflections(vocabulary)
    for term in excluded_terms:
        vocabulary.pop(" ".join(normalize_term(term)), None)
    if not vocabulary:
        raise ValueError("The supply-chain vocabulary is empty after exclusions")
    return vocabulary


def build_risk_vocabulary(
    risk_words: Iterable[str],
    version: str = DEFAULT_VOCABULARY_VERSION,
) -> list[str]:
    """Assemble the risk vocabulary for one version, inflecting only in v2."""

    if version not in VOCABULARY_VERSIONS:
        raise ValueError(f"Unknown vocabulary version {version!r}; expected one of {VOCABULARY_VERSIONS}")
    terms = [" ".join(normalize_term(term)) for term in risk_words]
    terms = [term for term in terms if term]
    if version == "v2_seeds_inflections":
        return expand_term_inflections(terms)
    ordered: list[str] = []
    seen: set[str] = set()
    for term in terms:
        if term not in seen:
            seen.add(term)
            ordered.append(term)
    return ordered


def assess_transcript_integrity(text: str) -> tuple[str, list[str]]:
    """Classify whether a transcript actually contains spoken call content.

    Returns the integrity status and the list of flags that fired.  A row with
    no text at all is ``no_transcript_text``: it was never a call, it already
    scores zero, and it never reaches the event study.  A row with text that
    is a provider placeholder, a repeated copyright notice, or a sub-1,000
    token stub is ``content_absent``: it is marked ``status = success``,
    it does reach the event study, and its score is not a measurement of
    anything that was said.
    """

    tokens = tokenize(text)
    if not tokens:
        return INTEGRITY_NO_TEXT, []
    lowered = text.lower()
    flags = [name for name, marker in TRANSCRIPT_INTEGRITY_MARKERS.items() if marker in lowered]
    distinct_ratio = len(set(tokens)) / len(tokens)
    if distinct_ratio < DEGENERATE_DISTINCT_TOKEN_RATIO:
        flags.append("degenerate_repetition")
    if len(tokens) < MINIMUM_SPOKEN_TOKENS:
        flags.append(f"under_{MINIMUM_SPOKEN_TOKENS}_tokens")
    if flags:
        return INTEGRITY_CONTENT_ABSENT, flags
    return INTEGRITY_OK, []


def calculate_raw_scores(
    transcript: str,
    supply_chain_weights: dict[str, float],
    risk_words: Iterable[str],
    resolution_words: Iterable[str],
    window: int = WINDOW,
    supply_chain_index: PhraseIndex | None = None,
    risk_index: PhraseIndex | None = None,
    resolution_index: PhraseIndex | None = None,
    forbid_identical_span_pairs: bool = False,
) -> ScoreResult:
    """Calculate both raw scores for one transcript without dataset scaling."""

    if window < 0:
        raise ValueError("window must be non-negative")
    tokens = tokenize(transcript)
    supply_chain_index = supply_chain_index or build_phrase_index(supply_chain_weights)
    risk_index = risk_index or build_phrase_index(risk_words)
    resolution_index = resolution_index or build_phrase_index(resolution_words)
    supply_occurrences = find_indexed_occurrences(tokens, supply_chain_index)
    risk_occurrences = find_indexed_occurrences(tokens, risk_index)
    resolution_occurrences = find_indexed_occurrences(tokens, resolution_index)

    scrisk_weight_sum = 0.0
    resolution_weight_sum = 0.0
    risk_pairs = 0
    resolution_pairs = 0
    identical_span_pairs = 0
    identical_span_weight_sum = 0.0
    for supply in supply_occurrences:
        nearby_resolution = any(
            spans_within(supply, resolution, window) for resolution in resolution_occurrences
        )
        for risk in risk_occurrences:
            if not spans_within(supply, risk, window):
                continue
            identical_span = supply.start == risk.start and supply.end == risk.end
            if identical_span and forbid_identical_span_pairs:
                continue
            weight = supply_chain_weights[supply.term]
            if identical_span:
                identical_span_pairs += 1
                identical_span_weight_sum += weight
            scrisk_weight_sum += weight
            risk_pairs += 1
            # Resolution is intentionally a subset of SCRisk pairs.
            if nearby_resolution:
                resolution_weight_sum += weight
                resolution_pairs += 1

    word_count = len(tokens)
    scrisk_raw = scrisk_weight_sum / word_count if word_count else 0.0
    resolution_raw = resolution_weight_sum / word_count if word_count else 0.0

    return ScoreResult(
        word_count=word_count,
        supply_chain_occurrences=len(supply_occurrences),
        risk_occurrences=len(risk_occurrences),
        resolution_occurrences=len(resolution_occurrences),
        risk_pairs=risk_pairs,
        resolution_pairs=resolution_pairs,
        scrisk_weight_sum=scrisk_weight_sum,
        resolution_weight_sum=resolution_weight_sum,
        scrisk_raw=scrisk_raw,
        resolution_raw=resolution_raw,
        identical_span_pairs=identical_span_pairs,
        identical_span_weight_sum=identical_span_weight_sum,
    )


def normalize_raw_scores(
    raw_scores: Sequence[float],
    in_population: Sequence[bool] | None = None,
) -> tuple[list[float | None], float]:
    """Divide raw scores by their dataset population SD without centering.

    ``in_population`` marks the rows the SD is calculated over.  A row outside
    the population gets ``None`` rather than a number: its transcript failed
    the integrity check, so its score is undefined, not zero.  With
    ``in_population`` omitted every row is in the population, which is the
    original behaviour.
    """

    if not raw_scores:
        return [], 0.0
    if in_population is None:
        in_population = [True] * len(raw_scores)
    if len(in_population) != len(raw_scores):
        raise ValueError("in_population must be the same length as raw_scores")
    population = [score for score, keep in zip(raw_scores, in_population) if keep]
    if not population:
        raise ValueError("The standardization population is empty")
    standard_deviation = pstdev(population) if len(population) > 1 else 0.0
    if standard_deviation == 0.0:
        return [0.0 if keep else None for keep in in_population], standard_deviation
    return [
        score / standard_deviation if keep else None
        for score, keep in zip(raw_scores, in_population)
    ], standard_deviation


def _starter_dictionary(path: Path | None, fallback: Sequence[str]) -> list[str]:
    return list(fallback) if path is None else load_dictionary(path)


SCORE_OUTPUT_FIELDS = [
    "SCRisk_weight_sum", "SCRisk_raw", "SCRisk_sd", "SCRisk",
    "Resolution_weight_sum", "Resolution_raw", "Resolution_sd",
    "Resolution", "score_word_count", "supply_chain_occurrences", "risk_occurrences",
    "resolution_occurrences", "supply_chain_risk_pairs", "supply_chain_resolution_pairs",
    # Added with the corrected vocabulary.  Every one of these is a diagnostic
    # about how the score was reached, not a change to the score.
    "scrisk_identical_span_pairs", "scrisk_identical_span_weight_sum",
    "vocabulary_version", "transcript_integrity_status", "transcript_integrity_flags",
    "in_standardization_population",
]


def score_csv(
    input_path: Path,
    output_path: Path,
    library_path: Path,
    risk_path: Path | None,
    resolution_path: Path | None,
    text_column: str,
    window: int,
    limit: int | None = None,
    vocabulary_version: str = DEFAULT_VOCABULARY_VERSION,
    seed_weight: float = SEED_WEIGHT,
    excluded_supply_chain_terms: Sequence[str] = (),
    forbid_identical_span_pairs: bool = False,
    filter_transcript_integrity: bool = True,
) -> dict[str, Any]:
    """Score every input row, then write a new CSV with raw and scaled fields.

    Returns the run manifest, which is also written next to ``output_path``.
    """

    if input_path.resolve() == output_path.resolve():
        raise ValueError("Refusing to overwrite the input CSV; choose a separate --output path")
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")

    library_weights = load_supply_chain_library(library_path)
    risk_dictionary = _starter_dictionary(risk_path, STARTER_RISK_WORDS)
    resolution_words = _starter_dictionary(resolution_path, STARTER_RESOLUTION_WORDS)
    supply_chain_weights = build_supply_chain_vocabulary(
        library_weights, vocabulary_version, seed_weight, excluded_supply_chain_terms
    )
    risk_words = build_risk_vocabulary(risk_dictionary, vocabulary_version)
    supply_chain_index = build_phrase_index(supply_chain_weights)
    risk_index = build_phrase_index(risk_words)
    resolution_index = build_phrase_index(resolution_words)

    # Pass 1 retains only score objects, not the potentially very large
    # transcript strings.  This is important for the study's full dataset.
    with input_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        if text_column not in fieldnames:
            raise ValueError(f"{input_path} is missing required column {text_column!r}")
        results: list[ScoreResult] = []
        integrity: list[tuple[str, list[str]]] = []
        for row in reader:
            if limit is not None and len(results) >= limit:
                break
            text = row.get(text_column, "") or ""
            results.append(
                calculate_raw_scores(
                    text,
                    supply_chain_weights,
                    risk_words,
                    resolution_words,
                    window,
                    supply_chain_index,
                    risk_index,
                    resolution_index,
                    forbid_identical_span_pairs,
                )
            )
            integrity.append(assess_transcript_integrity(text))

    # A transcript that holds no spoken content is excluded from the
    # standardization population rather than standardized against it.  Its raw
    # score is a fact about the file and is retained; its standardized score is
    # undefined and is written blank.
    in_population = [
        not (filter_transcript_integrity and status == INTEGRITY_CONTENT_ABSENT)
        for status, _ in integrity
    ]
    scrisk_scaled, scrisk_sd = normalize_raw_scores(
        [result.scrisk_raw for result in results], in_population
    )
    resolution_scaled, resolution_sd = normalize_raw_scores(
        [result.resolution_raw for result in results], in_population
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Pass 2 rereads the input so existing columns are preserved without
    # retaining all transcript text in memory while the SD is calculated.
    with input_path.open(newline="", encoding="utf-8") as source, output_path.open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        reader = csv.DictReader(source)
        writer = csv.DictWriter(
            handle, fieldnames=fieldnames + SCORE_OUTPUT_FIELDS, extrasaction="ignore"
        )
        writer.writeheader()
        for row, result, scrisk, resolution, (status, flags), keep in zip(
            reader, results, scrisk_scaled, resolution_scaled, integrity, in_population
        ):
            row.update(
                {
                    "SCRisk_weight_sum": f"{result.scrisk_weight_sum:.12g}",
                    "SCRisk_raw": f"{result.scrisk_raw:.12g}",
                    "SCRisk_sd": f"{scrisk_sd:.12g}",
                    "SCRisk": "" if scrisk is None else f"{scrisk:.12g}",
                    "Resolution_weight_sum": f"{result.resolution_weight_sum:.12g}",
                    "Resolution_raw": f"{result.resolution_raw:.12g}",
                    "Resolution_sd": f"{resolution_sd:.12g}",
                    "Resolution": "" if resolution is None else f"{resolution:.12g}",
                    "score_word_count": result.word_count,
                    "supply_chain_occurrences": result.supply_chain_occurrences,
                    "risk_occurrences": result.risk_occurrences,
                    "resolution_occurrences": result.resolution_occurrences,
                    "supply_chain_risk_pairs": result.risk_pairs,
                    "supply_chain_resolution_pairs": result.resolution_pairs,
                    "scrisk_identical_span_pairs": result.identical_span_pairs,
                    "scrisk_identical_span_weight_sum": f"{result.identical_span_weight_sum:.12g}",
                    "vocabulary_version": vocabulary_version,
                    "transcript_integrity_status": status,
                    "transcript_integrity_flags": ";".join(flags),
                    "in_standardization_population": int(keep),
                }
            )
            writer.writerow(row)

    shared_terms = sorted(set(supply_chain_weights) & set(risk_words))
    manifest = {
        "vocabulary_version": vocabulary_version,
        "window": window,
        "seed_weight": seed_weight,
        "library_path": str(library_path),
        "library_term_count": len(library_weights),
        "supply_chain_term_count": len(supply_chain_weights),
        "risk_term_count": len(risk_words),
        "resolution_term_count": len(set(" ".join(normalize_term(t)) for t in resolution_words)),
        "excluded_supply_chain_terms": [
            " ".join(normalize_term(term)) for term in excluded_supply_chain_terms
        ],
        "forbid_identical_span_pairs": forbid_identical_span_pairs,
        "filter_transcript_integrity": filter_transcript_integrity,
        "terms_in_both_supply_chain_and_risk": shared_terms,
        "rows_scored": len(results),
        "rows_in_standardization_population": sum(in_population),
        "rows_content_absent": sum(
            1 for status, _ in integrity if status == INTEGRITY_CONTENT_ABSENT
        ),
        "rows_no_transcript_text": sum(1 for status, _ in integrity if status == INTEGRITY_NO_TEXT),
        "SCRisk_sd": scrisk_sd,
        "Resolution_sd": resolution_sd,
        "output_path": str(output_path),
    }
    manifest_path = output_path.with_suffix(output_path.suffix + ".scoring_manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"Scored {len(results):,} transcripts with vocabulary {vocabulary_version}")
    print(
        f"Supply-chain terms: {len(supply_chain_weights):,} "
        f"(library {len(library_weights):,}); risk terms: {len(risk_words):,}"
    )
    print(f"Terms in both vocabularies: {shared_terms or 'none'}")
    print(
        f"Excluded from standardization for transcript integrity: "
        f"{manifest['rows_content_absent']:,}"
    )
    print(f"SCRisk population SD: {scrisk_sd:.12g}; Resolution population SD: {resolution_sd:.12g}")
    print(f"Wrote {output_path}")
    print(f"Wrote {manifest_path}")
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="CSV containing transcript_text")
    parser.add_argument("--output", type=Path, required=True, help="new CSV to write")
    parser.add_argument("--library", type=Path, required=True, help="supply-chain terms.jsonl")
    parser.add_argument("--risk-words", type=Path, help="reviewed risk dictionary; defaults to starter terms")
    parser.add_argument(
        "--resolution-words",
        type=Path,
        help="reviewed resolution dictionary; defaults to starter terms",
    )
    parser.add_argument("--text-column", default="transcript_text")
    parser.add_argument("--window", type=int, default=WINDOW, help="maximum token distance; default: 10")
    parser.add_argument(
        "--limit",
        type=int,
        help="score only the first N rows for a small validation run; omit for the full dataset",
    )
    parser.add_argument(
        "--vocabulary-version",
        choices=VOCABULARY_VERSIONS,
        default=DEFAULT_VOCABULARY_VERSION,
        help=(
            "v1_library_only reproduces the original run: terms.jsonl alone, no seeds, "
            "no inflections. v2_seeds_inflections adds the 16 supply-chain seeds at "
            "--seed-weight and completes the regular inflections of the supply-chain and "
            "risk vocabularies. Default: v2_seeds_inflections"
        ),
    )
    parser.add_argument(
        "--seed-weight",
        type=float,
        default=SEED_WEIGHT,
        help="weight given to the 16 supply-chain seeds in v2; default: 1.0",
    )
    parser.add_argument(
        "--exclude-supply-chain-terms",
        default="",
        help=(
            "comma-separated terms to drop from the supply-chain vocabulary. For "
            "sensitivity runs only; the default keeps every term the version defines"
        ),
    )
    parser.add_argument(
        "--forbid-identical-span-pairs",
        action="store_true",
        help=(
            "do not let a term that appears in both the supply-chain and risk "
            "vocabularies pair with its own occurrence at distance 0. For sensitivity "
            "runs only; off by default so the version's pairing rule is unchanged"
        ),
    )
    parser.add_argument(
        "--no-transcript-integrity-filter",
        dest="filter_transcript_integrity",
        action="store_false",
        help=(
            "standardize and report every row, including transcripts that hold no "
            "spoken content. Reproduces the original run's standardization population"
        ),
    )
    return parser.parse_args()


def main() -> None:
    configure_csv_field_size_limit()
    args = parse_args()
    if args.window < 0:
        raise SystemExit("--window must be non-negative")
    try:
        score_csv(
            args.input,
            args.output,
            args.library,
            args.risk_words,
            args.resolution_words,
            args.text_column,
            args.window,
            args.limit,
            args.vocabulary_version,
            args.seed_weight,
            [term.strip() for term in args.exclude_supply_chain_terms.split(",") if term.strip()],
            args.forbid_identical_span_pairs,
            args.filter_transcript_integrity,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
