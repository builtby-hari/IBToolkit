"""Contribution analysis and breakeven cost saves: workbook formulas match the Python engine,
the breakeven is hand checked, and both real and sample cases pass Checks."""
import copy

import pytest
from openpyxl import load_workbook

from ibtoolkit import merger, merger_book
from ibtoolkit.xl_eval import Evaluator
from merger_cases import ROOT, all_stock, sample
from test_integrity import flags

REAL = ROOT / "cases" / "merger_real_eastern_harborone.toml"


def real():
    return merger.load_case(REAL)


@pytest.mark.parametrize("make", [sample, real, all_stock])
def test_workbook_matches_engine_and_checks_pass(make, outdir):
    case = make()
    wb = load_workbook(merger_book.build(case, outdir / "c.xlsx"))
    ev = Evaluator(wb)
    assert all(f == 0 for f in flags(wb, ev))
    ct, be, grid = merger.contribution(case), merger.breakeven(case), merger.accretion_grid(case)
    ws = wb["Contribution"]
    for r in range(merger_book.CT_TOP, merger_book.CT_TOP + len(merger.CONTRIB)):
        key = next(k for k, label, _ in merger.CONTRIB if label == ws[f"A{r}"].value)
        if key in ct["rows"]:
            row = ct["rows"][key]
            for col, k in zip("EFG", ("acq_pct", "tgt_pct", "ratio")):
                assert ev.cell("Contribution", f"{col}{r}") == pytest.approx(row[k]), (key, k)
            assert row["acq_pct"] + row["tgt_pct"] == pytest.approx(1)
        else:
            assert ev.cell("Contribution", f"G{r}") == ""
    for name, k in [("Contrib_Ratio_Min", "ratio_lo"), ("Contrib_Ratio_Max", "ratio_hi"),
                    ("Contrib_Ratio_Pos", "ratio_pos"), ("Contrib_Tgt_Min", "tgt_lo"),
                    ("Contrib_Tgt_Max", "tgt_hi"), ("Contrib_Own_Pos", "own_pos")]:
        assert ev.name(name) == pytest.approx(ct[k]), name
    assert ev.name("BE_Saves") == pytest.approx(be["be_saves"])
    assert ev.name("BE_Saves_Pct") == pytest.approx(be["be_pct"])
    assert ev.name("BE_Acc_Check") == pytest.approx(0, abs=1e-9)
    t = merger_book.BE_GRID
    for i, p in enumerate(grid["price_axis"]):
        assert ev.cell("Breakeven", f"A{t + 2 + i}") == pytest.approx(p)
        for j, c in enumerate("BCDE"):
            assert ev.cell("Breakeven", f"{c}{t + 2 + i}") == pytest.approx(grid["acc_y1"][i][j]), (i, j)


def test_breakeven_hand_check():
    # all_stock with target earnings cut to 5: pro forma EPS 105 / 110 vs 1.00 standalone, so Year 1
    # needs 5 of after-tax income, or 5 / 0.75 = 6.667 pre-tax saves.
    c = all_stock()
    c["target"]["net_income"] = [5.0, 5.0]
    c["deal"]["phase_in"] = [0.5, 1.0]
    be = merger.breakeven(c)
    assert be["be_saves"] == pytest.approx(20 / 3)
    assert be["be_pct"] == pytest.approx(20 / 3 / 50)
    assert be["be_run_rate"] == pytest.approx(20 / 3 / 50 / 0.5)
    c2 = copy.deepcopy(c)
    c2["deal"]["cost_saves_pct"] = be["be_run_rate"]  # run the full engine at breakeven saves
    assert merger.run(c2)["years"][0]["acc_pct"] == pytest.approx(0, abs=1e-12)


@pytest.mark.parametrize("make", [sample, real])
def test_breakeven_gives_zero_accretion_on_cases(make):
    c = make()
    be = merger.breakeven(c)
    ph = c["deal"]["phase_in"][0]
    c["deal"]["cost_saves_pct"] = be["be_saves"] / (c["target"]["noninterest_expense"] * ph)
    assert merger.run(c)["years"][0]["acc_pct"] == pytest.approx(0, abs=1e-12)


def test_contribution_hand_check_and_missing_metric():
    c = all_stock()  # acquirer 100 shares at $10, target 20 shares at $4
    for side in ("acquirer", "target"):
        c[side].update(ltm_net_income=0.0, total_assets=0.0, deposits=0.0)  # 0 = not entered
    ct = merger.contribution(c)
    assert set(ct["rows"]) == {"ni_y1", "tce", "mcap"}  # 0 inputs are left out
    assert ct["rows"]["ni_y1"]["tgt_pct"] == pytest.approx(12 / 112)
    assert ct["rows"]["ni_y1"]["ratio"] == pytest.approx(12 / 100 * 100 / 20)  # 0.6x gives 12 / 112 ownership
    assert ct["rows"]["mcap"]["ratio"] == pytest.approx(4 / 10)  # unaffected price ratio
    assert ct["ratio_lo"] == pytest.approx(0.4) and ct["ratio_hi"] == pytest.approx(0.6)
    assert ct["exch_ratio"] == pytest.approx(0.5)  # $5 offer / $10
    assert ct["ratio_pos"] == pytest.approx(0.5)


def test_real_case_documented_values():
    ct, be = merger.contribution(real()), merger.breakeven(real())
    assert ct["ratio_lo"] == pytest.approx(0.554, abs=0.001)   # Year 1 net income
    assert ct["ratio_hi"] == pytest.approx(1.374, abs=0.001)   # loans
    assert ct["ratio_pos"] == pytest.approx(0.258, abs=0.001)  # 0.765 sits in the lower part of the range
    assert ct["own_tgt"] == pytest.approx(0.107, abs=0.001)
    assert be["be_saves"] == pytest.approx(-26_254, abs=1)     # accretive with no cost saves


def test_cli_breakeven_label(tmp_path, capsys, monkeypatch):
    from ibtoolkit.__main__ import main
    assert main(["merger", str(REAL), "--out", str(tmp_path / "m.xlsx")]) == 0
    assert ("Breakeven Year 1 cost saves none needed, accretive without synergies (breakeven -$26,254K pre-tax)"
            in capsys.readouterr().out)
    monkeypatch.setattr(merger, "breakeven", lambda c: {"be_saves": 1234.0})  # a deal that needs saves
    assert main(["merger", str(REAL), "--out", str(tmp_path / "m.xlsx")]) == 0
    assert "Breakeven Year 1 cost saves $1,234K pre-tax" in capsys.readouterr().out
