import unittest

from build_call_date_mapping import explicit_call_dates, fiscal_period_match


class CallDateEvidenceTests(unittest.TestCase):
    def test_explicit_call_date_near_call_cue(self) -> None:
        text = (
            "Example Corp announced results for the first quarter 2018. "
            "The company will host a conference call on May 3, 2018 at 8:00 a.m."
        )
        self.assertEqual(explicit_call_dates(text)[0][0], "2018-05-03")
        self.assertTrue(fiscal_period_match(text, "2018Q1"))

    def test_unrelated_date_is_not_a_call_date(self) -> None:
        text = "The quarter ended March 31, 2018. Revenue increased."
        self.assertEqual(explicit_call_dates(text), [])

    def test_release_dateline_is_not_confused_with_later_call_date(self) -> None:
        text = (
            "May 1, 2018. Example Corp announced results. "
            "The company will host a conference call on May 3, 2018 at 8:00 a.m."
        )
        self.assertEqual([value for value, _ in explicit_call_dates(text)], ["2018-05-03"])

    def test_wrong_fiscal_quarter_does_not_match(self) -> None:
        text = "Results for the second quarter 2018. Conference call on August 2, 2018."
        self.assertFalse(fiscal_period_match(text, "2018Q1"))
        self.assertTrue(fiscal_period_match(text, "2018Q2"))


if __name__ == "__main__":
    unittest.main()
