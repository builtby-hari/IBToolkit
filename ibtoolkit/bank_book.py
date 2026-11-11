"""Writes the bank valuation workbook: Summary, Inputs, Comps, DDM, Football_Field.

Every calculated cell is a live formula (regression uses SLOPE, INTERCEPT, RSQ).
Hard-coded inputs live only on Inputs.
"""
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter as L

from . import precedents
from .bank import STEPS, YEARS
from .excel import MULT, MULT2, PCT, Book

USD = '$#,##0.0_);($#,##0.0);"-"_)'  # $ millions, one decimal
PS = '$#,##0.00_);($#,##0.00);"-"_)'  # per share
COLS = [L(i) for i in range(2, 2 + YEARS + 1)]  # B = year 0, C..G = years 1..5

SCALARS = [
    ("NI_LTM", "Net Income (LTM, GAAP, $M)", ("target", "net_income"), USD),
    ("Core_NI_LTM", "Core Net Income (LTM, Excl. One-Time Items, $M)", ("target", "core_net_income"), USD),
    ("TCE", "Tangible Common Equity ($M)", ("target", "tce"), USD),
    ("Total_Assets", "Total Assets ($M)", ("target", "total_assets"), USD),
    ("Shares", "Diluted Shares (M)", ("target", "shares"), USD),
    ("Dividends_LTM", "Common Dividends (LTM, $M)", ("target", "dividends"), USD),
    ("Share_Price", "Current Share Price ($)", ("target", "share_price"), PS),
    ("Target_TCE_Ratio", "Target TCE / Total Assets", ("capital", "target_tce_ratio"), PCT),
    ("Max_Payout", "Maximum Payout (Distributions / Net Income)", ("capital", "max_payout"), PCT),
    ("Risk_Free", "Risk-Free Rate", ("cost_of_equity", "risk_free"), PCT),
    ("Beta", "Beta", ("cost_of_equity", "beta"), MULT2),
    ("ERP", "Equity Risk Premium", ("cost_of_equity", "erp"), PCT),
    ("Terminal_Growth", "Terminal Growth Rate", ("terminal", "growth"), PCT),
    ("Terminal_PTBV", "Terminal P/TBV (x Year 5 TCE)", ("terminal", "ptbv"), MULT2),
    ("Range_Pct", "Football Field Band (+/- % of Point Estimate)", ("valuation", "range_pct"), PCT),
    ("Ke_Step", "Sensitivity Step: Cost of Equity", ("steps", "ke"), PCT),
    ("PTBV_Step", "Sensitivity Step: Terminal P/TBV (x)", ("steps", "ptbv"), MULT2),
    ("G_Step", "Sensitivity Step: Terminal Growth", ("steps", "g"), PCT),
]
SERIES = [
    ("growth", "Net Income Growth", ("forecast", "net_income_growth")),
    ("agrowth", "Total Asset Growth", ("forecast", "asset_growth")),
]
IN_FIRST = 5
IN_ROW = {s[0]: IN_FIRST + i for i, s in enumerate(SCALARS)}
IN_SERIES = IN_FIRST + len(SCALARS) + 2
IN_SROW = {s[0]: IN_SERIES + 1 + i for i, s in enumerate(SERIES)}
IN_PEERS = IN_SERIES + len(SERIES) + 3  # peer header row; peers start on the next row

# DDM rows: ("sec", label) or (key, label, fmt, year0_formula, year_formula, bold)
R = {}


def _f(key, c):
    return f"{c}{R[key]}"


def _spec():
    f = _f
    return [
        ("sec", "Earnings and Capital"),
        ("ni", "Net Income", USD, lambda: "=NI_LTM",
         lambda c, p: f"={f('ni', p)}*(1+Inputs!{c}{IN_SROW['growth']})", True),
        ("assets", "Total Assets", USD, lambda: "=Total_Assets",
         lambda c, p: f"={f('assets', p)}*(1+Inputs!{c}{IN_SROW['agrowth']})", False),
        ("req_tce", "Required TCE (Target Ratio x Assets)", USD, None,
         lambda c, p: f"=Target_TCE_Ratio*{f('assets', c)}", False),
        ("tce_pre", "TCE Before Distributions (Prior TCE + Net Income)", USD, None,
         lambda c, p: f"={f('tce', p)}+{f('ni', c)}", False),
        ("div", "Distributions (Excess Capital, Capped at Max Payout)", USD, None,
         lambda c, p: f"=MAX(0,MIN(Max_Payout*{f('ni', c)},{f('tce_pre', c)}-{f('req_tce', c)}))", True),
        ("tce", "Ending TCE", USD, lambda: "=TCE",
         lambda c, p: f"={f('tce_pre', c)}-{f('div', c)}", True),
        ("excess", "Excess / (Shortfall) TCE vs Target, Retained", USD,
         lambda: f"={f('tce', 'B')}-Target_TCE_Ratio*{f('assets', 'B')}",
         lambda c, p: f"={f('tce', c)}-{f('req_tce', c)}", False),
        ("ratio", "TCE / Total Assets", PCT, lambda: f"={f('tce', 'B')}/{f('assets', 'B')}",
         lambda c, p: f"={f('tce', c)}/{f('assets', c)}", False),
        ("rote", "ROTE (Net Income / Beginning TCE)", PCT, None,
         lambda c, p: f"={f('ni', c)}/{f('tce', p)}", False),
        ("payout", "Payout Ratio (Distributions / Net Income; Year 0 = LTM Dividends)", PCT,
         lambda: "=Dividends_LTM/NI_LTM",
         lambda c, p: f"={f('div', c)}/{f('ni', c)}", False),
        ("sec", "Discounting at Cost of Equity (Year-End Cash Flows)"),
        ("df", "Discount Factor", '0.0000', None,
         lambda c, p: f"=1/(1+Cost_Of_Equity)^{c}$4", False),
        ("pv_div", "PV of Distributions", USD, None,
         lambda c, p: f"={f('div', c)}*{f('df', c)}", False),
    ]


MODEL_FIRST = 5
_row = MODEL_FIRST
for _s in _spec():
    if _s[0] != "sec":
        R[_s[0]] = _row
    _row += 1
SPEC = _spec()
MODEL_KEYS = list(R)
LAST = COLS[-1]
DDM_TOP = _row + 1  # first row of the valuation block under the schedule


def _inputs(b, case):
    ws = b.sheet("Inputs", "Inputs", "Blue cells are hard-coded inputs from the case file. $ in millions.",
                 {"A": 52, **{c: 14 for c in COLS}})
    b.header(ws, 4, ["Input", "Value"])
    for name, label, (sec, field), fmt in SCALARS:
        r = IN_ROW[name]
        b.label(ws, f"A{r}", label)
        b.inp(ws, f"B{r}", STEPS[field] if sec == "steps" else case[sec][field], fmt, name=name)
    b.header(ws, IN_SERIES, ["Time Series Inputs", ""] + list(range(1, YEARS + 1)))
    for key, label, (sec, field) in SERIES:
        r = IN_SROW[key]
        b.label(ws, f"A{r}", label)
        for i, v in enumerate(case[sec][field]):
            b.inp(ws, f"{COLS[i + 1]}{r}", v, PCT)
    b.header(ws, IN_PEERS, ["Peer Set", "P/TBV", "P/E (LTM)", "ROTE"])
    for i, p in enumerate(case["peers"]):
        r = IN_PEERS + 1 + i
        b.inp(ws, f"A{r}", p["name"], "@")
        ws[f"A{r}"].alignment = Alignment(horizontal="left")
        b.inp(ws, f"B{r}", p["ptbv"], MULT2)
        b.inp(ws, f"C{r}", p["pe"], MULT)
        b.inp(ws, f"D{r}", p["rote"], PCT)
    ws.freeze_panes = "B5"


def _comps(b, case):
    n = len(case["peers"])
    ws = b.sheet("Comps", "Peer Comps and Implied Valuation",
                 "Peer rows link to Inputs. Regression uses Excel SLOPE, INTERCEPT and RSQ, so it stays live.",
                 {"A": 46, "B": 14, "C": 14, "D": 14})
    b.header(ws, 4, ["Peer", "P/TBV", "P/E (LTM)", "ROTE"])
    first, last = 5, 4 + n
    for i in range(n):
        r, src = first + i, IN_PEERS + 1 + i
        b.calc(ws, f"A{r}", f"=Inputs!A{src}", "@")
        ws[f"A{r}"].alignment = Alignment(horizontal="left")
        for c, fmt in zip("BCD", (MULT2, MULT, PCT)):
            b.calc(ws, f"{c}{r}", f"=Inputs!{c}{src}", fmt)
    r = last + 1
    for label, fn in [("Mean", "AVERAGE"), ("Median", "MEDIAN"), ("High", "MAX"), ("Low", "MIN")]:
        b.label(ws, f"A{r}", label, bold=True)
        for c, fmt in zip("BCD", (MULT2, MULT, PCT)):
            b.calc(ws, f"{c}{r}", f"={fn}({c}{first}:{c}{last})", fmt, total=label == "Mean")
        if label == "Median":
            b.name(ws, f"C{r}", "Median_PE")
        r += 1
    rng = lambda c: f"{c}{first}:{c}{last}"  # noqa: E731
    r += 1
    b.label(ws, f"A{r}", "Target at Current Price", bold=True)
    b.calc(ws, f"B{r}", "=Share_Price/TBVPS", MULT2)
    b.calc(ws, f"C{r}", "=Share_Price/LTM_EPS", MULT)
    b.calc(ws, f"D{r}", "=Target_ROTE", PCT)
    b.name(ws, f"B{r}", "Market_PTBV")
    b.name(ws, f"C{r}", "Market_PE")
    r += 2
    b.section(ws, r, "Method 1: P/TBV vs ROTE Regression", 4)
    rows = [
        ("Regression Slope (P/TBV per 1.00 of ROTE)", f"=SLOPE({rng('B')},{rng('D')})", MULT2, "Reg_Slope"),
        ("Regression Intercept (x)", f"=INTERCEPT({rng('B')},{rng('D')})", MULT2, "Reg_Intercept"),
        ("R Squared", f"=RSQ({rng('B')},{rng('D')})", '0.00', "Reg_RSQ"),
        ("Target ROTE (Core LTM Net Income / TCE)", "=Core_NI_LTM/TCE", PCT, "Target_ROTE"),
        ("Implied P/TBV", "=Reg_Intercept+Reg_Slope*Target_ROTE", MULT2, "Implied_PTBV"),
        ("Tangible Book Value per Share ($)", "=TCE/Shares", PS, "TBVPS"),
        ("Implied Price per Share ($)", "=Implied_PTBV*TBVPS", PS, "Price_PTBV"),
        ("Premium / (Discount) to Current Price", "=Price_PTBV/Share_Price-1", PCT, None),
    ]
    r = _block(b, ws, r + 1, rows)
    b.section(ws, r + 1, "Method 2: P/E (LTM, normalized)", 4)
    rows = [
        ("Core Net Income (LTM, $M)", "=Core_NI_LTM", USD, None),
        ("Normalized LTM EPS ($)", "=Core_NI_LTM/Shares", PS, "LTM_EPS"),
        ("Peer Median P/E (LTM)", "=Median_PE", MULT, None),
        ("Implied Price per Share ($)", "=LTM_EPS*Median_PE", PS, "Price_PE"),
        ("Premium / (Discount) to Current Price", "=Price_PE/Share_Price-1", PCT, None),
    ]
    _block(b, ws, r + 2, rows)
    ws.freeze_panes = "B5"


def _block(b, ws, r, rows):
    for label, formula, fmt, name in rows:
        b.label(ws, f"A{r}", label)
        b.calc(ws, f"B{r}", formula, fmt, name=name)
        r += 1
    return r


def _ddm(b):
    ws = b.sheet("DDM", "Dividend Discount Model",
                 "$ in millions. Excess capital above the target TCE ratio is paid out each year.",
                 {"A": 54, **{c: 14 for c in COLS}})
    b.header(ws, 4, ["", *range(0, YEARS + 1)])
    row = MODEL_FIRST
    for s in SPEC:
        if s[0] == "sec":
            b.section(ws, row, s[1], len(COLS) + 1)
        else:
            key, label, fmt, y0, yr, bold = s
            b.label(ws, f"A{row}", label, bold=bold, indent=0 if bold else 1)
            if y0:
                b.calc(ws, f"B{row}", y0(), fmt, bold=bold)
            for i in range(1, YEARS + 1):
                b.calc(ws, f"{COLS[i]}{row}", yr(COLS[i], COLS[i - 1]), fmt, bold=bold)
        row += 1
    r = DDM_TOP
    b.section(ws, r, "Valuation", len(COLS) + 1)
    rows = [
        ("Cost of Equity (Risk-Free + Beta x ERP)", "=Risk_Free+Beta*ERP", PCT, "Cost_Of_Equity"),
        ("Sum of PV of Distributions", f"=SUM(C{R['pv_div']}:{LAST}{R['pv_div']})", USD, "PV_Divs"),
        ("Terminal Value: P/TBV x Year 5 TCE", f"=Terminal_PTBV*{LAST}{R['tce']}", USD, "TV_PTBV"),
        ("PV of Terminal Value (P/TBV)", f"=TV_PTBV*{LAST}{R['df']}", USD, "PV_TV_PTBV"),
        ("Value per Share, P/TBV Terminal ($)", "=(PV_Divs+PV_TV_PTBV)/Shares", PS, "DDM_Price_PTBV"),
        ("Normalized Year 6 Distribution (NI x (1+g) less g x TCE)",
         f"={LAST}{R['ni']}*(1+Terminal_Growth)-Terminal_Growth*{LAST}{R['tce']}", USD, None),
        ("Terminal Value: Gordon Growth", f"=B{r + 6}/(Cost_Of_Equity-Terminal_Growth)", USD, "TV_Gordon"),
        ("PV of Terminal Value (Gordon)", f"=TV_Gordon*{LAST}{R['df']}", USD, "PV_TV_Gordon"),
        ("Value per Share, Gordon Terminal ($)", "=(PV_Divs+PV_TV_Gordon)/Shares", PS, "DDM_Price_Gordon"),
        ("Value per Share, Average of Both ($)", "=AVERAGE(DDM_Price_PTBV,DDM_Price_Gordon)", PS, "DDM_Price_Mid"),
        ("Terminal Value Share of Equity Value (P/TBV)", "=PV_TV_PTBV/(PV_Divs+PV_TV_PTBV)", PCT, None),
        ("Cross-Check: Regression P/TBV at Year 5 ROTE", f"=Reg_Intercept+Reg_Slope*{LAST}{R['rote']}", MULT2,
         "Reg_PTBV_Y5"),
        ("Cross-Check: Gordon Terminal Value / Year 5 TCE (Implied P/TBV)", f"=TV_Gordon/{LAST}{R['tce']}", MULT2,
         "Gordon_PTBV"),
    ]
    _block(b, ws, r + 1, rows)
    ws.freeze_panes = "B5"


def _football(b, lay):
    ws = b.sheet("Football_Field", "Football Field: Value per Share ($)",
                 "Low and high per method. Current price shown for reference. Precedent rows run from the "
                 "25th to the 75th percentile, with the median as the midpoint.",
                 {"A": 36, **{c: 14 for c in "BCDEF"}})
    b.header(ws, 4, ["Method", "Low", "High", "Midpoint", "Spread", "Mid vs Current"])
    rows = [
        ("P/TBV vs ROTE Regression", "=Price_PTBV*(1-Range_Pct)", "=Price_PTBV*(1+Range_Pct)", None),
        ("P/E (LTM, normalized)", "=Price_PE*(1-Range_Pct)", "=Price_PE*(1+Range_Pct)", None),
        ("Dividend Discount Model", "=MIN(DDM_Price_PTBV,DDM_Price_Gordon)", "=MAX(DDM_Price_PTBV,DDM_Price_Gordon)", None),
    ]
    if lay:
        rows += [(lab, lo, hi, mid) for lab, lo, mid, hi in precedents.football_rows(lay)]
    last = 4 + len(rows)
    for i, (label, lo, hi, mid) in enumerate(rows):
        r = 5 + i
        b.label(ws, f"A{r}", label)
        b.calc(ws, f"B{r}", lo, PS)
        b.calc(ws, f"C{r}", hi, PS)
        b.calc(ws, f"D{r}", mid or f"=AVERAGE(B{r}:C{r})", PS, name=f"FF_Mid_{i + 1}")
        b.calc(ws, f"E{r}", f"=C{r}-B{r}", PS)
        b.calc(ws, f"F{r}", f"=D{r}/Share_Price-1", PCT)
    cur = last + 2
    b.label(ws, f"A{cur}", "Current Share Price", bold=True)
    b.calc(ws, f"B{cur}", "=Share_Price", PS, bold=True)
    ch = BarChart()
    ch.type, ch.grouping, ch.overlap = "bar", "stacked", 100
    ch.title = "Value per Share ($): Low to High"
    ch.add_data(Reference(ws, min_col=2, min_row=4, max_row=last), titles_from_data=True)
    ch.add_data(Reference(ws, min_col=5, min_row=4, max_row=last), titles_from_data=True)
    ch.set_categories(Reference(ws, min_col=1, min_row=5, max_row=last))
    ch.series[0].graphicalProperties.noFill = True
    ch.series[0].graphicalProperties.line.noFill = True
    ch.legend = None
    ch.height, ch.width = 7 + len(rows) - 3, 18
    ws.add_chart(ch, f"A{cur + 3}")
    ws.freeze_panes = "B5"
    return last


GRID_TOPS = (4, 13)


def _sensitivity(b):
    ws = b.sheet("Sensitivity", "DDM Value per Share Sensitivities ($)",
                 "Live formulas: distributions do not depend on the cost of equity, so each cell re-discounts "
                 "the DDM sheet's distributions and terminal value at its own assumptions. Axes are the base "
                 "case plus or minus the steps on Inputs; the shaded centre is the base case.",
                 {"A": 40, **{c: 12 for c in "BCDEF"}})
    tce, ni = f"DDM!${LAST}${R['tce']}", f"DDM!${LAST}${R['ni']}"
    for top, title, centre, step, fmt, tv in [
        (GRID_TOPS[0], "Cost of Equity (Down) by Terminal P/TBV (Across), P/TBV Terminal Value", "Terminal_PTBV",
         "PTBV_Step", MULT2, lambda k, x: f"{x}*{tce}"),
        (GRID_TOPS[1], "Cost of Equity (Down) by Terminal Growth (Across), Gordon Growth Terminal Value",
         "Terminal_Growth", "G_Step", '0.00%', lambda k, x: f"({ni}*(1+{x})-{x}*{tce})/({k}-{x})"),
    ]:
        b.section(ws, top, title, 6)
        b.axis(ws, [f"{c}{top + 1}" for c in "BCDEF"], centre, step, fmt)
        b.axis(ws, [f"A{top + 2 + i}" for i in range(5)], "Cost_Of_Equity", "Ke_Step", PCT)
        for i in range(5):
            r = top + 2 + i
            for c in "BCDEF":
                k, x = f"$A{r}", f"{c}${top + 1}"
                pv = "+".join(f"DDM!${col}${R['div']}/(1+{k})^DDM!${col}$4" for col in COLS[1:])
                price = f"({pv}+{tv(k, x)}/(1+{k})^DDM!${LAST}$4)/Shares"
                b.calc(ws, f"{c}{r}", f'=IF({k}>{x},{price},"n/a")' if top == GRID_TOPS[1] else f"={price}", PS)
        b.base(ws, f"D{top + 4}")
    ws.freeze_panes = "B4"


def _checks(b, lay, last):
    def rng(key):
        return f"DDM!{COLS[1]}{R[key]}:{LAST}{R[key]}"

    b.checks_sheet([
        ("Football field: low is at most high for every method",
         f"MIN(Football_Field!E5:E{last})<-Check_Tol"),
        ("Distributions never negative", f"MIN({rng('div')})<-Check_Tol"),
        ("TCE never negative", f"MIN(DDM!B{R['tce']}:{LAST}{R['tce']})<0"),
        ("TCE roll-forward: opening plus net income less distributions equals ending",
         f"ABS(DDM!{LAST}{R['tce']}-(TCE+SUM({rng('ni')})-SUM({rng('div')})))>Check_Tol"),
        ("TCE to assets ratio between 0% and 100% every year",
         f"(MIN(DDM!B{R['ratio']}:{LAST}{R['ratio']})<=0)+(MAX(DDM!B{R['ratio']}:{LAST}{R['ratio']})>=1)>0"),
        ("Cost of equity exceeds terminal growth (Gordon growth is defined)", "Cost_Of_Equity<=Terminal_Growth"),
        ("Regression R squared between 0 and 1", "(Reg_RSQ<0)+(Reg_RSQ>1)>0"),
        ("P/TBV sensitivity grid centre matches the DDM value (grid wiring)",
         f"ABS(Sensitivity!D{GRID_TOPS[0] + 4}-DDM_Price_PTBV)>Check_Tol"),
        ("Gordon sensitivity grid centre matches the DDM value (grid wiring)",
         f"IF(Cost_Of_Equity>Terminal_Growth,ABS(Sensitivity!D{GRID_TOPS[1] + 4}-DDM_Price_Gordon)>Check_Tol,0)"),
    ] + (precedents.checks(lay) if lay else []))


def _summary(b, case):
    ws = b.sheet("Summary", "Bank Valuation Summary", "$ in millions except per share", {"A": 44, "B": 18, "C": 60})
    meta = case["meta"]
    ws["A3"] = meta.get("name", "Bank Case")
    ws["A3"].font = Font(bold=True, size=12)
    if meta.get("illustrative"):
        ws["A4"] = "ILLUSTRATIVE CASE: made-up bank and peers, not real companies, not market data."
        ws["A4"].font = Font(bold=True, color="C00000")
    elif meta.get("source"):
        ws["A4"] = "Sources: " + meta["source"]
    b.master_check(ws)
    b.header(ws, 6, ["Key Outputs", "Value"])
    items = [
        ("Current Share Price", "=Share_Price", PS),
        ("Tangible Book Value per Share", "=TBVPS", PS),
        ("Current P/TBV", "=Market_PTBV", MULT2),
        ("Current P/E (LTM, normalized)", "=Market_PE", MULT),
        ("Target ROTE (Core LTM)", "=Target_ROTE", PCT),
        ("Cost of Equity", "=Cost_Of_Equity", PCT),
        ("Regression R Squared", "=Reg_RSQ", '0.00'),
        ("Implied P/TBV (Regression)", "=Implied_PTBV", MULT2),
        ("Value per Share: P/TBV Regression", "=Price_PTBV", PS),
        ("Value per Share: P/E (LTM, normalized)", "=Price_PE", PS),
        ("Value per Share: DDM (Average)", "=DDM_Price_Mid", PS),
    ]
    for i, (label, formula, fmt) in enumerate(items):
        b.label(ws, f"A{7 + i}", label)
        b.calc(ws, f"B{7 + i}", formula, fmt, bold=label.startswith("Value"))
    r = 7 + len(items) + 1
    r = b.color_key(ws, r)
    b.header(ws, r, ["Sheets", "", ""])
    guide = [("Inputs", "All hard-coded assumptions and the peer set"),
             ("Comps", "Peer multiples, regression, P/TBV and P/E values"),
             ("DDM", "Capital-constrained distributions and discounted value"),
             ("Sensitivity", "DDM value per share grids, live formulas"),
             ("Football_Field", "Low to high value per share by method"),
             ("Checks", "Live integrity checks, 0 means OK")]
    if "precedents" in case:
        guide.insert(2, ("Precedents", "Bank deal multiples paid, recency filter and implied target value"))
    for i, (n, d) in enumerate(guide):
        b.label(ws, f"A{r + 1 + i}", n)
        b.label(ws, f"C{r + 1 + i}", d)


def build(case, path):
    b = Book()
    _summary(b, case)
    _inputs(b, case)
    _comps(b, case)
    lay = precedents.add_sheet(b, case["precedents"], "bank") if "precedents" in case else None
    _ddm(b)
    _sensitivity(b)
    last = _football(b, lay)
    _checks(b, lay, last)
    return b.save(path)
