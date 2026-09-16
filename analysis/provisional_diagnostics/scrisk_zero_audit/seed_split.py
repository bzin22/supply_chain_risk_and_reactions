import os
import sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]  # repository root
sys.path.insert(0, str(ROOT))
import calculate_supply_chain_transcript_scores as S

OUT = os.environ.get('SCRISK_AUDIT_OUT', str(ROOT / 'outputs/scrisk_zero_audit')) + '/'
seeds = {" ".join(S.normalize_term(s)) for s in S.SUPPLY_CHAIN_SEEDS}
d = pd.read_csv(OUT + 'probe_flip_detail.csv')
s = d[d.probe == 'seeds'].copy()
s['driver_is_seed'] = s.supply_chain_term.isin(seeds)
print("seed-probe flips:", len(s))
print("driven by a restored seed term:", int(s.driver_is_seed.sum()))
print("\nflips by driving seed term:")
print(s[s.driver_is_seed].supply_chain_term.value_counts().to_string())
cust = s[s.supply_chain_term == 'customers']
# A run whose vocabulary already contains the seeds flips nothing on this
# probe, so the share is undefined rather than zero.
share = f"{100*len(cust)/len(s):.1f}% of seed flips" if len(s) else "no seed flips to divide"
print(f"\nflips driven by 'customers' alone: {len(cust)} ({share})")
print("flips excluding 'customers':", len(s) - len(cust))

# inflection probe, same split, excluding the shortage self-pair artifact
i = pd.read_csv(OUT + 'probe_inflection_per_call.csv')
i = i[i.probe == 'lib_seeds_and_risk_inflected']
self_pair = i[(i.supply_chain_term == i.risk_term)]
print(f"\ninflection probe flips: {len(i)}")
print(f"  identical term on both sides (single token counted as both vocabularies): {len(self_pair)}")
print("  self-pair terms:", self_pair.supply_chain_term.value_counts().to_dict())
print(f"  excluding self-pairs: {len(i) - len(self_pair)}")
cust_i = i[i.supply_chain_term == 'customers']
print(f"  excluding self-pairs and 'customers': {len(i) - len(self_pair) - len(cust_i)}")

# odd buckets
z = pd.read_csv(OUT + 'zero_audit_per_call.csv')
odd = z[z.bucket.isin(['no_supply_chain_vocab', 'no_supply_chain_and_no_risk_vocab'])]
print(f"\n=== {len(odd)} calls with no supply-chain vocabulary ===")
print(odd[['ticker','quarter_label','company_name','sector','recomputed_word_count',
           'supply_chain_occurrences_recomputed','risk_occurrences_recomputed',
           'segment_word_count','distinct_token_ratio','probe_seeds_becomes_nonzero',
           'probe_seeds_supply_chain_occurrences','bucket']].to_string(index=False))
nr = z[z.bucket == 'supply_chain_but_no_risk_vocab']
print(f"\n=== {len(nr)} calls with supply-chain but no risk vocabulary: length profile ===")
print(nr.recomputed_word_count.describe()[['count','mean','50%','min','max']].to_string())
print("median tokens, all zeros:", z.recomputed_word_count.median())
