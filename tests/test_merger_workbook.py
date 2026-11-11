import pytest
from openpyxl import load_workbook

from ibtoolkit import merger, merger_book
from ibtoolkit.__main__ import main
from merger_cases import all_stock, sample
from ibtoolkit.xl_eval import Evaluator

NAMES = ["Deal_Price", "Goodwill", "CDI", "Net_Marks", "New_Shares", "PF_TBV", "PF_TCE",
         "PF_eps_1", "PF_eps_2", "PF_acc_pct_1", "PF_acc_pct_2", "TBV_Dil_Pct", "Earnback_Years",
         "Own_Acq", "Own_Tgt", "Price_TBV", "Price_PE"]


def build(case, outdir):
    wb = load_workbook(merger_book.build(case, outdir / "m.xlsx"))
    return wb, Evaluator(wb)


def test_named_cells_exist_and_hold_formulas(outdir):
    wb, _ = build(sample(), outdir)
    for n in NAMES:
        sheet, ref = wb.defined_names[n].attr_text.split("!")
        assert str(wb[sheet][ref.replace("$", "")].value).startswith("="), n
    assert wb.sheetnames == ["Summary", "Inputs", "Purchase_Accounting", "Pro_Forma", "Earnback", "Sensitivity", "Contribution", "Breakeven", "Checks"]


def test_colors_inputs_blue_formulas_black_no_hardcodes(outdir):
    wb, _ = build(sample(), outdir)
    for ws in wb:
        for row in ws.iter_rows():
            for c in row:
                v = c.value
                if isinstance(v, str) and v.startswith("="):
                    assert c.font.color.rgb[-6:] in ("000000", "008000", "800080"), (ws.title, c.coordinate)
                elif isinstance(v, (int, float)) and ws.title == "Inputs" and c.row >= 5 and c.column >= 2:
                    assert c.font.color.rgb.endswith("0000FF"), c.coordinate
                elif isinstance(v, (int, float)) and ws.title in ("Purchase_Accounting", "Pro_Forma", "Earnback", "Summary", "Contribution", "Breakeven"):
                    assert c.row == 4, f"hard-coded number outside header: {ws.title}!{c.coordinate}"


@pytest.mark.parametrize("make", [sample, all_stock])
def test_formulas_match_python_engine(make, outdir):
    case = make()
    _, ev = build(case, outdir)
    r = merger.run(case)
    for name, key in [("Deal_Price", "price"), ("Goodwill", "goodwill"), ("CDI", "cdi"),
                      ("Net_Marks", "net_marks"), ("New_Shares", "new_shares"), ("PF_TBV", "pf_tbv"),
                      ("PF_TCE", "pf_tce"), ("TBV_Dil_Pct", "tbv_dil_pct"), ("Earnback_Years", "earnback"),
                      ("Own_Acq", "own_acq"), ("Own_Tgt", "own_tgt"), ("Price_TBV", "p_tbv"),
                      ("Price_PE", "p_e"), ("PF_TBVPS", "pf_tbvps"), ("Offer_PPS", "offer_pps")]:
        assert ev.name(name) == pytest.approx(r[key], rel=1e-9, abs=1e-9), name
    for y in (1, 2):
        assert ev.name(f"PF_eps_{y}") == pytest.approx(r["years"][y - 1]["eps"])
        assert ev.name(f"PF_acc_pct_{y}") == pytest.approx(r["years"][y - 1]["acc_pct"])


def test_price_per_share_input_variant(outdir):
    case = sample()
    case["deal"].pop("p_tbv")
    case["deal"]["price_per_share"] = 37.5
    wb, ev = build(case, outdir)
    assert ev.name("Offer_PPS") == pytest.approx(37.5)
    assert ev.name("Deal_Price") == pytest.approx(merger.run(case)["price"])


def test_all_stock_hand_check_workbook(outdir):
    _, ev = build(all_stock(), outdir)
    assert ev.name("PF_acc_pct_1") == pytest.approx(112 / 110 - 1)
    assert ev.name("Earnback_Years") == pytest.approx(5.0)


def test_cli_writes_workbook_and_reports_missing_field(outdir, capsys):
    out = outdir / "cli.xlsx"
    assert main(["merger", "cases/merger_sample.toml", "--out", str(out)]) == 0
    assert out.exists() and "EPS accretion" in capsys.readouterr().out
    bad = outdir / "bad.json"
    bad.write_text('{"acquirer": {}}')
    assert main(["merger", str(bad), "--out", str(out)]) == 1
    assert "acquirer.net_income" in capsys.readouterr().err
