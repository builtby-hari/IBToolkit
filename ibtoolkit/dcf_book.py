"""Writes the comps and DCF workbook: Summary, Inputs, Comps, DCF, Sensitivity, Football_Field.

Every calculated cell is a live formula. Hard-coded inputs live only on Inputs. The sensitivity
grids are live formulas (free cash flow does not depend on WACC, growth or the exit multiple), and
the football field DCF range reads them.
"""
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter as L

from . import precedents
from .comps import METRICS
from .dcf import STEPS
from .excel import MULT, PCT, Book
from .lbo import YEARS

MM = '$#,##0.0_);($#,##0.0);"-"_)'  # $ millions with one decimal
PX = '$#,##0.00_);($#,##0.00);"-"_)'  # per share
PCT2 = '0.00%'
NUM1 = '#,##0.0'
DF = '0.0000'
COLS = [L(i) for i in range(2, 2 + YEARS + 1)]  # B = LTM base, C..G = years 1..5

# Inputs: (name, label, (section, field), fmt)
SCALARS = [
    ("Net_Debt", "Target Net Debt", ("target", "net_debt"), MM),
    ("Diluted_Shares", "Target Diluted Shares (Millions)", ("target", "diluted_shares"), NUM1),
    ("Target_Rev_LTM", "Target LTM Revenue", ("target", "ltm_revenue"), MM),
    ("Target_Rev_NTM", "Target NTM Revenue", ("target", "ntm_revenue"), MM),
    ("Target_EBITDA_LTM", "Target LTM EBITDA", ("target", "ltm_ebitda"), MM),
    ("Target_EBITDA_NTM", "Target NTM EBITDA", ("target", "ntm_ebitda"), MM),
    ("Target_EPS_LTM", "Target LTM EPS", ("target", "ltm_eps"), PX),
    ("Target_EPS_NTM", "Target NTM EPS", ("target", "ntm_eps"), PX),
    ("DA_Pct", "D&A (% of Revenue)", ("dcf", "da_pct_revenue"), PCT),
    ("Capex_Pct", "Capex (% of Revenue)", ("dcf", "capex_pct_revenue"), PCT),
    ("NWC_Pct", "NWC Investment (% of Change in Revenue)", ("dcf", "nwc_pct_revenue_change"), PCT),
    ("Tax_Rate", "Tax Rate", ("dcf", "tax_rate"), PCT),
    ("Risk_Free", "Risk-Free Rate", ("dcf", "risk_free"), PCT2),
    ("Equity_Risk_Premium", "Equity Risk Premium", ("dcf", "equity_risk_premium"), PCT2),
    ("Equity_Beta", "Equity Beta", ("dcf", "beta"), '0.00'),
    ("Pre_Tax_Kd", "Pre-Tax Cost of Debt", ("dcf", "pre_tax_cost_of_debt"), PCT2),
    ("Debt_Weight", "Target Debt / Total Capital", ("dcf", "debt_to_capital"), PCT),
    ("Terminal_Growth", "Terminal Growth Rate", ("dcf", "terminal_growth"), PCT2),
    ("Exit_Multiple", "Exit Multiple (x Year 5 EBITDA)", ("dcf", "exit_multiple"), MULT),
    ("Mid_Year", "Mid-Year Convention (1 = On, 0 = Off)", ("dcf", "mid_year"), '0'),
    ("WACC_Step", "Sensitivity Step: WACC", ("steps", "wacc"), PCT2),
    ("G_Step", "Sensitivity Step: Terminal Growth", ("steps", "g"), PCT2),
    ("XM_Step", "Sensitivity Step: Exit Multiple (x)", ("steps", "mult"), MULT),
]
SERIES = [("growth", "Revenue Growth", "revenue_growth"), ("margin", "EBITDA Margin", "ebitda_margin")]
PEER_FIELDS = [("price", "Share Price", PX), ("shares", "Diluted Shares (M)", NUM1),
               ("net_debt", "Net Debt", MM), ("revenue_ltm", "LTM Revenue", MM),
               ("revenue_ntm", "NTM Revenue", MM), ("ebitda_ltm", "LTM EBITDA", MM),
               ("ebitda_ntm", "NTM EBITDA", MM), ("eps_ltm", "LTM EPS", PX), ("eps_ntm", "NTM EPS", PX)]
IN_FIRST = 5
IN_ROW = {s[0]: IN_FIRST + i for i, s in enumerate(SCALARS)}
IN_SERIES = IN_FIRST + len(SCALARS) + 1
IN_SROW = {s[0]: IN_SERIES + 1 + i for i, s in enumerate(SERIES)}
IN_PEER_HDR = IN_SERIES + len(SERIES) + 2
IN_PEER_FIRST = IN_PEER_HDR + 1

# DCF sheet rows
R = {}


def f(key, c):
    return f"{c}{R[key]}"


def _spec():
    return [
        ("sec", "Free Cash Flow Build"),
        ("rev", "Revenue", MM, lambda: "=Target_Rev_LTM",
         lambda c, p: f"={f('rev', p)}*(1+{f('growth', c)})", True),
        ("growth", "Revenue Growth", PCT, None, lambda c, p: f"=Inputs!{c}{IN_SROW['growth']}", False),
        ("ebitda", "EBITDA", MM, lambda: "=Target_EBITDA_LTM",
         lambda c, p: f"={f('rev', c)}*{f('margin', c)}", True),
        ("margin", "EBITDA Margin", PCT, lambda: f"={f('ebitda', 'B')}/{f('rev', 'B')}",
         lambda c, p: f"=Inputs!{c}{IN_SROW['margin']}", False),
        ("da", "Less: D&A", MM, None, lambda c, p: f"={f('rev', c)}*DA_Pct", False),
        ("ebit", "EBIT", MM, None, lambda c, p: f"={f('ebitda', c)}-{f('da', c)}", False),
        ("tax", "Less: Taxes on EBIT", MM, None,
         lambda c, p: f"=MAX(0,{f('ebit', c)})*Tax_Rate", False),
        ("nopat", "NOPAT", MM, None, lambda c, p: f"={f('ebit', c)}-{f('tax', c)}", False),
        ("plus_da", "Plus: D&A", MM, None, lambda c, p: f"={f('da', c)}", False),
        ("capex", "Less: Capex", MM, None, lambda c, p: f"={f('rev', c)}*Capex_Pct", False),
        ("dnwc", "Less: Increase in NWC", MM, None,
         lambda c, p: f"=NWC_Pct*({f('rev', c)}-{f('rev', p)})", False),
        ("ufcf", "Unlevered Free Cash Flow", MM, None,
         lambda c, p: (f"={f('nopat', c)}+{f('plus_da', c)}-{f('capex', c)}-{f('dnwc', c)}"), True),
        ("sec", "Discounting"),
        ("period", "Discount Period (Years)", '0.00', None,
         lambda c, p: f"={c}$4-0.5*Mid_Year", False),
        ("df", "Discount Factor", DF, None, lambda c, p: f"=1/(1+WACC)^{f('period', c)}", False),
        ("pv", "PV of Unlevered Free Cash Flow", MM, None,
         lambda c, p: f"={f('ufcf', c)}*{f('df', c)}", True),
    ]


_row = 5
for _s in _spec():
    if _s[0] != "sec":
        R[_s[0]] = _row
    _row += 1
SPEC = _spec()
MODEL_KEYS = list(R)

# Cost of capital block, then valuation block, below the projection.
W0 = _row + 1
WR = {k: W0 + 1 + i for i, k in enumerate(
    ["rf", "beta", "erp", "ke", "kd", "tax", "kd_at", "wd", "we", "wacc"])}
V0 = W0 + len(WR) + 2
VR = {k: V0 + 1 + i for i, k in enumerate(
    ["fcf", "ebitda", "inp", "tv", "per", "pv_tv", "sum_pv", "ev", "net_debt", "eq", "shares",
     "price", "tv_pct", "sec", "imp_mult", "imp_g"])}


def _inputs(b, case):
    ws = b.sheet("Inputs", "Inputs", "Blue cells are hard-coded inputs from the case file. $ in millions "
                 "except per-share figures.", {"A": 56, **{c: 14 for c in "BCDEFGHIJ"}})
    b.header(ws, 4, ["Input", "Value"])
    for name, label, (sec, field), fmt in SCALARS:
        r = IN_ROW[name]
        v = STEPS[field] if sec == "steps" else case[sec][field]
        b.label(ws, f"A{r}", label)
        b.inp(ws, f"B{r}", int(v) if name == "Mid_Year" else v, fmt, name=name)
    b.header(ws, IN_SERIES, ["Time Series Inputs", ""] + list(range(1, YEARS + 1)))
    for key, label, field in SERIES:
        r = IN_SROW[key]
        b.label(ws, f"A{r}", label)
        for i, v in enumerate(case["dcf"][field]):
            b.inp(ws, f"{COLS[i + 1]}{r}", v, PCT)
    b.header(ws, IN_PEER_HDR, ["Peer Inputs"] + [lab for _, lab, _ in PEER_FIELDS])
    for i, p in enumerate(case["peers"]):
        r = IN_PEER_FIRST + i
        b.label(ws, f"A{r}", p["name"])
        for j, (field, _, fmt) in enumerate(PEER_FIELDS):
            b.inp(ws, f"{L(2 + j)}{r}", p[field], fmt)
    ws.freeze_panes = "B5"


# Comps sheet columns
CC = dict(price="B", shares="C", mcap="D", net_debt="E", ev="F", revenue_ltm="G", revenue_ntm="H",
          ebitda_ltm="I", ebitda_ntm="J", eps_ltm="K", eps_ntm="L")
MCOL = {m[0]: L(13 + i) for i, m in enumerate(METRICS)}  # M..R
STAT_LABELS = [("mean", "Mean"), ("median", "Median"), ("p25", "25th Percentile"), ("p75", "75th Percentile")]


def comps_rows(n):
    """Row numbers on the Comps sheet for n peers."""
    first, last = 5, 4 + n
    st = {k: last + 2 + i for i, (k, _) in enumerate(STAT_LABELS)}
    imp0 = last + 2 + len(STAT_LABELS) + 2
    return dict(first=first, last=last, stat=st, imp_hdr=imp0,
                imp={m[0]: imp0 + 1 + i for i, m in enumerate(METRICS)})


def _comps(b, case):
    n = len(case["peers"])
    cr = comps_rows(n)
    ws = b.sheet("Comps", "Trading Comparables",
                 "$ in millions except per-share figures. Enterprise value = market cap + net debt.",
                 {"A": 30, **{L(i): 12 for i in range(2, 19)}})
    heads = ["Company", "Share Price", "Diluted Shares (M)", "Market Cap", "Net Debt", "Enterprise Value",
             "LTM Revenue", "NTM Revenue", "LTM EBITDA", "NTM EBITDA", "LTM EPS", "NTM EPS"]
    b.header(ws, 4, heads + [m[1] for m in METRICS])
    fmts = {"price": PX, "shares": NUM1, "net_debt": MM, "eps_ltm": PX, "eps_ntm": PX}
    for i in range(n):
        r, ir = cr["first"] + i, IN_PEER_FIRST + i
        b.calc(ws, f"A{r}", f"=Inputs!A{ir}", "General").alignment = Alignment(horizontal="left")
        for j, (field, _, _) in enumerate(PEER_FIELDS):
            b.calc(ws, f"{CC[field]}{r}", f"=Inputs!{L(2 + j)}{ir}", fmts.get(field, MM))
        b.calc(ws, f"D{r}", f"=B{r}*C{r}", MM)
        b.calc(ws, f"F{r}", f"=D{r}+E{r}", MM)
        for key, _, kind, pfield, _ in METRICS:
            den = f"{CC[pfield]}{r}"
            b.calc(ws, f"{MCOL[key]}{r}", f"=B{r}/{den}" if kind == "pe" else f"=F{r}/{den}", MULT)
    q = {"mean": "AVERAGE({})", "median": "MEDIAN({})",
         "p25": "PERCENTILE({},0.25)", "p75": "PERCENTILE({},0.75)"}
    for k, label in STAT_LABELS:
        r = cr["stat"][k]
        b.label(ws, f"A{r}", label, bold=True)
        for key, *_ in METRICS:
            c = MCOL[key]
            b.calc(ws, f"{c}{r}", "=" + q[k].format(f"{c}{cr['first']}:{c}{cr['last']}"), MULT,
                   bold=True, total=(k == "mean"))
    h = cr["imp_hdr"]
    b.section(ws, h - 1, "Implied Target Valuation (25th Percentile, Median, 75th Percentile)", 14)
    b.header(ws, h, ["Method", "Target Metric", "Multiple: 25th", "Multiple: Median", "Multiple: 75th",
                     "EV: 25th", "EV: Median", "EV: 75th", "Equity: 25th", "Equity: Median",
                     "Equity: 75th", "Price: 25th", "Price: Median", "Price: 75th"])
    for key, label, kind, _, tfield in METRICS:
        r, mc = cr["imp"][key], MCOL[key]
        b.label(ws, f"A{r}", label)
        tname = {"ltm_revenue": "Target_Rev_LTM", "ntm_revenue": "Target_Rev_NTM",
                 "ltm_ebitda": "Target_EBITDA_LTM", "ntm_ebitda": "Target_EBITDA_NTM",
                 "ltm_eps": "Target_EPS_LTM", "ntm_eps": "Target_EPS_NTM"}[tfield]
        b.calc(ws, f"B{r}", f"={tname}", PX if kind == "pe" else MM)
        for k, stat in enumerate(("p25", "median", "p75")):
            mult, ev, eq, px = "CDE"[k], "FGH"[k], "IJK"[k], "LMN"[k]
            b.calc(ws, f"{mult}{r}", f"={mc}{cr['stat'][stat]}", MULT)
            if kind == "ev":
                b.calc(ws, f"{ev}{r}", f"={mult}{r}*$B{r}", MM)
                b.calc(ws, f"{eq}{r}", f"={ev}{r}-Net_Debt", MM)
                b.calc(ws, f"{px}{r}", f"={eq}{r}/Diluted_Shares", PX, bold=True)
            else:
                b.calc(ws, f"{px}{r}", f"={mult}{r}*$B{r}", PX, bold=True)
                b.calc(ws, f"{eq}{r}", f"={px}{r}*Diluted_Shares", MM)
                b.calc(ws, f"{ev}{r}", f"={eq}{r}+Net_Debt", MM)
    ws.freeze_panes = "B5"


def _dcf(b):
    ws = b.sheet("DCF", "Discounted Cash Flow",
                 "$ in millions except per-share figures. Five-year unlevered free cash flow, two terminal value methods.",
                 {"A": 52, **{c: 16 for c in COLS}})
    b.header(ws, 4, ["", *range(0, YEARS + 1)])
    ws["B4"].number_format = '"LTM"'
    row = 5
    for s in SPEC:
        if s[0] == "sec":
            b.section(ws, row, s[1], len(COLS) + 1)
        else:
            key, label, fmt, close, yr, bold = s
            b.label(ws, f"A{row}", label, bold=bold, indent=0 if bold else 1)
            if close:
                b.calc(ws, f"B{row}", close(), fmt, bold=bold)
            for i in range(1, YEARS + 1):
                b.calc(ws, f"{COLS[i]}{row}", yr(COLS[i], COLS[i - 1]), fmt, bold=bold,
                       total=(key == "ufcf"))
        row += 1
    b.section(ws, W0, "Cost of Capital (CAPM and Target Capital Structure)", len(COLS) + 1)
    w = WR
    for k, label, formula, fmt, name in [
        ("rf", "Risk-Free Rate", "=Risk_Free", PCT2, None),
        ("beta", "Equity Beta", "=Equity_Beta", '0.00', None),
        ("erp", "Equity Risk Premium", "=Equity_Risk_Premium", PCT2, None),
        ("ke", "Cost of Equity (Risk-Free + Beta x ERP)", f"=B{w['rf']}+B{w['beta']}*B{w['erp']}", PCT2,
         "Cost_of_Equity"),
        ("kd", "Pre-Tax Cost of Debt", "=Pre_Tax_Kd", PCT2, None),
        ("tax", "Tax Rate", "=Tax_Rate", PCT, None),
        ("kd_at", "After-Tax Cost of Debt", f"=B{w['kd']}*(1-B{w['tax']})", PCT2, "After_Tax_Kd"),
        ("wd", "Debt / Total Capital (Target)", "=Debt_Weight", PCT, None),
        ("we", "Equity / Total Capital", f"=1-B{w['wd']}", PCT, None),
        ("wacc", "WACC", f"=B{w['we']}*B{w['ke']}+B{w['wd']}*B{w['kd_at']}", PCT2, "WACC"),
    ]:
        b.label(ws, f"A{w[k]}", label, bold=(k == "wacc"), indent=0 if k == "wacc" else 1)
        b.calc(ws, f"B{w[k]}", formula, fmt, name=name, bold=(k == "wacc"), total=(k == "wacc"))

    v = VR
    b.header(ws, V0, ["Terminal Value and Valuation", "Gordon Growth", "Exit Multiple"])
    last = COLS[-1]
    half = "(1+WACC)^(0.5*Mid_Year)"
    rows = [
        ("fcf", "Terminal-Year Unlevered Free Cash Flow", f"={last}{R['ufcf']}", f"={last}{R['ufcf']}", MM, None),
        ("ebitda", "Terminal-Year EBITDA", f"={last}{R['ebitda']}", f"={last}{R['ebitda']}", MM, None),
        ("tv", "Terminal Value (Undiscounted)",
         f"=B{v['fcf']}*(1+B{v['inp']})/(WACC-B{v['inp']})", f"=C{v['inp']}*C{v['ebitda']}", MM,
         ("TV_Gordon", "TV_Exit")),
        ("per", "Discount Period for Terminal Value (Years)", f"={last}$4-0.5*Mid_Year", f"={last}$4", '0.00', None),
        ("pv_tv", "PV of Terminal Value", f"=B{v['tv']}/(1+WACC)^B{v['per']}",
         f"=C{v['tv']}/(1+WACC)^C{v['per']}", MM, None),
        ("sum_pv", "Sum of PV of Unlevered Free Cash Flow", f"=SUM(C{R['pv']}:{last}{R['pv']})",
         f"=SUM(C{R['pv']}:{last}{R['pv']})", MM, ("Sum_PV_UFCF", None)),
        ("ev", "Enterprise Value", f"=B{v['sum_pv']}+B{v['pv_tv']}", f"=C{v['sum_pv']}+C{v['pv_tv']}", MM,
         ("EV_Gordon", "EV_Exit")),
        ("net_debt", "Less: Net Debt", "=Net_Debt", "=Net_Debt", MM, None),
        ("eq", "Equity Value", f"=B{v['ev']}-B{v['net_debt']}", f"=C{v['ev']}-C{v['net_debt']}", MM,
         ("Equity_Gordon", "Equity_Exit")),
        ("shares", "Diluted Shares (Millions)", "=Diluted_Shares", "=Diluted_Shares", NUM1, None),
        ("price", "Implied Share Price", f"=B{v['eq']}/B{v['shares']}", f"=C{v['eq']}/C{v['shares']}", PX,
         ("Price_Gordon", "Price_Exit")),
        ("tv_pct", "PV of Terminal Value as % of Enterprise Value", f"=B{v['pv_tv']}/B{v['ev']}",
         f"=C{v['pv_tv']}/C{v['ev']}", PCT, ("TV_Pct_EV_Gordon", "TV_Pct_EV_Exit")),
        ("imp_mult", "Implied Exit Multiple (x Year 5 EBITDA, Year-End Basis)",
         f"=B{v['tv']}*{half}/B{v['ebitda']}", f"=C{v['inp']}", MULT, ("Implied_Exit_Multiple", None)),
        ("imp_g", "Implied Perpetuity Growth Rate",
         f"=B{v['inp']}",
         f"=(C{v['tv']}/{half}*WACC-C{v['fcf']})/(C{v['tv']}/{half}+C{v['fcf']})", PCT2,
         (None, "Implied_Growth")),
    ]
    b.label(ws, f"A{v['inp']}", "Terminal Growth Rate (Gordon) / Exit Multiple", indent=1)
    b.calc(ws, f"B{v['inp']}", "=Terminal_Growth", PCT2)
    b.calc(ws, f"C{v['inp']}", "=Exit_Multiple", MULT)
    b.section(ws, v["sec"], "Cross-Checks", 3)
    for key, label, fb, fc, fmt, names in rows:
        r = v[key]
        bold = key in ("ev", "eq", "price")
        b.label(ws, f"A{r}", label, bold=bold, indent=0 if bold else 1)
        nb, nc = names or (None, None)
        b.calc(ws, f"B{r}", fb, fmt, name=nb, bold=bold, total=(key in ("ev", "eq", "price")))
        b.calc(ws, f"C{r}", fc, fmt, name=nc, bold=bold, total=(key in ("ev", "eq", "price")))
    ws.freeze_panes = "B5"


GRID_TOPS = (4, 13)


def _sensitivity(b):
    ws = b.sheet("Sensitivity", "Implied Share Price Sensitivities",
                 "Live formulas: each cell re-discounts the DCF sheet's free cash flow at its own WACC and "
                 "terminal assumption. Axes are the base case plus or minus the steps on Inputs; the shaded "
                 "centre is the base case.",
                 {"A": 40, **{c: 12 for c in "BCDEF"}})
    ufcf, per, last = R["ufcf"], R["period"], COLS[-1]
    for top, title, centre, step, fmt, tv in [
        (GRID_TOPS[0], "WACC (Down) by Terminal Growth (Across), Gordon Growth Method", "Terminal_Growth",
         "G_Step", PCT2, lambda w, x: f"DCF!${last}${ufcf}*(1+{x})/({w}-{x})/(1+{w})^DCF!$B${VR['per']}"),
        (GRID_TOPS[1], "WACC (Down) by Exit Multiple (Across), Exit Multiple Method", "Exit_Multiple",
         "XM_Step", MULT, lambda w, x: f"{x}*DCF!${last}${R['ebitda']}/(1+{w})^DCF!$C${VR['per']}"),
    ]:
        b.section(ws, top, title, 6)
        b.axis(ws, [f"{c}{top + 1}" for c in "BCDEF"], centre, step, fmt)
        b.axis(ws, [f"A{top + 2 + i}" for i in range(5)], "WACC", "WACC_Step", PCT2)
        for i in range(5):
            r = top + 2 + i
            for c in "BCDEF":
                w, x = f"$A{r}", f"{c}${top + 1}"
                pv = "+".join(f"DCF!${k}${ufcf}/(1+{w})^DCF!${k}${per}" for k in COLS[1:])
                price = f"({pv}+{tv(w, x)}-Net_Debt)/Diluted_Shares"
                # Gordon growth needs WACC above growth; the exit multiple method always prices.
                b.calc(ws, f"{c}{r}", f'=IF({w}>{x},{price},"n/a")' if top == GRID_TOPS[0] else f"={price}", PX)
        b.base(ws, f"D{top + 4}")
    ws.freeze_panes = "B4"


def grid_range(top):
    return f"Sensitivity!B{top + 2}:F{top + 6}"


def _football(b, case, lay):
    cr = comps_rows(len(case["peers"]))
    ws = b.sheet("Football_Field", "Football Field: Implied Share Price",
                 "Comps ranges run from the 25th to the 75th percentile multiple. DCF ranges are the low and "
                 "high of the live Sensitivity grids; the midpoint is the base case.",
                 {"A": 44, "B": 14, "C": 14, "D": 14, "E": 14})
    b.header(ws, 4, ["Method", "Low", "Midpoint", "High", "Spread"])
    rows = [(f"Comps: {m[1]}", f"=Comps!L{cr['imp'][m[0]]}", f"=Comps!M{cr['imp'][m[0]]}",
             f"=Comps!N{cr['imp'][m[0]]}") for m in METRICS]
    rows += [("DCF: Gordon Growth (WACC x Growth)", f"=MIN({grid_range(GRID_TOPS[0])})", "=Price_Gordon",
              f"=MAX({grid_range(GRID_TOPS[0])})"),
             ("DCF: Exit Multiple (WACC x Multiple)", f"=MIN({grid_range(GRID_TOPS[1])})", "=Price_Exit",
              f"=MAX({grid_range(GRID_TOPS[1])})")]
    if lay:
        rows += precedents.football_rows(lay)
    for i, (label, lo, mid, hi) in enumerate(rows):
        r = 5 + i
        b.label(ws, f"A{r}", label)
        b.calc(ws, f"B{r}", lo, PX)
        b.calc(ws, f"C{r}", mid, PX)
        b.calc(ws, f"D{r}", hi, PX)
        b.calc(ws, f"E{r}", f"=D{r}-B{r}", PX)
    last = 4 + len(rows)
    ch = BarChart()
    ch.type, ch.grouping, ch.overlap = "bar", "stacked", 100
    ch.title = "Implied Share Price Range ($)"
    ch.add_data(Reference(ws, min_col=2, min_row=4, max_row=last), titles_from_data=True)
    ch.add_data(Reference(ws, min_col=5, min_row=4, max_row=last), titles_from_data=True)
    ch.set_categories(Reference(ws, min_col=1, min_row=5, max_row=last))
    ch.series[0].graphicalProperties.noFill = True  # invisible base so the bar floats from Low to High
    ch.series[0].graphicalProperties.line.noFill = True
    ch.series[1].graphicalProperties.solidFill = "1F3864"
    ch.legend = None
    ch.x_axis.scaling.orientation = "maxMin"
    ch.x_axis.delete = ch.y_axis.delete = False
    ch.width, ch.height = 24, 11
    ws.add_chart(ch, f"A{last + 3}")
    ws.freeze_panes = "B5"
    return last


def _checks(b, case, lay, last):
    v, w = VR, WR
    g0, g1 = GRID_TOPS
    b.checks_sheet([
        ("Football field: low is at most high for every method", f"MIN(Football_Field!E5:E{last})<-Check_Tol"),
        ("WACC exceeds terminal growth (Gordon growth is defined)", "WACC<=Terminal_Growth"),
        ("Capital structure weights sum to 100%", f"ABS(DCF!B{w['we']}+DCF!B{w['wd']}-1)>Check_Tol"),
        ("Equity bridge ties, Gordon: equity plus net debt equals enterprise value",
         "ABS(Equity_Gordon+Net_Debt-EV_Gordon)>Check_Tol"),
        ("Equity bridge ties, exit multiple: equity plus net debt equals enterprise value",
         "ABS(Equity_Exit+Net_Debt-EV_Exit)>Check_Tol"),
        ("Gordon sensitivity grid centre matches the DCF price (grid wiring)",
         f"IF(WACC>Terminal_Growth,ABS(Sensitivity!D{g0 + 4}-Price_Gordon)>Check_Tol,0)"),
        ("Exit multiple sensitivity grid centre matches the DCF price (grid wiring)",
         f"ABS(Sensitivity!D{g1 + 4}-Price_Exit)>Check_Tol"),
    ] + (precedents.checks(lay) if lay else []))


def _summary(b, case):
    cr = comps_rows(len(case["peers"]))
    ws = b.sheet("Summary", "Trading Comps and DCF Summary", "$ in millions except per-share figures",
                 {"A": 46, "B": 18, "C": 60})
    meta = case["meta"]
    ws["A3"] = meta.get("name", "Comps and DCF Case")
    ws["A3"].font = Font(bold=True, size=12)
    if meta.get("illustrative"):
        ws["A4"] = "ILLUSTRATIVE CASE: made-up companies and round numbers, not market data."
        ws["A4"].font = Font(bold=True, color="C00000")
    b.master_check(ws)
    b.header(ws, 6, ["Key Outputs", "Value"])
    med = cr["imp"]["ev_ebitda_ntm"]
    items = [
        ("WACC", "=WACC", PCT2),
        ("Mid-Year Convention (1 = On)", "=Mid_Year", '0'),
        ("DCF Share Price: Gordon Growth", "=Price_Gordon", PX),
        ("DCF Share Price: Exit Multiple", "=Price_Exit", PX),
        ("PV of Terminal Value % of EV (Gordon)", "=TV_Pct_EV_Gordon", PCT),
        ("Implied Exit Multiple from Gordon Growth", "=Implied_Exit_Multiple", MULT),
        ("Implied Perpetuity Growth from Exit Multiple", "=Implied_Growth", PCT2),
        ("Comps Median EV / EBITDA (NTM)", f"=Comps!D{med}", MULT),
        ("Comps Implied Share Price at Median EV / EBITDA (NTM)", f"=Comps!M{med}", PX),
    ]
    for i, (label, formula, fmt) in enumerate(items):
        b.label(ws, f"A{7 + i}", label)
        b.calc(ws, f"B{7 + i}", formula, fmt, bold=label.startswith("DCF Share"))
    r = 7 + len(items) + 1
    r = b.color_key(ws, r)
    b.header(ws, r, ["Sheets", "", ""])
    guide = [("Inputs", "All hard-coded assumptions and peer data"),
             ("Comps", "Peer multiples, statistics and implied target valuation"),
             ("DCF", "Free cash flow build, WACC, terminal value, equity bridge"),
             ("Sensitivity", "Share price grids, live formulas"),
             ("Football_Field", "Comps and DCF ranges side by side"),
             ("Checks", "Live integrity checks, 0 means OK")]
    if "precedents" in case:
        guide.insert(2, ("Precedents", "Precedent deal multiples, recency filter and implied target value"))
    for i, (n, d) in enumerate(guide):
        b.label(ws, f"A{r + 1 + i}", n)
        b.label(ws, f"C{r + 1 + i}", d)


def build(case, path):
    b = Book()
    _summary(b, case)
    _inputs(b, case)
    _comps(b, case)
    lay = precedents.add_sheet(b, case["precedents"], "corporate") if "precedents" in case else None
    _dcf(b)
    _sensitivity(b)
    last = _football(b, case, lay)
    _checks(b, case, lay, last)
    return b.save(path)
