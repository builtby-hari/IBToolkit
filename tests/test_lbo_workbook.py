import pytest
from openpyxl import load_workbook

from ibtoolkit import lbo, lbo_book
from ibtoolkit.__main__ import main
from ibtoolkit.xl_eval import Evaluator

NAMES = ["Purchase_Price", "Total_Uses", "Total_Sources", "Sponsor_Equity", "Exit_EV",
         "Exit_Equity", "Sponsor_MOIC", "Sponsor_IRR", "Senior_Debt_0", "Mezz_Debt_0"]
COLS = "BCDEFG"


def build(case, outdir):
    path = lbo_book.build(case, outdir / "t.xlsx")
    wb = load_workbook(path)
    return wb, Evaluator(wb)


def test_named_cells_exist_and_hold_formulas(sample, outdir):
    wb, _ = build(sample, outdir)
    for n in NAMES:
        sheet, ref = wb.defined_names[n].attr_text.split("!")
        assert str(wb[sheet][ref.replace("$", "")].value).startswith("="), n
    assert wb.sheetnames == ["Summary", "Inputs", "Sources_Uses", "Model", "Returns", "Sensitivity", "Checks"]


def test_colors_inputs_blue_formulas_black_no_hardcodes(sample, outdir):
    wb, _ = build(sample, outdir)
    for ws in wb:
        for row in ws.iter_rows():
            for c in row:
                v = c.value
                if isinstance(v, str) and v.startswith("="):
                    assert c.font.color.rgb[-6:] in ("000000", "008000", "800080"), (ws.title, c.coordinate)
                elif isinstance(v, (int, float)) and ws.title == "Inputs" and c.row >= 5 and c.column >= 2 and c.row != lbo_book.IN_SERIES:
                    assert c.font.color.rgb.endswith("0000FF"), c.coordinate
                elif isinstance(v, (int, float)) and ws.title in ("Model", "Returns", "Sources_Uses", "Summary"):
                    assert c.row == 4, f"hard-coded number outside header: {ws.title}!{c.coordinate}"


def test_frozen_headers(sample, outdir):
    wb, _ = build(sample, outdir)
    for n in ("Inputs", "Sources_Uses", "Model", "Returns"):
        assert wb[n].freeze_panes == "B5"


def test_formulas_match_python_engine(sample, outdir):
    wb, ev = build(sample, outdir)
    res = lbo.run(sample)
    for key in lbo_book.MODEL_KEYS:
        for i, col in enumerate(COLS):
            py = res["years"][key][i]
            if py is None:
                assert wb["Model"][f"{col}{lbo_book.R[key]}"].value is None
            else:
                got = ev.cell("Model", f"{col}{lbo_book.R[key]}")
                assert got == pytest.approx(py, rel=1e-9, abs=1e-9), (key, i)
    r, su = res["returns"], res["su"]
    assert ev.name("Sponsor_IRR") == pytest.approx(r["irr"])
    assert ev.name("Sponsor_MOIC") == pytest.approx(r["moic"])
    assert ev.name("Exit_Equity") == pytest.approx(r["exit_equity"])
    assert ev.name("Total_Uses") == pytest.approx(su["total_uses"])
    assert ev.name("Sponsor_Equity") == pytest.approx(su["sponsor_equity"])
    assert ev.name("Min_Cash") == pytest.approx(r["min_cash"])
    assert ev.name("SU_Check") == pytest.approx(0)


def test_no_debt_case_workbook_hand_check(no_debt, outdir):
    _, ev = build(no_debt, outdir)
    assert ev.name("Sponsor_MOIC") == pytest.approx(1.625)
    assert ev.name("Sponsor_IRR") == pytest.approx(1.625 ** 0.2 - 1)


def test_cli_writes_workbook_and_reports_missing_field(outdir, capsys):
    out = outdir / "cli.xlsx"
    assert main(["lbo", "cases/lbo_sample.toml", "--out", str(out)]) == 0
    assert out.exists() and "Sponsor IRR" in capsys.readouterr().out
    bad = outdir / "bad.json"
    bad.write_text('{"transaction": {}}')
    assert main(["lbo", str(bad), "--out", str(out)]) == 1
    assert "transaction.ltm_revenue" in capsys.readouterr().err


def test_rollover_pool_and_value_bridge(sample, outdir):
    sample["transaction"].update(mgmt_rollover_pct=0.2, option_pool_pct=0.1)
    out = lbo.run(sample)
    su, ret = out["su"], out["returns"]
    # Pro rata rollover cancels out of MOIC; the option pool cuts it by its share.
    assert ret["moic"] == pytest.approx(ret["exit_equity"] * 0.9 / su["equity"])
    assert su["sponsor_equity"] == pytest.approx(su["equity"] * 0.8)
    assert sum(ret["bridge"].values()) == pytest.approx(ret["exit_equity"] - su["equity"])
    wb, ev = build(sample, outdir)
    for name, want in [("Sponsor_Equity", su["sponsor_equity"]), ("Sponsor_Proceeds", ret["sponsor_proceeds"]),
                       ("Sponsor_MOIC", ret["moic"]), ("Sponsor_IRR", ret["irr"]),
                       ("Equity_Gain", ret["exit_equity"] - su["equity"])]:
        assert ev.name(name) == pytest.approx(want), name
    assert ev.name("Checks_Total") == 0
    # Live grid centre still equals the sponsor IRR with rollover and pool on.
    assert ev.cell("Sensitivity", "D8") == pytest.approx(ret["irr"])
