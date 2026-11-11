"""Edge cases and SBA 8.1 rules. Rule values: SBA SOP 50 10 8.1 (effective 2026-10-01)."""
import os
import tempfile
import unittest

from biz_screener import config, dcf, ingest, sba

BANDS = dict(spread_under_50k=0.065, spread_50k_to_250k=0.06,
             spread_250k_to_350k=0.045, spread_over_350k=0.03)
HEAD = "ref,category,asking_price,fiscal_year,revenue,pretax_income\n"


def parse(text, encoding="utf-8"):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "x.csv")
        with open(path, "w", encoding=encoding, newline="") as f:
            f.write(text)
        return ingest.parse_csv(path)


class IngestTests(unittest.TestCase):
    def test_excel_bom(self):
        deals, rej = parse(HEAD + "a,gas,100000,2024,500000,50000\n", "utf-8-sig")
        self.assertEqual((len(deals), rej), (1, []))

    def test_nan_inf_and_zero_price_rejected(self):
        _, rej = parse(HEAD + "a,gas,nan,2024,5,5\nb,gas,100,2024,inf,5\nc,gas,0,2024,5,5\n")
        self.assertEqual(len(rej), 3)

    def test_customer_share_must_be_a_fraction(self):
        head = HEAD.rstrip("\n") + ",top_customer_share\n"
        deals, rej = parse(head + "a,gas,100000,2024,500000,50000,-0.5\n"
                           + "b,gas,100000,2024,500000,50000,30\n"
                           + "c,gas,100000,2024,500000,50000,0.2\n")
        self.assertEqual([d[0].external_ref for d in deals], ["c"])
        self.assertEqual(deals[0][0].top_customer_share, 0.2)
        self.assertEqual(len(rej), 2)
        self.assertIn("line 2", rej[0])
        self.assertIn("line 3", rej[1])

    def test_conflicting_duplicates_rejected(self):
        deals, rej = parse(HEAD + "a,gas,100,2024,5,5\na,gas,200,2023,5,5\na,gas,100,2024,5,5\n")
        self.assertEqual((len(deals[0][1]), len(rej)), (1, 2))


class DcfTests(unittest.TestCase):
    def test_no_tax_credit_on_negative_ebit(self):
        self.assertEqual(dcf.project_cash_flows(0, 55_000, 0.0, 0.24, 0.12, 1), [0.0])

    def test_empty_flows(self):
        with self.assertRaises(ValueError):
            dcf.dcf_value([], 0.2, 0.03)


class SbaRuleTests(unittest.TestCase):
    def test_price_not_positive_or_fully_funded(self):
        with self.assertRaises(ValueError):
            sba.loan_amount(0, 250_000, 0.10)
        with self.assertRaises(ValueError):
            sba.loan_amount(100_000, 250_000, 0.10)

    def test_standby_credit_capped_at_half_of_injection(self):
        # price 1.0M, 10% = 100k required; standby credit max 50k.
        self.assertEqual(sba.loan_amount(1_000_000, 50_000, 0.10, seller_standby=50_000), 900_000)
        with self.assertRaises(ValueError):  # 40k cash + 50k credit < 100k
            sba.loan_amount(1_000_000, 40_000, 0.10, seller_standby=200_000)
        # extra standby beyond the credit still shrinks the loan
        self.assertEqual(sba.loan_amount(1_000_000, 60_000, 0.10, seller_standby=200_000), 740_000)

    def test_guarantee_fee_sop_examples(self):
        self.assertAlmostEqual(sba.guarantee_fee(100_000), 1_700)      # SOP note 2
        self.assertAlmostEqual(sba.guarantee_fee(5_000_000), 138_125)  # SOP note 3

    def test_term_limit(self):
        with self.assertRaises(ValueError):
            sba.debt_summary(1_000_000, 300_000, 350_000, 0.0675, dict(term_years=0, **BANDS),
                             dict(max_cash_equity=200_000, min_equity_injection_pct=0.1,
                                  owner_living_draw=0))

    def test_config_rejects_zero_forecast_years(self):
        for bad in (0, -1, 2.5):
            self.assertIn("dcf.forecast_years must be a whole number of at least 1",
                          config.validate_settings({"dcf": {"forecast_years": bad}}))

    def test_config_rejects_bad_term(self):
        self.assertIn("sba.term_years must be 1-10",
                      config.validate_settings({"sba": {"term_years": 25}}))


if __name__ == "__main__":
    unittest.main()
