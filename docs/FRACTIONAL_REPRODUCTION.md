# Reproducing the documented fractional-allocation results

From the repository root, with **Python 3.14.7** installed:

```sh
sh scripts/reproduce_fractional.sh
```

If that interpreter is not `python3`, set `PYTHON=/path/to/python3.14` before
the command. No named Conda environment is required. The script creates an
isolated `.venv-fractional`, installs the exact direct and transitive versions
in `requirements-fractional.lock`, runs scoring/CAR/allocation tests, and
regenerates five PNGs, a five-page PDF, five tables and 630 pairwise
comparisons in `outputs/fractional_reproduction_v1/`. Package installation
requires network access or an already populated pip cache. The analysis itself
is offline. Pass a different output directory as the script's first argument
for another run; existing output directories are never overwritten.

The smaller invocation in an already installed pinned environment is:

```sh
python -m analysis.fractional_reproduction --output outputs/fractional_new
```

## Versioned inputs and implementations

`reproduction/fractional_v1/analysis.csv.gz` is a 5.6 MB compressed CSV containing
all **58,305** source calls, including the **5,772** excluded from portfolios.
The common eligible sample is **52,533 unique calls, 2,026 unique CIKs**. There
are no transcript texts, evidence excerpts, matched words, raw API responses,
or daily price histories. Export uses an explicit column allowlist and copies
the original CSV cells verbatim. Identifiers and SIC codes must be read as
strings, preserving leading zeroes. Empty fields represent missing values.
`schema.json` groups every column, declares flags and units, and identifies
string columns. Raw scores, population SDs, standardized scores, CARs, matching
counts, industry assignments, dates, eligibility and exclusion flags remain
available. Dictionary and source hashes are stored once in the manifest.

| Stage | Actual implementation used by the documented run |
| --- | --- |
| Tokenization, exact phrase matching, dictionary loading, SD scaling | `calculate_supply_chain_transcript_scores.py` |
| Optimized pair scoring, historical SIC assignment, Carhart OLS and both CAR windows | `analysis/primary_event_study/core.py` |
| Factor ZIP parsing, reused by `core.py` | `calculate_carhart_event_returns.py` |
| Call preparation, release-date policy, score population, price identity, eligibility | `analysis/primary_event_study/run.py`, `prepare.py`, `dates.py` |
| Frozen adjusted-price selection, including retries | `run.py`, `collect_prices.py`, `analysis/retry_primary_price_responses.py` |
| Original deterministic portfolios, pre-fractional thresholds | `analysis/primary_event_study/portfolios.py` |
| Final fractional and nested allocation, original means/intervals and figure rendering | `analysis/build_modified_portfolio_chart_pdfs.py` |
| Portable export and chart reproduction | `analysis/export_fractional_dataset.py`, `analysis/fractional_reproduction.py` |
| Joint uncertainty for overlapping portfolios | `analysis/fractional_covariance.py` |

The historical implementation is preserved byte for byte. Two chart source
files have since had descriptive labels and output filenames simplified; their
original snapshots and exact replacements are recorded under
[`provenance/fractional_naming_v1/`](../provenance/fractional_naming_v1/README.md).
The current top-level scoring and CAR scripts also differ from the frozen-run
versions because `main` merged primary dictionary handling and study-period
validation. Their prior snapshots and both sets of hashes are recorded under
[`provenance/fractional_main_integration_v1/`](../provenance/fractional_main_integration_v1/README.md).
The reproduction command verifies these records before calculating. It uses the
actual `core.py` CAR implementation; the top-level CAR CLI is not the final
pipeline. Historical manifests and reference tables are
copied unchanged under `reproduction/fractional_v1/historical/`. These are
historical evidence, not fresh validation claims. Some paths in them point to
private files deliberately excluded from Git.

The canonical dictionaries are unchanged:

| Library | Terms | File under `dictionaries/theile_reconstruction_v1/` |
| --- | ---: | --- |
| Supply chain | 254 | `supply_chain/supply_chain_terms.jsonl` |
| Reconstructed-full risk | 161 | `risk/risk_terms_reconstructed_full.txt` |
| Conservative Resolution baseline | 55 | `resolution/resolution_terms_conservative_baseline.txt` |

The corresponding SHA-256 values are in the package manifest. No dictionary
retraining, inflection expansion, seed additions or alternative baseline is
performed. The recovered Resolution source manifest describes additional
historical sensitivity artifacts; only the baseline is required here, and
those other artifacts are not claimed to be present or revalidated.

## Preserved analytical choices

- Study window: 2010Q1–2019Q4. All 58,305 validated calls enter score scaling.
- Weighted exact supply/risk occurrence pairs at closest-token distance **≤10**,
  including identical spans. Resolution counts the same pair only when
  Resolution language is within 10 tokens of its supply-chain span.
- Divide weighted sums by transcript token count, then by population SD
  (`ddof=0`), without centering. No substitutions for legacy heuristic flags.
- Event date: the frozen reported earnings-release date. Independent call-date
  confirmation/conflict fields remain audit information. No after-hours shift.
- Historical SIC: latest available dated filing known by fiscal period end;
  unavailable or conflicting classifications are explicitly excluded.
- Adjusted-close arithmetic daily returns; Carhart OLS with intercept and
  market-minus-RF, SMB, HML, momentum. Exactly 200 complete observations at
  trading offsets −209…−10. Day 0 is the first factor-calendar trading date on
  or after the release date. CAR(0,1) sums 2 days; CAR(2,60) sums 59 days.
- The common sample requires valid scores, verified ticker/CIK/security
  identity, both CARs and SIC division. Winsorize all four variables globally
  at linear 1st/99th percentiles of these 52,533 calls.
- Fractional SCRisk quintiles are sorted within SIC division. A tied block's
  overlap with each equal-mass quintile determines a common proportion for
  every member. Resolution is sorted within each **division × fractional
  SCRisk parent**, using those parent weights as base mass. Pool matching
  quintiles across divisions. All zero scores remain included.

`historical/winsorization_thresholds.csv` preserves the original cutoffs.
The command recomputes them from the analysis dataset and checks agreement.
It retains the historical pandas float parser; decimal strings are not
silently reserialized before parsing. All historical table fields, including
percentage columns, are checked to their published precision (10 decimal
places). New outputs retain 17 significant digits.

The reproducibility target is numerical: every historical table field must
match to its published ten-decimal precision, which the command asserts and
fails on. Figures are checked by hand. The five regenerated PNGs were
byte-identical between the original Conda environment and a fresh PyPI
environment on macOS arm64, and all five PDF pages were opened and read for
clipped labels, missing legends and wrong values. The command does **not**
compare its PNGs to the README images: those are 1650x1275 renders of the PDF
at 150 dpi, while the renderer writes 1980x1530 pages at 180 dpi, so the two
sets cannot be equal byte-for-byte. PDF creation timestamps also vary, so PDF
byte equality is not a target either.

## Counts and covariance-aware comparisons

Each SCRisk portfolio has fractional mass **10,506.6**; each nested cell has
mass **2,101.32**. A call may contribute to several portfolios. The new tables
distinguish `fractional_mass` (sum of weights), `contributing_calls` (distinct
call IDs with positive weight), `firms` (distinct CIKs), and `membership_rows`
(the number of rows in the expanded allocation). `effective_n` is retained
as a compatibility alias for fractional mass; it is **not** a Kish effective
sample size or a count of independent observations. Unique counts must not
be summed across portfolios.

The historical pooled Resolution table reported 77,997 membership rows as
“contributing calls” in its first portfolios. This exceeded the source call
count because one call could appear through several SCRisk parents. The new
table corrects that descriptive count. Means, standard errors and intervals
still use the original fractional calculation and are verified unchanged.

The corrected tables are what `docs/fractional_results/*.csv` publishes. The
frozen originals the command compares against stay byte-for-byte in
`reproduction/fractional_v1/historical/`, which is also the exporter's default
`--reference-tables` directory. An earlier exporter read those reference tables
from `docs/fractional_results/`; the existing package's `exporter_sha256`
therefore records the exporter as of commit `4f35baf`, before that path moved.
Nothing in the reproduction path verifies `exporter_sha256`, and the packaged
data, reference tables, historical code hashes and dictionary hashes are all
unchanged, so the frozen package stays valid. A future export records its own
exporter hash.

For portfolio k, let Wk be total weight and μk its weighted mean. A firm's
influence is `u[g,k] = sum_i_in_g w[i,k] * (y[i] - μk) / Wk`, multiplied by
`sqrt(Gk / (Gk - 1))`. The joint covariance is the cross-product of these
influences, aligned by CIK across all portfolios. Its diagonal exactly
preserves the original marginal variances. A B−A comparison uses
`var(B) + var(A) - 2*cov(A,B)`, implemented as the squared norm of the
influence difference to avoid cancellation for identical portfolios.

Contrasts use a t critical value with `min(GA, GB) - 1` degrees of freedom.
`portfolio_comparisons.csv` also shows the incorrect independence-based SE
for audit, shared calls, and shared firms (including different calls from the
same firm). The 630 comparisons cover all pairs within each of the five
panels. They are unadjusted descriptive intervals, not multiple-testing
controlled findings. Inference holds allocations fixed and does not cover
common-date cross-firm shocks, model/dictionary selection, or causal effects.

## Rebuilding from private raw inputs

This route starts from the **frozen validated transcript CSV**, not from a new
provider download. Recollecting transcripts cannot guarantee the same
responses or reconstruct all past adjudication decisions. The upstream raw
collection/adjudication workflow is therefore outside the reproducible
snapshot; `extract_earnings_call_transcript_data.py` alone does not rebuild v1.

Every required local raw input is enumerated with an exact relative path and
SHA-256 in `reproduction/fractional_v1/raw_inputs.json` (2,215 files). The main
path families are:

| Input | Exact path or root |
| --- | --- |
| Frozen transcripts | `data/final/earnings_call_transcripts_validated_2010_2019_v1.csv` |
| Frozen metadata, SIC history, dates, ticker links | `artifacts/primary_event_study_2010_2019_v1/{metadata,confirmed_dates,call_date_evidence_decisions,sic_history,ticker_history}.csv` |
| Date map and evidence | `data/call_dates/call_dates_v20260916/{call_date_mapping,source_evidence}.csv` |
| Archived adjusted-price envelopes and factor ZIPs | `.archive/post_2019_removed_20260916/artifacts/earnings_call_supply_chain/ppmi_svd_full_20260910/event_study_inputs/` |
| Supplemental prices and successful retries | `artifacts/primary_event_study_release_dates_v1/prices/` |

The archive path is historical storage; it does not extend the study period.
Keep these files outside Git. Mount or symlink an authorized local copy at
the recorded paths in a private checkout. Check completeness first:

```sh
.venv-fractional/bin/python -m analysis.check_fractional_raw_inputs \
  --input-root /path/to/private/input/root --report outputs/raw-input-check.json
```

Once those frozen inputs are mounted at the checkout paths, use the pinned
environment for a new pilot and full run. On macOS wrap long commands in
`caffeinate -i` if the laptop might sleep:

```sh
.venv-fractional/bin/python -m analysis.primary_event_study.run pilot \
  --date-policy release --output outputs/raw_rebuild_v2/pilot
# Inspect the scoring crosscheck, matches, date/SIC gates and daily return audit.
# Record actual findings in outputs/raw_rebuild_v2/pilot/INSPECTED.md.
.venv-fractional/bin/python -m analysis.primary_event_study.run full \
  --date-policy release --pilot outputs/raw_rebuild_v2/pilot \
  --output outputs/raw_rebuild_v2/full
```

Do not fabricate the inspection record. The full runner checks pilot code,
dictionaries and auxiliary-input hashes. Omit `--reuse-scores` to score the
frozen transcripts afresh; the historical run reused verified raw scores from
an earlier run. The historical `inspect_release_date_pilot.py` and
`verify_primary_event_study.py` are preserved as audit tools but contain
dependencies on prior private outputs; they are not the portable entry point.

Compare the new scored-CAR file to the packaged analysis fields by `call_id`
before accepting a new version. Original source files and existing outputs
must never be overwritten. The exporter deliberately requires the exact
documented source hash; a fresh raw run with different audit paths/timestamps
will require a new reviewed package even if all numerical values agree.

Auxiliary acquisition/preparation code is versioned in `prepare.py` and
`collect_prices.py`; network collection needs SEC identification and provider
credentials. Fresh retrieval can change price/factor vintages and inclusion.
`prepare metadata` additionally references historical commit `ae9526a` for
ticker links, which is not assumed present in a shallow or standalone checkout.
Use the frozen ticker-history input from the inventory for exact reproduction.
Rebuilding auxiliary inputs from changing services is not equivalent to
reproducing the documented results.

## Validation and limitations

See [FRACTIONAL_VALIDATION.md](FRACTIONAL_VALIDATION.md) for the clean-checkout
test evidence, environment details and checks actually completed. Historical
verification manifests do not substitute for those fresh checks. Restricted
raw inputs are intentionally absent from a public clean checkout, so the
portable command starts from the analysis dataset. Missing private inputs
fail the raw preflight explicitly rather than being silently skipped.
