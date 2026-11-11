"""Model integrity layer: every Checks flag is 0 on the samples, broken workbooks trip a check,
and calculation sheets hold no stray numeric constants inside formulas."""
import pytest
from openpyxl import load_workbook
from openpyxl.formula.tokenizer import Tokenizer

from ibtoolkit import bank, bank_book, dcf, dcf_book, lbo, lbo_book, merger, merger_book
from ibtoolkit.excel import OK_TEXT
from merger_cases import sample as merger_sample
from ibtoolkit.xl_eval import Evaluator

ROOT = lbo_book.__file__.rsplit("/ibtoolkit", 1)[0]
ALLOWED = {0, 1, 12, 100, 0.5, 0.25, 0.75}  # plus half-year (mid-year) and quartile arguments
YEAR_RANGE = range(1900, 2101)


def books(outdir):
    return {
        "lbo": lbo_book.build(lbo.load_case(f"{ROOT}/cases/lbo_sample.toml"), outdir / "lbo.xlsx"),
        "merger": merger_book.build(merger_sample(), outdir / "merger.xlsx"),
        "dcf": dcf_book.build(dcf.load_case(f"{ROOT}/cases/dcf_sample.toml"), outdir / "dcf.xlsx"),
        "bank": bank_book.build(bank.load_case(f"{ROOT}/cases/bank_sample.toml"), outdir / "bank.xlsx"),
    }


def flags(wb, ev):
    ws = wb["Checks"]
    return [ev.cell("Checks", f"B{r}") for r in range(5, ws.max_row + 1)
            if ws[f"A{r}"].value and ws[f"B{r}"].value and ws[f"A{r}"].value != "Total Errors"]


@pytest.mark.parametrize("key", ["lbo", "merger", "dcf", "bank"])
def test_checks_are_zero_on_samples(key, outdir):
    wb = load_workbook(books(outdir)[key])
    ev = Evaluator(wb)
    fl = flags(wb, ev)
    assert len(fl) >= 6 and all(f == 0 for f in fl), fl
    assert ev.name("Checks_Total") == 0
    ref = next(r for r in range(1, 8) if wb["Summary"][f"A{r}"].value == "Model Checks")
    assert ev.cell("Summary", f"B{ref}") == OK_TEXT
    assert wb["Summary"].conditional_formatting


def tripped(wb):
    ev = Evaluator(wb)
    return ev.name("Checks_Total"), ev.cell("Summary", "B5")


def test_broken_lbo_trips_sources_uses(outdir):
    wb = load_workbook(books(outdir)["lbo"])
    wb["Sources_Uses"]["B16"] = 5.0  # total sources pasted over with a hard-code
    n, text = tripped(wb)
    assert n >= 1 and text == f"{n} Check Errors"


def test_broken_merger_trips_goodwill_tie(outdir):
    wb = load_workbook(books(outdir)["merger"])
    wb["Inputs"][wb.defined_names["Tax_Rate"].attr_text.split("!")[1].replace("$", "")] = 0.5
    wb["Purchase_Accounting"]["B24"] = 1.0  # net deferred tax overwritten with a hard-code
    assert tripped(wb)[0] >= 1


def test_live_dcf_grid_follows_inputs(outdir):
    wb = load_workbook(books(outdir)["dcf"])
    ref = wb.defined_names["Exit_Multiple"].attr_text.split("!")[1].replace("$", "")
    wb["Inputs"][ref] = 20.0  # input changed after the workbook was written: the grid recentres
    ev = Evaluator(wb)
    assert ev.name("Checks_Total") == 0
    assert ev.cell("Sensitivity", "D17") == pytest.approx(ev.name("Price_Exit"))


def test_bank_growth_above_cost_of_equity_trips(outdir):
    wb = load_workbook(books(outdir)["bank"])
    ref = wb.defined_names["Terminal_Growth"].attr_text.split("!")[1].replace("$", "")
    wb["Inputs"][ref] = 0.5
    assert tripped(wb)[0] >= 1


def test_no_numeric_constants_in_calculation_formulas(outdir):
    bad = []
    for key, path in books(outdir).items():
        wb = load_workbook(path)
        for ws in wb:
            if ws.title == "Inputs":
                continue
            for row in ws.iter_rows():
                for c in row:
                    if isinstance(c.value, str) and c.value.startswith("="):
                        for t in Tokenizer(c.value).items:
                            if t.type == "OPERAND" and t.subtype == "NUMBER":
                                v = float(t.value)
                                if v not in ALLOWED and not (v == int(v) and int(v) in YEAR_RANGE):
                                    bad.append((key, ws.title, c.coordinate, c.value))
    assert not bad, sorted({(b[0], b[3][:70]) for b in bad})[:15]
