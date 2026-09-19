import csv
import unittest
from pathlib import Path

from build_historical_universe import exclusion_reason, quarter_end, quarter_start, sic_division
from sample_representative_coverage_pilot import allocate
from study_period import validate_study_quarter


ROOT = Path(__file__).resolve().parent


class HistoricalUniverseTests(unittest.TestCase):
    def test_quarter_boundaries(self) -> None:
        self.assertEqual(quarter_start("2010Q1").isoformat(), "2010-01-01")
        self.assertEqual(quarter_end("2019Q4").isoformat(), "2019-12-31")

    def test_security_filters_do_not_exclude_operating_trust_or_plain_ticker(self) -> None:
        base = {
            "symbol": "AWR", "name": "Example Realty Trust", "exchange": "NYSE",
            "assetType": "Stock", "ipoDate": "2000-01-01", "delistingDate": "null",
            "status": "Active",
        }
        self.assertEqual(exclusion_reason(base), "")
        self.assertEqual(exclusion_reason({**base, "name": "Example ETF"}), "name_pattern_fund")
        self.assertEqual(exclusion_reason({**base, "symbol": "ABC-W", "name": "Example Warrant"}), "name_pattern_warrant")
        for symbol in ("CHK-P-D", "SCE--P-D", "BAC-PL", "TY-P"):
            self.assertEqual(
                exclusion_reason({**base, "symbol": symbol}),
                "symbol_suffix_preferred_share",
            )

    def test_sic_divisions(self) -> None:
        self.assertEqual(sic_division("3571"), "manufacturing")
        self.assertEqual(sic_division("6021"), "finance_insurance_real_estate")
        self.assertEqual(sic_division(""), "unknown")

    def test_proportional_allocation_exact_total(self) -> None:
        strata = {"a": [{}] * 70, "b": [{}] * 20, "c": [{}] * 10}
        result = allocate(strata, 20, 20260916)
        self.assertEqual(result, {"a": 14, "b": 4, "c": 2})

    def test_generated_universe_is_unique_and_bounded(self) -> None:
        path = ROOT / "data" / "universe" / "us_operating_companies_v20260916" / "eligible_firm_quarters.csv"
        if not path.exists():
            self.skipTest("versioned universe has not been built")
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        keys = set()
        for row in rows:
            validate_study_quarter(row["quarter_label"])
            self.assertTrue(row["cik"])
            self.assertNotEqual(row.get("issuer_domicile_status"), "foreign")
            self.assertNotEqual(
                exclusion_reason({
                    "symbol": row["provider_ticker"], "name": row["company_name"],
                    "exchange": row["exchange"], "assetType": "Stock",
                    "ipoDate": row["eligibility_start"], "delistingDate": row["eligibility_end"],
                    "status": "Active",
                }),
                "symbol_suffix_preferred_share",
            )
            key = (row["company_id"], row["quarter_label"])
            self.assertNotIn(key, keys)
            keys.add(key)


if __name__ == "__main__":
    unittest.main()
