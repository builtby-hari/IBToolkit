import copy

import pytest
from openpyxl import load_workbook
from openpyxl.formula.tokenizer import Tokenizer

from ibtoolkit import debtcap, debtcap_book
from ibtoolkit.__main__ import main
from ibtoolkit.debtcap import CaseError, load_case, run, sensitivities, validate
from ibtoolkit.excel import OK_TEXT
from ibtoolkit.xl_eval import Evaluator

COLS = "BCDEFG"
NAMES = ["Max_Debt", "Binding_Name", "Proposed_Debt", "TLB_0", "Notes_0", "SL_0", "Total_Debt_0", "Blended_Rate"]


@pytest.fixture
def dc():
    return load_case("cases/debtcap_sample.toml")


@pytest.fixture
def simple(dc):
    """Hand-checkable: EBITDA 100 flat, cash flow before debt service 80, no cushion, no second lien.
    Blended rate 0.6 x 8% + 0.4 x 10% = 8.8%. Secured share 60%."""
    c = copy.deepcopy(dc)
    c["company"]["ltm_ebitda"] = 100.0
    c["projections"].update(ebitda=[100.0] * 5, capex=[10.0] * 5, cash_taxes=[10.0] * 5, nwc_increase=[0.0] * 5)
    c["limits"].update(max_total_leverage=5.0, max_senior_leverage=2.7, min_interest_coverage=2.0,
                       min_fcf_to_debt=0.05, cushion_pct=0.0)
    c["term_loan_b"].update(share=0.6, rate=0.08, amort_pct=0.01, sweep_pct=0.0)
    c["senior_notes"].update(share=0.4, rate=0.10)
    c["second_lien"] = {"share": 0.0, "rate": 0.0}
    c["covenant_ebitda"] = {k: 0.0 for k in debtcap.ADDBACKS} | {"cap_pct": 0.25}
    c["free_and_clear"] = {"amount": 0.0, "pct_ebitda": 0.0}
    return c


def build(case, outdir):
    path = debtcap_book.build(case, outdir / "t.xlsx")
    wb = load_workbook(path)
    return wb, Evaluator(wb)


def test_max_debt_hand_check(simple):
    # Total leverage 5.0 x 100 = 500. Senior: 2.7 x 100 / 0.6 = 450. Coverage: 100 / (2 x 0.088) = 568.18.
    # FCF / debt: 80 / (0.05 + 0.088) = 579.71. Senior leverage is lowest.
    s = run(simple)["sizing"]
    assert s["caps"] == pytest.approx([500, 450, 100 / 0.176, 80 / 0.138])
    assert s["max_debt"] == pytest.approx(450) and s["binding"] == "Senior Secured Leverage"
    assert s["tranches"]["term_loan_b"] == pytest.approx(270) and s["tranches"]["senior_notes"] == pytest.approx(180)


@pytest.mark.parametrize("field,value,binding,expected", [
    ("max_senior_leverage", 4.0, "Total Leverage", 500),
    ("min_interest_coverage", 3.0, "Interest Coverage", 100 / 0.264),
    ("min_fcf_to_debt", 0.20, "FCF / Debt", 80 / 0.288),
])
def test_binding_constraint_switches(simple, field, value, binding, expected):
    simple["limits"][field] = value
    s = run(simple)["sizing"]
    assert s["binding"] == binding and s["max_debt"] == pytest.approx(expected)


def test_cushion_and_tranche_split(dc):
    s = run(dc)["sizing"]
    assert s["proposed"] == pytest.approx(s["max_debt"] * 0.95)
    assert sum(s["tranches"].values()) == pytest.approx(s["proposed"])
    assert s["tranches"]["second_lien"] == pytest.approx(0.2 * s["proposed"])


def test_proposed_debt_passes_every_year(dc):
    r = run(dc)
    assert r["limit_fails"] == 0 and r["years"]["all_ok"] == [1] * 6
    y = r["years"]
    assert all(y["debt_tot"][i] <= y["debt_tot"][i - 1] + 1e-9 for i in range(1, 6))
    assert y["t_end"][1] == pytest.approx(y["t_beg"][1] - y["t_mand"][1] - y["t_sweep"][1])


def test_ebitda_collapse_fails_a_year(dc):
    dc["projections"]["ebitda"] = [53000, 30000, 30000, 30000, 30000]
    assert run(dc)["limit_fails"] > 0


def test_rating_bands(dc):
    r = run(dc)["ratings"][0]
    assert (r["lev_rating"], r["cov_rating"], r["rating"]) == ("BB-", "B", "B")
    assert debtcap.rate_grid(dc["rating_grid"], 2.0, 9.0, True)["rating"] == "BBB"
    assert debtcap.rate_grid(dc["rating_grid"], 2.0, 0.0, False)["rating"] == "BBB"  # no interest means no coverage test
    assert debtcap.rate_grid(dc["rating_grid"][:3], 9.0, 9.0, True)["rating"] == "Below BB"


def test_sensitivity_base_and_direction(dc):
    s = sensitivities(dc)
    assert s["max_debt"][0][2] == pytest.approx(run(dc)["sizing"]["max_debt"])
    assert s["binding"][0][2] == run(dc)["sizing"]["binding"]
    assert s["max_debt"][4][2] < s["max_debt"][0][2] and s["max_debt"][0][4] < s["max_debt"][0][0]


def _raw(case):
    raw = {k: dict(v) for k, v in case.items() if isinstance(v, dict) and k != "meta"}
    raw["rating_grid"] = [dict(g) for g in case["rating_grid"]]
    return raw


def test_missing_input_names_the_field(dc):
    with pytest.raises(CaseError, match="company.ltm_ebitda"):
        validate({"company": {}})
    raw = _raw(dc)
    del raw["limits"]["max_total_leverage"]
    with pytest.raises(CaseError, match="limits.max_total_leverage"):
        validate(raw)


def test_bad_values_are_rejected(dc):
    raw = _raw(dc)
    raw["senior_notes"]["share"] = 0.4  # shares now sum to 1.1
    with pytest.raises(CaseError, match="sum to 1"):
        validate(raw)
    raw = _raw(dc)
    raw["projections"]["capex"] = [1.0] * 4
    with pytest.raises(CaseError, match="projections.capex"):
        validate(raw)
    raw = _raw(dc)
    raw["rating_grid"].reverse()
    with pytest.raises(CaseError, match="rating_grid"):
        validate(raw)
    raw = _raw(dc)
    del raw["rating_grid"][0]["min_coverage"]
    with pytest.raises(CaseError, match=r"rating_grid\[0\].min_coverage"):
        validate(raw)


def test_workbook_formulas_match_python(dc, outdir):
    wb, ev = build(dc, outdir)
    res = run(dc)
    assert wb.sheetnames == ["Summary", "Inputs", "Covenant", "Capacity", "Structure", "Model", "Rating", "Sensitivity", "Checks"]
    for key in debtcap_book.MODEL_KEYS:
        for i, col in enumerate(COLS):
            py = res["years"][key][i]
            ref = f"{col}{debtcap_book.R[key]}"
            if py is None:
                assert wb["Model"][ref].value is None, (key, i)
            else:
                assert ev.cell("Model", ref) == pytest.approx(py, rel=1e-9, abs=1e-9), (key, i)
    s = res["sizing"]
    assert ev.name("Max_Debt") == pytest.approx(s["max_debt"])
    assert ev.name("Binding_Name") == s["binding"]
    assert ev.name("Proposed_Debt") == pytest.approx(s["proposed"])
    assert ev.name("TLB_0") == pytest.approx(s["tranches"]["term_loan_b"])
    assert ev.name("Rating_Close") == res["ratings"][0]["rating"]
    assert ev.name("Rating_Final") == res["ratings"][5]["rating"]
    g = sensitivities(dc)
    for i in range(5):
        for j, c in enumerate("BCDEF"):
            assert ev.cell("Sensitivity", f"{c}{6 + i}") == pytest.approx(g["max_debt"][i][j])
            assert wb["Sensitivity"][f"{c}{15 + i}"].value == g["binding"][i][j]


def test_workbook_hand_check_and_switch(simple, outdir):
    _, ev = build(simple, outdir)
    assert ev.name("Max_Debt") == pytest.approx(450) and ev.name("Binding_Name") == "Senior Secured Leverage"
    simple["limits"]["min_fcf_to_debt"] = 0.20
    _, ev = build(simple, outdir)
    assert ev.name("Binding_Name") == "FCF / Debt" and ev.name("Max_Debt") == pytest.approx(80 / 0.288)
    assert ev.name("Checks_Total") == 0


def test_checks_zero_and_broken_workbook_trips(dc, outdir):
    wb, ev = build(dc, outdir)
    assert ev.name("Checks_Total") == 0 and ev.cell("Summary", "B5") == OK_TEXT
    wb["Structure"]["B5"] = 1.0  # term loan pasted over with a hard-code
    assert Evaluator(wb).name("Checks_Total") >= 1
    wb, _ = build(dc, outdir)
    ref = wb.defined_names["Min_Coverage"].attr_text.split("!")[1].replace("$", "")
    wb["Inputs"][ref] = 9.0  # input changed after the sizing and static grid were written
    assert Evaluator(wb).name("Checks_Total") >= 1


def test_colors_and_no_numeric_constants(dc, outdir):
    wb, _ = build(dc, outdir)
    for ws in wb:
        for row in ws.iter_rows():
            for c in row:
                v = c.value
                if isinstance(v, str) and v.startswith("="):
                    assert c.font.color.rgb[-6:] in ("000000", "008000", "800080"), (ws.title, c.coordinate)
                    if ws.title != "Inputs":
                        for t in Tokenizer(v).items:
                            if t.type == "OPERAND" and t.subtype == "NUMBER":
                                assert float(t.value) in {0, 1}, (ws.title, c.coordinate, v)
                elif isinstance(v, (int, float)) and ws.title == "Inputs" and c.row >= 5 and c.column >= 2 \
                        and c.row != debtcap_book.IN_SERIES:
                    assert c.font.color.rgb.endswith("0000FF"), c.coordinate
                elif isinstance(v, (int, float)) and ws.title in ("Model", "Capacity", "Structure", "Summary", "Rating"):
                    assert c.row == 4, f"hard-coded number outside header: {ws.title}!{c.coordinate}"
    for n in NAMES:
        sheet, ref = wb.defined_names[n].attr_text.split("!")
        assert str(wb[sheet][ref.replace("$", "")].value).startswith("="), n


def test_cli_csv_and_errors(outdir, capsys):
    out = outdir / "cli.xlsx"
    assert main(["debtcap", "cases/debtcap_sample.toml", "--out", str(out), "--csv", str(outdir / "csv")]) == 0
    text = capsys.readouterr().out
    assert "Binding constraint FCF / Debt" in text and "Indicative rating" in text
    assert (outdir / "csv" / "Capacity.csv").exists()
    assert "All Checks OK" in (outdir / "csv" / "Summary.csv").read_text()
    bad = outdir / "bad.json"
    bad.write_text('{"company": {}}')
    assert main(["debtcap", str(bad), "--out", str(out)]) == 1
    assert "company.ltm_ebitda" in capsys.readouterr().err


def test_addback_cap_binds_and_capacity_change_hand_check(simple):
    # Add-backs 30 + 10 = 40 against a cap of 25% x 100 = 25, so 25 is allowed: covenant EBITDA 125, uncapped 140.
    # Leverage on 125: total 5.0 x 125 = 625, senior 2.7 x 125 / 0.6 = 562.5. Coverage (568.18) and
    # FCF / debt (579.71) stay on cash EBITDA. Senior binds at 562.5 vs 450 on reported: change 112.5.
    simple["covenant_ebitda"].update(synergies=30.0, other=10.0)
    r = run(simple)
    br = r["bridge"]
    assert (br["addbacks"], br["cap"], br["allowed"], br["excluded"], br["cap_binds"]) == (40, 25, 25, 15, 1)
    assert br["uncapped"] == 140 and br["covenant"] == 125
    assert r["sizing"]["caps"] == pytest.approx([625, 562.5, 100 / 0.176, 80 / 0.138])
    assert r["sizing"]["max_debt"] == pytest.approx(562.5) and r["reported"]["max_debt"] == pytest.approx(450)
    assert r["reported"]["change"] == pytest.approx(112.5)
    assert r["years"]["lev_cov"][0] == pytest.approx(562.5 / 125) and r["years"]["lev_tot"][0] == pytest.approx(5.625)
    simple["covenant_ebitda"]["cap_pct"] = 0.5  # cap 50 no longer binds: all 40 count
    assert run(simple)["bridge"]["covenant"] == 140


def test_cash_tests_binding_means_addbacks_add_no_debt(simple):
    simple["limits"]["min_fcf_to_debt"] = 0.20  # FCF / debt binds at 80 / 0.288
    simple["covenant_ebitda"]["synergies"] = 20.0
    r = run(simple)
    assert r["sizing"]["binding"] == "FCF / Debt" and r["reported"]["change"] == pytest.approx(0)


def test_no_addbacks_leaves_outputs_unchanged(dc):
    raw = _raw(dc)
    del raw["covenant_ebitda"], raw["free_and_clear"]
    plain = validate(raw)
    assert plain["covenant_ebitda"]["cap_pct"] == debtcap.DEFAULT_CAP
    r = run(plain)
    assert r["bridge"]["covenant"] == r["bridge"]["reported"] == 50000
    assert r["sizing"]["caps"] == debtcap.caps(plain, adjusted=False) and r["reported"]["change"] == 0
    assert r["years"]["lev_cov"] == r["years"]["lev_tot"] and r["years"]["sen_cov"] == r["years"]["lev_sen"]
    assert r["free_clear"] == {"basket": 0, "max_with_basket": r["sizing"]["max_debt"]}
    # values the model produced before the bridge existed
    assert r["sizing"]["max_debt"] == pytest.approx(37500 / 0.147) and r["sizing"]["binding"] == "FCF / Debt"
    base = run(dc)
    for k in ("max_debt", "binding", "proposed", "tranches"):
        assert base["sizing"][k] == r["sizing"][k]  # sample add-backs do not move it: a cash test binds
    assert base["ratings"] == r["ratings"] and base["years"]["lev_tot"] == r["years"]["lev_tot"]


def test_free_and_clear_greater_of(simple):
    simple["free_and_clear"].update(amount=30.0, pct_ebitda=0.5)
    assert run(simple)["free_clear"]["basket"] == pytest.approx(50)  # 0.5 x 100 beats 30
    simple["free_and_clear"]["amount"] = 80.0
    fc = run(simple)["free_clear"]
    assert fc["basket"] == 80 and fc["max_with_basket"] == pytest.approx(450 + 80)


def test_negative_addback_rejected(dc):
    raw = _raw(dc)
    raw["covenant_ebitda"]["restructuring"] = -5
    with pytest.raises(CaseError, match="covenant_ebitda.restructuring"):
        validate(raw)
    raw = _raw(dc)
    raw["covenant_ebitda"]["cap_pct"] = 1.5
    with pytest.raises(CaseError, match="covenant_ebitda.cap_pct"):
        validate(raw)


@pytest.mark.parametrize("cap", [0.25, 0.5])
def test_workbook_bridge_matches_python_and_checks_pass(simple, outdir, cap):
    simple["covenant_ebitda"].update(synergies=30.0, other=10.0, cap_pct=cap)
    simple["free_and_clear"].update(amount=30.0, pct_ebitda=0.5)
    assert run(simple)["limit_fails"] > 0  # flat projections: add-backs never realized, so year 1 breaches
    simple["projections"]["ebitda"] = [140.0] * 5  # projections realize the add-backs
    r = run(simple)
    assert r["limit_fails"] == 0
    _, ev = build(simple, outdir)
    assert ev.name("Covenant_EBITDA") == pytest.approx(r["bridge"]["covenant"])
    assert ev.name("Uncapped_EBITDA") == pytest.approx(140)
    assert ev.name("Max_Debt") == pytest.approx(r["sizing"]["max_debt"])
    assert ev.name("Max_Debt_Reported") == pytest.approx(450)
    assert ev.name("Addback_Debt_Change") == pytest.approx(r["reported"]["change"])
    assert ev.name("Free_Clear") == pytest.approx(r["free_clear"]["basket"])
    assert ev.name("Checks_Total") == 0


def test_sample_bridge_in_workbook(dc, outdir):
    r = run(dc)
    _, ev = build(dc, outdir)
    assert r["bridge"]["cap_binds"] == 1 and ev.name("Covenant_EBITDA") == pytest.approx(62500)
    assert ev.name("Max_Debt_Reported") == pytest.approx(r["reported"]["max_debt"])
    assert ev.cell("Covenant", "B13") == pytest.approx(12500)
