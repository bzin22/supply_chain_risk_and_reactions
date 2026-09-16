# Test fixtures

`synthetic_supply_chain_library.jsonl` is a 15-term stand-in for the generated
supply-chain library, in the same JSONL shape as
`artifacts/sec_10k_supply_chain/terms.jsonl`. It is committed so the unit tests
run on a clean checkout, where the real library is a gitignored local artifact.

It is a test fixture and nothing else. It is never used for scoring, never used
in `validation_report.md`, and the terms in it are not a proposed supply-chain
vocabulary. `solution` and `solutions` are deliberately absent: the overlap
between the resolution dictionary and the supply-chain vocabulary is a real open
question and it must be settled against the final reconstructed vocabulary, not
against a fixture.
