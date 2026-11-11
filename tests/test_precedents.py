import copy
import datetime as dt
import tomllib
from pathlib import Path

import pytest
from openpyxl import load_workbook
from openpyxl.formula.tokenizer import Tokenizer

from ibtoolkit import bank, bank_book, dcf, dcf_book, precedents
from ibtoolkit.__main__ import main
from ibtoolkit.lbo import CaseError
from ibtoolkit.xl_eval import Evaluator
from test_integrity import ALLOWED, YEAR_RANGE, flags
from test_pitch import TAG, parse

ROOT = Path(__file__).resolve().parent.parent
BANK = ROOT / "cases" / "bank_precedents_real.toml"
CORP = ROOT / "cases" / "dcf_precedents_sample.toml"


def deals(rows):
    return [dict(date=dt.date(2025, 1, 1 + i), acquirer=f"A{i}", target=f"T{i}", deal_value=100.0, **r)
            for i, r in enumerate(rows)]


def raw(kind, rows, **kw):
    return dict(as_of=dt.date(2026, 1, 1), deals=deals(rows), **kw)


def test_percentile_and_stats_hand_checked():
    p = precedents.validate(raw("corporate", [dict(ev_rev_ltm=x, ev_ebitda_ltm=x * 5) for x in (1, 2, 3, 4)]),
                            "corporate")
    t = dict(ltm_revenue=100.0, ltm_ebitda=20.0, net_debt=50.0, diluted_shares=10.0)
    r = precedents.run(p, "corporate", t)["ev_rev_ltm"]
    assert r["stats"] == pytest.approx(dict(mean=2.5, median=2.5, p25=1.75, p75=3.25, high=4, low=1))
    # median 2.5x revenue of 100 is EV 250, less net debt 50 is equity 200, over 10 shares is $20
    assert r["implied"]["median"] == pytest.approx((250.0, 200.0, 20.0))


def test_bank_implied_hand_checked():
    rows = [dict(ptbv=1.0 + i / 10, pe_ltm=10 + i, cdp=0.02 * (i + 1)) for i in range(3)]
    p = precedents.validate(raw("bank", rows, target_core_deposits=1000.0), "bank")
    t = dict(net_income=50.0, tce=400.0, shares=20.0)
    r = precedents.run(p, "bank", t)
    assert r["ptbv"]["implied"]["median"][-1] == pytest.approx(1.1 * 400 / 20)  # median 1.1x TBV of $20
    assert r["pe_ltm"]["implied"]["median"][-1] == pytest.approx(11 * 50 / 20)  # median 11x EPS of $2.50
    assert r["cdp"]["implied"]["median"][-1] == pytest.approx((400 + 0.04 * 1000) / 20)


def test_recency_filter_and_edate():
    assert precedents.edate(dt.date(2024, 2, 29), -12) == dt.date(2023, 2, 28)
    assert precedents.edate(dt.date(2026, 10, 21), -24) == dt.date(2024, 10, 21)
    rows = [dict(ev_rev_ltm=1.0 + i, ev_ebitda_ltm=5.0 + i) for i in range(6)]
    d = raw("corporate", rows, max_age_years=0.5)
    for x in d["deals"][1:]:
        x["date"] = dt.date(2025, 11, 1)
    d["deals"][0]["date"] = dt.date(2025, 6, 30)  # older than 6 months before the as-of date
    p = precedents.validate(d, "corporate")
    assert dt.date(2025, 6, 30) < precedents.cutoff(p) and len(precedents.included(p)) == 5
    assert len(precedents.values(p, "ev_rev_ltm")) == 5
    d["max_age_years"] = 0
    assert len(precedents.included(precedents.validate(d, "corporate"))) == 6


def test_thin_metrics_are_skipped_and_empty_set_errors():
    rows = [dict(ptbv=1.0 + i / 10, pe_ltm=10 + i) for i in range(4)] + [dict(ptbv=1.5, cdp=0.03)]
    p = precedents.validate(raw("bank", rows, target_core_deposits=500.0), "bank")
    assert p["metrics"] == ["ptbv", "pe_ltm"] and "Core Deposit Premium" in p["skipped"][0]
    with pytest.raises(CaseError, match="no multiple has enough deals"):
        precedents.validate(raw("bank", rows[:2]), "bank")
    with pytest.raises(CaseError, match=r"precedents\.deals\[0\]\.ptbv"):
        precedents.validate(raw("bank", [dict(ptbv=-1)] + rows), "bank")
    with pytest.raises(CaseError, match="after precedents.as_of"):
        bad = raw("bank", rows)
        bad["deals"][0]["date"] = dt.date(2027, 1, 1)
        precedents.validate(bad, "bank")


def build_bank(tmp, case=None):
    case = case or bank.load_case(BANK)
    wb = load_workbook(bank_book.build(case, tmp / "b.xlsx"))
    return case, wb, Evaluator(wb)


def build_corp(tmp):
    case = dcf.load_case(CORP)
    wb = load_workbook(dcf_book.build(case, tmp / "d.xlsx"))
    return case, wb, Evaluator(wb)


def compare(ev, case, kind, res):
    ws = ev.wb["Precedents"]
    hdr = {str(c.value): c.column_letter for c in ws[4] if c.value}
    labels = {k: lab for k, lab, *_ in precedents.KINDS[kind]}
    stat_row = {c.value: c.row for c in ws["A"] if isinstance(c.value, str)}
    for key, r in res.items():
        col = hdr[labels[key]]
        for stat, name in (("mean", "Mean"), ("median", "Median"), ("p25", "25th Percentile"),
                           ("p75", "75th Percentile"), ("high", "High"), ("low", "Low")):
            assert ev.cell("Precedents", f"{col}{stat_row[name]}") == pytest.approx(r["stats"][stat]), (key, stat)
        assert ev.cell("Precedents", f"{col}{stat_row['Deals Included']}") == r["n"]
        row = stat_row[r["label"]]
        px = {"corporate": "LMN", "bank": "IJK"}[kind]
        for q, c in zip(("p25", "median", "p75"), px):
            assert ev.cell("Precedents", f"{c}{row}") == pytest.approx(r["implied"][q][-1]), (key, q)


def test_bank_workbook_matches_python(outdir):
    case, wb, ev = build_bank(outdir)
    res = bank.run(case)
    assert wb.sheetnames == ["Summary", "Inputs", "Comps", "Precedents", "DDM", "Sensitivity", "Football_Field", "Checks"]
    compare(ev, case, "bank", res["precedents"])
    ff = {ev.cell("Football_Field", f"A{r}"): r for r in range(5, 12)}
    for label, lo, hi in res["football"]:
        r = ff[label]
        assert ev.cell("Football_Field", f"B{r}") == pytest.approx(lo)
        assert ev.cell("Football_Field", f"C{r}") == pytest.approx(hi)
    assert ev.cell("Football_Field", "D8") == pytest.approx(res["precedents"]["ptbv"]["implied"]["median"][-1])
    assert ev.cell("Football_Field", "A12") == "Current Share Price"


def test_corporate_workbook_matches_python(outdir):
    case, wb, ev = build_corp(outdir)
    compare(ev, case, "corporate", precedents.run(case["precedents"], "corporate", case["target"]))
    assert wb.sheetnames == ["Summary", "Inputs", "Comps", "Precedents", "DCF", "Sensitivity", "Football_Field", "Checks"]
    included = sum(ev.cell("Precedents", f"E{r}") for r in range(5, 11))
    assert included == len(precedents.included(case["precedents"])) == 4


def test_recency_filter_is_live_in_the_workbook(outdir):
    case, wb, ev = build_corp(outdir)
    cut = precedents.cutoff(case["precedents"])
    assert ev.name("Prec_Cutoff") == (cut - dt.date(1899, 12, 30)).days
    wb2 = load_workbook(outdir / "d.xlsx")
    ref = wb2.defined_names["Prec_Max_Age"].attr_text.split("!")[1].replace("$", "")
    wb2["Inputs"][ref] = 0  # filter off: all six deals count
    ev2 = Evaluator(wb2)
    assert sum(ev2.cell("Precedents", f"E{r}") for r in range(5, 11)) == 6


@pytest.mark.parametrize("builder", [build_bank, build_corp])
def test_checks_pass_and_trip(builder, outdir):
    _, wb, ev = builder(outdir)
    fl = flags(wb, ev)
    assert len(fl) >= 9 and all(f == 0 for f in fl), fl
    names = [wb["Checks"][f"A{r}"].value for r in range(5, 5 + len(fl))]
    assert sum("Precedents" in n for n in names) == 2
    ref = wb.defined_names["Prec_Min_Deals"].attr_text.split("!")[1].replace("$", "")
    wb["Inputs"][ref] = 99  # more deals demanded than the set holds
    assert Evaluator(wb).name("Checks_Total") >= 1


@pytest.mark.parametrize("builder", [build_bank, build_corp])
def test_no_hardcodes_and_colors(builder, outdir):
    _, wb, _ = builder(outdir)
    for ws in wb:
        for row in ws.iter_rows():
            for c in row:
                v = c.value
                if isinstance(v, str) and v.startswith("="):
                    assert c.font.color.rgb[-6:] in ("000000", "008000", "800080"), (ws.title, c.coordinate)
                    if ws.title != "Inputs":
                        for t in Tokenizer(v).items:
                            if t.type == "OPERAND" and t.subtype == "NUMBER":
                                x = float(t.value)
                                assert x in ALLOWED or (x == int(x) and int(x) in YEAR_RANGE), (ws.title, v)
                elif ws.title == "Inputs" and c.row >= 5 and isinstance(v, (int, float)) and not c.font.color.rgb.endswith("FFFFFF"):
                    assert c.font.color.rgb.endswith("0000FF"), c.coordinate


@pytest.mark.parametrize("model,case", [("bank", BANK), ("dcf", CORP)])
def test_pitch_precedent_page_ties_to_workbook(model, case, tmp_path):
    xlsx, page = tmp_path / "m.xlsx", tmp_path / "p.html"
    assert main([model, str(case), "--out", str(xlsx), "--pitch", str(page)]) == 0
    doc = page.read_text(encoding="utf-8")
    assert "Precedent Transactions" in doc and "Precedents: " in doc  # page and football bars
    ev = Evaluator(load_workbook(xlsx))
    tags = TAG.findall(doc)
    assert any(ref.startswith("Precedents!") for _, _, ref, _ in tags)
    for _, attrs, ref, shown in tags:
        sheet, cell = ref.split("!")
        want = ev.cell(sheet, cell)
        if "data-text" in attrs:
            assert shown == want
        elif shown in ("Pass", "Fail"):
            assert (want == int(attrs.split('data-pass="')[1][0])) == (shown == "Pass")
        else:
            got, tol = parse(shown)
            assert abs(got - want) <= tol, (ref, shown, want)
    assert chr(0x2014) not in doc and chr(0x2013) not in doc


def test_samples_without_precedents_are_unchanged(outdir):
    c = bank.load_case(ROOT / "cases" / "bank_sample.toml")
    assert "precedents" not in c and bank.run(c)["precedents"] == {} and len(bank.run(c)["football"]) == 3
    assert "Precedents" not in load_workbook(bank_book.build(c, outdir / "x.xlsx")).sheetnames


def test_real_case_rows_are_sourced():
    raw_case = tomllib.loads(BANK.read_text())
    ds = raw_case["precedents"]["deals"]
    assert 6 <= len(ds) <= 10
    for d in ds:
        assert d["source"].startswith("https://") and dt.date(2023, 1, 1) <= d["date"] <= dt.date(2026, 12, 31)
        assert d.get("ptbv") and d["acquirer"] and d["target"]
    assert BANK.read_text().count("[[precedents.deals]]") == len(ds)


def test_cli_prints_precedents(outdir, capsys):
    assert main(["bank", str(BANK), "--out", str(outdir / "c.xlsx")]) == 0
    out = capsys.readouterr().out
    assert "Precedents P / TBV Paid: median 1.55 of 8 deals" in out
    assert "Precedents Core Deposit Premium: median 4.71% of 6 deals" in out
