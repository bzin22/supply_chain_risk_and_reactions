# Theile et al. risk dictionary reconstruction

## Recommendation

Use `risk_terms_observed_baseline.txt` as the conservative replication dictionary. It contains only the 144 exact forms printed in Table 3. `risk_terms_reconstructed_full.txt` adds 17 high-confidence upstream candidates, but no author-provided Theile dictionary was available.

No CAR values, regression coefficients, return quintiles, or outcome-based term-selection evidence were inspected or used.

## Table 3 extraction

- Observed terms: **144**
- `H/W = Y`: **110**
- Supply-chain-specific `H/W = N`: **34**
- The 34 `N` entries exactly match the paper's stated number of supply-chain additions.
- Baseline set equality with `table_3_extraction.csv`: **PASS**
- Duplicate terms: **0**
- Exact word-form changes: **0**

The baseline follows the visual row-major order of Table 3: left, middle, then right panel for each printed row. Frequencies are stored as integers.

### OCR and extraction corrections

The PDF contains embedded text, so no image-only OCR was required. The embedded layer inserted a space after the comma in six five-digit frequencies. Visual inspection of PDF page 7 (journal page 2987) confirmed these corrections:

- `issues`: embedded extraction `35, 497` normalized to `35,497` after page-image verification.
- `issue`: embedded extraction `26, 875` normalized to `26,875` after page-image verification.
- `risk`: embedded extraction `26, 160` normalized to `26,160` after page-image verification.
- `backlog`: embedded extraction `24, 867` normalized to `24,867` after page-image verification.
- `difficult`: embedded extraction `19, 609` normalized to `19,609` after page-image verification.
- `delays`: embedded extraction `10, 068` normalized to `10,068` after page-image verification.

No term or H/W classification required correction.

## Upstream reconciliation

Hassan et al.'s official Online Appendix Table III prints **123** Oxford-derived risk/uncertainty forms with positive frequency in its construction. **106** appear among Theile's `Y` rows. Theile has four additional observed `Y` terms not printed in Hassan's table: `issue`, `issues`, `problem`, and `problems`. Because Table 3 defines `Y` as inherited from Hassan/Wu, these four are attributable to the Wu side of that combined label.

The 17 Hassan Appendix Table III forms absent from Theile Table 3 are:

- `chancy` - high confidence
- `defenseless` - high confidence
- `diffidence` - high confidence
- `doubtfulness` - high confidence
- `fitful` - high confidence
- `fluctuant` - high confidence
- `incalculable` - high confidence
- `incertitude` - high confidence
- `indecisive` - high confidence
- `misgiving` - high confidence
- `niggle` - high confidence
- `parlous` - high confidence
- `precariousness` - high confidence
- `unconfident` - high confidence
- `undependable` - high confidence
- `unsureness` - high confidence
- `untrustworthy` - high confidence

This difference is exactly 17, matching Theile's statement that 17 library terms did not occur. Adding those candidates gives 127 upstream terms (123 Hassan terms plus four Wu-attributable observed anchors) and 161 total terms after the 34 supply-chain additions.

This is strong set-reconciliation evidence, but not direct proof from Theile's unpublished file. Wu's official replication archive is behind a form with restrictive terms and an email requirement. Those terms were not accepted, and the archive was not inspected. The irreducible uncertainty is whether Theile's unpublished 17-term set differs despite the exact count match. All 17 candidates are therefore marked **high confidence**, not direct.

## Starter dictionary comparison

The current starter contains 95 entries and 94 unique forms. It was read without modification. 19 unique starter forms are independently supported by the reconstructed full set: `bottleneck`, `bottlenecks`, `danger`, `disruption`, `disruptions`, `hazard`, `jeopardy`, `peril`, `risk`, `risks`, `risky`, `shortage`, `shortages`, `threat`, `uncertain`, `uncertainties`, `uncertainty`, `volatile`, `volatility`.

### Paper-observed terms missing from the starter (125)

- `ambivalence`
- `ambivalent`
- `apprehension`
- `backlog`
- `backlogs`
- `bet`
- `chance`
- `changeability`
- `changeable`
- `constrain`
- `constrained`
- `constraining`
- `constraint`
- `constraints`
- `dangerous`
- `debatable`
- `delay`
- `delayed`
- `delaying`
- `delays`
- `dicey`
- `difficult`
- `difficulties`
- `difficulty`
- `diffident`
- `dilemma`
- `disquiet`
- `disrupted`
- `disrupting`
- `dodgy`
- `doubt`
- `doubtful`
- `dubious`
- `endanger`
- `equivocating`
- `equivocation`
- `erratic`
- `exposed`
- `faltering`
- `fear`
- `fickleness`
- `fluctuating`
- `gamble`
- `glitch`
- `glitches`
- `gnarly`
- `hairy`
- `halting`
- `hazardous`
- `hazy`
- `hesitancy`
- `hesitant`
- `hesitating`
- `iffy`
- `imperil`
- `indecision`
- `insecure`
- `insecurity`
- `instability`
- `irregular`
- `issue`
- `issues`
- `jeopardize`
- `likelihood`
- `menace`
- `oscillating`
- `pending`
- `perilous`
- `possibility`
- `precarious`
- `probability`
- `problem`
- `problematic`
- `problems`
- `prospect`
- `qualm`
- `quandary`
- `queries`
- `query`
- `reservation`
- `risked`
- `riskier`
- `riskiest`
- `riskiness`
- `risking`
- `shortfall`
- `shortfalls`
- `skepticism`
- `speculative`
- `sticky`
- `suspicion`
- `tentative`
- `tentativeness`
- `torn`
- `treacherous`
- `tricky`
- `trouble`
- `troubles`
- `unclear`
- `undecided`
- `undetermined`
- `unexpected`
- `unexpectedly`
- `unforeseeable`
- `unforeseen`
- `unknown`
- `unpredictability`
- `unpredictable`
- `unreliability`
- `unreliable`
- `unresolved`
- `unsafe`
- `unsettled`
- `unstable`
- `unsure`
- `vacillating`
- `vacillation`
- `vague`
- `vagueness`
- `variability`
- `variable`
- `varying`
- `wager`
- `wariness`
- `wavering`

### Starter terms unsupported by Table 3 or the reconstructed upstream set (75)

- `business disruption`
- `capacity constraint`
- `capacity constraints`
- `component availability`
- `concern`
- `concerns`
- `contingencies`
- `contingency`
- `counterfeit`
- `counterfeiting`
- `counterfeits`
- `cyber threat`
- `cyberattack`
- `cyberattacks`
- `dangers`
- `delivery delay`
- `delivery delays`
- `demand shock`
- `downside`
- `exposure`
- `exposures`
- `external dependency`
- `extreme weather`
- `forecast error`
- `foreign dependency`
- `geographic concentration`
- `geopolitical conflict`
- `hazards`
- `labor shortage`
- `lead time`
- `lead times`
- `malicious hardware`
- `malicious software`
- `manufacturing defect`
- `manufacturing defects`
- `material shortage`
- `natural disaster`
- `natural disasters`
- `perils`
- `poor manufacturing`
- `port congestion`
- `quality failure`
- `quality failures`
- `ransomware`
- `raw material availability`
- `regulatory violation`
- `regulatory violations`
- `sanction`
- `sanctions`
- `shipping delay`
- `single source`
- `single sourcing`
- `stockout`
- `stockouts`
- `supplier bankruptcy`
- `supplier concentration`
- `supplier dependency`
- `supplier failure`
- `supplier insolvency`
- `supply chain disruption`
- `supply disruption`
- `susceptible`
- `tampering`
- `tariff`
- `tariffs`
- `theft`
- `threats`
- `trade dispute`
- `trade disputes`
- `trade restriction`
- `trade restrictions`
- `transportation delay`
- `unauthorized production`
- `vulnerabilities`
- `vulnerability`

Unsupported starter terms were excluded even when intuitively relevant, including ransomware, sanctions, cyberattacks, and multiword disruption phrases. No safety-stock term was added.

## Token-matching validation

Matching used the repository scorer's token pattern and lowercase exact-form comparison. It did not stem, lemmatize, or generate inflections.

- Synthetic tests: **27 passed, 0 failed**. Each prominent term matched in lowercase and uppercase/punctuation contexts and did not match inside a longer alphabetic token.
- Transcript subset: **100 calls**, selected as the first 100 successful rows with non-empty transcript text in file order.
- Subset tokens: **684,204**
- Transcript source SHA-256: `053df4242aa2d34cd17652246425c5dc7de55ea2f03bac18755d274b80e30c31`

| Term | Paper Table 3 frequency | Subset occurrences | Calls containing term |
|---|---:|---:|---:|
| `issues` | 35,497 | 86 | 46 |
| `issue` | 26,875 | 75 | 47 |
| `risk` | 26,160 | 82 | 55 |
| `backlog` | 24,867 | 83 | 37 |
| `difficult` | 19,609 | 77 | 41 |
| `delays` | 10,068 | 17 | 9 |
| `constraints` | 8,755 | 89 | 25 |
| `shortages` | 3,564 | 56 | 30 |
| `disruption` | 6,145 | 12 | 8 |

These subset counts validate exact token reachability only. They are not intended to reproduce the paper's 129,981-call frequencies.

## Sensitivity inflections

`risk_terms_sensitivity_inflections.txt` was not created. The authoritative materials already list separate forms, and automatic expansion would reduce source fidelity. Any future generated variants should remain outside both baseline files.

## Files

- `risk_terms_observed_baseline.txt`: conservative 144-term Table 3 dictionary
- `risk_terms_reconstructed_full.txt`: baseline plus 17 high-confidence candidates
- `risk_terms.csv`: term-level provenance and inclusion decisions
- `table_3_extraction.csv`: direct extraction, raw fields, and correction log
- `source_manifest.json`: URLs, retrieval status, hashes, filenames, and license notes
