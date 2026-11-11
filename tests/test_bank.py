import io
import json
from pathlib import Path

import pytest
from openpyxl import load_workbook

from ibtoolkit import bank, bank_book, fdic, pitch
from ibtoolkit.__main__ import main
from ibtoolkit.lbo import CaseError
from ibtoolkit.xl_eval import Evaluator

ROOT = Path(__file__).resolve().parent.parent
COLS = "BCDEFG"


@pytest.fixture
def sample():
    return bank.load_case(ROOT / "cases" / "bank_sample.toml")


def raw_simple():
    """Hand-checkable: flat earnings, all paid out, 10% cost of equity, zero terminal growth."""
    return {
        "target": dict(net_income=100, tce=80, total_assets=1000, shares=10, dividends=100, share_price=90),
        "forecast": dict(net_income_growth=[0] * 5, asset_growth=[0] * 5),
        "capital": dict(target_tce_ratio=0.08),
        "cost_of_equity": dict(risk_free=0.05, beta=1.0, erp=0.05),
        "terminal": dict(growth=0.0, ptbv=12.5),
        "valuation": dict(range_pct=0.1),
        "peers": [dict(name=n, ptbv=p, pe=10 + i, rote=r)
                  for i, (n, p, r) in enumerate([("A", 1.0, 0.10), ("B", 1.2, 0.12), ("C", 1.4, 0.14)])],
    }


def build(case, outdir):
    wb = load_workbook(bank_book.build(case, outdir / "t.xlsx"))
    return wb, Evaluator(wb)


def test_regression_hand_checked():
    slope, icpt, rsq = bank.ols([0.10, 0.12, 0.14], [1.0, 1.2, 1.4])
    assert (slope, icpt, rsq) == pytest.approx((10.0, 0.0, 1.0))
    res = bank.run(bank.validate(raw_simple()))
    assert res["regression"]["implied_ptbv"] == pytest.approx(10.0 * 1.25)  # target ROTE is 100 / 80 = 125%
    assert res["pe"]["median_pe"] == 11


def test_ddm_simple_case_hand_checked(outdir):
    case = bank.validate(raw_simple())
    res = bank.run(case)
    assert res["years"]["div"][1:] == pytest.approx([100.0] * 5)
    # 100 a year for 5 years at 10% is 379.0787; Gordon TV 100 / 10% = 1,000 discounted 5 years is 620.9213
    assert res["ddm"]["price_gordon"] == pytest.approx(100.0)
    assert res["ddm"]["price_ptbv"] == pytest.approx(100.0)
    _, ev = build(case, outdir)
    assert ev.name("DDM_Price_Gordon") == pytest.approx(100.0)
    assert ev.name("DDM_Price_PTBV") == pytest.approx(100.0)


def test_excess_capital_only_and_shortfall_retains():
    raw = raw_simple()
    raw["capital"]["target_tce_ratio"] = 0.10  # needs 100 of TCE against 80 held
    y = bank.run(bank.validate(raw))["years"]
    assert y["div"][1] == pytest.approx(80.0)
    assert y["tce"][1] == pytest.approx(100.0)  # 80 + 100 NI - 80 distribution
    assert all(r >= 0.1 - 1e-12 for r in y["ratio"][1:])


def test_workbook_formulas_match_python_engine(sample, outdir):
    wb, ev = build(sample, outdir)
    res = bank.run(sample)
    for key in bank_book.MODEL_KEYS:
        for i, col in enumerate(COLS):
            py = res["years"][key][i]
            if py is None:
                assert wb["DDM"][f"{col}{bank_book.R[key]}"].value is None
            else:
                assert ev.cell("DDM", f"{col}{bank_book.R[key]}") == pytest.approx(py, rel=1e-9), (key, i)
    reg, pe, d = res["regression"], res["pe"], res["ddm"]
    for name, want in [("Reg_Slope", reg["slope"]), ("Reg_Intercept", reg["intercept"]), ("Reg_RSQ", reg["rsq"]),
                       ("Implied_PTBV", reg["implied_ptbv"]), ("Price_PTBV", reg["price"]),
                       ("LTM_EPS", pe["ltm_eps"]), ("Price_PE", pe["price"]), ("Market_PE", res["market"]["pe"]),
                       ("Reg_PTBV_Y5", d["reg_ptbv_y5"]), ("Gordon_PTBV", d["gordon_ptbv"]),
                       ("Cost_Of_Equity", res["ke"]), ("DDM_Price_PTBV", d["price_ptbv"]),
                       ("DDM_Price_Gordon", d["price_gordon"]), ("DDM_Price_Mid", d["price_mid"]),
                       ("Market_PTBV", res["market"]["ptbv"])]:
        assert ev.name(name) == pytest.approx(want, rel=1e-9), name
    ff = wb["Football_Field"]
    for i, (_, lo, hi) in enumerate(res["football"]):
        assert ev.cell("Football_Field", f"B{5 + i}") == pytest.approx(lo)
        assert ev.cell("Football_Field", f"C{5 + i}") == pytest.approx(hi)
    assert ff["B9"].value == "=Share_Price"


def test_sheets_colors_and_no_hardcodes(sample, outdir):
    wb, _ = build(sample, outdir)
    assert wb.sheetnames == ["Summary", "Inputs", "Comps", "DDM", "Sensitivity", "Football_Field", "Checks"]
    for ws in wb:
        for row in ws.iter_rows():
            for c in row:
                v = c.value
                if isinstance(v, str) and v.startswith("="):
                    assert c.font.color.rgb[-6:] in ("000000", "008000", "800080"), (ws.title, c.coordinate)
                elif isinstance(v, (int, float)) and ws.title == "Inputs" and c.row >= 5 and c.column >= 2 and c.row != bank_book.IN_SERIES and c.row != bank_book.IN_PEERS:
                    assert c.font.color.rgb.endswith("0000FF"), c.coordinate
                elif isinstance(v, (int, float)) and ws.title == "Sensitivity":
                    assert c.font.color.rgb.endswith("595959"), c.coordinate  # static gray italic
                elif isinstance(v, (int, float)) and ws.title != "Inputs":
                    assert c.row == 4, f"hard-coded number outside header: {ws.title}!{c.coordinate}"
    for n in ("Reg_Slope", "Price_PTBV", "DDM_Price_Mid"):
        sheet, ref = wb.defined_names[n].attr_text.split("!")
        assert str(wb[sheet][ref.replace("$", "")].value).startswith("="), n
    assert any("SLOPE(" in str(c.value) for r in wb["Comps"].iter_rows() for c in r)


@pytest.mark.parametrize("sec,field", [("target", "net_income"), ("cost_of_equity", "beta"), ("terminal", "ptbv")])
def test_missing_field_errors_clearly(sec, field):
    raw = raw_simple()
    del raw[sec][field]
    with pytest.raises(CaseError, match=f"Missing required input: {sec}.{field}"):
        bank.validate(raw)


def test_bad_inputs_error():
    raw = raw_simple()
    raw["peers"] = raw["peers"][:2]
    with pytest.raises(CaseError, match="peers"):
        bank.validate(raw)
    raw = raw_simple()
    raw["terminal"]["growth"] = 0.2
    with pytest.raises(CaseError, match="terminal.growth"):
        bank.validate(raw)
    raw = raw_simple()
    del raw["peers"][1]["pe"]
    with pytest.raises(CaseError, match=r"peers\[1\].pe"):
        bank.validate(raw)


def test_fdic_fetch_offline_fixture():
    data = (ROOT / "tests" / "fixtures" / "fdic_financials_3511_20241231.json").read_bytes()
    seen = []

    def opener(url):
        seen.append(url)
        return io.BytesIO(data)

    t = fdic.fetch_target(3511, "20241231", opener=opener)
    assert "CERT%3A3511" in seen[0] and "REPDTE%3A20241231" in seen[0]
    assert t == pytest.approx({"net_income": 22633.0, "tce": 136077.0, "total_assets": 1705538.0,
                               "dividends": 18600.0})
    empty = lambda url: io.BytesIO(json.dumps({"data": []}).encode())  # noqa: E731
    with pytest.raises(CaseError, match="no data"):
        fdic.fetch_target(1, "20241231", opener=empty)


def test_cli_writes_workbook_and_reports_missing_field(outdir, capsys):
    out = outdir / "bank.xlsx"
    assert main(["bank", "cases/bank_sample.toml", "--out", str(out)]) == 0
    assert out.exists() and "Dividend Discount Model" in capsys.readouterr().out
    bad = outdir / "bad.json"
    bad.write_text('{"target": {}}')
    assert main(["bank", str(bad), "--out", str(out)]) == 1
    assert "target.net_income" in capsys.readouterr().err


def test_cli_reports_malformed_case_and_unwritable_output(outdir, capsys):
    bad = outdir / "bad.toml"
    bad.write_text("x = \n")
    assert main(["bank", str(bad), "--out", str(outdir / "b.xlsx")]) == 1
    assert capsys.readouterr().err.startswith("Error:")
    blocker = outdir / "file"
    blocker.write_text("")
    assert main(["bank", "cases/bank_sample.toml", "--out", str(blocker / "b.xlsx")]) == 1
    assert capsys.readouterr().err.startswith("Error:")
    assert main(["bank", "cases/bank_sample.toml", "--out", str(outdir / "b.xlsx"),
                 "--pitch", str(blocker / "p.html")]) == 1
    assert capsys.readouterr().err.startswith("Error:")


def test_sensitivity_grids_centre_and_monotone(sample, outdir):
    wb, ev = build(sample, outdir)
    s = bank.sensitivities(sample)
    res = bank.run(sample)["ddm"]
    assert s["price_ke_ptbv"][2][2] == pytest.approx(res["price_ptbv"])
    assert s["price_ke_g"][2][2] == pytest.approx(res["price_gordon"])
    assert ev.cell("Sensitivity", "D8") == pytest.approx(ev.name("DDM_Price_PTBV"))
    assert ev.cell("Sensitivity", "D17") == pytest.approx(ev.name("DDM_Price_Gordon"))
    for grid in (s["price_ke_ptbv"], s["price_ke_g"]):
        assert all(grid[i][j] > grid[i + 1][j] for i in range(4) for j in range(5))  # higher cost of equity, lower value
        assert all(grid[i][j] < grid[i][j + 1] for i in range(5) for j in range(4))  # higher terminal, higher value
    assert ev.name("Checks_Total") == 0


def test_stale_grid_trips_check(sample, outdir):
    path = bank_book.build(sample, outdir / "stale.xlsx")
    wb = load_workbook(path)
    wb["Sensitivity"]["D8"] = 1.0
    wb.save(path)
    assert Evaluator(load_workbook(path)).name("Checks_Total") == 1


def test_real_case_loads_and_all_checks_pass(outdir):
    case = bank.load_case(ROOT / "cases" / "bank_real_hwc.toml")  # file read only, no network
    assert not case["meta"].get("illustrative") and len(case["peers"]) >= 6
    assert case["target"]["share_price"] == 74.13
    wb, ev = build(case, outdir)
    assert ev.name("Checks_Total") == 0
    assert "ILLUSTRATIVE" not in str(wb["Summary"]["A4"].value or "").upper()
    assert 0.9 < ev.name("DDM_Price_Mid") / case["target"]["share_price"] < 1.4


def test_core_earnings_drive_regression_rote_and_pe():
    raw = raw_simple()
    res = bank.run(bank.validate(raw))
    assert res["regression"]["target_rote"] == pytest.approx(100 / 80)  # core defaults to GAAP net income
    raw["target"]["core_net_income"] = 120
    res = bank.run(bank.validate(raw))
    assert res["regression"]["target_rote"] == pytest.approx(120 / 80)
    assert res["pe"]["ltm_eps"] == pytest.approx(12.0)  # core LTM / shares, not year 1 forecast
    assert res["pe"]["price"] == pytest.approx(12.0 * 11)
    assert res["years"]["ni"][1] == pytest.approx(100)  # the DDM still projects from GAAP LTM


def test_max_payout_caps_distributions_and_retains_excess(outdir):
    raw = raw_simple()
    raw["target"]["tce"] = 130  # 50 of excess over the 80 required
    y = bank.run(bank.validate(raw))["years"]
    assert y["div"][1] == pytest.approx(100)  # default cap of 100% of net income holds the excess back
    assert y["excess"][1] == pytest.approx(50)
    assert y["payout"][0] == pytest.approx(1.0)  # LTM dividends / LTM net income
    raw["capital"]["max_payout"] = 1.2
    case = bank.validate(raw)
    y = bank.run(case)["years"]
    assert y["div"][1:3] == pytest.approx([120, 120])  # 20 a year of excess released
    assert y["div"][3] == pytest.approx(110) and y["excess"][3] == pytest.approx(0)
    _, ev = build(case, outdir)
    assert ev.cell("DDM", f"D{bank_book.R['div']}") == pytest.approx(120)
    assert ev.name("Checks_Total") == 0


def test_real_case_basis_exit_and_payout(outdir):
    case = bank.load_case(ROOT / "cases" / "bank_real_hwc.toml")
    res = bank.run(case)
    t = case["target"]
    assert res["regression"]["target_rote"] == pytest.approx(t["core_net_income"] / t["tce"])
    assert 0.14 < res["regression"]["target_rote"] < 0.15  # core ROTE, not the 12.4% GAAP figure
    assert res["pe"]["price"] == pytest.approx(t["core_net_income"] / t["shares"] * res["pe"]["median_pe"])
    assert abs(case["terminal"]["ptbv"] - res["ddm"]["reg_ptbv_y5"]) < 0.05  # exit agrees with year 5 ROTE
    assert max(res["years"]["payout"][1:]) <= case["capital"]["max_payout"] + 1e-12
    assert res["years"]["div"][1] < 485.9  # below LTM dividends plus buybacks (case file comment)
    xlsx = bank_book.build(case, outdir / "hwc.xlsx")
    wb = load_workbook(xlsx)
    html = Path(pitch.build("bank", xlsx, outdir / "hwc.html")).read_text()
    for text in [html] + [str(c.value) for ws in wb for r in ws.iter_rows() for c in r]:
        assert "Forward" not in text
    assert "P/E (LTM, normalized)" in html
