"""PDF intake: hand tie-out to two real 10-Ks plus synthetic layout cases. Runs offline.

Fixtures (tests/fixtures/pdf) are only the statement pages of public 10-Ks, fetched from SEC EDGAR
and rendered to PDF locally. Page numbers below are fixture pages; the filing's own page is in the
comment next to each.
"""
import os

import pytest

pytest.importorskip("pdfplumber")

from ibtoolkit.intake import pdf
from ibtoolkit.intake.fields import FLAG, OK, FY, QTR, YTD, INSTANT, SourcedValue, by_field

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "pdf")
M = 1e6


@pytest.fixture(scope="module")
def hd():
    return pdf.extract_report(os.path.join(FIX, "hd_10k_fy2025_statements.pdf"))


@pytest.fixture(scope="module")
def tsla():
    return pdf.extract_report(os.path.join(FIX, "tsla_10k_fy2025_statements.pdf"))


# ---- hand tie-out: numbers copied from the printed statements

def test_home_depot_ties_to_filing(hd):
    v = by_field(hd["values"])
    expected = {
        # Consolidated Statements of Earnings, fixture p.4 (10-K page 40), fiscal 2025
        "revenue": (164683, 4, "Net sales"),
        "operating_income": (20890, 4, "Operating income"),
        "interest_expense": (2412, 4, "Interest expense"),
        "income_tax": (4446, 4, "Provision for income taxes"),
        "net_income": (14156, 4, "Net earnings"),
        "diluted_shares": (995, 4, "Diluted weighted average common shares"),
        # Consolidated Balance Sheets, fixture p.3 (10-K page 39), February 1, 2026
        "cash": (1389, 3, "Cash and cash equivalents"),
        "current_assets": (34391, 3, "Total current assets"),
        "current_liabilities": (32424, 3, "Total current liabilities"),
        "total_assets": (105095, 3, "Total assets"),
        "total_equity": (12813, 3, "Total stockholders"),
        "goodwill": (22344, 3, "Goodwill"),
        "intangibles": (10329, 3, "Intangible assets, net"),
        # Consolidated Statements of Cash Flows, fixture p.5 (10-K page 43)
        "capex": (3679, 5, "Capital expenditures"),
        "operating_cash_flow": (16325, 5, "Net cash provided by operating activities"),
    }
    for name, (millions, page, line) in expected.items():
        assert v[name].value == millions * M, name
        assert f"p.{page}" in v[name].source_ref and line in v[name].source_ref, v[name].source_ref
        assert v[name].source_kind == "pdf" and v[name].source_ref.startswith("hd_10k_fy2025_statements.pdf")
    assert v["diluted_eps"].value == 14.23
    assert v["net_income"].period_end == "2026-02-01" and v["net_income"].period_type == FY
    assert v["cash"].period_type == INSTANT and v["cash"].period_end == "2026-02-01"
    assert v["net_income"].form == "10-K"


def test_tesla_ties_to_filing(tsla):
    v = by_field(tsla["values"])
    expected = {
        # Consolidated Balance Sheets, fixture p.2 (10-K page 49), December 31, 2025
        "cash": (16513, 2), "current_assets": (68642, 2), "current_liabilities": (31714, 2),
        "total_assets": (137806, 2), "total_equity": (82137, 2),
        # Consolidated Statements of Operations, fixture p.3 (10-K page 50)
        "revenue": (94827, 3), "operating_income": (4355, 3), "interest_expense": (338, 3),
        "income_tax": (1423, 3), "net_income": (3794, 3), "diluted_shares": (3528, 3),
        # Consolidated Statements of Cash Flows, fixture p.4 (10-K page 53)
        "capex": (8527, 4), "operating_cash_flow": (14747, 4), "d_and_a": (6148, 4),
    }
    for name, (millions, page) in expected.items():
        assert v[name].value == millions * M, name
        assert f"p.{page}," in v[name].source_ref, v[name].source_ref
    assert v["diluted_eps"].value == 1.08
    assert v["net_income"].period_end == "2025-12-31"
    assert v["net_income"].period_start == "2025-01-01"


def test_statement_pages_skip_toc_and_mdna(hd, tsla):
    # HD fixture p.1 is MD&A with its own 'Net sales' table, p.2 is the Item 8 index: neither is used
    assert hd["pages"] == {"balance": [3], "income": [4], "cashflow": [5]}
    # Tesla fixture p.1 is the index to financial statements
    assert tsla["pages"] == {"balance": [2], "income": [3], "cashflow": [4]}
    assert all(v.source_ref.split(" p.")[1][0] != "1" for v in hd["values"] + tsla["values"])


# ---- flags: anything odd is returned but flagged

def test_ambiguous_values_are_flagged_not_dropped(hd, tsla):
    h, t = by_field(hd["values"]), by_field(tsla["values"])
    # HD debt is a sum of three printed lines (4,464 + 4,967 + 46,341), flagged as computed
    assert h["debt"].value == (4464 + 4967 + 46341) * M and h["debt"].status == FLAG
    assert "sum of balance sheet lines" in h["debt"].notes[0]
    # D&A on the cash flow statement excludes intangible amortization for HD
    assert h["d_and_a"].value == 3514 * M and h["d_and_a"].status == FLAG
    # Tesla D&A includes impairment; capex is net of sales and excludes finance leases
    assert t["d_and_a"].status == FLAG and any("impairment" in n for n in t["d_and_a"].notes)
    assert t["capex"].status == FLAG
    # shares outstanding comes from a caption, never silently trusted
    assert h["shares_outstanding"].value == 996 * M and h["shares_outstanding"].status == FLAG
    assert t["shares_outstanding"].value == 3751 * M and t["shares_outstanding"].status == FLAG
    # Tesla net income: attributable line used, consolidated line mentioned
    assert any("3,855" in n for n in t["net_income"].notes)
    # clean values stay ok
    assert h["total_assets"].status == OK and t["revenue"].status == OK
    # a field not on the pages is simply missing (Tesla has no goodwill line)
    assert "goodwill" not in t and "goodwill" in tsla["warnings"][-1]


# ---- synthetic layouts

def test_thousands_dashes_footnotes_and_oldest_first_columns():
    income = """ACME CORP
CONSOLIDATED STATEMENTS OF OPERATIONS
(in thousands, except per share data)
Year Ended December 31,
2023 2024 2025
Total revenues (1) $ 100,000 $ 120,000 $ 150,000
Cost of revenues 60,000 70,000 80,000
Operating income 10,000 15,000 22,500
Interest expense (500) (600) —
Provision for income taxes 2,000 3,000 4,000
Net income $ 7,000 $ 11,000 $ 18,000
Diluted earnings per share $ 0.70 $ 1.10 $ 1.80
Diluted weighted average shares 10,000 10,000 10,000
Other line 1 2 3
"""
    rep = pdf.report_from_pages([income], "acme.pdf")
    v = by_field(rep["values"])
    assert v["revenue"].value == 150_000 * 1e3          # newest column even though it is printed last
    assert v["revenue"].period_end == "2025-12-31"
    assert v["net_income"].value == 18_000 * 1e3
    assert v["diluted_eps"].value == 1.80
    assert v["diluted_shares"].value == 10_000 * 1e3
    # a dash is nil: kept as 0 but flagged
    assert v["interest_expense"].value == 0 and v["interest_expense"].status == FLAG
    assert "dash" in " ".join(v["interest_expense"].notes)
    assert "balance" in " ".join(rep["warnings"])


def test_negative_parentheses_and_missing_scale_flag():
    income = """Statements of Income
Year Ended December 31,
2025 2024
Revenues 500 400
Operating income (loss) (35) 20
Net loss (40) 10
Provision for (benefit from) income taxes (5) 3
Other 1 2
Other 3 4
"""
    v = by_field(pdf.report_from_pages([income], "x.pdf")["values"])
    assert v["operating_income"].value == -35
    assert v["income_tax"].value == -5          # a tax benefit keeps its sign
    assert v["net_income"].value == -40
    assert v["revenue"].status == FLAG and "scale" in v["revenue"].notes[0]


def test_wrapped_labels_and_ten_q_quarter_and_ytd():
    income = """Globex Inc.
CONDENSED CONSOLIDATED STATEMENTS OF INCOME (Unaudited)
(in millions, except per share data)
Three Months Ended Six Months Ended
June 30, June 30,
2026 2025 2026 2025
Net sales $ 1,000 $ 900 $ 1,900 $ 1,700
Operating income 100 90 190 170
Earnings before provision for income
taxes 95 85 180 160
Net income 70 60 130 120
Diluted earnings per share 0.70 0.60 1.30 1.20
Cost of sales 600 540 1,100 1,000
"""
    v = pdf.report_from_pages([income], "globex_10q.pdf")["values"]
    rev = {x.period_type: x for x in v if x.field == "revenue"}
    assert rev[QTR].value == 1000 * M and rev[QTR].period_end == "2026-06-30" and rev[QTR].period_start == "2026-04-01"
    assert rev[YTD].value == 1900 * M and rev[YTD].period_start == "2026-01-01"
    assert all(x.form == "10-Q" for x in v)
    assert not [x for x in v if x.field == "income_tax"]     # 'before provision' line is not tax expense


def test_toc_and_prose_are_not_statements():
    toc = """TABLE OF CONTENTS
Consolidated Balance Sheets 39
Consolidated Statements of Operations 40
Consolidated Statements of Cash Flows 43
"""
    prose = """Results
The following table is taken from our consolidated
statements of operations:
Net sales 5 4
Total revenues 5 4
Net income 1 1
Net income 1 1
Net income 1 1
Net income 1 1
"""
    rep = pdf.report_from_pages([toc, prose], "x.pdf")
    assert rep["values"] == [] and len(rep["warnings"]) >= 3


# ---- compare helper

def _sv(field, value, kind="pdf"):
    return SourcedValue(field=field, value=value, unit="USD", period_type=FY, period_end="2025-12-31",
                        source_kind=kind, source_ref=f"{kind} ref")


def test_compare_flags_only_real_mismatches():
    a = [_sv("revenue", 1000.0), _sv("cash", 500.0), _sv("goodwill", 7.0)]
    b = [_sv("revenue", 1004.0, "xbrl"), _sv("cash", 520.0, "xbrl"), _sv("capex", 3.0, "xbrl")]
    notes = pdf.compare(a, b)                       # default 0.5%
    assert len(notes) == 1 and notes[0].startswith("cash FY 2025-12-31")
    assert pdf.compare(a, b, tolerance=0.05) == []
    assert len(pdf.compare(a, b, tolerance=0.001)) == 2


def test_missing_pdfplumber_gives_clear_error(monkeypatch):
    import builtins
    real = builtins.__import__

    def fake(name, *args, **kw):
        if name == "pdfplumber":
            raise ImportError("no pdfplumber")
        return real(name, *args, **kw)
    monkeypatch.setattr(builtins, "__import__", fake)
    with pytest.raises(pdf.PdfIntakeError, match="requirements-intake.txt"):
        pdf.extract("whatever.pdf")
