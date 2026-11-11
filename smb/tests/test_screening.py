"""Config validation, scoring, red flags, CSV ingest and the end-to-end screen."""
import contextlib
import io
import os
import tempfile
import unittest
from datetime import date
from unittest import mock

from biz_screener import cli, config, ingest, pipeline, red_flags, scoring
from biz_screener.models import FinancialPeriod, Listing, Normalized, RedFlag, Score

ROOT = os.path.join(os.path.dirname(__file__), "..")
EXAMPLE = os.path.join(ROOT, "config", "settings.example.toml")
SAMPLE = os.path.join(ROOT, "data", "sample", "sample_listings.csv")
CFG = config.load_settings(EXAMPLE)


class ConfigTests(unittest.TestCase):
    def test_example_is_valid(self):
        self.assertEqual(config.validate_settings(CFG), [])

    def test_catches_bad_values(self):
        bad = config.load_settings(EXAMPLE)
        bad["valuation"]["weight_dcf"] = 0.9
        bad["industries"]["gas_station"]["sde_multiple_low"] = 9
        bad["dcf"]["tax_rate"] = 24
        bad["dcf"]["terminal_growth"] = 0.5
        errs = " | ".join(config.validate_settings(bad))
        for needle in ("valuation weights", "gas_station.sde", "dcf.tax_rate", "exceed"):
            self.assertIn(needle, errs)

    def test_env_loader_never_needs_file(self):
        self.assertEqual(config.load_env("/nonexistent/.env"), {})
        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as f:
            f.write("# c\nFRED_API_KEY=abc\nEMPTY=\n")
        try:
            self.assertEqual(config.load_env(f.name), {"FRED_API_KEY": "abc"})
        finally:
            os.unlink(f.name)


class ScoringTests(unittest.TestCase):
    def test_valuation_gap_anchors(self):
        self.assertEqual(scoring.valuation_gap_score(90, 100), 100)
        self.assertEqual(scoring.valuation_gap_score(140, 100), 0)
        self.assertAlmostEqual(scoring.valuation_gap_score(101.6, 100), 76.8)
        self.assertEqual(scoring.valuation_gap_score(50, 0), 0)

    def test_other_anchors(self):
        self.assertEqual(scoring.dscr_score(1.0), 0)
        self.assertEqual(scoring.dscr_score(2.5), 100)
        self.assertAlmostEqual(scoring.dscr_score(2.35), 90)
        self.assertEqual(scoring.trend_score(-0.05), 0)
        self.assertEqual(scoring.trend_score(0.2), 100)
        self.assertEqual(scoring.concentration_score(0.05), 100)
        self.assertEqual(scoring.concentration_score(0.5), 0)
        self.assertEqual(scoring.market_score(0.03), 100)
        self.assertIsNone(scoring.market_score(None))
        self.assertEqual(scoring.trend_score(None), 0)
        self.assertEqual(scoring.concentration_score(None), 0)

    def test_total_matches_doc_example(self):
        comps = dict(valuation_gap=77, dscr=90, revenue_trend=60, concentration=90,
                     market_context=65, data_quality=75, operational_risk=80)
        w = CFG["scoring"]["weights"]
        self.assertAlmostEqual(scoring.total_score(comps, w, 0), 76.5)
        self.assertAlmostEqual(scoring.total_score(comps, w, 5), 71.5)
        self.assertEqual(scoring.total_score(comps, w, 500), 0)

    def test_missing_market_drops_component_and_rescales_weights(self):
        w = CFG["scoring"]["weights"]
        comps = dict(valuation_gap=100, dscr=100, revenue_trend=100, concentration=100,
                     data_quality=100, operational_risk=100)
        self.assertAlmostEqual(scoring.total_score(comps, w, 0), sum(w.values()))
        comps["revenue_trend"] = 0  # weight 15 of the 85 remaining, scaled up to 100
        self.assertAlmostEqual(scoring.total_score(comps, w, 0), 100 - 15 * 100 / 85)

    def test_deal_score_has_no_neutral_market_50(self):
        deals, _ = ingest.parse_csv(SAMPLE)
        sc = pipeline.screen_deal(*deals[0], CFG)[0]
        self.assertNotIn("market_context", sc.components)
        self.assertEqual(sc.notes, ["market context not scored (data not built)",
                                    "customer concentration not provided: ask the broker"])
        self.assertEqual(sc.components["concentration"], 0)

    def test_blank_growth_scores_zero_with_note(self):
        deals, _ = ingest.parse_csv(SAMPLE)
        listing, periods, adds = deals[0]
        listing.top_customer_share = 0.1
        sc = pipeline.screen_deal(listing, periods[:1], adds, CFG)[0]
        self.assertEqual(sc.components["revenue_trend"], 0)
        self.assertIn("revenue growth not provided: ask the broker", sc.notes)
        self.assertNotIn("customer concentration not provided: ask the broker", sc.notes)

    def test_rank_ties_go_to_cheaper(self):
        a, b, c = Score({}, 0, 70, 900), Score({}, 0, 70, 500), Score({}, 0, 80, 1000)
        self.assertEqual(scoring.rank_listings([a, b, c]), [c, b, a])
        self.assertEqual((c.rank, b.rank, a.rank), (1, 2, 3))


def _periods(*revs):
    return [FinancialPeriod(2020 + i, r, 100) for i, r in enumerate(revs)]


class FlagTests(unittest.TestCase):
    def codes(self, listing, periods, norm, ind=None):
        return {f.code for f in red_flags.evaluate_flags(listing, periods, norm, CFG, ind)}

    def test_clean_deal_has_no_flags(self):
        l = Listing("t", "x", "laundromat", 300_000)
        n = [Normalized(2022, 150_000, 100_000, 0.1)]
        self.assertEqual(self.codes(l, _periods(10, 11, 12), n), set())

    def test_each_rule(self):
        l = Listing("t", "x", "laundromat", 600_000, top_customer_share=0.3,
                    lease_years_remaining=2)
        n = [Normalized(2022, 150_000, 100_000, 0.9)]
        got = self.codes(l, _periods(12, 11, 10), n, dict(tabc_transfer_flag=True, environmental_flag=True))
        self.assertEqual(got, {"addback_ratio", "asking_multiple", "declining_revenue",
                               "concentration", "short_lease", "tabc_transfer", "environmental"})

    def test_missing_and_estimated_financials(self):
        l = Listing("t", "x", "laundromat", 1)
        self.assertIn("missing_financials", self.codes(l, [], []))
        est = [FinancialPeriod(2022, 1, 1, is_stated=False)]
        self.assertIn("missing_financials", self.codes(l, est, []))

    def test_one_down_year_is_not_a_decline_flag(self):
        l = Listing("t", "x", "laundromat", 1)
        self.assertNotIn("declining_revenue", self.codes(l, _periods(10, 12, 11), []))

    def test_penalty_cap(self):
        flags = [RedFlag("a", "high", "")] * 9
        self.assertEqual(red_flags.penalty(flags, 5, 20), 20)
        self.assertEqual(red_flags.penalty(flags[:2], 5, 20), 10)


class IngestTests(unittest.TestCase):
    def test_parse_money(self):
        self.assertEqual(ingest.parse_money("$1,250"), 1250.0)
        self.assertEqual(ingest.parse_money("(5,000)"), -5000.0)
        self.assertIsNone(ingest.parse_money(" "))
        with self.assertRaises(ValueError):
            ingest.parse_money("abc")

    def test_sample_groups_years_and_rejects_bad_rows(self):
        deals, rejects = ingest.parse_csv(SAMPLE)
        self.assertEqual(len(deals), 4)
        self.assertEqual([len(d[1]) for d in deals], [2, 2, 2, 3])
        self.assertEqual(rejects, [])
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write("ref,category,asking_price,fiscal_year,revenue,pretax_income\n"
                    "A,laundromat,100,2024,50,10\nB,laundromat,,2024,50,10\nC,laundromat,1,x,5,5\n")
        try:
            deals, rejects = ingest.parse_csv(f.name)
        finally:
            os.unlink(f.name)
        self.assertEqual(len(deals), 1)
        self.assertEqual(len(rejects), 2)
        self.assertIn("line 3", rejects[0])


class PipelineTests(unittest.TestCase):
    def test_gas_example_blended_and_dscr(self):
        deals, _ = ingest.parse_csv(SAMPLE)
        listing, periods, adds = deals[0]
        score, val, debt = pipeline.screen_deal(listing, periods, adds, CFG)
        self.assertEqual(listing.external_ref, "SAMPLE-GAS-1")
        self.assertGreater(val.blended_value, 0)
        self.assertGreater(debt.dscr_lender, 1.25)
        self.assertTrue(0 <= score.total <= 100)

    def test_equity_shortfall_flagged_not_crashed(self):
        listing = Listing("t", "big", "laundromat", 9_000_000)
        p = [FinancialPeriod(2024, 5e6, 900_000, depreciation=50_000)]
        score, _, debt = pipeline.screen_deal(listing, p, [], CFG)
        self.assertIsNone(debt)
        self.assertIn("equity_shortfall", [f.code for f in score.flags])

    def test_losing_business_scores_low_without_crashing(self):
        listing = Listing("t", "bad", "car_wash", 500_000)
        p = [FinancialPeriod(2024, 400_000, -50_000)]
        score, val, _ = pipeline.screen_deal(listing, p, [], CFG)
        self.assertEqual(val.sde_value, 0)
        self.assertIn("nonpositive_sde", [f.code for f in score.flags])


class CliTests(unittest.TestCase):
    def test_screen_prints_ranked_table(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["screen", SAMPLE])
        self.assertEqual(code, 0)
        lines = out.getvalue().splitlines()
        self.assertTrue(lines[1].startswith("1 "))
        self.assertIn("SAMPLE-LIQUOR-1", lines[4])  # worst deal ranks last
        # long refs widen the Ref column, so every row's Category starts under the header
        col = lines[0].index("Category")
        self.assertTrue(all(l[col - 1] == " " and l[col] != " " for l in lines[:5]))

    def test_reports_db_live_rates_and_alerts_with_fake_network(self):
        class Resp:
            def __init__(self, body):
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return self.body.encode()

        sent = []

        def opener(req, timeout=None):
            if isinstance(req, str):
                return Resp("observation_date,%s\n2026-10-13,5.0\n" % req.split("=")[-1])
            sent.append(req)
            return Resp('{"ok": true}')

        env = {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "1"}
        out = io.StringIO()
        with tempfile.TemporaryDirectory(dir=ROOT) as d, \
                mock.patch.dict(os.environ, env), contextlib.redirect_stdout(out):
            db, html, csv_out = [os.path.join(d, n) for n in ("a.db", "a.html", "a.csv")]
            code = cli.screen(SAMPLE, db=db, html=html, csv_out=csv_out, live_rates=True,
                              alert=True, opener=opener, today=date(2026, 10, 21))
            with open(html) as f:
                self.assertIn("<table>", f.read())
            with open(csv_out) as f:
                self.assertIn("Blocked", f.read())
        self.assertEqual(code, 0)
        self.assertIn("Alerts sent: 1", out.getvalue())  # only the illustrative deal passes
        self.assertEqual(len(sent), 1)

    def _live_run(self, body, today=date(2026, 10, 21)):
        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return body.encode()

        with tempfile.TemporaryDirectory(dir=ROOT) as d:
            db = os.path.join(d, "a.db")
            with self.assertRaises(SystemExit) as cm, contextlib.redirect_stdout(io.StringIO()):
                cli.screen(SAMPLE, db=db, live_rates=True, opener=lambda u, timeout=None: Resp(),
                           today=today)
            self.assertFalse(os.path.exists(db))  # a stopped run saves nothing
        return str(cm.exception)

    def test_maintenance_page_stops_the_run(self):
        self.assertIn("Nothing was scored", self._live_run("<html>Down for maintenance</html>"))

    def test_stale_observation_stops_the_run(self):
        msg = self._live_run("observation_date,DPRIME\n2026-10-01,6.75\n")
        self.assertIn("days old", msg)

    def test_alert_without_db_is_refused(self):
        with self.assertRaises(SystemExit):
            cli.screen(SAMPLE, alert=True)


if __name__ == "__main__":
    unittest.main()
