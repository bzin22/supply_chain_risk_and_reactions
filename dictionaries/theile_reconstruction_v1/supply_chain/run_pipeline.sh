#!/usr/bin/env bash
# Reconstruction pipeline. Corpus stages and PPMI run in dap-env; the two
# Word2Vec arms run in dap-w2v because gensim will not build on dap-env's
# Python 3.14. Nothing here touches transcripts, scores, or returns.
set -euo pipefail

ROOT=/Users/bzin/stock_market_reactions_recreation_study
ART=$ROOT/artifacts/sec_10k_theile_v1
DICT=$ROOT/dictionaries/theile_reconstruction_v1/supply_chain
C=$DICT/corpus
M=$DICT/models
SEED=20260916
UA="stock-market-reactions-recreation-study bryan@usereframe.ai"

step() { echo; echo "=== $* ==="; }

step "4. coverage gate"
conda run --no-capture-output -n dap-env python -u $C/build_coverage_report.py \
  --sample $C/selected_sample.jsonl --manifest $ART/manifest.jsonl \
  --discovery-report $C/discovery_report.json --sampling-report $C/sampling_report.json \
  --output-dir $DICT --per-year 2000

step "5. training corpora (unigram + phrase-augmented)"
conda run --no-capture-output -n dap-env python -u $C/build_training_corpus.py \
  --manifest $ART/manifest.jsonl --sample $C/selected_sample.jsonl \
  --text-dir $ART/text --output-dir $ART/corpora --report-dir $DICT

step "6. corpus term statistics"
for V in unigram phrased; do
  conda run --no-capture-output -n dap-env python -u $C/corpus_stats.py \
    --corpus $ART/corpora/corpus_$V.txt.gz --output $ART/corpora/stats_$V.json.gz
done

step "7. train models"
for V in phrased unigram; do
  conda run --no-capture-output -n dap-w2v python -u $M/train_word2vec.py --corpus $ART/corpora/corpus_$V.txt.gz \
    --run-dir $ART/models/sgns_$V --sg 1 --seed $SEED
  conda run --no-capture-output -n dap-w2v python -u $M/train_word2vec.py --corpus $ART/corpora/corpus_$V.txt.gz \
    --run-dir $ART/models/cbow_$V --sg 0 --seed $SEED
  conda run --no-capture-output -n dap-env python -u $M/train_ppmi_svd.py --corpus $ART/corpora/corpus_$V.txt.gz \
    --run-dir $ART/models/ppmi_$V --seed $SEED
done

step "8. extract candidate libraries"
for MODEL in sgns cbow ppmi; do
  conda run --no-capture-output -n dap-env python -u $M/extract_candidates.py \
    --run-dir $ART/models/${MODEL}_phrased --stats $ART/corpora/stats_phrased.json.gz \
    --output-dir $DICT/sensitivity/${MODEL}_phrased_phraseseed --multiword-seed-mode phrase
  conda run --no-capture-output -n dap-env python -u $M/extract_candidates.py \
    --run-dir $ART/models/${MODEL}_phrased --stats $ART/corpora/stats_phrased.json.gz \
    --output-dir $DICT/sensitivity/${MODEL}_phrased_avgseed --multiword-seed-mode average
  conda run --no-capture-output -n dap-env python -u $M/extract_candidates.py \
    --run-dir $ART/models/${MODEL}_unigram --stats $ART/corpora/stats_unigram.json.gz \
    --output-dir $DICT/sensitivity/${MODEL}_unigram_avgseed --multiword-seed-mode average
done

echo; echo "pipeline stages 4-8 complete"
