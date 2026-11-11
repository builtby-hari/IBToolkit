import copy
import io
import json
from pathlib import Path

import pytest
from openpyxl import load_workbook

from ibtoolkit import comps, dcf, dcf_book, edgar
from ibtoolkit.__main__ import main
from ibtoolkit.xl_eval import Evaluator

ROOT = Path(__file__).resolve().parent.parent
COLS = "BCDEFG"


@pytest.fixture
def case():
    return dcf.load_case(ROOT / "cases" / "dcf_sample.toml")


@pytest.fixture
def flat(case):
    """Hand-checkable: revenue 1000, EBITDA 200 every year, no D&A, capex, NWC or tax.
    WACC is 10% (5% + 1.0 x 5%, no debt), terminal growth 2%, year-end timing."""
    c = copy.deepcopy(case)
    c["target"].update(ltm_revenue=1000.0, net_debt=0.0, diluted_shares=10.0)
    c["dcf"].update(revenue_growth=[0.0] * 5, ebitda_margin=[0.2] * 5, da_pct_revenue=0.0,
                    capex_pct_revenue=0.0, nwc_pct_revenue_change=0.0, tax_rate=0.0, risk_free=0.05,
                    equity_risk_premium=0.05, beta=1.0, debt_to_capital=0.0, terminal_growth=0.02,
                    exit_multiple=10.0, mid_year=False)
    return c


def build(case, outdir):
    wb = load_workbook(dcf_book.build(case, outdir / "t.xlsx"))
    return wb, Evaluator(wb)


def test_gordon_terminal_value_hand_check(flat):
    r = dcf.run(flat)
    assert r["wacc"]["wacc"] == pytest.approx(0.10)
    assert r["val"]["gordon"]["tv"] == pytest.approx(200 * 1.02 / 0.08)  # 2,550
    annuity = (1 - 1.1 ** -5) / 0.1
    assert r["sum_pv"] == pytest.approx(200 * annuity)
    assert r["val"]["gordon"]["ev"] == pytest.approx(200 * annuity + 2550 / 1.1 ** 5)
    assert r["val"]["gordon"]["price"] == pytest.approx(r["val"]["gordon"]["ev"] / 10)


def test_mid_year_factor(flat):
    flat["dcf"]["mid_year"] = True
    y = dcf.run(flat)["years"]
    assert y["period"][1:] == [0.5, 1.5, 2.5, 3.5, 4.5]
    assert y["df"][1] == pytest.approx(1 / 1.1 ** 0.5)
    # Gordon TV is discounted at N - 0.5, exit multiple TV at N
    v = dcf.run(flat)["val"]
    assert v["gordon"]["pv_tv"] == pytest.approx(2550 / 1.1 ** 4.5)
    assert v["exit"]["pv_tv"] == pytest.approx(2000 / 1.1 ** 5)


def test_cross_checks_round_trip(case):
    """Feeding the implied multiple back in as the exit multiple recovers the Gordon price."""
    r = dcf.run(case)
    m = r["val"]["gordon"]["implied_multiple"]
    assert dcf.run(case, exit_mult=m)["val"]["exit"]["price"] == pytest.approx(r["val"]["gordon"]["price"])
    g = r["val"]["exit"]["implied_growth"]
    assert dcf.run(case, g=g)["val"]["gordon"]["price"] == pytest.approx(r["val"]["exit"]["price"])


def test_percentile_math():
    xs = [1, 2, 3, 4]
    assert comps.percentile(xs, 0.25) == pytest.approx(1.75)
    assert comps.percentile(xs, 0.75) == pytest.approx(3.25)
    assert comps.stats(xs)["median"] == 2.5
    assert comps.percentile([5], 0.25) == 5


def test_comps_implied_prices_hand_check():
    ev, eq, px = comps.implied("ev", 10.0, 100.0, 200.0, 40.0)
    assert (ev, eq, px) == (1000.0, 800.0, 20.0)
    ev, eq, px = comps.implied("pe", 15.0, 2.0, 200.0, 40.0)
    assert (px, eq, ev) == (30.0, 1200.0, 1400.0)


def test_workbook_matches_python(case, outdir):
    wb, ev = build(case, outdir)
    res, cr = dcf.run(case), comps.run(case)
    for key in dcf_book.MODEL_KEYS:
        for i, col in enumerate(COLS):
            py = res["years"].get(key, [None] * 6)[i]
            if py is not None:
                assert ev.cell("DCF", f"{col}{dcf_book.R[key]}") == pytest.approx(py, rel=1e-9), (key, i)
    v = res["val"]
    for name, py in [("WACC", res["wacc"]["wacc"]), ("Cost_of_Equity", res["wacc"]["ke"]),
                     ("After_Tax_Kd", res["wacc"]["kd_at"]), ("Sum_PV_UFCF", res["sum_pv"]),
                     ("TV_Gordon", v["gordon"]["tv"]), ("TV_Exit", v["exit"]["tv"]),
                     ("EV_Gordon", v["gordon"]["ev"]), ("EV_Exit", v["exit"]["ev"]),
                     ("Equity_Gordon", v["gordon"]["equity"]), ("Price_Gordon", v["gordon"]["price"]),
                     ("Price_Exit", v["exit"]["price"]), ("TV_Pct_EV_Gordon", v["gordon"]["tv_pct_ev"]),
                     ("Implied_Exit_Multiple", v["gordon"]["implied_multiple"]),
                     ("Implied_Growth", v["exit"]["implied_growth"])]:
        assert ev.name(name) == pytest.approx(py, rel=1e-9), name
    rows = dcf_book.comps_rows(len(case["peers"]))
    for i, p in enumerate(cr["peers"]):
        r = rows["first"] + i
        assert ev.cell("Comps", f"D{r}") == pytest.approx(p["mcap"])
        assert ev.cell("Comps", f"F{r}") == pytest.approx(p["ev"])
        for key, *_ in comps.METRICS:
            assert ev.cell("Comps", f"{dcf_book.MCOL[key]}{r}") == pytest.approx(p[key])
    for key, *_ in comps.METRICS:
        st = cr["metrics"][key]["stats"]
        for stat, r in rows["stat"].items():
            assert ev.cell("Comps", f"{dcf_book.MCOL[key]}{r}") == pytest.approx(st[stat]), (key, stat)
        ir = rows["imp"][key]
        for q, cols in zip(("p25", "median", "p75"), ("FIL", "GJM", "HKN")):
            got = [ev.cell("Comps", f"{c}{ir}") for c in cols]
            assert got == pytest.approx(list(cr["metrics"][key]["implied"][q]))


def test_football_field_matches_python(case, outdir):
    _, ev = build(case, outdir)
    s = dcf.sensitivities(case)
    flat_g = [x for row in s["price_wacc_g"] for x in row]
    assert ev.cell("Football_Field", "B11") == pytest.approx(min(flat_g))
    assert ev.cell("Football_Field", "D11") == pytest.approx(max(flat_g))
    assert ev.cell("Football_Field", "C11") == pytest.approx(dcf.run(case)["val"]["gordon"]["price"])
    p = comps.run(case)["metrics"]["pe_ntm"]["implied"]
    assert ev.cell("Football_Field", "B10") == pytest.approx(p["p25"][2])
    assert ev.cell("Football_Field", "D10") == pytest.approx(p["p75"][2])


def test_sensitivity_center_is_base_case(case):
    s, r = dcf.sensitivities(case), dcf.run(case)
    assert s["price_wacc_g"][2][2] == pytest.approx(r["val"]["gordon"]["price"])
    assert s["price_wacc_mult"][2][2] == pytest.approx(r["val"]["exit"]["price"])


def test_colors_and_no_hardcodes(case, outdir):
    wb, _ = build(case, outdir)
    assert wb.sheetnames == ["Summary", "Inputs", "Comps", "DCF", "Sensitivity", "Football_Field", "Checks"]
    for ws in wb:
        for row in ws.iter_rows():
            for c in row:
                v = c.value
                if isinstance(v, str) and v.startswith("="):
                    assert c.font.color.rgb[-6:] in ("000000", "008000", "800080"), (ws.title, c.coordinate)
                elif isinstance(v, (int, float)) and ws.title == "Inputs" and c.row >= 5 and c.row != dcf_book.IN_SERIES:
                    assert c.font.color.rgb.endswith("0000FF"), c.coordinate
                elif isinstance(v, (int, float)) and ws.title == "Sensitivity" and c.row >= 5:
                    assert c.font.color.rgb.endswith("595959"), c.coordinate
                elif isinstance(v, (int, float)):
                    assert c.row in (4, dcf_book.IN_SERIES) or ws.title == "Sensitivity", f"hard-coded: {ws.title}!{c.coordinate}"
    for n in ("WACC", "Price_Gordon", "Price_Exit"):
        sheet, ref = wb.defined_names[n].attr_text.split("!")
        assert str(wb[sheet][ref.replace("$", "")].value).startswith("="), n


def test_mid_year_flag_flows_through_workbook(case, outdir):
    case["dcf"]["mid_year"] = False
    _, ev = build(case, outdir)
    assert ev.name("Price_Gordon") == pytest.approx(dcf.run(case)["val"]["gordon"]["price"])
    assert ev.cell("DCF", f"C{dcf_book.R['period']}") == 1


def test_missing_and_invalid_fields_error_clearly(case):
    def raw(mut):
        r = {"meta": {}, "target": dict(case["target"]), "dcf": dict(case["dcf"]),
             "peers": [dict(p) for p in case["peers"]]}
        mut(r)
        return r
    cases = [
        (lambda r: r["peers"][1].pop("price"), "peers[1].price"),
        (lambda r: r["dcf"].pop("beta"), "dcf.beta"),
        (lambda r: r["target"].pop("diluted_shares"), "target.diluted_shares"),
        (lambda r: r.__setitem__("peers", r["peers"][:2]), "peers"),
        (lambda r: r["peers"][0].__setitem__("eps_ltm", 0), "peers[0].eps_ltm"),
        (lambda r: r["dcf"].__setitem__("mid_year", "yes"), "dcf.mid_year"),
    ]
    for mut, field in cases:
        with pytest.raises(dcf.CaseError, match=field.replace("[", r"\[").replace("]", r"\]")):
            dcf.validate(raw(mut))


def test_wacc_must_exceed_growth(case):
    case["dcf"]["terminal_growth"] = 0.2
    with pytest.raises(dcf.CaseError, match="WACC"):
        dcf.run(case)


def test_cli(outdir, capsys):
    out = outdir / "cli.xlsx"
    assert main(["dcf", "cases/dcf_sample.toml", "--out", str(out)]) == 0
    assert out.exists() and "DCF share price" in capsys.readouterr().out
    bad = outdir / "bad.json"
    bad.write_text('{"target": {}}')
    assert main(["dcf", str(bad), "--out", str(out)]) == 1
    assert "target.net_debt" in capsys.readouterr().err


# EDGAR fetcher, offline

class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_edgar_requires_user_agent(monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    with pytest.raises(edgar.EdgarError, match="SEC_USER_AGENT"):
        edgar.fetch_companyfacts("320193", opener=lambda req: pytest.fail("must not be called"))


def test_edgar_fetch_and_summarize_offline(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "Test Agent test-contact")
    body = (ROOT / "tests" / "fixtures" / "companyfacts_sample.json").read_bytes()
    seen = {}

    def opener(req):
        seen["url"], seen["ua"] = req.full_url, req.get_header("User-agent")
        return _Resp(body)

    facts = edgar.fetch_companyfacts("320193", opener=opener)
    assert seen["url"] == "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"
    assert seen["ua"] == "Test Agent test-contact"
    s = edgar.summarize(facts)
    assert s["revenue"]["value"] == 1_000_000_000 and s["revenue"]["end"] == "2023-12-31"  # latest 10-K, not the 10-Q
    assert s["diluted_eps"]["value"] == 2.5
    assert s["cash"] is None
    with pytest.raises(edgar.EdgarError, match="CIK"):
        edgar.fetch_companyfacts("abc", opener=opener)
