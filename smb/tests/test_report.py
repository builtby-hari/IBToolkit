"""HTML and CSV reports: escaping, self-contained page, plain-words blocked reasons."""
import csv
import io
import os
import re
import tempfile
import unittest

from biz_screener import report
from biz_screener.models import RedFlag, Result

def make(ref="A1", dscr=1.4, flags=(), rank=1):
    return Result("csv", ref, "gas_station", "48113", 1000000.0, 900000.0, dscr, 71.5, rank,
                  list(flags))


LOW = RedFlag("low_dscr", "high", "Lender DSCR 1.10x is below 1.25x")


class ReportTests(unittest.TestCase):
    def test_pass_and_block(self):
        self.assertEqual(report.blocked_reasons(make()), [])
        why = report.blocked_reasons(make(dscr=1.1, flags=[LOW]))
        self.assertEqual(len(why), 1)
        self.assertIn("too thin", why[0])
        self.assertIn("1.10x", why[0])

    def test_missing_dscr_blocks_even_without_flags(self):
        self.assertIn("No loan coverage", report.blocked_reasons(make(dscr=None))[0])

    def test_medium_flag_does_not_block(self):
        self.assertEqual(report.blocked_reasons(make(flags=[RedFlag("short_lease", "medium", "x")])), [])

    def test_html_escapes_and_is_self_contained(self):
        evil = '<script>alert(1)</script>'
        html = report.render_html([make(ref=evil, dscr=None)], title="A & B")
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("A &amp; B", html)
        self.assertIn("not advice", html)
        self.assertIsNone(re.search(r"(src|href)\s*=|@import|url\(", html))
        self.assertIn("Blocked", html)

    def test_csv_rows_and_formula_guard(self):
        out = report.render_csv([make("=CMD()", flags=[LOW], dscr=1.1), make("B2", rank=2)])
        rows = list(csv.reader(io.StringIO(out)))
        self.assertEqual(rows[1][1], "'=CMD()")
        self.assertEqual(rows[1][8], "Blocked")
        self.assertIn("too thin", rows[1][9])
        self.assertEqual(rows[2][8], "Passes")


if __name__ == "__main__":
    unittest.main()


HEAD = ("ref,category,county_fips,asking_price,fiscal_year,revenue,pretax_income,interest,"
        "depreciation,amortization,owner_salary,addbacks,top_customer_share,lease_years_remaining\n")
PASSING = "%s,laundromat,48085,500000,%d,420000,%d,0,0,0,0,0,0.1,8\n"
BLOCKED = "BAD-1,car_wash,48085,500000,2024,400000,-50000,0,0,0,0,0,,8\n"


class TeaserTests(unittest.TestCase):
    def run_screen(self, d, refs):
        import contextlib
        from biz_screener import cli
        rows = "".join(PASSING % (r, y, inc) for r in refs for y, inc in ((2023, 150000), (2024, 160000)))
        path = os.path.join(d, "in.csv")
        with open(path, "w", encoding="utf-8") as f:
            f.write(HEAD + rows + BLOCKED)
        out = os.path.join(d, "out")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cli.screen(path, teasers=out)
        return out, sorted(os.listdir(out))

    def test_file_per_passing_deal_only_with_footer_and_no_external_urls(self):
        with tempfile.TemporaryDirectory() as d:
            out, names = self.run_screen(d, ["OK-1", "OK-2"])
            self.assertEqual(len(names), 2)  # BAD-1 is blocked, so it gets no page
            for n in names:
                html = open(os.path.join(out, n), encoding="utf-8").read()
                self.assertIn("Illustrative analysis, not advice", html)
                self.assertIn("@media print", html)
                self.assertIn("Lender DSCR", html)
                self.assertIsNone(re.search(r"(src|href)\s*=|@import|url\(|https?://", html))

    def test_text_is_escaped_and_file_name_is_safe(self):
        with tempfile.TemporaryDirectory() as d:
            out, names = self.run_screen(d, ["<b>x</b>/.."])
            self.assertEqual(len(names), 1)
            self.assertNotIn("/", names[0])
            html = open(os.path.join(out, names[0]), encoding="utf-8").read()
            self.assertNotIn("<b>x</b>", html)
            self.assertIn("&lt;b&gt;x&lt;/b&gt;", html)
