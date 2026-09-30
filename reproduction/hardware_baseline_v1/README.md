# Portable hardware inputs

`calls.csv.gz` contains all 12,832 input call records, including exclusions.
The common sample is 11,950 calls from 378 firms; the canonical roster stays at
379. `score_valid` is false for 119 issuer/period transcript conflicts.
CIKs are strings. `call_id` and `provider_quarter_label` are stable source keys;
`issuer_fiscal_period_label` is the adjudicated fiscal period (including `2018T`
for VF's transition), blank when unresolved. Do not interpret a provider label
as independently verified issuer history. `quarter_label` is retained as the
legacy provider identifier for compatibility. Dates are earnings releases.

`date_audit.csv.gz` covers every input once, with source/evidence and explicit
unresolved exclusions. `collision_adjudications.csv` documents all original
shared events. `schema.json` defines types, units and missing cells.
`roster_379.csv` and `screened_universe_400.csv` preserve fixed membership and
classification sources; observed coverage fields reflect the corrected sample.
`pair_coverage.csv.gz` retains the 16,000 requested slots and collection
provenance, with new audit and analysis flags. `security_history.csv` documents
historical ticker/CIK/security mappings. Current physical-product/headquarters
classification does not establish historical international supply-chain exposure.

`manifest.json` hashes public files; `audit_input_contract.json` and
`private_inputs.json` identify private prerequisites without redistributing them.
See [input access](INPUT_ACCESS.md), [results](../../docs/hardware_baseline/README.md),
and [audit scope and limitations](../../docs/hardware_baseline/DATE_AUDIT.md).
