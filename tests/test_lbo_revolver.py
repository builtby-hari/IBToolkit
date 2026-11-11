"""Revolver, financing fees, covenants and the live sensitivity grid."""
import copy

import pytest
from openpyxl import load_workbook

from ibtoolkit import lbo, lbo_book
from ibtoolkit.lbo import CaseError, run, sensitivities, validate
from ibtoolkit.xl_eval import Evaluator

COLS = "BCDEFG"


def variant(sample, **sections):
    c = copy.deepcopy(sample)
    for sec, vals in sections.items():
        c[sec].update(vals)
    return c


def test_revolver_draws_when_cash_short_then_repays_before_sweep(sample):
    y = run(sample)["years"]
    # Year 1: cash before revolver is below the 3,000 minimum, so the revolver covers the gap.
    assert y["cash_pre"][1] < 3000
    assert y["r_draw"][1] == pytest.approx(3000 - y["cash_pre"][1])
    assert y["cash_end"][1] == pytest.approx(3000)
    assert y["s_sweep"][1] == 0
    # Year 2: repaid in full first, and the sweep is on what is left after that repayment.
    assert y["r_repay"][2] == pytest.approx(y["r_draw"][1])
    assert y["r_end"][2] == pytest.approx(0)
    assert y["s_sweep"][2] == pytest.approx(0.5 * (y["fcf"][2] - y["s_mand"][2] - y["r_repay"][2]))
    # Interest and fee are on beginning balances.
    assert y["r_int"][2] == pytest.approx(y["r_draw"][1] * 0.085)
    assert y["r_fee"][2] == pytest.approx((5000 - y["r_draw"][1]) * 0.005)


def test_revolver_draw_is_capped_by_commitment(sample):
    c = variant(sample, revolver=dict(commitment=300))
    r = run(c)
    assert r["years"]["r_draw"][1] == pytest.approx(300)
    assert r["returns"]["min_cash"] < 3000  # cash stays short, which the Checks sheet flags


def test_no_revolver_section_keeps_old_behavior(sample):
    c = variant(sample, revolver=dict(commitment=0.0, rate=0.0, undrawn_fee=0.0, min_cash=0.0))
    y = run(c)["years"]
    assert max(y["r_end"]) == 0 and max(y["r_int"][1:]) == 0


def test_financing_fees_amortize_to_zero_and_are_tax_deductible(sample):
    r = run(sample)
    y, fin = r["years"], r["su"]["financing"]
    assert fin == pytest.approx(0.025 * (35000 + 10000 + 5000))  # revolver commitment is in the base
    assert sum(y["fee_amort"][1:]) == pytest.approx(fin)
    assert y["fee_end"][5] == pytest.approx(0)
    assert y["ebt"][1] == pytest.approx(y["ebit"][1] - fin / 5 - y["s_int"][1] - y["m_cash"][1]
                                        - y["m_pik"][1] - y["r_int"][1] - y["r_fee"][1])
    assert y["fcf"][1] + y["tax"][1] == pytest.approx(  # amortization is non-cash
        y["ebitda"][1] - y["s_int"][1] - y["m_cash"][1] - y["r_int"][1] - y["r_fee"][1]
        - y["capex"][1] - y["dnwc"][1])


def test_longer_fee_term_leaves_unamortized_balance(sample):
    y = run(variant(sample, transaction=dict(financing_fee_years=10.0)))["years"]
    assert y["fee_end"][5] == pytest.approx(y["fee_end"][0] / 2)


def test_covenant_flags_and_headroom(sample):
    y = run(sample)["years"]
    assert all(y["lev_ok"][1:]) and all(y["cov_ok"][1:])
    assert y["lev_head"][1] == pytest.approx(1 - y["lev_tot"][1] / 5.75)
    assert y["cov_head"][1] == pytest.approx(1 - 1.75 / y["cov"][1])
    tight = variant(sample, covenants=dict(max_total_leverage=[3.0] * 5, min_interest_coverage=[3.0] * 5))
    r = run(tight)
    assert r["years"]["lev_ok"][1] == 0 and r["years"]["lev_head"][1] < 0
    assert r["years"]["cov_ok"][1] == 0  # year 1 coverage is about 2.8x
    assert r["returns"]["cov_fails"] > 0


def test_partial_sections_rejected(sample):
    raw = {"revolver": {"commitment": 100.0}}
    with pytest.raises(CaseError, match="revolver.rate"):
        validate({**_raw(sample), **raw})
    with pytest.raises(CaseError, match="covenants.min_interest_coverage"):
        validate({**_raw(sample), "covenants": {"max_total_leverage": [5.0] * 5}})


def _raw(case):
    return {k: v for k, v in case.items() if k in ("meta", "transaction", "operating", "senior", "mezz")}


VARIANTS = {
    "sample": {},
    "capped_revolver": dict(revolver=dict(commitment=300)),
    "long_fee_term": dict(transaction=dict(financing_fee_years=7.0)),
    "tight_covenants": dict(covenants=dict(max_total_leverage=[3.0] * 5, min_interest_coverage=[3.0] * 5)),
    "heavy_draws": dict(revolver=dict(min_cash=9000, commitment=20000)),
}


@pytest.mark.parametrize("name", list(VARIANTS))
def test_workbook_matches_python(name, sample, outdir):
    case = variant(sample, **VARIANTS[name])
    wb = load_workbook(lbo_book.build(case, outdir / "v.xlsx"))
    ev = Evaluator(wb)
    res = run(case)
    for key in lbo_book.MODEL_KEYS:
        for i, col in enumerate(COLS):
            py = res["years"][key][i]
            if py is not None:
                assert ev.cell("Model", f"{col}{lbo_book.R[key]}") == pytest.approx(py, rel=1e-9, abs=1e-9), (key, i)
    assert ev.name("Sponsor_IRR") == pytest.approx(res["returns"]["irr"])
    assert ev.name("Covenant_Fails") == res["returns"]["cov_fails"]
    assert ev.name("Peak_Revolver") == pytest.approx(res["returns"]["peak_revolver"])
    expect_fail = name in ("capped_revolver", "tight_covenants")
    assert (ev.name("Checks_Total") > 0) == expect_fail, ev.name("Checks_Total")


def test_live_entry_exit_grid_matches_python_engine(sample, outdir):
    wb = load_workbook(lbo_book.build(sample, outdir / "g.xlsx"))
    ev = Evaluator(wb)
    s = sensitivities(sample)
    top = lbo_book.GRID_TOPS[0]
    for j, c in enumerate("BCDEF"):
        assert ev.cell("Sensitivity", f"{c}{top + 1}") == pytest.approx(s["exit_axis"][j])
    for i in range(5):
        assert ev.cell("Sensitivity", f"A{top + 2 + i}") == pytest.approx(s["entry_axis"][i])
        for j, c in enumerate("BCDEF"):
            assert ev.cell("Sensitivity", f"{c}{top + 2 + i}") == pytest.approx(s["irr_entry_exit"][i][j])
    assert ev.cell("Sensitivity", f"D{top + 4}") == pytest.approx(run(sample)["returns"]["irr"])
