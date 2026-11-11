"""Selling securities to repay borrowings shrinks pro forma tangible assets, not TBV.

Before this fix the pro forma tangible assets ignored the sale, which understated the
pro forma TCE ratio. Both the Python engine and the workbook must agree.
"""
import copy

import pytest
from openpyxl import load_workbook

from ibtoolkit import merger, merger_book
from ibtoolkit.xl_eval import Evaluator
from merger_cases import all_stock


def _sold(amount=40.0):
    c = copy.deepcopy(all_stock())
    c["target"]["securities"] = 50.0  # same book in the base case, so only the sale differs
    c["restructuring"] = {"securities_sold": amount, "securities_yield": 0.0, "borrowing_rate": 0.0}
    return c


def _no_sale():
    c = _sold(0.0)
    return c


def test_securities_sold_reduce_pro_forma_tangible_assets_only():
    base, r = merger.run(_no_sale()), merger.run(_sold(40.0))
    assert r["pf_ta"] == pytest.approx(base["pf_ta"] - 40.0)
    assert r["pf_tbv"] == pytest.approx(base["pf_tbv"])
    assert r["pf_tce"] == pytest.approx(r["pf_tbv"] / r["pf_ta"])
    assert r["pf_tce"] > base["pf_tce"]


def test_workbook_pro_forma_tangible_assets_match_python(outdir):
    case = _sold(40.0)
    path = merger_book.build(case, outdir / "restr.xlsx")
    ev = Evaluator(load_workbook(path))
    assert ev.name("PF_TA") == pytest.approx(merger.run(case)["pf_ta"])
