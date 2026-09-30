# Portable hardware inputs

`calls.csv.gz` contains one row per valid call, including the 88 excluded calls.
`schema.json` gives ordered columns, types, units and missing-value semantics.
Read CIKs as strings (leading zeros matter). `call_id` is the stable call key;
`portfolio_cik` identifies the current roster company, while `cik`,
`historical_ticker` and `security_id` identify its historical issuer/security.
`quarter_label` is fiscal year/quarter; event dates can cross calendar years.

`roster_379.csv` is the canonical reporting roster. It records historical CIKs,
ticker aliases, primary physical products, classification and headquarters
sources, listing-history evidence, company-screen date, requested study period,
and first/last valid and eligible quarters and events. Those endpoints describe
observed coverage, not uninterrupted eligibility. `pair_coverage.csv.gz` records
every requested issuer-quarter, including holes. `security_history.csv` supplies
historical ticker/CIK validity intervals and mapping evidence. Provider history
starts are security-history evidence, never founding dates. Headquarters and
product classifications are current as of the screen, not year-by-year claims.
`screened_universe_400.csv` preserves the fixed pre-analysis screen and includes
the 21 firms with no usable calls. No share classes are counted as extra firms.

`manifest.json` hashes public inputs, code, dictionaries and reference outputs.
`source_run.json` identifies the private source run; `private_inputs.json` lists
relative paths and hashes only. It contains no raw payloads. See
[access instructions](INPUT_ACCESS.md) and the
[results and methods](../../docs/hardware_baseline/README.md).
