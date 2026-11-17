"""Pitch pages: a short printable HTML book built from a finished workbook.

Every figure is read from the saved workbook after xl_eval evaluates its
formulas, and is tagged with data-cell="Sheet!A1" so tests (and readers) can
trace it back. Nothing is recomputed here. The page is self-contained: inline
CSS and inline SVG only, no scripts and no external resources. Print it to PDF
from any browser (US letter, landscape).
"""
import datetime as dt
import html
import re
from datetime import datetime

from openpyxl import load_workbook

from .xl_eval import Evaluator

esc = html.escape

CSS = """
@page { size: 11in 8.5in; margin: 0.45in; }
* { box-sizing: border-box; }
body { margin: 0; background: #e9ecf2; color: #1a1a1a; font: 9.5pt/1.35 "Helvetica Neue", Helvetica, Arial, sans-serif;
  -webkit-print-color-adjust: exact; print-color-adjust: exact; }
.page { width: 10.1in; min-height: 7.6in; margin: 0.3in auto; padding: 0.15in 0.2in; background: #fff; position: relative;
  break-after: page; page-break-after: always; }
.page:last-child { break-after: auto; page-break-after: auto; }
@media print { body { background: #fff; } .page { margin: 0; width: auto; min-height: 0; padding: 0; } }
h1 { font-size: 30pt; margin: 0 0 6pt; color: #1F3864; letter-spacing: 0.2pt; }
h2 { font-size: 15pt; margin: 0 0 4pt; color: #1F3864; border-bottom: 2pt solid #1F3864; padding-bottom: 3pt; }
h3 { font-size: 10.5pt; margin: 10pt 0 3pt; color: #1F3864; }
.sub { color: #595959; margin: 0 0 8pt; }
.cover { padding-top: 1.6in; }
.cover .case { font-size: 15pt; margin: 0 0 14pt; }
.badge { display: inline-block; border: 1.5pt solid #C00000; color: #C00000; padding: 2pt 10pt; font-weight: bold;
  letter-spacing: 1pt; text-transform: uppercase; font-size: 10pt; }
.cover .date { margin-top: 18pt; color: #595959; font-size: 11pt; }
.tiles { display: flex; gap: 10pt; margin: 8pt 0 10pt; }
.tile { flex: 1; border: 1pt solid #c9d1e3; border-top: 4pt solid #1F3864; padding: 8pt 8pt 6pt; background: #f6f8fc; }
.tile .num { display: block; font-size: 20pt; font-weight: bold; color: #1F3864; }
.tile .cap { color: #595959; font-size: 8.5pt; }
.cols { display: flex; gap: 18pt; align-items: flex-start; }
.cols > div { flex: 1; min-width: 0; }
table { border-collapse: collapse; width: 100%; font-size: 8.5pt; }
th { background: #1F3864; color: #fff; text-align: right; padding: 2.5pt 5pt; font-weight: bold; }
th:first-child, td:first-child { text-align: left; }
td { padding: 2pt 5pt; border-bottom: 0.5pt solid #d5dbe8; text-align: right; }
td.lab { text-align: left; }
tr.total td { font-weight: bold; border-top: 1pt solid #1F3864; }
tr.sec td { background: #D9E1F2; font-weight: bold; text-align: left; }
td.base { background: #FFF2CC; font-weight: bold; }
.status { font-weight: bold; padding: 1pt 8pt; border-radius: 3pt; }
.status.ok, .flag.ok { color: #1e6b2e; }
.status.bad, .flag.bad { color: #C00000; font-weight: bold; }
.status.ok { background: #C6EFCE; }
.status.bad { background: #FFC7CE; }
ul { margin: 2pt 0 0; padding-left: 14pt; }
li { margin-bottom: 2pt; }
.note { color: #595959; font-size: 8.5pt; margin-top: 6pt; }
footer { position: absolute; left: 0.2in; right: 0.2in; bottom: 0; display: flex; justify-content: space-between;
  color: #595959; font-size: 8pt; border-top: 0.5pt solid #c9d1e3; padding-top: 3pt; }
svg { width: 100%; height: auto; display: block; }
svg text { font: 10px "Helvetica Neue", Helvetica, Arial, sans-serif; fill: #1a1a1a;
           paint-order: stroke; stroke: #fff; stroke-width: 3px; stroke-linejoin: round; }
svg .bar { fill: #1F3864; }
svg .mid { stroke: #fff; stroke-width: 2; }
svg .ref { stroke: #C00000; stroke-width: 1.5; stroke-dasharray: 4 3; }
svg .reftxt { fill: #C00000; font-weight: bold; }
svg .grid { stroke: #e1e6f0; stroke-width: 1; }
"""


def fmt_spec(nf, v):
    """Map a workbook number format to a display spec such as p1, x2, d0, n1."""
    if "Pass" in nf:
        return "pf"
    m = re.search(r"\.(0+)", nf)
    d = len(m.group(1)) if m else 0
    if nf == "General":
        d = 0 if float(v).is_integer() else 2
    return ("p" if "%" in nf else "x" if '"x"' in nf else "d" if "$" in nf else "n") + str(d)


def fmt_value(v, spec):
    kind, d = spec[0], int(spec[1:])
    x = v * 100 if kind == "p" else v
    s = f"{abs(x):,.{d}f}"
    s = {"p": s + "%", "x": s + "x", "d": "$" + s}.get(kind, s)
    return f"({s})" if round(x, d) < 0 else s


class Pitch:
    def __init__(self, xlsx):
        self.wb = load_workbook(xlsx)
        self.ev = Evaluator(self.wb)
        self._rows = {}

    # ---- lookups -------------------------------------------------------
    def row(self, sheet, label, nth=0):
        """Row number of the nth cell in column A whose text equals label."""
        if sheet not in self._rows:
            self._rows[sheet] = {}
            for c in self.wb[sheet]["A"]:
                if isinstance(c.value, str):
                    self._rows[sheet].setdefault(c.value.strip(), []).append(c.row)
        try:
            return self._rows[sheet][label][nth]
        except (KeyError, IndexError):
            raise KeyError(f"Pitch: no row {label!r} on sheet {sheet}") from None

    def val(self, sheet, ref):
        return self.ev.cell(sheet, ref)

    def text(self, sheet, ref):
        return str(self.val(sheet, ref) or "")

    # ---- tagged output ---------------------------------------------------
    def n(self, sheet, ref, f=None, tag="span", cls="num"):
        """One figure, formatted like the workbook cell, tagged with its source cell."""
        v = self.val(sheet, ref)
        if v is None or isinstance(v, str):
            return esc(str(v or ""))
        spec = f or fmt_spec(self.wb[sheet][ref].number_format, v)
        if spec == "pf":
            ok = v == 1
            return (f'<{tag} class="flag {"ok" if ok else "bad"}" data-cell="{sheet}!{ref}" data-pass="1">'
                    f'{"Pass" if ok else "Fail"}</{tag}>')
        return f'<{tag} class="{cls}" data-cell="{sheet}!{ref}">{esc(fmt_value(v, spec))}</{tag}>'

    def lbl(self, sheet, label, col="B", nth=0, f=None, **kw):
        return self.n(sheet, f"{col}{self.row(sheet, label, nth)}", f, **kw)

    def flag(self, sheet, ref, pass_value):
        v = self.val(sheet, ref)
        ok = v == pass_value
        return (f'<span class="flag {"ok" if ok else "bad"}" data-cell="{sheet}!{ref}" data-pass="{pass_value}">'
                f'{"Pass" if ok else "Fail"}</span>')

    def head(self, sheet, ref):
        """Column header text from a header cell (Year n, Close, or plain text)."""
        v, nf = self.val(sheet, ref), self.wb[sheet][ref].number_format
        if isinstance(v, (int, float)):
            if nf.startswith('"Year'):
                return f"Year {int(v)}"
            lit = re.fullmatch(r'"([^"]*)"', nf)  # a pure text format, e.g. "Close" or "LTM" on the year-0 column
            return lit.group(1) if lit else fmt_value(v, fmt_spec(nf, v))
        return str(v or "")

    def master_status(self):
        ref = f"B{self.row('Summary', 'Model Checks')}"
        t = self.text("Summary", ref)
        cls = "ok" if t == "All Checks OK" else "bad"
        return f'<span class="status {cls}" data-cell="Summary!{ref}" data-text="1">{esc(t)}</span>'

    # ---- building blocks -------------------------------------------------
    def table(self, head, rows):
        """rows: (label, [cell markup], css class)"""
        out = ["<table><tr>" + "".join(f"<th>{esc(h)}</th>" for h in head) + "</tr>"]
        for label, cells, cls in rows:
            if cls == "sec":
                out.append(f'<tr class="sec"><td colspan="{len(head)}">{esc(label)}</td></tr>')
                continue
            out.append(f'<tr class="{cls}"><td class="lab">{esc(label)}</td>'
                       + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
        return "".join(out) + "</table>"

    def lines(self, sheet, items, cols, head, title=None):
        """Table of labelled workbook rows. items: label or (label, shown label, class)."""
        rows = []
        for it in items:
            label, shown, cls = (it, it, "") if isinstance(it, str) else (tuple(it) + ("",))[:3]
            if label is None:
                rows.append((shown, [], "sec"))
            else:
                r = self.row(sheet, label)
                rows.append((shown, [self.n(sheet, f"{c}{r}") for c in cols], cls))
        return self.table(head, rows)

    def grid(self, sheet, title_prefix):
        """5 by 5 sensitivity grid found by its title. Returns (title, refs) with axis refs."""
        r = next(c.row for c in self.wb[sheet]["A"] if isinstance(c.value, str) and c.value.startswith(title_prefix))
        cols = "BCDEF"
        title = re.sub(r"^Grid \d+, [^:]+: ", "", self.text(sheet, f"A{r}"))  # drop workbook-only build notes
        return {"title": title, "sheet": sheet, "top": r + 1,
                "cols": cols, "rows": list(range(r + 2, r + 7))}

    def grid_html(self, g, base=(2, 2)):
        s, top = g["sheet"], g["top"]
        out = [f"<h3>{esc(g['title'])}</h3><table><tr><th></th>"
               + "".join(f'<th>{self.n(s, f"{c}{top}")}</th>' for c in g["cols"]) + "</tr>"]
        for i, r in enumerate(g["rows"]):
            out.append(f'<tr><td class="lab">{self.n(s, f"A{r}")}</td>'
                       + "".join(f'<td class="{"base" if (i, j) == base else ""}">{self.n(s, f"{c}{r}")}</td>'
                                 for j, c in enumerate(g["cols"])) + "</tr>")
        return "".join(out) + "</table>"

    def football(self, items, ref=None, unit_f=None):
        """Horizontal range bars. items: (label markup, (sheet, lo ref), (sheet, hi ref), mid or None).
        ref: (label, sheet, cell) draws a dashed reference line."""
        vals = [self.val(*i[1]) for i in items] + [self.val(*i[2]) for i in items]
        if ref:
            vals.append(self.val(ref[1], ref[2]))
        lo, hi = min(vals), max(vals)
        pad = (hi - lo) * 0.06 or 1
        lo, hi = lo - pad, hi + pad
        # gutter fits the longest label: ~6px per char at the 10px svg font, plus 80px for the low-value text
        label_w = max(len(html.unescape(re.sub(r"<[^>]+>", "", i[0]))) for i in items) * 6
        x0, x1, row_h, top = max(360, label_w + 88), 880, 28, 22

        def x(v):
            return x0 + (v - lo) / (hi - lo) * (x1 - x0)

        h = top + row_h * len(items) + 14
        out = [f'<svg viewBox="0 0 960 {h}" role="img" aria-label="Football field chart">']
        for k in range(5):
            gx = x0 + (x1 - x0) * k / 4
            out.append(f'<line class="grid" x1="{gx:.1f}" y1="{top - 8}" x2="{gx:.1f}" y2="{h - 10}"/>')
        if ref:  # drawn first so value labels sit on top of the line
            rx = x(self.val(ref[1], ref[2]))
            out.append(f'<line class="ref" x1="{rx:.1f}" y1="{top - 10}" x2="{rx:.1f}" y2="{h - 10}"/>')
            out.append(f'<text class="reftxt" x="{rx + 4:.1f}" y="{top - 11}">{esc(ref[0])} '
                       f'{self.n(ref[1], ref[2], tag="tspan", cls="")}</text>')
        for i, (label, lo_ref, hi_ref, mid_ref) in enumerate(items):
            y = top + i * row_h
            a, b = self.val(*lo_ref), self.val(*hi_ref)
            out.append(f'<text x="{x0 - 80}" y="{y + 12}" text-anchor="end">{label}</text>')
            out.append(f'<rect class="bar" x="{x(a):.1f}" y="{y}" width="{max(x(b) - x(a), 2):.1f}" height="16"/>')
            if mid_ref:
                m = x(self.val(*mid_ref))
                out.append(f'<line class="mid" x1="{m:.1f}" y1="{y}" x2="{m:.1f}" y2="{y + 16}"/>')
            out.append(f'<text x="{x(a) - 5:.1f}" y="{y + 12}" text-anchor="end">{self.n(*lo_ref, tag="tspan", cls="")}</text>')
            out.append(f'<text x="{x(b) + 5:.1f}" y="{y + 12}">{self.n(*hi_ref, tag="tspan", cls="")}</text>')
        out.append("</svg>")
        return "".join(out)

    def rows_below(self, sheet, header_label):
        """Row numbers under a header row in column A, up to the first blank cell."""
        r = self.row(sheet, header_label) + 1
        out = []
        while self.val(sheet, f"A{r}"):
            out.append(r)
            r += 1
        return out

    def precedents_page(self):
        """Precedent transactions page, or [] when the workbook has no Precedents sheet."""
        S = "Precedents"
        if S not in self.wb.sheetnames:
            return []
        hr = self.row(S, "Target")
        cells_ = [c for c in self.wb[S][hr] if c.value]
        heads, letters = [str(c.value) for c in cells_], [c.column_letter for c in cells_]
        mi = heads.index("Included") + 1  # metric columns follow the Included column
        rows = []
        for r in range(hr + 1, self.row(S, "Mean") - 1):
            if not self.val(S, f"A{r}"):
                continue
            day = dt.date(1899, 12, 30) + dt.timedelta(days=int(self.val(S, f"C{r}")))
            rows.append((f"{self.text(S, f'A{r}')} / {self.text(S, f'B{r}')}",
                         [esc(day.isoformat()), self.n(S, f"D{r}"), self.n(S, f"E{r}")]
                         + [self.n(S, f"{c}{r}") for c in letters[mi:]], ""))
        for st in ("Median", "25th Percentile", "75th Percentile", "Mean", "Deals Included"):
            sr = self.row(S, st)
            rows.append((st, ["", "", ""] + [self.n(S, f"{c}{sr}") for c in letters[mi:]],
                         "total" if st == "Median" else ""))
        deals = self.table(["Target / Acquirer", "Announced", "Deal Value ($M)", "Included"] + heads[mi:], rows)
        ih = self.row(S, "Method")
        hc = [c for c in self.wb[S][ih] if c.value and str(c.value).startswith(("Multiple", "Price"))]
        imp = [(self.text(S, f"A{r}"), [self.n(S, f"{c.column_letter}{r}") for c in hc], "")
               for r in self.rows_below(S, "Method")]
        impl = self.table(["Method"] + [str(c.value) for c in hc], imp)
        note = str(self.wb[S]["A2"].value or "")
        return [page("Precedent Transactions", deals + "<h3>Implied Target Valuation</h3>" + impl
                     + f'<p class="note">{esc(note)} Deals outside the recency window show blank multiples and are '
                       "left out of every statistic. The source for each deal is on the Inputs sheet.</p>",
                     "Dollars in millions except per share")]

    def checks_html(self):
        s = "Checks"
        r0, r1 = self.row(s, "Check") + 1, self.row(s, "Total Errors")
        rows = [(self.text(s, f"A{r}"), [self.flag(s, f"B{r}", 0)], "") for r in range(r0, r1)]
        rows.append(("Total Errors", [self.n(s, f"B{r1}", "n0")], "total"))
        return self.table(["Check", "Status"], rows)


def tiles(items):
    return '<div class="tiles">' + "".join(
        f'<div class="tile">{v}<span class="cap">{esc(c)}</span></div>' for c, v in items) + "</div>"


def cols(*parts):
    return '<div class="cols">' + "".join(f"<div>{p}</div>" for p in parts) + "</div>"


def page(title, body, sub=""):
    return (f'<section class="page"><h2>{esc(title)}</h2>' + (f'<p class="sub">{esc(sub)}</p>' if sub else "")
            + body + "</section>")


def bullets(items):
    return "<ul>" + "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul>"


def appendix(p, conventions, source):
    body = cols(
        "<h3>Model Conventions</h3>" + bullets(conventions)
        + f'<p class="note">{esc(source)}</p>',
        "<h3>Checks Status</h3><p>Master check: " + p.master_status() + "</p>" + p.checks_html())
    return page("Appendix: Conventions and Checks", body)


def cover(p, book_title):
    case, note = p.text("Summary", "A3"), p.text("Summary", "A4")
    label = "Illustrative" if "ILLUSTRATIVE" in note.upper() else "Model Output"
    d = datetime.now().astimezone()
    return ('<section class="page cover">'
            f'<h1>{esc(book_title)}</h1><p class="case">{esc(case)}</p>'
            f'<span class="badge">{label}</span>'
            f'<p class="sub" style="margin-top:14pt">{esc(note)}</p>'
            f'<p class="sub">{esc(p.text("Summary", "A2"))}</p>'
            f'<p class="date">{d:%B} {d.day}, {d.year}</p></section>')


# ---- LBO ----------------------------------------------------------------------

def lbo_pages(p):
    S, SU, M, R, SE = "Summary", "Sources_Uses", "Model", "Returns", "Sensitivity"
    yrs = [p.head(M, f"{c}4") for c in "BCDEFG"]
    exec_ = page("Executive Summary", tiles([
        ("Purchase Price", p.lbl(S, "Purchase Price")),
        ("Sponsor Equity", p.lbl(S, "Sponsor Equity")),
        ("Total Debt / LTM EBITDA at Close", p.lbl(S, "Total Debt / LTM EBITDA at Close")),
        ("Sponsor MOIC", p.lbl(S, "Sponsor MOIC")),
        ("Sponsor IRR", p.lbl(S, "Sponsor IRR"))])
        + cols(p.lines(S, ["Entry Multiple", "Exit Enterprise Value", "Exit Equity Value", "Minimum Year-End Cash",
                           "Peak Revolver Balance", "Covenant Tests Failed"], "B", ["Supporting Figures", "Value"]),
               "<h3>Operating Case</h3>" + p.lines(M, ["Revenue", "EBITDA", "EBITDA Margin",
                                                      ("Free Cash Flow Before Debt Repayment", "Free Cash Flow Before Debt", "")],
                                                   "BCDEFG", [""] + yrs)), "Dollars in thousands")
    su_items = lambda names: [(n, n, "total" if n.startswith("Total") else "") for n in names]
    su = ["Uses", "Sources"]
    su_head = ["", "Amount", "x LTM EBITDA", "% of Total"]
    uses = p.lines(SU, su_items(["Purchase Price (Enterprise Value)", "Advisory and Transaction Fees (Expensed at Close)",
                                 "Financing Fees (Capitalized, Amortized)", "Cash to Balance Sheet", "Total Uses"]), "BCD", su_head)
    srcs = p.lines(SU, su_items(["Senior Term Loan", "Mezzanine Notes", "Total Equity: Sponsor and Management Rollover (Plug)", "Total Sources"]), "BCD", su_head)
    ret = p.lines(R, ["Exit-Year EBITDA", "Exit Enterprise Value", "Less: Senior Debt",
                      "Less: Mezzanine Notes (Including PIK)", "Less: Revolver", "Plus: Cash",
                      ("Exit Equity Value", "Exit Equity Value", "total"), "Less: Management Option Pool",
                      "Sponsor Exit Proceeds", "Sponsor Equity Invested",
                      "Sponsor MOIC", "Sponsor IRR"], "B", ["Exit and Returns", "Value"])
    core = page("Sources and Uses, Returns", cols("<h3>Uses</h3>" + uses + "<h3>Sources</h3>" + srcs, ret), "Dollars in thousands")
    credit = page("Credit Statistics", p.lines(M, [
        (None, "Leverage and Coverage", ""),
        "Total Debt / EBITDA", ("Senior Debt (Term Loan and Revolver) / EBITDA", "Senior Debt / EBITDA", ""),
        ("EBITDA / Cash Interest (Including Revolver Interest and Fees)", "EBITDA / Cash Interest", ""),
        ("Fixed Charge Coverage: (EBITDA - Capex - Cash Taxes) / (Cash Interest + Mandatory Amort.)",
         "Fixed Charge Coverage", ""),
        (None, "Covenant Tests", ""),
        "Maximum Total Debt / EBITDA", "Leverage Headroom (1 - Actual / Maximum)",
        "Minimum EBITDA / Cash Interest", "Coverage Headroom (1 - Minimum / Actual)"],
        "BCDEFG", [""] + yrs)
        + '<p class="note">Headroom is the EBITDA cushion before a covenant breach. Covenant test results (Pass or Fail) '
          "are on the Model sheet and are all counted in the Checks status in the appendix.</p>"
        + "<h3>Covenant Results</h3>" + p.table([""] + yrs[1:], [
            (name, [p.flag(M, f"{c}{p.row(M, name)}", 1) for c in "CDEFG"], "")
            for name in ("Leverage Test", "Coverage Test")]), "Dollars in thousands except ratios")
    g1 = p.grid(SE, "Grid 1,")
    g2 = p.grid(SE, "Grid 2,")
    items = []
    top = g1["top"]
    for r in g1["rows"]:
        label = f'Entry {p.n(SE, f"A{r}", tag="tspan", cls="")}, exit {p.n(SE, f"B{top}", tag="tspan", cls="")} to {p.n(SE, f"F{top}", tag="tspan", cls="")}'
        items.append((label, (SE, f"B{r}"), (SE, f"F{r}"), (SE, f"D{r}")))
    sens = page("Football Field and Sensitivity",
                "<h3>Sponsor IRR Range by Entry Multiple</h3>" + p.football(items)
                + '<p class="note">Each bar runs across the exit multiples on the grid below; the white tick is the middle exit multiple.</p>'
                + cols(p.grid_html(g1), p.grid_html(g2)))
    conv = ["Units are $ thousands. Multiples are in x and rates are decimals.",
            "The deal closes at the end of year 0. Cash flows fall at year end, and exit is at the end of year 5.",
            "Interest is on beginning balances, so there are no circular references.",
            "Mezzanine pays cash and PIK interest; both are tax deductible.",
            "The revolver draws when cash would fall below the minimum balance and repays first from cash above it.",
            "A cash sweep applies a share of free cash flow after mandatory amortization to the term loan.",
            "Advisory fees are expensed at close. Financing fees are capitalized, amortized straight line and tax deductible.",
            "Cash taxes are floored at zero with no loss carryforward.",
            "Returns assume one equity outflow at close and one inflow at exit, with no interim dividends.",
            "The leverage sensitivity reruns the full debt schedule outside the workbook; its centre is checked against the model."]
    return [exec_, core, credit, sens,
            appendix(p, conv, "Every figure in this book is read from the evaluated workbook. Nothing is recomputed.")]


# ---- Merger -----------------------------------------------------------------------

def merger_pages(p):
    S, PA, PF, EB, SE = "Summary", "Purchase_Accounting", "Pro_Forma", "Earnback", "Sensitivity"
    exec_ = page("Executive Summary", tiles([
        ("Aggregate Price Paid", p.lbl(S, "Aggregate Price Paid")),
        ("Price / Tangible Book Value", p.lbl(S, "Price / Tangible Book Value")),
        ("Year 1 EPS Accretion / (Dilution)", p.lbl(S, "Year 1 EPS Accretion / (Dilution)")),
        ("Year 2 EPS Accretion / (Dilution)", p.lbl(S, "Year 2 EPS Accretion / (Dilution)")),
        ("TBV Earnback (Years)", p.lbl(S, "TBV Earnback (Years, -1 = Not Within 10)", f="n1"))])
        + cols(p.lines(S, ["Offer Price per Target Share", "Price / Year 1 Earnings", "Goodwill Created",
                           "Core Deposit Intangible", "TBV per Share Accretion / (Dilution) at Close",
                           "Pro Forma TCE Ratio"], "B", ["Supporting Figures", "Value"]),
               "<p class=\"note\">Earnback is the first year pro forma TBV per share reaches the standalone line, "
               "interpolated within the year. Zero means no dilution at close. Minus one means no crossover "
               "within 10 years.</p>"), "Dollars in thousands except per share")
    terms = p.lines(PA, ["Offer Price per Target Share", "Premium to Unaffected Target Price", "Aggregate Price Paid",
                         "Price / Tangible Book Value", "Price / Year 1 Earnings Paid", "Stock Consideration",
                         "Cash Consideration", "Consideration Mix: Stock (% of Price)",
                         "Consideration Mix: Cash (% of Price)",
                         "Exchange Ratio (Stock Election, Acquirer Shares per Target Share)",
                         "Blended Acquirer Shares Issued per Target Share",
                         "New Acquirer Shares Issued (Thousands)"], "B", ["Deal Terms", "Value"])
    gw = p.lines(PA, ["Target Tangible Book Value", "Plus: Net Fair Value Marks", "Plus: Core Deposit Intangible",
                      "Plus: Net Deferred Tax Asset / (Liability)", ("Fair Value of Net Identifiable Assets", "Fair Value of Net Identifiable Assets", "total"),
                      ("Goodwill (Price Less Fair Value of Net Assets)", "Goodwill", "total")], "B", ["Goodwill", "Value"])
    core = page("Deal Terms and Purchase Accounting", cols(terms, gw), "Dollars in thousands except per share")
    ad = p.lines(PF, ["Acquirer Standalone Net Income", "Plus: Target Net Income", "Plus: Cost Saves (Pre-Tax, Phased)",
                      "Less: Cost of Cash Consideration (Pre-Tax)", "Plus: Accretion of Fair Value Marks (Pre-Tax)",
                      "Plus: Balance Sheet Restructuring Pickup (Pre-Tax)",
                      "Plus: Accretion of Non-PCD Credit Mark (Pre-Tax)",
                      "Less: Amortization of Deposit and Borrowings Marks (Pre-Tax)",
                      "Less: CDI Amortization (Pre-Tax)", ("Pro Forma Net Income", "Pro Forma Net Income", "total"),
                      "Pro Forma EPS", "Acquirer Standalone EPS", "Accretion / (Dilution) per Share",
                      ("Accretion / (Dilution) %", "Accretion / (Dilution) %", "total")],
                 "BC", ["Accretion and Dilution", p.head(PF, "B4") or "Year 1", p.head(PF, "C4") or "Year 2"])
    ad = ad.replace("<th>1</th>", "<th>Year 1</th>").replace("<th>2</th>", "<th>Year 2</th>")
    close = p.lines(PF, ["Acquirer Standalone TBV per Share", "Pro Forma TBV per Share",
                         "TBV per Share Accretion / (Dilution) %", "Acquirer Standalone TCE / Tangible Assets",
                         "Pro Forma TCE / Tangible Assets", "Ownership: Acquirer Shareholders",
                         "Ownership: Target Shareholders"], "B", ["At Close", "Value"])
    ycols = "BCDEFGHIJKL"
    eb_head = [""] + [p.head(EB, f"{c}4").replace("1", "1") for c in ycols]
    eb = p.lines(EB, ["Standalone TBV per Share", "Pro Forma TBV per Share", "Gap: Standalone Less Pro Forma"], ycols,
                 ["TBV per Share"] + [h if h.startswith("Year") else f"Year {h}" for h in eb_head[1:]])
    eb = eb.replace("<th>Year 0</th>", "<th>Close</th>")
    ebv = p.lbl(EB, "TBV Earnback Period in Years (0 = None Needed, -1 = Not Within 10 Years)", f="n1")
    accr = page("Accretion, Dilution and TBV Earnback",
                cols(ad, close) + "<h3>TBV Earnback</h3>" + eb
                + f'<p class="note">Earnback period in years: {ebv}. Zero means none needed; minus one means not within 10 years.</p>',
                "Dollars in thousands except per share")
    g1, g2 = p.grid(SE, "Year 1"), p.grid(SE, "Year 2")
    items = []
    for yr, g in (("Year 1", g1), ("Year 2", g2)):
        for r in g["rows"]:
            t = g["top"]
            label = (f'{yr}, offer {p.n(SE, f"A{r}", tag="tspan", cls="")}, cost saves '
                     f'{p.n(SE, f"B{t}", tag="tspan", cls="")} to {p.n(SE, f"F{t}", tag="tspan", cls="")}')
            items.append((label, (SE, f"B{r}"), (SE, f"F{r}"), (SE, f"D{r}")))
    sens = page("Football Field and Sensitivity",
                "<h3>EPS Accretion Range by Offer Price</h3>" + p.football(items)
                + '<p class="note">Each bar runs across the cost save range on the grids below; the white tick is the middle case. '
                  "Grid values are live workbook formulas; the shaded centre is the base case.</p>"
                + cols(p.grid_html(g1), p.grid_html(g2)))
    contrib, breakeven = merger_contribution_page(p), merger_breakeven_page(p)

    def inp(label):
        return p.val("Inputs", f"B{p.row('Inputs', label)}") or 0
    syd = inp("CDI Method (1 = Sum of Years Digits, 0 = Straight Line)") == 1
    gross = inp("CDI Tax Treatment in TBV (1 = Gross, 0 = Net of Deferred Tax)") == 1
    plus, less = ["cost saves (phased)", "rate mark accretion"], ["cost of cash"]
    for label, word, side in [("Restructuring: Target Securities Sold", "the balance sheet restructuring pickup", plus),
                              ("Gross Credit Mark (Total)", "non-PCD credit mark accretion", plus),
                              ("Revenue Dis-Synergies (Pre-Tax, Annual)", "revenue dis-synergies", less),
                              ("Deposit Mark (Positive = Liability Written Down)", "deposit mark amortization", less),
                              ("Borrowings Mark (Positive = Liability Written Down)", "borrowings mark amortization", less)]:
        if inp(label):
            side.append(word)
    less.append("CDI amortization")
    gross_up = inp("Non-PCD Method (1 = ASU 2025-08 Gross-Up, 0 = Day 2 Reserve Expensed)") == 1
    one_time = "merger charges and the CECL day 2 reserve" if inp(
        "CECL Day 2 Reserve on Non-PCD Loans (Pre-Tax, One-Time)") and not gross_up else "merger charges"
    conv = ["Units are $ thousands, shares in thousands, share prices in dollars.",
            "Rate mark equals negative duration times the rate change times the balance. It ignores convexity and cash flow timing, and accretes straight line.",
            "Goodwill is price less the fair value of net identifiable assets: target TBV plus net marks plus CDI, plus a net deferred tax asset (marks) or less a net liability (CDI).",
            "The non-PCD credit mark writes loans down at close (through goodwill and TBV) and accretes into income. The PCD mark grosses up the allowance with no income and no TBV effect."
            if inp("Gross Credit Mark (Total)") else "No credit mark is entered.",
            ("Non-PCD loans follow ASU 2025-08 (purchased seasoned loans): the day 1 allowance is added to amortized cost "
             "(gross-up) with no credit loss expense and no TBV effect, and only the credit mark in excess of that allowance accretes."
             if gross_up else "Non-PCD loans follow pre-ASU 2025-08 CECL: any day 2 allowance is expensed at close (after tax, against TBV)."),
            "CDI is a percent of core deposits, amortized " + ("by sum of years digits" if syd else "straight line")
            + " and tax effected. " + ("The full CDI is deducted from TBV (gross of its deferred tax liability)."
                                       if gross else "TBV deducts CDI net of its deferred tax liability."),
            "Pro forma EPS adds, after tax, " + ", ".join(plus[:-1]) + " and " + plus[-1] + ", and deducts "
            + ", ".join(less[:-1]) + " and " + less[-1] + ".",
            f"One-time {one_time} are excluded from EPS and deducted after tax from TBV at close.",
            "The exchange ratio is the stock election ratio. Blended shares per target share spread the new shares over all target shares, cash and stock.",
            "Earnback is a simple crossover: each side's TBV per share grows by its own EPS, with no dividends. Later years hold Year 2 EPS flat.",
            "Pro forma EPS for earnback adds back CDI amortization because it is not a tangible cost: "
            + ("pre-tax, since the full CDI is deducted from TBV." if gross else "after tax, since CDI is deducted net of its deferred tax.")]
    conv += ["Contribution: the implied exchange ratio is the all-stock ratio that gives target holders their share of each "
             "metric. A metric with a 0 input on either side is left out of the range.",
             "Breakeven cost saves are closed form: saves only move pro forma net income, after tax. The accretion grid "
             "is live formulas that change only the offer price and Year 1 saves realized."]
    return [exec_, core, accr, sens, contrib, breakeven,
            appendix(p, conv, "Every figure in this book is read from the evaluated workbook. Nothing is recomputed.")]


def merger_contribution_page(p):
    C = "Contribution"
    rows = [(p.text(C, f"A{r}"), [p.n(C, f"{c}{r}") for c in "BCEFG"], "")
            for r in p.rows_below(C, "Metric")]
    table = p.table(["Metric", "Acquirer", "Target", "Acquirer %", "Target %", "Implied Exchange Ratio"], rows)
    lo, hi = (C, f"B{p.row(C, 'Implied Exchange Ratio: Minimum')}"), (C, f"B{p.row(C, 'Implied Exchange Ratio: Maximum')}")
    tlo, thi = (C, f"B{p.row(C, 'Target Contribution: Minimum')}"), (C, f"B{p.row(C, 'Target Contribution: Maximum')}")
    ratio = p.football([("Implied exchange ratio range", lo, hi, None)],
                       ref=("Announced", C, f"B{p.row(C, 'Announced Exchange Ratio (Stock Election)')}"))
    own = p.football([("Target contribution range", tlo, thi, None)],
                     ref=("Pro forma ownership", C, f"B{p.row(C, 'Target Pro Forma Ownership')}"))
    pos = p.lines(C, ["Announced Ratio Position in Range (0% = Minimum, 100% = Maximum)",
                      "Ownership Position in Range (0% = Minimum, 100% = Maximum)"], "B", ["Where the Deal Sits", "Value"])
    return page("Contribution Analysis", table + "<h3>Exchange Ratio vs Contribution</h3>" + ratio
                + "<h3>Target Ownership vs Contribution</h3>" + own + pos
                + '<p class="note">Implied ratio = (target / acquirer) x acquirer shares / target shares, the all-stock '
                  "ratio that matches ownership to contribution. With cash in the consideration, pro forma ownership "
                  "sits below contribution by design.</p>", "Dollars in thousands")


def merger_breakeven_page(p):
    B = "Breakeven"
    head = p.lines(B, ["Modeled Year 1 Cost Saves (Pre-Tax, as Realized)",
                       ("Breakeven Year 1 Cost Saves (Pre-Tax, as Realized)", "Breakeven Year 1 Cost Saves (Pre-Tax)", "total"),
                       "Breakeven Saves as % of Target Noninterest Expense",
                       "Breakeven Run-Rate Saves % at the Modeled Year 1 Phase-In",
                       "Modeled Run-Rate Cost Saves (% of Target Noninterest Expense)",
                       "Cushion: Modeled Less Breakeven Year 1 Saves (Pre-Tax)",
                       "Year 1 EPS Accretion at Breakeven Saves (Should Be 0%)"], "B", ["Breakeven", "Value"])
    g = p.grid(B, "Year 1 EPS Accretion / (Dilution):")
    g["cols"] = "BCDE"
    return page("Breakeven Cost Saves and Accretion Grid",
                cols(head + '<p class="note">Breakeven = modeled saves less (pro forma EPS less standalone EPS) x pro forma '
                            "shares / (1 - tax rate). A negative breakeven means Year 1 is accretive even with no cost "
                            "saves, carried by purchase accounting accretion and the other deal adjustments.</p>",
                     p.grid_html(g, base=(2, 3))
                     + '<p class="note">Columns are the share of run-rate cost saves realized in Year 1; the last column '
                       "is the modeled phase-in, so its middle row is the base case.</p>"),
                "Dollars in thousands except per share")


# ---- DCF --------------------------------------------------------------------------

def dcf_pages(p):
    S, C, D, SE, F = "Summary", "Comps", "DCF", "Sensitivity", "Football_Field"
    exec_ = page("Executive Summary", tiles([
        ("WACC", p.lbl(S, "WACC")),
        ("DCF Share Price, Gordon Growth", p.lbl(S, "DCF Share Price: Gordon Growth")),
        ("DCF Share Price, Exit Multiple", p.lbl(S, "DCF Share Price: Exit Multiple")),
        ("Comps Median EV / EBITDA (NTM)", p.lbl(S, "Comps Median EV / EBITDA (NTM)")),
        ("Comps Price at Median EV / EBITDA", p.lbl(S, "Comps Implied Share Price at Median EV / EBITDA (NTM)"))])
        + cols(p.lines(S, ["PV of Terminal Value % of EV (Gordon)", "Implied Exit Multiple from Gordon Growth",
                           "Implied Perpetuity Growth from Exit Multiple"], "B", ["Cross-Checks", "Value"]),
               p.lines(D, [("Enterprise Value", "Enterprise Value", "")], "BC", ["Enterprise Value", "Gordon Growth", "Exit Multiple"])),
        "Dollars in millions except per share")
    hr = p.row(C, "Company")
    colof = {str(c.value): c.column_letter for c in p.wb[C][hr] if c.value}
    want = ["Market Cap", "Enterprise Value", "EV / Revenue (NTM)", "EV / EBITDA (LTM)", "EV / EBITDA (NTM)", "P / E (NTM)"]
    letters = [colof[w] for w in want]
    rows = []
    r = hr + 1
    while p.val(C, f"A{r}"):
        rows.append((p.text(C, f"A{r}"), [p.n(C, f"{c}{r}") for c in letters], ""))
        r += 1
    for st in ("Mean", "Median", "25th Percentile", "75th Percentile"):
        sr = p.row(C, st)
        rows.append((st, [p.n(C, f"{c}{sr}") if p.val(C, f"{c}{sr}") is not None else "" for c in letters],
                     "total" if st == "Median" else ""))
    peers = p.table(["Company"] + want, rows)
    ih = p.row(C, "Method")
    imp_rows = []
    for k in range(1, 7):
        r = ih + k
        imp_rows.append((p.text(C, f"A{r}"), [p.n(C, f"{c}{r}") for c in "CDELMN"], ""))
    imp = p.table(["Method", "Multiple: 25th", "Multiple: Median", "Multiple: 75th", "Price: 25th", "Price: Median", "Price: 75th"], imp_rows)
    comps = page("Trading Comps Summary", peers + "<h3>Implied Target Valuation</h3>" + imp,
                 "Dollars in millions except per share")
    ycols = "CDEFG"
    ufcf = p.lines(D, ["Revenue", "EBITDA", "Less: Capex", ("Unlevered Free Cash Flow", "Unlevered Free Cash Flow", "total"),
                       "PV of Unlevered Free Cash Flow"], ycols, [""] + [p.head(D, f"{c}4") for c in ycols])
    wacc = p.lines(D, ["Cost of Equity (Risk-Free + Beta x ERP)", "After-Tax Cost of Debt", "Debt / Total Capital (Target)",
                       ("WACC", "WACC", "total")], "B", ["Cost of Capital", "Value"])
    two = ["Terminal Value (Undiscounted)", "PV of Terminal Value", "Sum of PV of Unlevered Free Cash Flow",
           ("Enterprise Value", "Enterprise Value", "total"), "Less: Net Debt", "Equity Value", "Diluted Shares (Millions)",
           ("Implied Share Price", "Implied Share Price", "total"), "PV of Terminal Value as % of Enterprise Value"]
    val = p.lines(D, two, "BC", ["Valuation", "Gordon Growth", "Exit Multiple"])
    dcfp = page("DCF Summary", "<h3>Unlevered Free Cash Flow</h3>" + ufcf + cols(wacc, val),
                "Dollars in millions except per share. Mid-year convention follows the case setting.")
    ff = [(esc(p.text(F, f"A{r}")), (F, f"B{r}"), (F, f"D{r}"), (F, f"C{r}")) for r in p.rows_below(F, "Method")]
    g1, g2 = p.grid(SE, "WACC (Down) by Terminal"), p.grid(SE, "WACC (Down) by Exit")
    sens = page("Football Field and Sensitivity", "<h3>Implied Share Price by Method</h3>" + p.football(ff)
                + '<p class="note">Comps bars run from the 25th to the 75th percentile multiple. DCF bars run across the '
                  "sensitivity grid. The white tick is the median or base case.</p>" + cols(p.grid_html(g1), p.grid_html(g2)))
    conv = ["Units are $ millions and per-share figures are dollars.",
            "WACC uses CAPM for cost of equity and an after-tax cost of debt at a target capital structure.",
            "Terminal value is shown by Gordon growth and by exit multiple, each with an implied cross-check.",
            "The mid-year convention is a case setting. When on, the Gordon terminal value is discounted at year 5 less one half, and the exit multiple value at year 5.",
            "Percentiles use inclusive interpolation, like Excel PERCENTILE.",
            "Comps ranges run from the 25th to the 75th percentile. DCF ranges come from the live sensitivity grids; the midpoint is the base case.",
            "The peers and target are made up unless the case file says otherwise."]
    return [exec_, comps, dcfp, sens, *p.precedents_page(), appendix(p, conv, "Every figure in this book is read from the evaluated workbook. Nothing is recomputed.")]


# ---- Bank -------------------------------------------------------------------------

def bank_pages(p):
    S, C, D, F = "Summary", "Comps", "DDM", "Football_Field"
    exec_ = page("Executive Summary", tiles([
        ("Current Share Price", p.lbl(S, "Current Share Price")),
        ("Value per Share, P/TBV Regression", p.lbl(S, "Value per Share: P/TBV Regression")),
        ("Value per Share, P/E (LTM, normalized)", p.lbl(S, "Value per Share: P/E (LTM, normalized)")),
        ("Value per Share, DDM (Average)", p.lbl(S, "Value per Share: DDM (Average)")),
        ("Cost of Equity", p.lbl(S, "Cost of Equity"))])
        + p.lines(S, ["Tangible Book Value per Share", "Current P/TBV", "Current P/E (LTM, normalized)", "Target ROTE (Core LTM)",
                      "Regression R Squared", "Implied P/TBV (Regression)"], "B", ["Supporting Figures", "Value"]),
        "Dollars in millions except per share")
    r0 = p.row(F, "Method")
    meth = p.table(["Method", "Low", "Midpoint", "High", "Midpoint vs Current"], [
        (p.text(F, f"A{r}"), [p.n(F, f"{c}{r}") for c in "BDCF"] , "") for r in p.rows_below(F, "Method")])
    reg = p.lines(C, ["Regression Slope (P/TBV per 1.00 of ROTE)", "Regression Intercept (x)", "R Squared",
                      "Target ROTE (Core LTM Net Income / TCE)", "Implied P/TBV", "Tangible Book Value per Share ($)"],
                  "B", ["P/TBV Against ROTE", "Value"])
    pe = p.lines(C, ["Normalized LTM EPS ($)", "Peer Median P/E (LTM)"], "B", ["P/E (LTM, normalized)", "Value"])
    ddm = p.lines(D, ["Cost of Equity (Risk-Free + Beta x ERP)", "Sum of PV of Distributions",
                      "Value per Share, P/TBV Terminal ($)", "Value per Share, Gordon Terminal ($)",
                      "Value per Share, Average of Both ($)", "Cross-Check: Regression P/TBV at Year 5 ROTE",
                      "Cross-Check: Gordon Terminal Value / Year 5 TCE (Implied P/TBV)"],
                 "B", ["Dividend Discount Model", "Value"])
    core = page("Method Summary", "<h3>Value per Share by Method</h3>" + meth + cols(reg, pe + ddm),
                "Dollars in millions except per share")
    pr0 = p.row(C, "Peer")
    rows, r = [], pr0 + 1
    while p.text(C, f"A{r}") != "Mean":
        rows.append((p.text(C, f"A{r}"), [p.n(C, f"{c}{r}") for c in "BCD"], ""))
        r += 1
    for st in ("Mean", "Median", "High", "Low", "Target at Current Price"):
        sr = p.row(C, st)
        rows.append((st, [p.n(C, f"{c}{sr}") for c in "BCD"], "total" if st.startswith("Target") else ""))
    peers = p.table(["Peer", "P/TBV", "P/E (LTM)", "ROTE"], rows)
    yc = "CDEFG"
    dd = p.lines(D, ["Net Income", "Distributions (Excess Capital, Capped at Max Payout)", "Ending TCE",
                     "TCE / Total Assets", "Payout Ratio (Distributions / Net Income; Year 0 = LTM Dividends)"], yc, [""] + [p.head(D, f"{c}4") for c in yc])
    peerp = page("Peer Set and Distributions", cols("<h3>Peer Multiples</h3>" + peers,
                                                    "<h3>Capital-Constrained Distributions</h3>" + dd), "Dollars in millions")
    cur = ("Current price", F, f"B{p.row(F, 'Current Share Price')}")
    ff = [(esc(p.text(F, f"A{r}")), (F, f"B{r}"), (F, f"C{r}"), (F, f"D{r}")) for r in p.rows_below(F, "Method")]
    g1 = p.grid("Sensitivity", "Cost of Equity (Down) by Terminal P/TBV")
    g2 = p.grid("Sensitivity", "Cost of Equity (Down) by Terminal Growth")
    sens = page("Football Field and Sensitivity", "<h3>Value per Share by Method</h3>" + p.football(ff, ref=cur)
                + '<p class="note">Regression and P/E bars are the point estimate plus and minus the case band. '
                  "The DDM bar runs between the two terminal value methods. The white tick is the midpoint. "
                  "DDM grids below are dollars per share, live workbook formulas; the shaded centre "
                  "is the base case, checked on the Checks sheet.</p>" + cols(p.grid_html(g1), p.grid_html(g2)))
    conv = ["Units are $ millions and shares in millions. Per-share values are dollars.",
            "Peers are regressed with SLOPE, INTERCEPT and RSQ. The target's core (normalized) LTM ROTE gives an implied P/TBV.",
            "P/E applies the peer median trailing P/E to the target's normalized LTM EPS, so multiple and earnings share one basis.",
            "In the dividend discount model, TCE above the target ratio times assets is paid out each year, capped at the maximum payout of net income and floored at zero; capital above target that the cap holds back is shown as retained excess.",
            "Terminal value is shown as P/TBV times year 5 TCE and as Gordon growth on a normalized distribution. The football field uses the range between them.",
            "Year-end cash flows with no mid-year discounting. Distributions stand in for dividends and buybacks.",
            "The sensitivity grids are live formulas that re-discount the DDM at each cell's assumptions."]
    return [exec_, core, peerp, sens, *p.precedents_page(), appendix(p, conv, "Every figure in this book is read from the evaluated workbook. Nothing is recomputed.")]


# ---- Debt capacity ----------------------------------------------------------------

def debtcap_pages(p):
    S, C, ST, M, RT, SE, CV = "Summary", "Capacity", "Structure", "Model", "Rating", "Sensitivity", "Covenant"

    def text(ref, size="13pt"):
        return (f'<span class="num" style="font-size:{size}" data-cell="{S}!{ref}" data-text="1">'
                f'{esc(p.text(S, ref))}</span>')

    def srow(label):
        return f"B{p.row(S, label)}"

    r0 = p.row(C, "Constraint")
    cap_rows = [(p.text(C, f"A{r}").split(":")[0], [p.n(C, f"B{r}"), p.n(C, f"C{r}"), p.flag(C, f"D{r}", 1)], "")
                for r in range(r0 + 1, r0 + 5)]
    cap = p.table(["Constraint", "Maximum Debt", "x LTM EBITDA", "Lowest"], cap_rows)
    drivers = p.lines(C, ["LTM EBITDA", "Year 1 Cash Flow Before Debt Service",
                          "Blended Interest Rate (Weighted by Share of Debt)",
                          "Senior Secured Share of Debt (Term Loan B Plus Second Lien)",
                          "Maximum Total Debt (Lowest of the Four)", "Sizing Cushion (% Below the Binding Maximum)",
                          ("Proposed Total Debt", "Proposed Total Debt", "total")], "B", ["Sizing Drivers", "Value"])
    exec_ = page("Executive Summary", tiles([
        ("Proposed Total Debt", p.lbl(S, "Proposed Total Debt")),
        ("Binding Constraint", text(srow("Binding Constraint"))),
        ("Total Debt / LTM EBITDA", p.lbl(S, "Total Debt / LTM EBITDA at Close")),
        ("EBITDA / Cash Interest", p.lbl(S, "EBITDA / Cash Interest at Close")),
        ("Indicative Rating at Close", text(srow("Indicative Rating at Close"), "20pt"))])
        + cols("<h3>Maximum Debt by Constraint</h3>" + cap
               + '<p class="note">Each constraint is solved for total debt. The lowest one binds and is marked Pass '
                 "in the Lowest column.</p>"
               + p.lines(S, ["Senior Secured Debt / LTM EBITDA at Close", "Total Debt / EBITDA in Year 5",
                             "Debt Repaid by Year 5 (% of Closing Debt)", "Limit Tests Failed (Years 1 to 5)"],
                         "B", ["Supporting Figures", "Value"]),
               drivers + "<h3>Year 5 Indicative Rating</h3><p>" + text(srow("Indicative Rating in Year 5"), "20pt")
               + '</p><p class="note">Ratings come from an illustrative leverage and coverage grid in the case file. '
                 "They are not a rating agency view.</p>"), "Dollars in thousands")
    br = p.lines(CV, [(lab, lab, "total" if lab.startswith(("Reported", "Adjusted", "Covenant")) else "")
                      for lab in [p.text(CV, f"A{r}") for r in range(5, 17)]], "BC",
                 ["Covenant EBITDA Bridge", "Amount", "% of Reported"])
    basis = p.lines(CV, [p.text(CV, f"A{r}") for r in (20, 21, 22)], "B", ["EBITDA Basis by Test", "Amount"])
    cmp_ = p.table(["Constraint", "On Reported", "On Covenant", "Change"],
                   [(p.text(CV, f"A{r}"), [p.n(CV, f"{c}{r}") for c in "BCD"], "total" if r == 30 else "")
                    for r in range(26, 31)])
    fc = p.lines(CV, ["Fixed Amount", "% of Covenant EBITDA Times Covenant EBITDA",
                      ("Free-and-Clear Basket (Greater of the Two)", "Free-and-Clear Basket (Greater of the Two)",
                       "total"),
                      ("Maximum Debt Plus Free-and-Clear Basket (Cash Tests Not Re-Run; Not in Proposed Debt)",
                       "Maximum Debt Plus Free-and-Clear Basket", "")], "B", ["Free-and-Clear Basket", "Amount"])
    covenant = page("Covenant EBITDA Bridge", tiles([
        ("Reported LTM EBITDA", p.lbl(S, "Reported LTM EBITDA")),
        ("Covenant EBITDA (Capped)", p.lbl(S, "Covenant EBITDA (Capped Adjusted)")),
        ("Max Debt on Reported EBITDA", p.lbl(S, "Maximum Total Debt on Reported EBITDA")),
        ("Max Debt on Covenant EBITDA", p.lbl(S, "Maximum Total Debt")),
        ("Change From Add-Backs", p.lbl(S, "Change in Maximum Debt From Add-Backs"))])
        + cols(br + '<p class="note">Add-backs are capped at a percentage of reported LTM EBITDA before '
                    "add-backs. The cap is an input; see the case file for its source.</p>",
               basis + '<p class="note">Lenders size the two leverage tests on capped covenant EBITDA. Interest '
                       "coverage and FCF / debt use cash EBITDA, so add-backs add no debt when a cash test "
                       "binds.</p><h3>Maximum Debt: Reported vs Covenant EBITDA</h3>" + cmp_ + fc),
        "Dollars in thousands")
    h = ["Tranche", "Amount", "x LTM EBITDA", "% of Total", "Interest Rate", "Annual Interest", "Cumulative x EBITDA"]
    rows = []
    for name in ("Term Loan B", "Senior Notes", "Second Lien", "Total Debt"):
        r = p.row(ST, name)
        rows.append((name, [p.n(ST, f"{c}{r}") if p.val(ST, f"{c}{r}") is not None else ""
                            for c in "BCDEFG"], "total" if name == "Total Debt" else ""))
    yrs = [p.head(M, f"{c}4") for c in "BCDEFG"]
    stats = p.lines(M, [
        (None, "Credit Statistics", ""),
        "Total Debt", "Total Debt / EBITDA", "Senior Secured Debt / EBITDA", "EBITDA / Cash Interest",
        "(EBITDA - Capex) / Cash Interest",
        ("Cash Flow After Interest / Beginning Debt (Close Column Shows Year 1)", "Cash Flow After Interest / Debt", ""),
        (None, "Deleveraging Path", ""),
        "Cumulative Debt Repaid", "Debt Repaid (% of Closing Debt)", "Turns of Leverage Removed Since Close"],
        "BCDEFG", [""] + yrs)
    tests = p.table([""] + yrs, [
        (name, [p.flag(M, f"{c}{p.row(M, name)}", 1) for c in "BCDEFG"], "total" if name == "All Limits Met" else "")
        for name in ("Total Leverage Within Limit", "Senior Secured Leverage Within Limit",
                     "Interest Coverage Within Limit", "FCF / Debt Within Limit", "All Limits Met")])
    struct = page("Proposed Capital Structure", "<h3>Debt by Tranche at Close</h3>" + p.table(h, rows)
                  + "<h3>Credit Statistics and Deleveraging</h3>" + stats, "Dollars in thousands except ratios")
    rating = p.table([""] + yrs, [
        (name, [p.n(RT, f"{c}{p.row(RT, name)}") for c in "BCDEFG"], "total" if name.startswith("Indicative") else "")
        for name in ("Leverage-Implied Rating", "Coverage-Implied Rating",
                     "Indicative Rating (Best Band Where Both Tests Pass)")])
    limits = page("Limit Tests and Indicative Rating", "<h3>Limit Tests by Year</h3>" + tests
                  + '<p class="note">The proposed debt is sized at close. These tests show that the binding '
                    "constraint, and the other three, still hold in each projected year.</p>"
                  + "<h3>Indicative Rating by Year</h3>" + rating
                  + '<p class="note">Illustrative grid from the case file. A band is met when debt / EBITDA is at or '
                    "below its maximum and EBITDA / interest is at or above its minimum.</p>")
    g1, g2 = p.grid(SE, "Grid 1,"), p.grid(SE, "Grid 2,")
    items = []
    for r in g1["rows"]:
        t = g1["top"]
        label = (f'EBITDA haircut {p.n(SE, f"A{r}", tag="tspan", cls="")}, rate shift '
                 f'{p.n(SE, f"B{t}", tag="tspan", cls="")} to {p.n(SE, f"F{t}", tag="tspan", cls="")}')
        items.append((label, (SE, f"F{r}"), (SE, f"B{r}"), (SE, f"D{r}")))
    sens = page("Football Field and Sensitivity",
                "<h3>Maximum Debt Range by EBITDA Haircut</h3>" + p.football(items)
                + '<p class="note">Each bar runs across the interest rate shifts on the grid below; the white tick is '
                  "the unshifted rate.</p>"
                + cols(p.grid_html(g1, base=(0, 2)), p.grid_html(g2, base=(0, 2))))
    conv = ["Units are $ thousands. Multiples are in x and rates are decimals.",
            "Total debt is sized four ways: total leverage, senior secured leverage, interest coverage and "
            "cash flow after interest to debt. The lowest maximum binds, and an optional cushion sizes below it.",
            "Tranches are fixed shares of total debt, so the blended rate does not depend on the debt amount and "
            "each constraint has a closed form.",
            "Senior secured debt is the term loan B plus any second lien. Senior notes are unsecured.",
            "Leverage is sized on covenant EBITDA: reported LTM EBITDA plus add-backs, capped at an input "
            "percentage of reported EBITDA. Coverage uses reported (cash) LTM EBITDA. The FCF to debt limit uses "
            "Year 1 cash flow after interest.",
            "Add-backs apply at close only. Projected EBITDA is assumed to include any add-backs that are realized, "
            "so unrealized add-backs show up as leverage test fails in the projected years.",
            "The free-and-clear basket is the greater of a fixed amount and a % of covenant EBITDA. It is shown on "
            "top of maximum debt and is not sized into the proposed structure.",
            "Interest is on beginning balances. Cash taxes, capex and working capital are inputs and are not "
            "re-computed for interest or for EBITDA haircuts.",
            "Only the term loan B amortizes and takes a cash sweep. Notes and second lien are bullets. Cash not "
            "applied to debt is not netted against it.",
            "The rating grid and every limit are illustrative inputs, not agency methodology or lender terms.",
            "The haircut and rate sensitivities show the maximum debt at the binding constraint before any cushion."]
    return [exec_, covenant, struct, limits, sens,
            appendix(p, conv, "Every figure in this book is read from the evaluated workbook. Nothing is recomputed.")]


BOOKS = {"lbo": ("LBO Pitch Book", lbo_pages), "merger": ("Bank Merger Pitch Book", merger_pages),
         "dcf": ("Comps and DCF Pitch Book", dcf_pages), "bank": ("Bank Valuation Pitch Book", bank_pages),
         "debtcap": ("Debt Capacity Pitch Book", debtcap_pages)}


def build(model, xlsx, out):
    """Write the pitch book for a built workbook. Returns the output path."""
    title, pages = BOOKS[model]
    p = Pitch(xlsx)
    secs = [cover(p, title)] + pages(p)
    n = len(secs)
    foot = f"IBToolkit | {title} | {p.text('Summary', 'A3')}"
    secs = [s.replace("</section>", f"<footer><span>{esc(foot)}</span><span>Page {i} of {n}</span></footer></section>")
            for i, s in enumerate(secs, 1)]
    doc = ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
           "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
           f"<title>{esc(title)}</title><style>{CSS}</style></head><body>" + "".join(secs) + "</body></html>")
    from pathlib import Path
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    return out
