# Validation report: reconstructed resolution dictionary

Source date 2026-09-16. Validated at commit `16b2309bbae1f39d3546440ef5057c1c4ea2fdf8-dirty`. Directory `dictionaries/theile_reconstruction_v1/resolution/`.

**Scope: source validation only.** Everything in this report runs on a clean checkout of this repository. Its inputs are the paper's published tables, the committed dictionaries, and the committed synthetic supply-chain fixture. No local artifact, no transcript corpus, no generated supply-chain library.

**The corpus diagnostic is not here, and it is not PR validation.** Zero rates and matched-term counts over real transcripts are an archived local diagnostic. They cannot be reproduced from this repository: they need `earnings_call_transcripts.csv` and `artifacts/sec_10k_supply_chain/terms.jsonl`, both gitignored, and other work in this repository regenerates both. `run_validation.py` writes them to `outputs/resolution_validation/`, which is gitignored, together with the hashes of the inputs each run used. Nothing there is evidence that this dictionary is correct, and no number in it should be quoted as a result.

No CAR, return, or regression output was read at any point in building or validating this dictionary.

## 0. Specification and hashes

**The primary Resolution specification is `resolution_terms_conservative_baseline.txt`, 55 terms.** It is the only dictionary the production pipeline loads, and the pipeline produces exactly one Resolution measure from it. The other three files in this directory are documented sensitivity artifacts and are never a default.

| dictionary | role | terms | sha256 |
| --- | --- | --- | --- |
| resolution (conservative baseline) | **primary** | 55 | `070b8cdc168a0db96db7f68fef5b0f3e08bde10ec5d7b4161ed882453a57d464` |
| risk (reconstructed full) | **primary** | 161 | `c5f9fecb77f52802047aa7094e3999e428c3a53f8c936424d7ab50b9884136b8` |
| paper_anchor | sensitivity | 28 | `d28cadd63975026d78a979380859cb47a6489cd1bf7e75de756f393bf3fcccdd` |
| expanded_sensitivity_extra_terms | sensitivity | 42 | `c3739478bda22114e62090b5c78eb12f23b939e1bf63a0f4cc849ae5e2ca7f5e` |
| overlap_sensitivity | sensitivity | 53 | `1517d8575318c06fb64d7d9b3d79a5c8363cc822b5dbd3341d3980fcfc0b8599` |
| synthetic supply chain fixture | test fixture | 15 | `002e210cc1c28cbc84c2b570eb6ac920f0cf57786c8bb7df5c8653bd9c8dbc92` |

Window 10 tokens. Paths and the full record in `validation_run.json`.

Generated files in this directory carry no runtime date. The source date above is fixed and supplied, so a rebuild that changes nothing substantive leaves every hash in `source_manifest.json` unchanged. Two consecutive rebuilds produce byte-identical output except for the commit recorded above.

## 1. Table 4 coverage

Table 4 prints 30 slots and 28 distinct keywords. Slots 24 and 25 repeat slots 22 and 23 (`enhance` 591, `recover` 566). The repetition is in the typeset page, confirmed by rendering page 8 at 250 dpi, so it is not a PDF extraction artifact and no OCR correction was applied.

- **conservative_baseline_PRIMARY** **(PRIMARY)**: 55 terms, 28/28 Table 4 terms present
- **paper_anchor** (sensitivity): 28 terms, 28/28 Table 4 terms present
- **expanded_sensitivity** (sensitivity): 97 terms, 28/28 Table 4 terms present
- **overlap_sensitivity** (sensitivity): 53 terms, 26/28 Table 4 terms present, missing ['solutions', 'solution']

The overlap-adjusted variant deliberately drops `solution`, `solutions`, so it does not cover Table 4 in full. That is the point of it, and it is why it is a sensitivity artifact rather than a candidate primary.

Coverage passes for the primary dictionary and for every sensitivity variant that is meant to cover Table 4.

## 2. Exact token matching

Matching is whole-token, case-folded, against the tokenizer the scoring script already uses. Each case would be a false positive under substring matching.

| case | term that must not fire | terms actually matched | result |
| --- | --- | --- | --- |
| `helpful_is_not_help` | `help` | (none) | pass |
| `prefix_is_not_fix` | `fix` | (none) | pass |
| `unresolved_is_not_resolved` | `resolved` | (none) | pass |
| `dissolved_is_not_solved` | `solved` | `dissolved` | pass |
| `easy_going_is_not_easy` | `easy` | (none) | pass |
| `easing_is_not_easy` | `easy` | `easing` | pass |

## 3. The paper's proximity rule

A supply chain occurrence counts toward Resolution only when a risk occurrence is within ten tokens of it and a resolution occurrence is within ten tokens of the *same* supply chain occurrence. Run with the primary resolution dictionary, the 161-term primary risk library, and the committed synthetic supply-chain fixture `fixtures/synthetic_supply_chain_library.jsonl`.

| case | expect Resolution | Resolution pairs | SCRisk pairs | result |
| --- | --- | --- | --- | --- |
| `sc_risk_and_resolution_together` | yes | 1 | 1 | pass |
| `sc_risk_without_resolution` | no | 0 | 1 | pass |
| `resolution_far_from_supply_chain` | no | 0 | 1 | pass |
| `generic_resolution_no_supply_chain_risk` | no | 0 | 0 | pass |
| `resolution_without_risk` | no | 0 | 0 | pass |
| `resolution_and_risk_on_different_supply_chain_words` | no | 0 | 1 | pass |

The three that matter most are `generic_resolution_no_supply_chain_risk`, `resolution_without_risk` and `resolution_and_risk_on_different_supply_chain_words`. All score zero, which is what the measure is for: generic positive language outside a supply-chain-risk context must not count, and equation (2) ties the risk word and the resolution word to the same supply chain word, not to each other.

## 4. Overlap, settled comparisons only

Every library below is committed, so every row reproduces on a clean checkout.

| resolution variant | compared against | shared | terms |
| --- | --- | --- | --- |
| conservative_baseline_PRIMARY | primary_risk_library_reconstructed_full_161 | 0 | - |
| conservative_baseline_PRIMARY | risk_observed_baseline_144 | 0 | - |
| conservative_baseline_PRIMARY | published_reference_risk_table_3_144 | 0 | - |
| conservative_baseline_PRIMARY | paper_supply_chain_table_2_top30 | 0 | - |
| conservative_baseline_PRIMARY | paper_supply_chain_seed_terms_table_1 | 0 | - |
| paper_anchor | primary_risk_library_reconstructed_full_161 | 0 | - |
| paper_anchor | risk_observed_baseline_144 | 0 | - |
| paper_anchor | published_reference_risk_table_3_144 | 0 | - |
| paper_anchor | paper_supply_chain_table_2_top30 | 0 | - |
| paper_anchor | paper_supply_chain_seed_terms_table_1 | 0 | - |
| expanded_sensitivity | primary_risk_library_reconstructed_full_161 | 0 | - |
| expanded_sensitivity | risk_observed_baseline_144 | 0 | - |
| expanded_sensitivity | published_reference_risk_table_3_144 | 0 | - |
| expanded_sensitivity | paper_supply_chain_table_2_top30 | 0 | - |
| expanded_sensitivity | paper_supply_chain_seed_terms_table_1 | 0 | - |
| overlap_sensitivity | primary_risk_library_reconstructed_full_161 | 0 | - |
| overlap_sensitivity | risk_observed_baseline_144 | 0 | - |
| overlap_sensitivity | published_reference_risk_table_3_144 | 0 | - |
| overlap_sensitivity | paper_supply_chain_table_2_top30 | 0 | - |
| overlap_sensitivity | paper_supply_chain_seed_terms_table_1 | 0 | - |

**Risk library: no overlap.** Not one of the 161 terms in the primary risk dictionary, nor of its observed-baseline variant, nor of the 144 risk keywords printed in Table 3, appears in the primary resolution dictionary or in any sensitivity variant. The closest call is `unresolved`, a risk word that shares a root with `resolved` and carries the opposite sense. Exact token matching keeps them apart, which is why the matching test above includes it.

**Supply chain vocabulary: not settled, and deliberately left open.** The final reconstructed supply-chain vocabulary does not exist yet. The only one available is the repo's provisional 10-K-derived library, gap number two in the repo README. An overlap measured against it is a property of that provisional input, not a finding about this dictionary, so it is not reported here: it goes to `outputs/resolution_validation/provisional_overlap_report.csv` with the archived diagnostic.

`solution` and `solutions` stay in the primary dictionary. `solutions` is Table 4's second most frequent keyword at 4,289 and `solution` its tenth at 1,932; removing either would depart from the paper on the strength of a provisional input. The definitive overlap calculation is deferred until the reconstructed supply-chain vocabulary lands.

What is at stake, so the deferred check has a stated expectation. Equation (2) counts the cosine similarity of a supply chain word `w` when some risk word `r` and some resolution word `m` are each within ten tokens of `w`. A term in both libraries can act as its own `m` at distance zero, so every occurrence of it near a risk word turns an SCRisk pair into a Resolution pair for free. In "our supply chain solution addressed the shortage", `solution` would be the supply chain word, `shortage` the risk word, and `solution` its own resolution word. If the final vocabulary contains either term, the fix is a decision about which library keeps it, and `resolution_terms_overlap_sensitivity.txt` already holds the variant that drops them from the resolution side.

## 5. What is still uncertain

- **The Oxford edition is unknown.** The paper says only "the Oxford dictionary" and names no product, edition, or date. Hassan et al. (2019), whose method the paper follows for the risk library, are equally vague. The product whose synonym runs would most plausibly generate this library, the Oxford Thesaurus of English, is behind a subscription: `premium.oxforddictionaries.com` returns an OAuth redirect, `oed.com` bounces to its home page, and Lexico, the free surface that existed when Hassan et al. wrote, shut down in 2022. The Internet Archive was returning "Temporarily Offline" on the retrieval date, so no archived capture could be read either. Everything Oxford-derived here comes from the free Oxford Advanced Learner's Dictionary, which prints one or two synonym cross-references per sense rather than a thesaurus run. See `source_manifest.json`.

- **The tail of the library is unpublished.** Table 4 is the top 30 by frequency. How many terms sit below rank 30 is not stated. For the risk library the paper does publish the full list, so a comparable resolution library could plausibly run to a hundred terms or more. The primary dictionary reaches 55.

- **Two Table 4 entries are lost to the duplication.** Slots 24 and 25 should have held the 24th and 25th most frequent keywords. Because the column is printed in descending order, their frequencies lie between 566 (slot 23) and 553 (slot 26), so both are in the range 554 to 566. Which two words they are is unrecoverable from the published paper.

- **Table 4 frequencies are not raw corpus counts.** Table 2's note says frequency is "the count of occurrences relevant to the construction of the SCRisk measure", that is, occurrences that satisfied the proximity conditions. `help` at 5,448 across 129,981 calls is not how often `help` is spoken. A form like `mitigating` being absent from the top 30 is therefore weak evidence that it is outside the library.

- **Inflection policy is inferred, not stated.** The published risk library carries many inflections of a headword (`risk`/`risks`/`risky`/`riskier`/`riskiest`/`risked`/`risking`/`riskiness`) but not blanket regular inflection: `threat` appears without `threats`, `hazard` without `hazards`, `peril` without `perils`. The primary dictionary follows that pattern by adding only the forms Oxford itself prints, and holds regular plurals Oxford omits back to the sensitivity file.

- **The supply-chain overlap is unresolved by construction.** See section 4.

- **Behaviour on real transcripts is not validated here.** That is the archived local diagnostic, and it currently runs against a provisional supply-chain library and a provisional firm universe. It is a check on behaviour, not evidence of correctness, which is why it is gitignored rather than tracked.

## 6. Recommendation

`resolution_terms_conservative_baseline.txt`, 55 terms, is the primary specification and is already wired into the scoring script as the only default. It covers every Table 4 keyword, adds only forms an Oxford entry prints, and adds exactly two words beyond the Table 4 roots: `alleviate` and `settle`, the synonym cross-references Oxford puts on the two seed headwords the paper names.

The anchor, expanded and overlap-adjusted files stay as predeclared sensitivity specifications. Declare them before any outcome analysis runs. Do not promote one to primary on the strength of an outcome.

