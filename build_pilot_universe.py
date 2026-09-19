"""Build the fixed, public-source pilot universe for 2010Q1-2019Q4."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from study_period import study_quarters

ROOT = Path(__file__).resolve().parent
VERSION = "pilot_universe_v20260916"
OUTPUT = ROOT / "data" / "pilot" / VERSION

COMPANIES = [
    {
        "company_id": "CIK0000320193", "cik": "0000320193", "company_name": "Apple Inc.",
        "pilot_category": "active_large", "sic_2digit": "35", "us_operating_company": "yes",
        "source_url": "https://www.sec.gov/Archives/edgar/data/320193/000032019319000119/a10-k20199282019.htm",
    },
    {
        "company_id": "CIK0000008177", "cik": "0000008177", "company_name": "Atlantic American Corporation",
        "pilot_category": "active_small", "sic_2digit": "63", "us_operating_company": "yes",
        "source_url": "https://www.sec.gov/Archives/edgar/data/8177/000114036120006734/hc10009874x1_10k.htm",
    },
    {
        "company_id": "CIK0000037996", "cik": "0000037996", "company_name": "Ford Motor Company",
        "pilot_category": "active_large", "sic_2digit": "37", "us_operating_company": "yes",
        "source_url": "https://www.sec.gov/Archives/edgar/data/37996/000003799620000010/f1231201910-k.htm",
    },
    {
        "company_id": "CIK0000945436", "cik": "0000945436", "company_name": "SunEdison, Inc.",
        "pilot_category": "delisted_ticker_reuse", "sic_2digit": "36", "us_operating_company": "yes",
        "source_url": "https://www.sec.gov/Archives/edgar/data/945436/000119312516559806/d185590d8k.htm",
    },
    {
        "company_id": "CIK0000031791", "cik": "0000031791", "company_name": "PerkinElmer, Inc.",
        "pilot_category": "renamed", "sic_2digit": "38", "us_operating_company": "yes",
        "source_url": "https://www.sec.gov/Archives/edgar/data/31791/000003179120000003/pki1229201910k.htm",
    },
]

TICKER_HISTORY = [
    ("CIK0000320193", "AAPL", "2010Q1", "2019Q4", "NASDAQ", "common_stock"),
    ("CIK0000008177", "AAME", "2010Q1", "2019Q4", "NASDAQ", "common_stock"),
    ("CIK0000037996", "F", "2010Q1", "2019Q4", "NYSE", "common_stock"),
    ("CIK0000945436", "SUNE", "2010Q1", "2016Q2", "NYSE", "common_stock"),
    ("CIK0000031791", "PKI", "2010Q1", "2019Q4", "NYSE", "common_stock"),
]


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    by_id = {row["company_id"]: row for row in COMPANIES}
    ticker_rows = []
    eligible_rows = []
    for company_id, ticker, start, end, exchange, security_type in TICKER_HISTORY:
        ticker_rows.append({
            "company_id": company_id, "cik": by_id[company_id]["cik"],
            "ticker": ticker, "effective_start_quarter": start,
            "effective_end_quarter": end, "exchange": exchange,
            "security_type": security_type, "source_url": by_id[company_id]["source_url"],
            "retrieved_date": "2026-09-16",
        })
        for quarter in study_quarters():
            if start <= quarter <= end:
                company = by_id[company_id]
                eligible_rows.append({
                    "company_id": company_id, "cik": company["cik"],
                    "company_name": company["company_name"], "provider_ticker": ticker,
                    "quarter_label": quarter, "exchange": exchange,
                    "sic_2digit": company["sic_2digit"],
                    "pilot_category": company["pilot_category"],
                    "eligibility_status": "eligible_pilot",
                    "eligibility_reason": "US operating-company common stock listed during quarter",
                    "source_url": company["source_url"], "retrieved_date": "2026-09-16",
                })

    companies_path = OUTPUT / "companies.csv"
    tickers_path = OUTPUT / "ticker_history.csv"
    eligible_path = OUTPUT / "eligible_firm_quarters.csv"
    write_csv(companies_path, list(COMPANIES[0]), COMPANIES)
    write_csv(tickers_path, list(ticker_rows[0]), ticker_rows)
    write_csv(eligible_path, list(eligible_rows[0]), eligible_rows)
    manifest = {
        "version": VERSION,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "scope": "bounded public-source pilot only; not the complete historical universe",
        "study_period": "2010Q1-2019Q4",
        "company_count": len(COMPANIES),
        "eligible_firm_quarter_count": len(eligible_rows),
        "files": {
            path.name: {"sha256": digest(path), "bytes": path.stat().st_size}
            for path in (companies_path, tickers_path, eligible_path)
        },
        "limitations": [
            "Public SEC evidence is filer-centric rather than a complete historical security master.",
            "SunEdison 2016Q2 eligibility means listed during part of the quarter; its call may not exist after bankruptcy.",
            "Pilot categories are deliberately selected and are not population weights.",
        ],
    }
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
