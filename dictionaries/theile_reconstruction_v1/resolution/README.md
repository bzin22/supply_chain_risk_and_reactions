# Reconstructed resolution dictionary: Theile et al. (2026)

The paper's resolution library (its "𝕄 library") is "the terms mitigate and
resolve as well as their synonyms from the Oxford dictionary" (journal p. 2986).
The library itself is never published. Table 4 publishes its 30 most frequent
word forms. This directory reconstructs the library from that, without any
author-provided file.

Nothing here was selected by looking at CAR, returns, or a regression. Selection
used Table 4, Oxford dictionary entries, and the paper's own prose only.

## What is validated here, and what is not

**Tracked, reproducible on a clean checkout.** `validation_report.md`,
`validation_run.json` and `overlap_report.csv`. Table 4 coverage, exact token
matching, the paper's proximity rule, the settled overlaps, and the SHA-256 of
every dictionary. The inputs are the paper's published tables, the committed
dictionaries, and a committed 15-term synthetic supply-chain fixture. Clone the
repo and you get the same bytes.

**Archived local diagnostic, gitignored, and not PR validation.** Zero rates and
matched-term counts over real transcripts go to `outputs/resolution_validation/`.
They cannot be reproduced from this repository: they need
`data/provisional/earnings_call_transcripts.csv` and `artifacts/sec_10k_supply_chain/terms.jsonl`,
both gitignored, and other work in this repository regenerates both. The
supply-chain library behind them is provisional and so is the firm universe.
Nothing in that directory is evidence that this dictionary is correct, and no
number in it should be quoted as a result. Each archive records the SHA-256 of
the inputs it ran against, because those inputs move: the corpus was regenerated
mid-development and the integrity-passing call count went from 18,162 to 11,598.

## The primary specification

`resolution_terms_conservative_baseline.txt`, **55 terms**, is the only
Resolution dictionary the production pipeline loads.
`scoring/calculate_supply_chain_transcript_scores.py` validates it on every run (exactly
55 unique lowercase whole tokens or it refuses to start) and emits exactly one
Resolution measure from it. `--resolution-words` overrides it for development
and marks the run `resolution_dictionary_is_primary: false` in the manifest.

The risk library in scoring and in validation is the 161-term
`../risk/risk_terms_reconstructed_full.txt`. The 144-term Table 3 list kept here
is a record of the published table, not a specification.

| File | Terms | Role |
| --- | --- | --- |
| `resolution_terms_conservative_baseline.txt` | 55 | **PRIMARY.** Table 4 keywords, the inflected forms Oxford itself prints for each of those roots, plus `alleviate` and `settle` with their Oxford-printed verb forms. |
| `resolution_terms_paper_anchor.txt` | 28 | Sensitivity. The distinct keywords printed in Table 4, nothing added. |
| `resolution_terms_expanded_sensitivity.txt` | 42 extra, 97 combined | Sensitivity. Regular inflections Oxford does not print, Oxford synonym-graph neighbours two or three hops out, and the four resolution keywords the paper adds in its own Table 10 Column (5) check. |
| `resolution_terms_overlap_sensitivity.txt` | 53 | Sensitivity. The primary minus `solution` and `solutions`, held ready for the deferred overlap question below. |

Anchor ⊂ primary ⊂ expanded. The overlap variant sits below the primary by two
declared terms.

Every term file is bare: one lowercase term per line, no comment header, no
build date. They are hashed in `source_manifest.json`, so their bytes must be a
pure function of the term list.

## What Table 4 actually says

The printed table has 30 slots but only **28 distinct keywords**. Slots 24 and
25 repeat slots 22 and 23 verbatim: `enhance` 591 and `recover` 566. The
repetition is in the typeset page, confirmed by rendering PDF page 8 at 250 dpi
and reading the third column off the image. No OCR correction was applied
because the text layer and the rendered page agree character for character.

The two lost entries are not recoverable. The column is printed in descending
order, so their frequencies sit between 566 (slot 23) and 553 (slot 26), that is
somewhere in 554 to 566. Which words they are is gone.

One thing that is easy to misread: the frequencies are **not** raw corpus counts.
Table 2's note says frequency is "the count of occurrences relevant to the
construction of the SCRisk measure", meaning occurrences that already satisfied
the proximity conditions. `help` at 5,448 across 129,981 calls is not how often
anyone said "help". That matters when reasoning about which forms are missing: a
common word like `mitigating` being absent from the top 30 is weak evidence that
it is outside the library, because the ranking is over a heavily filtered count.

## Where the Oxford terms came from, and what is missing

The paper names no Oxford product, edition, or date. Neither do Hassan et al.
(2019), whose method it follows for the risk library. The product whose synonym
runs would most plausibly generate this library, the Oxford Thesaurus of
English, is behind a subscription. Retrieval attempts on 2026-09-16:

- `premium.oxforddictionaries.com` → HTTP 302 to an OAuth login.
- `oed.com` → HTTP 200 but bounced to the unauthenticated home page.
- `lexico.com`, the free Oxford surface that existed when Hassan et al. wrote →
  shut down in 2022, connection failure. The Internet Archive was returning
  "Temporarily Offline" that day, so no capture could be read either.
- macOS bundled New Oxford American Dictionary → not installed on this machine.

Everything Oxford-derived here therefore comes from the free **Oxford Advanced
Learner's Dictionary, 10th edition**. It is a real Oxford product but a learner's
dictionary: it prints one or two synonym cross-references per sense, not a
thesaurus run, and it does not print regular noun plurals. The exact fields
retrieved are in `oxford_evidence.json`; the full provenance including the
failed attempts is in `source_manifest.json`.

The consequence is that the baseline adds exactly two words beyond the Table 4
roots, `alleviate` and `settle`, because those are the only synonyms Oxford
prints on `mitigate` and `resolve`. The real library's tail is longer and is not
recoverable without the thesaurus.

## Inflection policy

Inferred from Table 3, the paper's risk library, which is published in full. It
carries many inflections of a headword (`risk`, `risks`, `risky`, `riskier`,
`riskiest`, `risked`, `risking`, `riskiness`) but not blanket regular inflection:
`threat` appears without `threats`, `hazard` without `hazards`, `peril` without
`perils`. So the baseline adds only forms Oxford itself prints, and holds regular
plurals Oxford omits (`resolutions`, `mitigations`, `enhancements`) back to the
sensitivity file.

## What the old starter dictionary got wrong

`STARTER_RESOLUTION_WORDS` used to live in
`scoring/calculate_supply_chain_transcript_scores.py`. It is gone; the 55-term file
replaces it. It carried 37 tokens with no support in the paper's stated
procedure: `address*`,
`avoid*`, `prevent*`, `contain*`, `diversify*`, `substitute*`, `remediate*`, and
the operational strategies `dual sourcing`, `backup supplier`, `buffer stock`,
`safety stock`, `alternative source`. Those last are concepts, not Oxford
synonyms of mitigate or resolve, and they are multiword phrases where the paper's
library is a word list.

Going the other way, it omitted 40 of the 55 primary forms, including four of
Table 4's five most frequent keywords: `help` (5,448), `solutions` (4,289),
`solve` (3,722) and `improve` (2,688). That omission mattered more than the
additions.

## Overlaps

**Risk library: zero overlap, settled.** Not one of the 161 terms in the primary
risk dictionary, nor of its observed-baseline variant, nor of the 144 risk
keywords printed in Table 3, appears in the primary or in any sensitivity
variant. The closest call is `unresolved`. It shares a root with `resolved` and
carries the opposite sense, and exact token matching keeps them apart. There is
a test for it.

**Supply chain vocabulary: deferred, on purpose.** The final reconstructed
supply-chain vocabulary does not exist yet. The only one available is the repo's
provisional 10-K-derived library, gap number two in the repo README. `solution`
and `solutions` appear in it, but an overlap measured against a provisional
input is a property of that input, not a finding about this dictionary, so it is
kept out of the tracked `overlap_report.csv` entirely and written to
`outputs/resolution_validation/provisional_overlap_report.csv` instead.

`solution` and `solutions` stay in the primary dictionary. `solutions` is Table
4's second most frequent keyword at 4,289 and `solution` its tenth at 1,932.
`resolution_terms_overlap_sensitivity.txt` holds the variant that drops them, so
the sensitivity run is ready the moment the question becomes answerable.
`validation_report.md` section 4 states what is at stake: under equation (2) a
term in both libraries acts as its own resolution word at distance zero, so
every occurrence near a risk word turns an SCRisk pair into a Resolution pair
for free.

## Files

| File | What |
| --- | --- |
| `resolution_terms_*.txt` | The four dictionary variants, one bare lowercase term per line. |
| `resolution_terms.csv` | Every term with its Table 4 frequency, root, Oxford source, relationship, confidence, and whether it is in the baseline. |
| `table_4_extraction.csv` | All 30 printed slots with column, row, frequency, and the duplicate flags. |
| `table_3_risk_terms_reference.csv` | The paper's 144 published risk keywords. A record of the table, not a specification. The primary risk library is `../risk/risk_terms_reconstructed_full.txt`. |
| `fixtures/synthetic_supply_chain_library.jsonl` | 15-term committed stand-in for the generated supply-chain library, so the tests run on a clean checkout. |
| `validation_run.json` | Commit, window, and SHA-256 of every dictionary and the test fixture. Source validation only, no corpus. |
| `overlap_report.csv` | Every variant against every committed library. Settled comparisons only. |
| `oxford_evidence.json` | The Oxford fields retrieved, verbatim. |
| `source_manifest.json` | Full provenance including what could not be retrieved. |
| `validation_report.md` | Coverage, token matching, the proximity rule, settled overlaps, open uncertainty. No corpus numbers. |

## Reproducing

```
python3 build_resolution_dictionary.py     # the four term files, the two CSVs
python3 build_source_manifest.py           # manifest and Oxford evidence
python3 run_validation.py --sample 400     # overlap report and validation report
conda run -n dap-env python -m pytest tests/test_resolution_dictionary.py -q
```

`run_validation.py` always writes the three tracked source-validation files.
The corpus diagnostic is extra: it needs `data/provisional/earnings_call_transcripts.csv` and
`artifacts/sec_10k_supply_chain/terms.jsonl`, and without them the script says
so and carries on. `--skip-corpus-diagnostic` turns it off explicitly, and
`--diagnostic-dir` moves the archive. It takes about a minute when it runs.

The test suite needs neither: it scores against the committed fixture. On a
clean checkout the two corpus-dependent tests skip and everything else passes.

Rebuilds are deterministic. Running the three scripts twice in a row produces
byte-identical output except for the commit recorded in `validation_run.json`.
