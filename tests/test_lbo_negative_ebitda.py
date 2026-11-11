"""A year with negative EBITDA must fail the leverage covenant, not pass it.

Leverage is debt divided by EBITDA, so negative EBITDA gives a negative ratio that
looked like headroom. Python and the workbook formula must agree on the fail.
"""
import copy

from openpyxl import load_workbook

from ibtoolkit import lbo, lbo_book
from ibtoolkit.xl_eval import Evaluator


def _negative_year_three(sample):
    c = copy.deepcopy(sample)
    c["operating"]["ebitda_margin"] = [0.168, 0.170, -0.30, 0.174, 0.175]
    return c


def test_negative_ebitda_fails_leverage_test(sample):
    r = lbo.run(_negative_year_three(sample))
    y = r["years"]
    assert y["ebitda"][3] < 0
    assert y["lev_ok"][3] == 0
    assert y["lev_ok"][1] == 1  # positive EBITDA years are unchanged
    assert r["returns"]["cov_fails"] >= 1


def test_workbook_leverage_test_fails_the_same_year(sample, outdir):
    path = lbo_book.build(_negative_year_three(sample), outdir / "neg.xlsx")
    ev = Evaluator(load_workbook(path))
    row = lbo_book.R["lev_ok"]
    assert ev.cell("Model", f"E{row}") == 0  # year 3 (column C is year 1)
    assert ev.cell("Model", f"C{row}") == 1
