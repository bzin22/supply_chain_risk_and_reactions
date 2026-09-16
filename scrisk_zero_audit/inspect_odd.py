import csv, sys, re, json
sys.path.insert(0, '/Users/bzin/stock_market_reactions_recreation_study')
import calculate_supply_chain_transcript_scores as S
S.configure_csv_field_size_limit()
WANT = {("ETN","2012Q4"),("F","2012Q4"),("OHI","2021Q3"),("CHE","2015Q2"),("ARKR","2012Q3")}
P='artifacts/earnings_call_supply_chain/ppmi_svd_full_20260910/earnings_call_transcripts_scored.csv'
found={}
with open(P, newline='', encoding='utf-8') as h:
    for row in csv.DictReader(h):
        k=(row['ticker'],row['quarter_label'])
        if k in WANT:
            found[k]=row['transcript_text']
for k,t in found.items():
    toks=S.tokenize(t)
    print(f"=== {k[0]} {k[1]} | chars={len(t)} tokens={len(toks)} distinct={len(set(toks))}")
    print("HEAD:", re.sub(r'\s+',' ',t[:420]))
    print("TAIL:", re.sub(r'\s+',' ',t[-260:]))
    print()
