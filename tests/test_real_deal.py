"""Eastern / HarborOne real deal case: loads, workbook checks pass, and outputs stay within the
tolerances the README documents (no network)."""
import pytest
from openpyxl import load_workbook

from ibtoolkit import merger, merger_book
from ibtoolkit.xl_eval import Evaluator
from merger_cases import ROOT, all_stock
from test_integrity import flags

CASE = ROOT / "cases" / "merger_real_eastern_harborone.toml"


def test_real_case_matches_documented_values():
    r = merger.run(merger.load_case(CASE))
    y1 = r["years"][0]
    assert r["price"] == pytest.approx(490_000, rel=0.01)       # deck: $490mm
    assert r["p_tbv"] == pytest.approx(1.00, abs=0.01)           # deck: 1.00x
    assert r["new_shares"] == pytest.approx(25_200, rel=0.01)    # deck: 25.2mm
    assert r["pf_shares"] == pytest.approx(235_000, rel=0.01)    # deck: 235.0mm
    assert r["loan_mark"] == pytest.approx(-234_000, rel=0.001)  # deck: $234mm
    # Deck $203mm; ours is higher by the after-tax non-PCD credit mark booked at close (41.6mm x 77.4%).
    assert r["goodwill"] + r["cdi"] == pytest.approx(203_000 + 41_600 * (1 - 0.226), rel=0.005)
    assert r["exch_ratio"] == 0.765                              # deck: 0.765 stock election
    assert r["blend_ratio"] == pytest.approx(0.612, abs=0.001)   # 80% stock x 0.765
    assert y1["acc_pct"] == pytest.approx(0.156, abs=0.003)      # documented 15.6%, deck ~16%
    assert y1["eps"] == pytest.approx(1.98, abs=0.01)            # deck: $1.98
    assert r["tbv_dil_pct"] == pytest.approx(-0.0835, abs=0.001)  # documented -8.3%, deck -7.3%
    assert r["pf_tbv"] == pytest.approx(2_772_000, rel=0.001)    # deck: $2,803mm, less the $32mm after-tax non-PCD mark
    assert r["earnback"] == pytest.approx(3.06, abs=0.01)        # documented 3.1, deck 2.8


def test_real_workbook_checks_pass_and_match_engine(outdir):
    case = merger.load_case(CASE)
    wb = load_workbook(merger_book.build(case, outdir / "real.xlsx"))
    ev = Evaluator(wb)
    assert all(f == 0 for f in flags(wb, ev))
    r = merger.run(case)
    assert ev.name("PF_acc_pct_1") == pytest.approx(r["years"][0]["acc_pct"])
    assert ev.name("PF_acc_pct_2") == pytest.approx(r["years"][1]["acc_pct"])
    assert ev.name("PF_TBV") == pytest.approx(r["pf_tbv"])
    assert ev.name("Earnback_Years") == pytest.approx(r["earnback"])


def test_syd_cdi_sums_to_total_and_front_loads():
    c = all_stock()
    c["target"]["core_deposits"] = 1000.0
    c["deal"].update(cdi_pct=0.055, cdi_years=10, cdi_method="syd")
    y = merger.run(c)["years"][0]["cdi_amort"]
    assert y == pytest.approx(55 * 10 / 55)  # 10/55 of the CDI in year 1


def test_day2_reserve_and_dissynergies_hand_check():
    c = all_stock()
    c["deal"].update(day2_reserve=40.0, revenue_dissynergies=8.0)
    base = merger.run(all_stock())
    r = merger.run(c)
    assert base["pf_tbv"] - r["pf_tbv"] == pytest.approx(40 * 0.75)  # after-tax, at close
    assert r["years"][0]["ni"] == pytest.approx(base["years"][0]["ni"] - 8 * 0.75)
    assert r["years"][0]["acc_pct"] < base["years"][0]["acc_pct"]


def test_workbook_matches_engine_with_new_inputs(outdir):
    c = all_stock()
    c["target"]["core_deposits"] = 1000.0
    c["deal"].update(day2_reserve=40.0, revenue_dissynergies=8.0, cdi_pct=0.02, cdi_method="syd")
    wb = load_workbook(merger_book.build(c, outdir / "n.xlsx"))
    ev, r = Evaluator(wb), merger.run(c)
    assert ev.name("PF_TBV") == pytest.approx(r["pf_tbv"])
    assert ev.name("PF_eps_1") == pytest.approx(r["years"][0]["eps"])
    assert ev.name("PF_eps_2") == pytest.approx(r["years"][1]["eps"])


def test_bad_cdi_method_is_rejected():
    from ibtoolkit.lbo import CaseError
    c = all_stock()
    c["deal"]["cdi_method"] = "declining"
    with pytest.raises(CaseError, match="cdi_method"):
        merger.validate(c)


def test_restructuring_hand_check():
    c = all_stock()
    c["target"]["securities"] = 200.0
    c["marks"]["securities_duration"] = 0.0  # isolate the restructuring pickup from any securities mark
    c["restructuring"].update(securities_sold=200.0, securities_yield=0.02, borrowing_rate=0.05)
    base, r = merger.run(all_stock()), merger.run(c)
    assert r["years"][0]["restr"] == pytest.approx(6.0)  # 200 x 3 points
    assert r["years"][0]["ni"] == pytest.approx(base["years"][0]["ni"] + 6 * 0.75)
    assert r["pf_tbv"] == base["pf_tbv"]


def test_credit_mark_split_hand_check():
    c = all_stock()
    c["credit_mark"].update(total=100.0, pcd_share=0.6, life=4)
    base, r = merger.run(all_stock()), merger.run(c)
    assert r["pcd_mark"] == pytest.approx(60) and r["nonpcd_mark"] == pytest.approx(40)
    assert r["years"][0]["credit_accr"] == pytest.approx(10)  # 40 over 4 years, PCD never accretes
    assert r["years"][0]["ni"] == pytest.approx(base["years"][0]["ni"] + 10 * 0.75)
    # The non-PCD part is a loan write-down at close: goodwill up and TBV down by 40 after tax.
    assert r["net_marks"] == pytest.approx(-40)
    assert r["goodwill"] - base["goodwill"] == pytest.approx(40 * 0.75)
    assert base["pf_tbv"] - r["pf_tbv"] == pytest.approx(40 * 0.75)
    assert r["pf_ta"] == pytest.approx(base["pf_ta"] - 40 * 0.75)
    c["credit_mark"]["life"] = 1  # accretion stops after its life
    assert merger.run(c)["years"][1]["credit_accr"] == 0


def test_deposit_and_borrowings_marks_hand_check():
    c = all_stock()
    c["marks"].update(deposit_mark=20.0, deposit_life=1, borrowings_mark=-10.0, borrowings_life=2)
    base, r = merger.run(all_stock()), merger.run(c)
    # Net +10 of liability write-down lifts TBV after tax; amortization hits income: Y1 20 - 5, Y2 0 + 5 reversed.
    assert r["pf_tbv"] - base["pf_tbv"] == pytest.approx(10 * 0.75)
    assert r["years"][0]["dep_amort"] == pytest.approx(20 - 5)
    assert r["years"][1]["dep_amort"] == pytest.approx(-5)
    assert r["years"][0]["ni"] == pytest.approx(base["years"][0]["ni"] - 15 * 0.75)


def test_cdi_gross_deducts_deferred_tax_liability():
    c = all_stock()
    c["target"]["core_deposits"] = 1000.0
    c["deal"]["cdi_pct"] = 0.04  # CDI 40, DTL 10
    net = merger.run(c)
    c["deal"]["cdi_tax_treatment"] = "gross"
    gross = merger.run(c)
    assert net["pf_tbv"] - gross["pf_tbv"] == pytest.approx(10)
    assert net["pf_ta"] - gross["pf_ta"] == pytest.approx(10)
    assert gross["years"][0]["eps"] == net["years"][0]["eps"]


def test_new_inputs_validate():
    from ibtoolkit.lbo import CaseError
    c = all_stock()
    c["restructuring"]["securities_sold"] = 5.0  # target holds 0 securities
    with pytest.raises(CaseError, match="securities_sold"):
        merger.validate(c)
    c = all_stock()
    c["deal"]["cdi_tax_treatment"] = "half"
    with pytest.raises(CaseError, match="cdi_tax_treatment"):
        merger.validate(c)
    c = all_stock()
    c["credit_mark"]["pcd_share"] = 1.5
    with pytest.raises(CaseError, match="pcd_share"):
        merger.validate(c)


def test_workbook_matches_engine_with_all_new_items(outdir):
    c = all_stock()
    c["target"].update(securities=200.0, core_deposits=1000.0)
    c["deal"].update(cdi_pct=0.04, cdi_tax_treatment="gross")
    c["restructuring"].update(securities_sold=200.0, securities_yield=0.02, borrowing_rate=0.05)
    c["credit_mark"].update(total=100.0, pcd_share=0.6, life=4)
    c["marks"].update(deposit_mark=20.0, deposit_life=1, borrowings_mark=-10.0, borrowings_life=2)
    wb = load_workbook(merger_book.build(c, outdir / "all.xlsx"))
    ev, r = Evaluator(wb), merger.run(c)
    assert all(f == 0 for f in flags(wb, ev))
    for y in (1, 2):
        assert ev.name(f"PF_eps_{y}") == pytest.approx(r["years"][y - 1]["eps"])
    assert ev.name("PF_TBV") == pytest.approx(r["pf_tbv"])
    assert ev.name("PF_TA") == pytest.approx(r["pf_ta"])
    assert ev.name("Goodwill") == pytest.approx(r["goodwill"])
    assert ev.name("Earnback_Years") == pytest.approx(r["earnback"])


def test_earnback_adds_back_cdi_amortization_by_tax_treatment():
    c = all_stock()
    c["target"]["core_deposits"] = 1000.0
    c["deal"]["cdi_pct"] = 0.04  # CDI 40, 4 a year straight line
    net = merger.run(c)["years"][0]
    assert net["tang_eps"] == pytest.approx((net["ni"] + 4 * 0.75) / 110)
    c["deal"]["cdi_tax_treatment"] = "gross"
    gross = merger.run(c)["years"][0]
    assert gross["tang_eps"] == pytest.approx((gross["ni"] + 4) / 110)  # full pre-tax amount


def test_exchange_ratio_is_stock_election_not_blended():
    from merger_cases import sample
    r = merger.run(sample())
    assert r["exch_ratio"] == pytest.approx(r["offer_pps"] / 48.0)  # default: offer price / acquirer price
    assert r["blend_ratio"] == pytest.approx(r["new_shares"] / 10000)
    assert r["blend_ratio"] == pytest.approx(r["exch_ratio"] * 0.60)


def test_net_deferred_tax_sign_follows_economics():
    c = all_stock()
    c["target"]["loans"] = 1000.0
    c["marks"].update(loan_duration=3.0, loan_rate_change=0.01)  # 30 write-down, no CDI
    assert merger.run(c)["net_dta"] == pytest.approx(7.5)  # deferred tax asset, positive
    c["target"]["core_deposits"] = 2000.0
    c["deal"]["cdi_pct"] = 0.04  # CDI 80 outweighs the write-down
    assert merger.run(c)["net_dta"] == pytest.approx(-0.25 * 50)  # net liability, negative


def test_real_workbook_labels_and_conventions(tmp_path):
    from ibtoolkit.__main__ import main
    xlsx, page = tmp_path / "r.xlsx", tmp_path / "r.html"
    assert main(["merger", str(CASE), "--out", str(xlsx), "--pitch", str(page)]) == 0
    wb, ev = load_workbook(xlsx), Evaluator(load_workbook(xlsx))
    labels = [c.value for c in wb["Purchase_Accounting"]["A"] if c.value]
    assert "Plus: Net Deferred Tax Asset / (Liability)" in labels and "Less: Deferred Tax Liability" not in labels
    assert ev.name("Exch_Ratio") == pytest.approx(0.765)
    assert ev.name("Net_DTA") == pytest.approx(merger.run(merger.load_case(CASE))["net_dta"])
    doc = page.read_text()
    assert "sum of years digits" in doc and "straight line and tax effected" not in doc
    for item in ("restructuring pickup", "non-PCD credit mark accretion", "deposit mark amortization",
                 "dis-synergies", "day 2 reserve"):
        assert item in doc, item


def test_asu_2025_08_gross_up_hand_check():
    c = all_stock()
    c["deal"]["day2_reserve"] = 40.0
    c["credit_mark"].update(total=100.0, pcd_share=0.6, life=4)  # non-PCD mark 40
    day2 = merger.run(c)
    c["credit_mark"]["non_pcd_method"] = "gross_up"
    up = merger.run(c)
    # The 40 allowance goes to amortized cost, not expense: TBV is higher by 40 after tax.
    assert up["pf_tbv"] - day2["pf_tbv"] == pytest.approx(40 * 0.75)
    assert up["tbv_dil_pct"] > day2["tbv_dil_pct"]
    assert up["goodwill"] == day2["goodwill"]  # net loan carrying value is still fair value
    # The credit component covered by the allowance is not accreted: (40 - 40) / 4 = 0 versus 10.
    assert day2["years"][0]["credit_accr"] == pytest.approx(10)
    assert up["years"][0]["credit_accr"] == pytest.approx(0)


def test_asu_2025_08_real_case_and_workbook(tmp_path):
    from ibtoolkit import pitch
    from ibtoolkit.lbo import CaseError
    case = merger.load_case(CASE)
    assert case["credit_mark"]["non_pcd_method"] == "day2"  # default leaves the documented results unchanged
    day2 = merger.run(case)
    case["credit_mark"]["non_pcd_method"] = "gross_up"
    up = merger.run(case)
    assert up["pf_tbv"] - day2["pf_tbv"] == pytest.approx(42_000 * (1 - 0.226))  # $32.5mm
    assert up["tbv_dil_pct"] == pytest.approx(-0.0727, abs=0.001)
    assert up["earnback"] == pytest.approx(2.90, abs=0.01)
    xlsx = merger_book.build(case, tmp_path / "g.xlsx")
    wb = load_workbook(xlsx)
    ev = Evaluator(wb)
    assert all(f == 0 for f in flags(wb, ev))
    assert ev.name("PF_TBV") == pytest.approx(up["pf_tbv"])
    assert ev.name("PF_eps_1") == pytest.approx(up["years"][0]["eps"])
    assert ev.name("Earnback_Years") == pytest.approx(up["earnback"])
    pitch.build("merger", xlsx, tmp_path / "g.html")
    assert "ASU 2025-08 (purchased seasoned loans)" in (tmp_path / "g.html").read_text()
    case["credit_mark"]["non_pcd_method"] = "pcd"
    with pytest.raises(CaseError, match="non_pcd_method"):
        merger.validate(case)
