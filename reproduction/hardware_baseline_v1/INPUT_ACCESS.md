# Private inputs and raw-stage reproduction

The portable command uses transcript-free derived raw scores and refitted CARs.
To independently rescore and refit, obtain the private source vintages from the
study maintainer through an authorized transfer, subject to provider rights.
Restore relative paths in `private_inputs.json` beneath a private root. Verify
SHA-256; the inventory is not redistribution permission. Preserve raw JSON
transcripts, adjusted-close responses, historical SIC and French factor archives.
No credential is needed for the cached-data route below.

The corrected private `artifacts/hardware_fiscal_date_audit_20260930/refit_inputs.csv.gz`
contains stable identity/raw-score references and price hashes, without obsolete
regressions. `audit_input_contract.json` pins this input, SIC tables and factor
archives. The public all-call date ledger is authoritative. Frozen/provider
metadata cannot bypass it. Price payload hashes and transcript content hashes
are checked during use; `--rescore` recomputes exact dictionary scores and
compares them with retained raw scores.

```sh
python -m analysis.hardware_us400.rebuild_audited   --private-root /path/to/private-tree   --output /path/to/new-pilot --pilot --rescore
# Inspect the pilot before the full run.
python -m analysis.hardware_us400.rebuild_audited   --private-root /path/to/private-tree   --output /path/to/new-full --rescore
```

Omitting `--rescore` reuses the unchanged hash-linked raw scores, but still
recomputes scaling, all CARs, historical SIC, eligibility and fractional results.
All outputs must be new directories. There are no network requests. Private
intermediate outputs include provenance paths and must stay outside Git; only
the public schema allowlist is exported in `calls.csv.gz`.

For diagnostic screening of any call dataset against the local caches:

```sh
python -m analysis.hardware_us400.audit   --private-root /path/to/private-tree   --calls reproduction/hardware_baseline_v1/calls.csv.gz   --output /path/to/new-diagnostics.csv
```

Diagnostics are flags, not date evidence or automatic adjudications. Fiscal
ends and release dates need explicit source matching. Historical SEC `fy`
conventions, comparative dates and forecast mentions require review. The code
never guesses a release from a quarter label or date window. Fresh collection
is a separate authorized task; keep any Alpha Vantage key in the environment.
