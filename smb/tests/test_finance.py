"""Money math: SDE/EBITDA, multiples, DCF and SBA debt service.

Expected numbers come from docs/METHODOLOGY.md (worked example, made-up data).
"""
import unittest

from biz_screener import dcf, multiples, normalize, sba
from biz_screener.models import AddBack, FinancialPeriod

GAS = dict(sde_multiple_low=2.0, sde_multiple_high=3.0,
           ebitda_multiple_low=3.0, ebitda_multiple_high=4.0)
BANDS = dict(spread_under_50k=0.065, spread_50k_to_250k=0.06,
             spread_250k_to_350k=0.045, spread_over_350k=0.03)


class NormalizeTests(unittest.TestCase):
    def setUp(self):
        self.period = FinancialPeriod(2024, 2_000_000, 270_000, 0, 55_000, 0, 90_000)
        self.adds = [AddBack(2024, "legal", 15_000), AddBack(2024, "truck", 10_000, "personal"),
                     AddBack(2023, "other year", 99_999)]

    def test_example_sde_ebitda_ratio(self):
        (n,) = normalize.normalize_periods([self.period], self.adds, 80_000, 0.0)
        self.assertEqual(n.sde, 440_000)
        self.assertEqual(n.ebitda, 360_000)
        self.assertAlmostEqual(n.addback_ratio, 170_000 / 270_000)

    def test_burden_default_applies(self):
        self.assertAlmostEqual(normalize.compute_ebitda(440_000, 80_000), 440_000 - 86_120)

    def test_ratio_floors_zero_income(self):
        p = FinancialPeriod(2024, 100, -50, depreciation=10)
        self.assertEqual(normalize.addback_ratio(p, []), 10.0)


class MultiplesTests(unittest.TestCase):
    def test_values(self):
        self.assertEqual(multiples.value_from_sde(440_000, GAS), 1_100_000)
        self.assertEqual(multiples.value_from_ebitda(360_000, GAS), 1_260_000)
        self.assertEqual(multiples.value_from_sde(440_000, GAS, False), 880_000)

    def test_bad_range(self):
        with self.assertRaises(ValueError):
            multiples.pick_multiple(3, 2, True)

    def test_asking_multiples(self):
        a, b = multiples.asking_multiples(1_200_000, 440_000, 360_000)
        self.assertAlmostEqual(a, 2.727, 3)
        self.assertAlmostEqual(b, 3.333, 3)
        self.assertEqual(multiples.asking_multiples(1, 0, -5), (float("inf"),) * 2)


class DcfTests(unittest.TestCase):
    def test_discount_rate(self):
        self.assertAlmostEqual(dcf.discount_rate(0.042, 0.14, 0.04), 0.222)

    def test_year_one_matches_doc(self):
        cfs = dcf.project_cash_flows(360_000, 55_000, 0.03, 0.24, 0.12, 5)
        self.assertAlmostEqual(cfs[0], 243_600)
        self.assertAlmostEqual(cfs[4], 272_517.23, places=2)  # D&A shield stays flat

    def test_value_matches_doc(self):
        cfs = dcf.project_cash_flows(360_000, 55_000, 0.03, 0.24, 0.12, 5)
        value, share = dcf.dcf_value(cfs, 0.222, 0.03)
        self.assertAlmostEqual(value, 1_263_626, delta=1)
        self.assertAlmostEqual(share, 536_505 / 1_263_626, places=4)

    def test_constant_flow_perpetuity(self):
        # Zero growth, one flow of 100 at 10%: value = 100/1.1 + (100/0.1)/1.1 = 1000.
        value, _ = dcf.dcf_value([100.0], 0.10, 0.0)
        self.assertAlmostEqual(value, 1000.0)

    def test_rate_must_exceed_growth(self):
        with self.assertRaises(ValueError):
            dcf.dcf_value([100.0], 0.03, 0.03)


class SbaTests(unittest.TestCase):
    def test_loan_amount_cash_governs(self):
        self.assertEqual(sba.loan_amount(1_200_000, 250_000, 0.10), 950_000)

    def test_loan_amount_min_pct_governs(self):
        self.assertEqual(sba.loan_amount(1_000_000, 100_000, 0.10), 900_000)

    def test_equity_shortfall_raises(self):
        with self.assertRaises(ValueError):
            sba.loan_amount(3_000_000, 250_000, 0.10)

    def test_loan_cap(self):
        self.assertEqual(sba.loan_amount(6_000_000, 1_000_000, 0.10), 5_000_000)
        with self.assertRaisesRegex(ValueError, "needs \\$4000000 more equity"):
            sba.loan_amount(10_000_000, 1_000_000, 0.10)

    def test_spread_bands_edges(self):
        s = lambda x: sba.spread_for_loan(x, BANDS)
        # SOP 50 10: $50,000 or less; $50,001-$250,000; $250,001-$350,000; over $350,000
        self.assertEqual(s(50_000), 0.065)
        self.assertEqual(s(50_001), 0.06)
        self.assertEqual(s(250_000), 0.06)
        self.assertEqual(s(250_001), 0.045)
        self.assertEqual(s(350_000), 0.045)
        self.assertEqual(s(350_001), 0.03)

    def test_payment_matches_doc(self):
        self.assertAlmostEqual(sba.monthly_payment(950_000, 0.0975, 10), 12_423, delta=1)

    def test_payment_amortizes_to_zero(self):
        pmt, bal, j = sba.monthly_payment(500_000, 0.09, 10), 500_000, 0.09 / 12
        for _ in range(120):
            bal = bal * (1 + j) - pmt
        self.assertAlmostEqual(bal, 0, places=4)

    def test_zero_rate(self):
        self.assertEqual(sba.monthly_payment(120_000, 0, 10), 1000)

    def test_dscr_zero_debt(self):
        self.assertEqual(sba.dscr(100, 0), float("inf"))

    def test_debt_summary_doc_example(self):
        cfg = dict(term_years=10, **BANDS)
        buyer = dict(max_cash_equity=250_000, min_equity_injection_pct=0.10,
                     owner_living_draw=90_000)
        d = sba.debt_summary(1_200_000, 360_000, 440_000, 0.0675, cfg, buyer)
        self.assertAlmostEqual(d.rate, 0.0975)
        self.assertAlmostEqual(d.annual_payment, 149_075, delta=15)
        self.assertAlmostEqual(d.dscr_ebitda, 2.41, 2)
        self.assertAlmostEqual(d.dscr_owner, 2.35, 2)
        self.assertEqual(d.dscr_lender, d.dscr_owner)


if __name__ == "__main__":
    unittest.main()


class ReturnsTests(unittest.TestCase):
    CFG = {"dcf": dict(forecast_years=5, revenue_growth_base=0.03, tax_rate=0.24,
                       maintenance_capex_pct_of_ebitda=0.12),
           "buyer": dict(max_cash_equity=60_000, seller_standby_note=30_000)}

    def test_loan_balance_runs_to_zero_and_matches_schedule(self):
        self.assertAlmostEqual(sba.loan_balance(500_000, 0.0975, 10, 120), 0.0)
        bal, pmt = 500_000.0, sba.monthly_payment(500_000, 0.0975, 10)
        for _ in range(60):
            bal = bal * (1 + 0.0975 / 12) - pmt
        self.assertAlmostEqual(sba.loan_balance(500_000, 0.0975, 10, 60), bal, places=4)

    def test_irr_solves_npv_and_moic_ties(self):
        from biz_screener import returns
        from biz_screener.models import DebtRun
        debt = DebtRun(510_000, 0.0975, 10, 12 * sba.monthly_payment(510_000, 0.0975, 10), 2.0, 2.0, 11_475)
        r = returns.equity_returns(600_000, 220_000, 10_000, debt, self.CFG)
        self.assertAlmostEqual(r["invested"], 71_475)
        self.assertAlmostEqual(r["exit_equity"], r["exit_ev"] - r["payoff"])
        cash = [cf - debt.annual_payment for cf in dcf.project_cash_flows(220_000, 10_000, 0.03, 0.24, 0.12, 5)]
        self.assertAlmostEqual(cash[0], r["year1_cash"])
        npv = -r["invested"] + sum(c / (1 + r["irr"]) ** t for t, c in enumerate(cash, 1)) \
            + r["exit_equity"] / (1 + r["irr"]) ** 5
        self.assertAlmostEqual(npv, 0.0, places=3)
        self.assertAlmostEqual(r["moic"], (sum(cash) + r["exit_equity"]) / r["invested"])

    def test_no_returns_without_positive_ebitda(self):
        from biz_screener import returns
        from biz_screener.models import DebtRun
        self.assertIsNone(returns.equity_returns(600_000, 0, 0, DebtRun(1, 0.1, 10, 1, 1, 1), self.CFG))
