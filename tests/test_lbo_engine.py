import copy

import pytest

from ibtoolkit.lbo import CaseError, load_case, run, sensitivities, validate


def test_sources_equal_uses(sample):
    su = run(sample)["su"]
    assert su["total_sources"] == pytest.approx(su["total_uses"])
    assert su["purchase_price"] == 70000
    assert su["senior"] == 35000 and su["mezz"] == 10000


def test_no_debt_flat_ebitda_hand_check(no_debt):
    # EV 800 = equity 800. Five years of 100 cash build to 500. Exit 800 + 500 = 1300.
    r = run(no_debt)["returns"]
    assert r["exit_equity"] == pytest.approx(1300)
    assert r["moic"] == pytest.approx(1.625)
    assert r["irr"] == pytest.approx(1.625 ** 0.2 - 1)


def test_debt_rolls_forward_and_never_negative(sample):
    for sweep in (0.0, 0.5, 1.0):
        c = copy.deepcopy(sample)
        c["senior"]["sweep_pct"] = sweep
        y = run(c)["years"]
        for i in range(1, 6):
            assert y["s_end"][i] == pytest.approx(y["s_beg"][i] - y["s_mand"][i] - y["s_sweep"][i])
            assert y["s_beg"][i] == y["s_end"][i - 1]
            assert y["m_end"][i] == pytest.approx(y["m_beg"][i] + y["m_pik"][i])
            assert y["s_end"][i] >= -1e-9 and y["m_end"][i] >= 0


def test_full_sweep_on_tiny_loan_stops_at_zero(sample):
    c = copy.deepcopy(sample)
    c["senior"].update(leverage=0.2, sweep_pct=1.0)
    y = run(c)["years"]
    assert min(y["s_end"]) >= -1e-9
    assert y["s_end"][5] == pytest.approx(0)


def test_pik_accrues_only_on_mezz(sample):
    y = run(sample)["years"]
    assert y["m_end"][1] == pytest.approx(10000 * 1.06)


def test_missing_input_names_the_field(sample):
    raw = copy.deepcopy(sample)
    del raw["senior"]["rate"]
    with pytest.raises(CaseError, match="senior.rate"):
        validate(raw)


def test_bad_value_names_the_field(sample):
    raw = copy.deepcopy(sample)
    raw["operating"]["revenue_growth"] = [0.05] * 4
    with pytest.raises(CaseError, match="operating.revenue_growth"):
        validate(raw)


def test_partial_mezz_rejected(sample):
    raw = copy.deepcopy(sample)
    del raw["mezz"]["pik_rate"]
    with pytest.raises(CaseError, match="mezz.pik_rate"):
        validate(raw)


def test_sensitivity_center_matches_base(sample):
    s = sensitivities(sample)
    assert s["irr_entry_exit"][2][2] == pytest.approx(run(sample)["returns"]["irr"])
    assert s["irr_leverage_exit"][2][2] == pytest.approx(run(sample)["returns"]["irr"])
    # Higher exit multiple raises IRR; higher entry multiple lowers it.
    assert s["irr_entry_exit"][2][4] > s["irr_entry_exit"][2][0]
    assert s["irr_entry_exit"][0][2] > s["irr_entry_exit"][4][2]


def test_fixed_charge_coverage_deducts_cash_taxes(sample):
    y = run(sample)["years"]
    for i in range(1, 6):
        fixed = y["s_int"][i] + y["m_cash"][i] + y["r_int"][i] + y["r_fee"][i] + y["s_mand"][i]
        assert y["tax"][i] > 0
        assert y["fccr"][i] == pytest.approx((y["ebitda"][i] - y["capex"][i] - y["tax"][i]) / fixed)
