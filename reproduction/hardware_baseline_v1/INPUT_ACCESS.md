# Private inputs and full raw-stage reproduction

The portable command needs no provider credentials or private files. It
reproduces figures and tables from derived scores/CARs, not the raw-data stages.
The source code for scoring, issuer-quarter reconciliation, dates, historical
SIC, price identity and Carhart fitting is included under
`analysis/hardware_us400/`, `analysis/primary_event_study/` and `scoring/`.

To repeat raw scoring and regression, an authorized researcher needs the
original frozen corpus and licensed provider evidence. Obtain the exact source
vintages from the study maintainer through an authorized private transfer,
subject to provider access rights. Restore repository-relative paths listed in
`private_inputs.json`, and verify SHA-256 before using them. This manifest is a
content inventory, not permission to redistribute. It includes the frozen v1
transcript CSV, supplemental transcript JSONs, enriched prepared-call manifest,
company/security manifests, historical SIC and ticker caches, adjusted-price
responses, release/call-date evidence, factor archives and previous-run parity
reference. Auxiliary evidence hashes do not imply that public websites retain
the same historic content today.

Alpha Vantage transcripts, EARNINGS dates and TIME_SERIES_DAILY_ADJUSTED prices
require an account with the relevant endpoint entitlements. Keep
`ALPHAVANTAGE_API_KEY` only in the process environment; never write it into Git.
For fresh collection, reconcile issuer/fiscal-quarter caches and predecessor
aliases with `python -m analysis.hardware_us400.inventory` before invoking
`analysis.hardware_us400.data`. Collection is separate from the portable route
and can incur API usage. Do not replace frozen inputs with newly fetched
vintages: revisions will change hashes and may change estimates. Factor inputs
are the daily Fama–French three factors and momentum archives from the
[Kenneth French Data Library](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html);
retain the exact archived vintages listed in the private manifest.

With the private input tree restored and dependencies installed, rerun the
bounded pilot using the final enriched input (this performs fresh scoring and
CAR fitting):

```sh
python -m analysis.hardware_us400.run pilot \
  --input data/final/hardware_portfolio_us400_2010_2019_v1/prepared_enriched_calls.csv \
  --output outputs/hardware_private_review/pilot
```

Inspect the pilot's score/CAR parity tables, event-date audits, exclusions and
figures. Only after inspection, place a short `INSPECTED.md` in that pilot
output directory; the full driver requires this marker, matching source-code
hashes and a passed pilot. Then run:

```sh
python -m analysis.hardware_us400.run full \
  --input data/final/hardware_portfolio_us400_2010_2019_v1/prepared_enriched_calls.csv \
  --pilot-dir outputs/hardware_private_review/pilot \
  --output outputs/hardware_private_review/full
```

Outputs must be new directories. The original frozen corpus is hash-checked
and never overwritten. Raw transcripts, daily prices, factors and caches stay
in ignored paths. The three `scripts/*hardware_us400*` helpers preserve the
source-specific history/date enrichment operations; the restored enriched
manifest already incorporates these decisions. They are not needed by the
offline route or to rescore/refit from the restored final manifest.
