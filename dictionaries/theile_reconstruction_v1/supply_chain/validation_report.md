# Supply chain keyword library: reconstruction validation

This is a **reconstructed approximation** of the keyword library in Theile et al. (2026). It is not the authors' library. metaHeuristica's algorithm is not public, the authors' corpus and files were unavailable, and several terms in their Table 2 cannot be produced by any distributional model. Treat every number here as evidence about a reconstruction, not as a replication of the original dictionary.

## 1. Corpus

- Documents used for training: **50,000** of 50,246 selected (50,182 parsed cleanly)
- Tokens: **1,634,226,218**
- Years: 1997-2021, sampled at exactly 2,000 filings per year
- Eligible population discovered: 205,384 (forms 10-K, 10-K405)
- Sampling seed: `20260916`, random.Random(f'{seed}:{year}') per year, sample() over accession-sorted pool
- Excluded as duplicates before training: 182 ({'duplicate_content_hash': 35, 'duplicate_cik_report_period': 147})
- Phrase-augmented space: 136,803 phrases, 231,186,355 joins applied

The paper trains on *all* 10-K reports 1997-2021. This reconstruction uses a year-balanced sample because the full set is roughly 600 GB of submissions. Year balance is a deliberate departure: it prevents the embedding from being dominated by the high-filing-count early 2000s.

## 2. Method comparison

| method | corpus | seed mode | size | T2 /30 | T2 non-seed /17 | rho | seeds | generic | med df | % df<100 |
|---|---|---|---|---|---|---|---|---|---|---|
| ppmi_svd | phrased | phrase | 254 | 27 | 14 | 0.6549 | 16 | 1 | 1449 | 2.4 |
| word2vec_cbow | phrased | phrase | 354 | 28 | 15 | 0.6667 | 16 | 2 | 1595 | 13.3 |
| word2vec_skipgram | phrased | phrase | 493 | 28 | 15 | 0.611 | 16 | 1 | 28 | 68.0 |
| ppmi_svd | phrased | average | 273 | 25 | 12 | -0.1582 | 16 | 1 | 1486 | 1.8 |
| word2vec_cbow | phrased | average | 377 | 27 | 14 | 0.1573 | 16 | 7 | 2340 | 11.7 |
| word2vec_skipgram | phrased | average | 577 | 25 | 12 | 0.0947 | 16 | 2 | 24 | 72.3 |
| ppmi_svd | unigram | average | 1109 | 27 | 14 | 0.1726 | 16 | 4 | 359 | 33.5 |
| word2vec_cbow | unigram | average | 1104 | 28 | 15 | 0.103 | 16 | 7 | 340 | 32.5 |

Blinded precision (method labels hidden from the reviewer during judging):

| arm | reviewed | relevant | borderline | not relevant | strict | lenient |
|---|---|---|---|---|---|---|
| ppmi_svd / average | 55 | 41 | 4 | 10 | 0.7455 | 0.8182 |
| ppmi_svd / phrase | 55 | 29 | 19 | 7 | 0.5273 | 0.8727 |
| word2vec_cbow / average | 55 | 28 | 13 | 14 | 0.5091 | 0.7455 |
| word2vec_cbow / phrase | 55 | 30 | 11 | 14 | 0.5455 | 0.7455 |
| word2vec_skipgram / average | 55 | 20 | 11 | 24 | 0.3636 | 0.5636 |
| word2vec_skipgram / phrase | 55 | 21 | 7 | 27 | 0.3818 | 0.5091 |

## 3. Table 2, term by term

Baseline arm: `ppmi_svd` / `phrase`. Recovered **27/30**.

| keyword | paper cos | our cos | our seed | our rank | corpus freq | status |
|---|---|---|---|---|---|---|
| customers | 1.0 | 1.0 | customers | 0 | 1,167,298 | recovered |
| supply | 1.0 | 1.0 | supply | 0 | 189,249 | recovered |
| inventory | 1.0 | 1.0 | inventory | 0 | 267,431 | recovered |
| manufacturing | 1.0 | 1.0 | manufacturing | 0 | 255,536 | recovered |
| distribution | 1.0 | 1.0 | distribution | 0 | 426,358 | recovered |
| suppliers | 1.0 | 1.0 | suppliers | 0 | 168,230 | recovered |
| transportation | 1.0 | 1.0 | transportation | 0 | 102,570 | recovered |
| logistics | 1.0 | 1.0 | logistics | 0 | 27,773 | recovered |
| purchasing | 1.0 | 1.0 | purchasing | 0 | 55,622 | recovered |
| sourcing | 1.0 | 1.0 | sourcing | 0 | 17,234 | recovered |
| procurement | 1.0 | 1.0 | procurement | 0 | 21,189 | recovered |
| fulfillment | 1.0 | 1.0 | fulfillment | 0 | 16,587 | recovered |
| warehousing | 1.0 | 1.0 | warehousing | 0 | 11,005 | recovered |
| resellers | 0.86 | 0.839895 | channel partners | 9 | 18,639 | recovered |
| endcustomers | 0.84 | 0.747602 | channel partners | 30 | 2,980 | recovered |
| inventories | 0.83 | 0.88924 | inventory | 1 | 95,646 | recovered |
| vars | 0.83 | 0.884439 | channel partners | 1 | 2,700 | recovered |
| pims | 0.83 | - | - | - | 345 | **missing** (proprietary_algorithm) |
| supplychain | 0.81 | 0.874055 | supply chain | 1 | 584 | recovered |
| vendors | 0.8 | 0.821088 | suppliers | 10 | 90,764 | recovered |
| isvs | 0.8 | 0.742544 | channel partners | 32 | 776 | recovered |
| warehouse | 0.79 | 0.805302 | warehousing | 2 | 33,216 | recovered |
| workflow | 0.78 | 0.550934 | supply chain | 100 | 4,820 | recovered |
| integrators | 0.78 | 0.746267 | channel partners | 31 | 1,970 | recovered |
| workinprocess | 0.78 | 0.806464 | inventory | 5 | 2,599 | recovered |
| endcustomer | 0.78 | - | - | - | 1,143 | **missing** (model) |
| eprocurement | 0.77 | 0.562269 | supply chain | 82 | 296 | recovered |
| customer | 0.76 | - | - | - | 433,122 | **missing** (model) |
| slowmoving | 0.76 | 0.780987 | inventory | 18 | 1,389 | recovered |
| supplier | 0.75 | 0.736418 | suppliers | 30 | 52,050 | recovered |

## 4. Discrepancy classification

| class | n | terms |
|---|---|---|
| model | 2 | `endcustomer`, `customer` |
| proprietary_algorithm | 1 | `pims` |

- `pims` (proprietary_algorithm): in vocabulary (tf=345) with max seed cosine 0.272, and missed by every method tested, so no single model explains it
- `endcustomer` (model): in vocabulary (tf=1,143) but max seed cosine 0.463 is outside every top-100; other arms do recover it
- `customer` (model): in vocabulary (tf=433,122) but max seed cosine 0.499 is outside every top-100; other arms do recover it

## 4b. Frequency and document-frequency support

The `% df<100` column separates the arms more sharply than anything except
precision. It is the share of a vocabulary whose terms appear in fewer than 100
of the 50,000 filings.

| arm | median document frequency | % of terms in <100 docs |
|---|---|---|
| ppmi_svd / phrase | 1,449 | **2.4%** |
| word2vec_cbow / phrase | 1,595 | 13.3% |
| word2vec_skipgram / phrase | 28 | **68.0%** |

Two thirds of the skip-gram vocabulary rests on fewer than 100 documents, and its
median term appears in 28. A cosine estimated from that little evidence is not
measuring much, which is the same thing the blinded review found independently
when it scored skip-gram at 0.382 strict precision. The two criteria are not
independent, but they were computed independently and they agree.

This is also the cleanest single reason to reject skip-gram rather than treat it
as a close third.

## 5. Stability

Same configuration, one input changed at a time.

| arm | perturbation | size | Jaccard | top 100 | top 208 | all |
|---|---|---|---|---|---|---|
| ppmi | random_seed | 254 → 251 | 0.8635 | 98.0% | 95.7% | 92.1% |
| ppmi | corpus_50pct | 254 → 269 | 0.7911 | 98.0% | 94.7% | 90.9% |
| cbow | random_seed | 354 → 358 | 0.6993 | 98.0% | 91.8% | 82.8% |
| cbow | corpus_50pct | 354 → 377 | 0.5961 | 95.0% | 88.5% | 77.1% |
| skipgram | random_seed | 493 → 514 | 0.5959 | 99.0% | 87.5% | 76.3% |

Instability is confined to the low-cosine tail. For the chosen PPMI arm, the 100
highest-cosine terms are 98% reproducible under either perturbation, while the
full 254-term list is 91-92%. The terms that move are things like `acetylene`,
`asure` and `cribs`, not supply chain vocabulary.

One result here matters for the ranking rather than just for confidence. Under
seed 777 the skip-gram arm recovers **27** Table 2 terms, not 28, and its size
moves from 493 to 514. Its apparent one-term edge over PPMI was seed noise. The
CBOW arm recovers 28 at both seeds, so CBOW's edge is real; skip-gram's was not.

## 6. Phrase augmentation is what reproduces the paper's funnel

This is the single most important finding, and it is not a tuning choice.

The paper takes 16 x 100 = 1,600 candidates down to 208 by removing duplicates
and multiword n-grams. That 87% attrition can only happen if the model proposes
multiword phrases in the first place. metaHeuristica did. A unigram model does
not, so its lists survive almost intact.

Same documents, same seeds, phrase augmentation the only difference. Run on two
methods independently, so the effect is not a quirk of one model:

| method | candidate space | unique candidates | multiword removed | final |
|---|---|---|---|---|
| ppmi_svd | phrase-augmented | 1,054 | 805 | **254** |
| ppmi_svd | unigram only | 1,109 | 0 | **1,109** |
| cbow | phrase-augmented | 1,134 | 782 | **354** |
| cbow | unigram only | 1,103 | 0 | **1,104** |

Both methods land within 5 terms of each other at ~1,105 when the candidate space
is unigrams, and both collapse toward the paper's order of magnitude when it is
not. The unigram numbers reproduce the 1,093-term library this repository built
earlier. That library was not a bad dictionary, it was the right method applied
in a candidate space that cannot express the paper's filtering step.

## 7. Multiword seeds: phrase token beats averaging

The paper drops all three multiword seeds from its final list (only 13 of 16
seeds appear at cosine 1.00 in Table 2), but they still generate candidates.
Resolving them to a joined phrase token beats averaging their component vectors
on every method and every criterion:

| method | seed mode | size | Table 2 | ordering rho |
|---|---|---|---|---|
| ppmi_svd | phrase | 254 | 27/30 | 0.655 |
| ppmi_svd | average | 273 | 25/30 | -0.158 |
| cbow | phrase | 354 | 28/30 | 0.667 |
| cbow | average | 377 | 27/30 | 0.157 |
| skipgram | phrase | 493 | 28/30 | 0.611 |
| skipgram | average | 577 | 25/30 | 0.095 |

Averaging does not just perform slightly worse, it destroys the cosine ordering
signal entirely (rho near zero or negative). The reason is visible in the output:
under the phrase token, `channel partners` is the nearest seed for `resellers`,
`vars`, `isvs`, `integrators` and `endcustomers`, which is exactly where the
paper puts them. Averaging `channel` and `partners` produces a vector that points
at neither.

## 8. Recommended baseline

**`ppmi_svd` on the phrase-augmented corpus, multiword seeds resolved to their
joined phrase token. 254 terms.** Promoted to the top level of this directory.

Why this arm, on outcome-blind evidence only:

- Smallest vocabulary of any arm, 254 against the paper's 208. CBOW gives 354 and
  skip-gram 493.
- Most stable under both perturbations, by a clear margin (Jaccard 0.864 and
  0.791, against CBOW's 0.699 and 0.596).
- Highest lenient blinded precision, 0.873 against CBOW's 0.746.
- Joint-lowest generic-term count.
- Cosine ordering rho 0.655, against CBOW's 0.667. On 14 points that difference
  is noise.
- Bit-reproducible: unlike gensim with multiple workers, the PPMI/SVD path gives
  identical vectors for a given seed.

What it costs: CBOW recovers one more Table 2 term (28/30 vs 27/30). The PPMI arm
misses `customer`, which is the paper's second most frequent keyword at 44,204
occurrences. `customer` is in our corpus 433,122 times and in the model
vocabulary, but its best seed cosine is 0.499, outside every top-100. If Table 2
recovery were weighted above all else, CBOW would win. It is one term against a
vocabulary 100 terms smaller and materially more reproducible.

Skip-gram is rejected outright: worst size (493), worst blinded precision (0.382
strict, 0.509 lenient), and no compensating advantage.

## 9. What this is not

This is a reconstruction, not the authors' library. Specific reasons it cannot be
theirs:

- **Corpus.** The paper uses all 10-K reports 1997-2021. This uses a
  year-balanced sample of 2,000 per year, because the full set is roughly 600 GB
  of submissions. Year balance is itself a departure: it stops the embedding
  being dominated by the high-filing-count early 2000s, but it is not what the
  paper did.
- **Algorithm.** metaHeuristica's clustering is proprietary and undocumented
  beyond "cluster terms by semantic topics based on their relative
  co-occurrence". PPMI plus SVD is the closest public analogue to that
  description, not a reimplementation of it.
- **Phrase detection.** The paper's n-gram candidates came from metaHeuristica.
  Ours come from a PMI bigram detector with documented thresholds. The two will
  not propose the same phrase inventory, which directly changes which unigrams
  survive into the final list.
- **Cosine values.** Ours are close on most Table 2 terms but not equal, and two
  (`workflow`, `eprocurement`) are far off.

Do not describe any result built on this vocabulary as a replication of Theile et
al. (2026). It is a recreation using a reconstructed approximation of their
keyword library.

## 10. Reproducing

```
conda run --no-capture-output -n dap-env python -u corpus/discover_population.py ...
bash run_pipeline.sh
```

Random seeds, model fingerprints, and both environment definitions are recorded
in `model_config.json`. Word2Vec arms require the `dap-w2v` sidecar environment
because gensim does not build on dap-env's Python 3.14.

