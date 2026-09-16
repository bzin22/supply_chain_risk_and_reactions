"""Pick up to N companies per sector from a listing CSV, using yfinance labels.

Provenance warning. This is the script that produced
``convenience_sample_450_companies_9_sectors.csv``, but it cannot reproduce
that file:

  * it asks yfinance for each ticker's current sector and industry, and those
    labels change over time, so the same input gives a different sample on a
    later run;
  * it stops as soon as every bucket is full, so the sample depends on the
    input row order;
  * the target here is 50 per sector across 10 sectors, and the committed
    sample has 450 companies across 9, so the committed file came from a
    different configuration or was edited afterwards. Which is not recorded.

Keep it as the record of how the convenience sample was built. Do not treat
its output as the paper's firm universe: yfinance sectors are not SIC codes,
and the input listing is a current-membership snapshot, not a historical one.
See README.md in this directory.
"""

import os
from pathlib import Path

import pandas as pd
import yfinance as yf

# --- CONFIGURATION ---
HERE = Path(__file__).resolve().parent
INPUT_CSV = str(HERE / "companies_traded_15_years.csv")
OUTPUT_CSV = str(HERE / "convenience_sample_regenerated.csv")
TARGET_PER_SECTOR = 50

# 10 Distinct Sectors mapped to Yahoo Finance sector/industry labels
TARGET_SECTORS = {
    # 1. High-priority sub-industry check first
    "Semiconductors": ["Semiconductor", "Semiconductors"],
    
    # 2. Broader sectors
    "Technology": ["Technology", "Software", "Information Technology"],
    "Financial Services": ["Financial Services", "Banks", "Insurance", "Credit Services"],
    "Real Estate": ["Real Estate", "REIT"],
    "Industrials": ["Industrials", "Specialty Industrial Machinery", "Aerospace & Defense"],
    "Retail": ["Consumer Cyclical", "Specialty Retail", "Internet Retail", "Apparel Retail"],
    "Transportation": ["Airlines", "Trucking", "Railroads", "Marine Shipping", "Integrated Freight & Logistics"],
    "Consumer Goods": ["Consumer Defensive", "Household & Personal Products", "Packaged Foods", "Beverages"],
    "Healthcare": ["Healthcare", "Drug Manufacturers", "Biotechnology", "Medical Devices"],
    "Energy": ["Energy", "Oil & Gas Exploration & Production", "Oil & Gas Midstream"]
}

# Verify input file
if not os.path.exists(INPUT_CSV):
    raise FileNotFoundError(f"File not found: {INPUT_CSV}")

df_companies = pd.read_csv(INPUT_CSV)
ticker_col = "symbol" if "symbol" in df_companies.columns else "ticker"
tickers = df_companies[ticker_col].dropna().unique().tolist()

print(f"Loaded {len(tickers)} companies. Fetching metadata for 10 sectors...")

# Buckets to hold tickers per sector
sector_buckets = {sector: [] for sector in TARGET_SECTORS}

def is_all_full(buckets, target):
    return all(len(items) >= target for items in buckets.values())

# Scan tickers and populate buckets
for idx, ticker in enumerate(tickers):
    # Stop early if all 10 buckets have reached 50
    if is_all_full(sector_buckets, TARGET_PER_SECTOR):
        print("\nAll 10 sectors have reached 50 companies!")
        break

    try:
        yf_ticker = yf.Ticker(str(ticker).strip())
        info = yf_ticker.info
        
        yf_sector = info.get("sector", "")
        yf_industry = info.get("industry", "")
        company_name = info.get("longName", ticker)

        matched_sector = None

        # Priority Check: Semiconductors must be separated from general Technology
        if any(term.lower() in yf_industry.lower() or term.lower() in yf_sector.lower() for term in TARGET_SECTORS["Semiconductors"]):
            matched_sector = "Semiconductors"
        else:
            # Check remaining 9 sectors
            for sec_name, keywords in TARGET_SECTORS.items():
                if sec_name == "Semiconductors":
                    continue
                if any(kw.lower() in yf_sector.lower() or kw.lower() in yf_industry.lower() for kw in keywords):
                    matched_sector = sec_name
                    break

        # If it matched a sector and that sector still needs companies, add it
        if matched_sector and len(sector_buckets[matched_sector]) < TARGET_PER_SECTOR:
            sector_buckets[matched_sector].append({
                "symbol": ticker,
                "name": company_name,
                "sector": matched_sector,
                "industry": yf_industry
            })
            count = len(sector_buckets[matched_sector])
            print(f"[{idx+1}/{len(tickers)}] {ticker} -> {matched_sector} ({count}/{TARGET_PER_SECTOR})")

    except Exception:
        continue

# Combine into a single final DataFrame
final_rows = []
for sector, items in sector_buckets.items():
    final_rows.extend(items)
    print(f"{sector}: {len(items)} companies")

df_final_500 = pd.DataFrame(final_rows)
df_final_500.to_csv(OUTPUT_CSV, index=False)

print(f"\nSaved {len(df_final_500)} companies to {OUTPUT_CSV}")

