import copy

import pytest

from ibtoolkit.lbo import CaseError
from ibtoolkit.merger import run, sensitivities, validate
from merger_cases import all_stock, sample


def test_all_stock_hand_check():
    r = run(all_stock())
    assert r["price"] == 100 and r["stock"] == 100 and r["cash"] == 0
    assert r["new_shares"] == pytest.approx(10)
    assert r["own_tgt"] == pytest.approx(10 / 110)
    # PF NI 112 over 110 shares against standalone EPS of 1.00.
    assert r["years"][0]["eps"] == pytest.approx(112 / 110)
    assert r["years"][0]["acc_pct"] == pytest.approx(112 / 110 - 1)
    # PF TBV 540 over 110 shares against 5.00, so 0.0909 of dilution at close.
    assert r["pf_tbvps"] == pytest.approx(540 / 110)
    assert r["tbv_dil_d"] == pytest.approx(540 / 110 - 5)
    assert r["goodwill"] == pytest.approx(60)  # 100 price less 40 TBV
    assert r["pf_tce"] == pytest.approx(540 / 5400)


def test_earnback_simple_case_is_five_years():
    # Gap of 0.1/1.1 closes by 2/110 a year: exactly 5.0 years.
    assert run(all_stock())["earnback"] == pytest.approx(5.0)


def test_earnback_zero_when_no_dilution_and_negative_one_when_never():
    c = all_stock()
    c["target"]["tbv"] = 400.0
    assert run(c)["earnback"] == 0
    c = all_stock()
    c["target"]["net_income"] = [1.0, 1.0]  # dilutive EPS, so the gap never closes
    assert run(c)["earnback"] == -1


def test_purchase_accounting_marks_and_goodwill(): 
    c = all_stock()
    c["target"].update(loans=1000.0, securities=200.0, core_deposits=800.0)
    c["marks"].update(loan_duration=3.0, loan_rate_change=0.01, securities_duration=4.0,
                      securities_rate_change=0.01)
    c["deal"]["cdi_pct"] = 0.02
    r = run(c)
    assert r["loan_mark"] == pytest.approx(-30) and r["sec_mark"] == pytest.approx(-8)
    assert r["cdi"] == pytest.approx(16)
    # FV net assets = 40 - 38 + 16 - 25% x (-38 + 16)
    assert r["fv_net_assets"] == pytest.approx(40 - 38 + 16 + 5.5)
    assert r["goodwill"] == pytest.approx(100 - r["fv_net_assets"])


def test_p_tbv_pricing_matches_price_per_share():
    c = all_stock()
    c["deal"].pop("price_per_share")
    c["deal"]["p_tbv"] = 2.5  # 2.5 x 40 / 20 shares = $5.00
    assert run(c)["offer_pps"] == pytest.approx(5.0)


def test_cash_deal_charges_funding_and_ownership():
    c = all_stock()
    c["deal"].update(stock_pct=0.0, cost_of_cash=0.04)
    r = run(c)
    assert r["new_shares"] == 0 and r["own_acq"] == 1
    assert r["years"][0]["ni"] == pytest.approx(112 - 4 * 0.75)


def test_missing_and_bad_inputs_name_the_field():
    raw = copy.deepcopy(sample())
    del raw["deal"]["tax_rate"]
    with pytest.raises(CaseError, match="deal.tax_rate"):
        validate(raw)
    raw = copy.deepcopy(sample())
    raw["target"]["net_income"] = [1.0]
    with pytest.raises(CaseError, match="target.net_income"):
        validate(raw)
    raw = copy.deepcopy(sample())
    raw["deal"]["price_per_share"] = 40.0  # p_tbv is already set
    with pytest.raises(CaseError, match="exactly one"):
        validate(raw)


def test_sensitivity_center_and_direction():
    c = sample()
    s = sensitivities(c)
    base = run(c)["years"]
    assert s["acc_y2"][2][2] == pytest.approx(base[1]["acc_pct"])
    assert s["acc_y1"][2][2] == pytest.approx(base[0]["acc_pct"])
    assert s["acc_y2"][0][2] > s["acc_y2"][4][2]  # lower price, more accretion
    assert s["acc_y2"][2][4] > s["acc_y2"][2][0]  # more saves, more accretion
