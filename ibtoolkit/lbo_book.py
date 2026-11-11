"""Writes the LBO workbook: Summary, Inputs, Sources_Uses, Model, Returns, Sensitivity.

Every calculated cell is a live formula. Hard-coded inputs live only on Inputs.
"""
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter as L

from .excel import MULT, MULT2, PCT, USD, Book
from .lbo import YEARS, sensitivities

PASS = '[=1]"Pass";[=0]"Fail"'


COLS = [L(i) for i in range(2, 2 + YEARS + 1)]  # B = close, C..G = years 1..5

# Inputs: (name, label, (section, field), fmt)
SCALARS = [
    ("LTM_Revenue", "LTM Revenue", ("transaction", "ltm_revenue"), USD),
    ("LTM_EBITDA", "LTM EBITDA", ("transaction", "ltm_ebitda"), USD),
    ("Entry_Multiple", "Entry Multiple (x LTM EBITDA)", ("transaction", "entry_multiple"), MULT),
    ("Exit_Multiple", "Exit Multiple (x Year 5 EBITDA)", ("transaction", "exit_multiple"), MULT),
    ("Advisory_Fee_Pct", "Advisory Fees (% of Purchase Price)", ("transaction", "advisory_fee_pct"), PCT),
    ("Financing_Fee_Pct", "Financing Fees (% of Funded Debt plus Revolver Commitment)", ("transaction", "financing_fee_pct"), PCT),
    ("Fee_Years", "Financing Fee Amortization Period (Years)", ("transaction", "financing_fee_years"), '0.0'),
    ("Cash_To_BS", "Cash to Balance Sheet at Close", ("transaction", "cash_at_close"), USD),
    ("Mgmt_Rollover", "Management Rollover (% of Total Equity, Pro Rata With Sponsor)", ("transaction", "mgmt_rollover_pct"), PCT),
    ("Option_Pool", "Management Option Pool (% of Exit Equity)", ("transaction", "option_pool_pct"), PCT),
    ("DA_Pct", "D&A (% of Revenue)", ("operating", "da_pct_revenue"), PCT),
    ("Capex_Pct", "Capex (% of Revenue)", ("operating", "capex_pct_revenue"), PCT),
    ("NWC_Pct", "NWC Investment (% of Change in Revenue)", ("operating", "nwc_pct_revenue_change"), PCT),
    ("Tax_Rate", "Cash Tax Rate", ("operating", "tax_rate"), PCT),
    ("Senior_Leverage", "Senior Term Loan (x LTM EBITDA)", ("senior", "leverage"), MULT),
    ("Senior_Rate", "Senior Interest Rate", ("senior", "rate"), PCT),
    ("Senior_Amort_Pct", "Senior Mandatory Amortization (% of Original per Year)", ("senior", "amort_pct"), PCT),
    ("Sweep_Pct", "Cash Sweep (% of Excess Cash Flow)", ("senior", "sweep_pct"), PCT),
    ("Mezz_Leverage", "Mezzanine Notes (x LTM EBITDA)", ("mezz", "leverage"), MULT),
    ("Mezz_Cash_Rate", "Mezzanine Cash Interest Rate", ("mezz", "cash_rate"), PCT),
    ("Mezz_PIK_Rate", "Mezzanine PIK Interest Rate", ("mezz", "pik_rate"), PCT),
    ("Revolver_Commit", "Revolver Commitment (Undrawn at Close)", ("revolver", "commitment"), USD),
    ("Revolver_Rate", "Revolver Interest Rate (on Beginning Drawn Balance)", ("revolver", "rate"), PCT),
    ("Revolver_Fee", "Revolver Undrawn Fee (on Beginning Undrawn Commitment)", ("revolver", "undrawn_fee"), '0.00%'),
    ("Min_Cash_Balance", "Minimum Cash Balance (Revolver Draws Below This)", ("revolver", "min_cash"), USD),
    ("Mult_Step", "Sensitivity Step for Entry and Exit Multiples (x)", ("sensitivity", "multiple_step"), MULT),
]
SERIES = [
    ("growth", "Revenue Growth", ("operating", "revenue_growth"), PCT),
    ("margin", "EBITDA Margin", ("operating", "ebitda_margin"), PCT),
    ("cov_lev", "Covenant: Maximum Total Debt / EBITDA", ("covenants", "max_total_leverage"), MULT2),
    ("cov_cov", "Covenant: Minimum EBITDA / Cash Interest", ("covenants", "min_interest_coverage"), MULT2),
]
IN_FIRST = 5
IN_ROW = {s[0]: IN_FIRST + i for i, s in enumerate(SCALARS)}
IN_SERIES = IN_FIRST + len(SCALARS) + 2
IN_SROW = {s[0]: IN_SERIES + 1 + i for i, s in enumerate(SERIES)}

# Model rows. ("sec", label) or (key, label, fmt, close_formula, year_formula, bold).
# Formulas are functions of (c, p): current and previous column letters.
R = {}


def _f(key, c):
    return f"{c}{R[key]}"


def ci(c):
    """Cash interest expression for column c: senior, mezzanine cash, revolver interest and fee."""
    return f"({_f('s_int', c)}+{_f('m_cash', c)}+{_f('r_int', c)}+{_f('r_fee', c)})"


def _spec():
    f = _f
    return [
        ("sec", "Operating Build"),
        ("rev", "Revenue", USD, lambda: "=LTM_Revenue",
         lambda c, p: f"={f('rev', p)}*(1+Inputs!{c}{IN_SROW['growth']})", True),
        ("ebitda", "EBITDA", USD, lambda: "=LTM_EBITDA",
         lambda c, p: f"={f('rev', c)}*Inputs!{c}{IN_SROW['margin']}", True),
        ("margin", "EBITDA Margin", PCT, lambda: f"={f('ebitda', 'B')}/{f('rev', 'B')}",
         lambda c, p: f"={f('ebitda', c)}/{f('rev', c)}", False),
        ("da", "Less: D&A", USD, None, lambda c, p: f"={f('rev', c)}*DA_Pct", False),
        ("ebit", "EBIT", USD, None, lambda c, p: f"={f('ebitda', c)}-{f('da', c)}", False),
        ("capex", "Less: Capex", USD, None, lambda c, p: f"={f('rev', c)}*Capex_Pct", False),
        ("dnwc", "Less: Increase in NWC", USD, None,
         lambda c, p: f"=NWC_Pct*({f('rev', c)}-{f('rev', p)})", False),
        ("sec", "Taxes and Free Cash Flow"),
        ("ebt", "Pre-Tax Income", USD, None,
         lambda c, p: (f"={f('ebit', c)}-{f('fee_amort', c)}-{f('s_int', c)}-{f('m_cash', c)}"
                       f"-{f('m_pik', c)}-{f('r_int', c)}-{f('r_fee', c)}"), False),
        ("tax", "Less: Cash Taxes", USD, None,
         lambda c, p: f"=MAX(0,{f('ebt', c)})*Tax_Rate", False),
        ("ni", "Net Income", USD, None, lambda c, p: f"={f('ebt', c)}-{f('tax', c)}", False),
        ("fcf", "Free Cash Flow Before Debt Repayment", USD, None,
         lambda c, p: (f"={f('ebitda', c)}-{f('s_int', c)}-{f('m_cash', c)}-{f('r_int', c)}-{f('r_fee', c)}"
                       f"-{f('tax', c)}-{f('capex', c)}-{f('dnwc', c)}"), True),
        ("cash_end", "Ending Cash Balance", USD, lambda: "=Cash_To_BS",
         lambda c, p: (f"={f('cash_pre', c)}-{f('s_sweep', c)}+{f('r_draw', c)}-{f('r_repay', c)}"), True),
        ("sec", "Senior Term Loan"),
        ("s_beg", "Beginning Balance", USD, None, lambda c, p: f"={f('s_end', p)}", False),
        ("s_int", "Interest (on Beginning Balance)", USD, None,
         lambda c, p: f"={f('s_beg', c)}*Senior_Rate", False),
        ("s_mand", "Less: Mandatory Amortization", USD, None,
         lambda c, p: f"=MIN({f('s_beg', c)},Senior_Amort_Pct*Senior_Debt_0)", False),
        ("s_sweep", "Less: Cash Sweep", USD, None,
         lambda c, p: (f"=MIN({f('s_beg', c)}-{f('s_mand', c)},"
                       f"Sweep_Pct*MAX(0,{f('fcf', c)}-{f('s_mand', c)}-{f('r_repay', c)}),"
                       f"MAX(0,{f('cash_pre', c)}-{f('r_repay', c)}-Min_Cash_Balance))"), False),
        ("s_end", "Ending Balance", USD, lambda: "=Senior_Debt_0",
         lambda c, p: f"={f('s_beg', c)}-{f('s_mand', c)}-{f('s_sweep', c)}", True),
        ("sec", "Revolver"),
        ("r_beg", "Beginning Balance", USD, None, lambda c, p: f"={f('r_end', p)}", False),
        ("r_int", "Interest (on Beginning Balance)", USD, None,
         lambda c, p: f"={f('r_beg', c)}*Revolver_Rate", False),
        ("r_fee", "Undrawn Fee (on Beginning Undrawn Commitment)", USD, None,
         lambda c, p: f"=(Revolver_Commit-{f('r_beg', c)})*Revolver_Fee", False),
        ("cash_pre", "Cash Before Revolver (After Mandatory Amortization)", USD, None,
         lambda c, p: f"={f('cash_end', p)}+{f('fcf', c)}-{f('s_mand', c)}", False),
        ("r_draw", "Plus: Draw (Cash Below Minimum)", USD, None,
         lambda c, p: (f"=MIN(Revolver_Commit-{f('r_beg', c)},"
                       f"MAX(0,Min_Cash_Balance-{f('cash_pre', c)}))"), False),
        ("r_repay", "Less: Repayment (First from Cash Above Minimum)", USD, None,
         lambda c, p: f"=MIN({f('r_beg', c)},MAX(0,{f('cash_pre', c)}-Min_Cash_Balance))", False),
        ("r_end", "Ending Balance", USD, lambda: "=0",
         lambda c, p: f"={f('r_beg', c)}+{f('r_draw', c)}-{f('r_repay', c)}", True),
        ("sec", "Mezzanine Notes"),
        ("m_beg", "Beginning Balance", USD, None, lambda c, p: f"={f('m_end', p)}", False),
        ("m_cash", "Cash Interest (on Beginning Balance)", USD, None,
         lambda c, p: f"={f('m_beg', c)}*Mezz_Cash_Rate", False),
        ("m_pik", "PIK Interest (Added to Principal)", USD, None,
         lambda c, p: f"={f('m_beg', c)}*Mezz_PIK_Rate", False),
        ("m_end", "Ending Balance", USD, lambda: "=Mezz_Debt_0",
         lambda c, p: f"={f('m_beg', c)}+{f('m_pik', c)}", True),
        ("sec", "Capitalized Financing Fees (Amortized Straight Line, Tax Deductible, Non-Cash)"),
        ("fee_beg", "Beginning Balance", USD, None, lambda c, p: f"={f('fee_end', p)}", False),
        ("fee_amort", "Less: Amortization", USD, None,
         lambda c, p: f"=MIN({f('fee_beg', c)},Financing_Fees/Fee_Years)", False),
        ("fee_end", "Ending Balance", USD, lambda: "=Financing_Fees",
         lambda c, p: f"={f('fee_beg', c)}-{f('fee_amort', c)}", True),
        ("sec", "Credit Statistics"),
        ("debt_tot", "Total Debt (Term Loan, Revolver, Mezzanine)", USD,
         lambda: f"={f('s_end', 'B')}+{f('m_end', 'B')}+{f('r_end', 'B')}",
         lambda c, p: f"={f('s_end', c)}+{f('m_end', c)}+{f('r_end', c)}", False),
        ("lev_tot", "Total Debt / EBITDA", MULT, lambda: f"={f('debt_tot', 'B')}/{f('ebitda', 'B')}",
         lambda c, p: f"={f('debt_tot', c)}/{f('ebitda', c)}", False),
        ("lev_sen", "Senior Debt (Term Loan and Revolver) / EBITDA", MULT,
         lambda: f"=({f('s_end', 'B')}+{f('r_end', 'B')})/{f('ebitda', 'B')}",
         lambda c, p: f"=({f('s_end', c)}+{f('r_end', c)})/{f('ebitda', c)}", False),
        ("cov", "EBITDA / Cash Interest (Including Revolver Interest and Fees)", MULT, None,
         lambda c, p: f"=IF({ci(c)}>0,{f('ebitda', c)}/{ci(c)},0)", False),
        ("fccr", "Fixed Charge Coverage: (EBITDA - Capex - Cash Taxes) / (Cash Interest + Mandatory Amort.)",
         MULT, None,
         lambda c, p: (f"=IF(({ci(c)}+{f('s_mand', c)})>0,"
                       f"({f('ebitda', c)}-{f('capex', c)}-{f('tax', c)})/({ci(c)}+{f('s_mand', c)}),0)"), False),
        ("sec", "Covenant Tests (Headroom Is the EBITDA Cushion Before a Breach)"),
        ("lev_max", "Maximum Total Debt / EBITDA", MULT2, None,
         lambda c, p: f"=Inputs!{c}{IN_SROW['cov_lev']}", False),
        ("lev_head", "Leverage Headroom (1 - Actual / Maximum)", PCT, None,
         lambda c, p: f"=1-{f('lev_tot', c)}/{f('lev_max', c)}", False),
        ("lev_ok", "Leverage Test", PASS, None,
         lambda c, p: f"=IF({f('ebitda', c)}>0,IF({f('lev_head', c)}>=0,1,0),0)", False),
        ("cov_min", "Minimum EBITDA / Cash Interest", MULT2, None,
         lambda c, p: f"=Inputs!{c}{IN_SROW['cov_cov']}", False),
        ("cov_head", "Coverage Headroom (1 - Minimum / Actual)", PCT, None,
         lambda c, p: (f"=IF({f('cov', c)}>0,1-{f('cov_min', c)}/{f('cov', c)},"
                       f"IF({ci(c)}>0,-1,1))"), False),
        ("cov_ok", "Coverage Test", PASS, None,
         lambda c, p: f"=IF({f('cov_head', c)}>=0,1,0)", False),
    ]


MODEL_FIRST = 5
_row = MODEL_FIRST
for _s in _spec():
    if _s[0] != "sec":
        R[_s[0]] = _row
    _row += 1
SPEC = _spec()
MODEL_KEYS = list(R)


def _inputs(b, case):
    ws = b.sheet("Inputs", "Inputs", "Blue cells are hard-coded inputs from the case file. $ in thousands.",
                 {"A": 56, **{c: 14 for c in COLS}})
    b.header(ws, 4, ["Input", "Value"])
    for name, label, (sec, field), fmt in SCALARS:
        r = IN_ROW[name]
        b.label(ws, f"A{r}", label)
        b.inp(ws, f"B{r}", case[sec][field], fmt, name=name)
    b.header(ws, IN_SERIES, ["Time Series Inputs", ""] + list(range(1, YEARS + 1)))
    for key, label, (sec, field), fmt in SERIES:
        r = IN_SROW[key]
        b.label(ws, f"A{r}", label)
        for i, v in enumerate(case[sec][field]):
            b.inp(ws, f"{COLS[i + 1]}{r}", v, fmt)
    ws.freeze_panes = "B5"


def _sources_uses(b):
    ws = b.sheet("Sources_Uses", "Sources and Uses", "$ in thousands", {"A": 36, "B": 14, "C": 14, "D": 14})
    b.header(ws, 4, ["", "Amount", "x LTM EBITDA", "% of Total"])
    rows = [
        (6, "Purchase Price (Enterprise Value)", "=LTM_EBITDA*Entry_Multiple", "Purchase_Price"),
        (7, "Advisory and Transaction Fees (Expensed at Close)", "=Advisory_Fee_Pct*Purchase_Price", None),
        (8, "Financing Fees (Capitalized, Amortized)",
         "=Financing_Fee_Pct*(Senior_Debt_0+Mezz_Debt_0+Revolver_Commit)", "Financing_Fees"),
        (9, "Cash to Balance Sheet", "=Cash_To_BS", None),
        (13, "Senior Term Loan", "=Senior_Leverage*LTM_EBITDA", "Senior_Debt_0"),
        (14, "Mezzanine Notes", "=Mezz_Leverage*LTM_EBITDA", "Mezz_Debt_0"),
        (15, "Total Equity: Sponsor and Management Rollover (Plug)", "=Total_Uses-Senior_Debt_0-Mezz_Debt_0",
         "Total_Equity"),
    ]
    b.section(ws, 5, "Uses", 4)
    b.section(ws, 12, "Sources", 4)
    for r, label, formula, name in rows:
        b.label(ws, f"A{r}", label, indent=1)
        b.calc(ws, f"B{r}", formula, USD, name=name)
    for r, label, rng, name in [(10, "Total Uses", "B6:B9", "Total_Uses"),
                                (16, "Total Sources", "B13:B15", "Total_Sources")]:
        b.label(ws, f"A{r}", label, bold=True)
        b.calc(ws, f"B{r}", f"=SUM({rng})", USD, name=name, bold=True, total=True)
    for r in (6, 7, 8, 9, 10, 13, 14, 15, 16):
        tot = "Total_Uses" if r <= 10 else "Total_Sources"
        b.calc(ws, f"C{r}", f"=B{r}/LTM_EBITDA", MULT)
        b.calc(ws, f"D{r}", f"=B{r}/{tot}", PCT)
    b.label(ws, "A18", "Check: Sources Less Uses (Should Be Zero)")
    b.calc(ws, "B18", "=Total_Sources-Total_Uses", USD, name="SU_Check")
    ws.freeze_panes = "B5"


def _model(b):
    ws = b.sheet("Model", "Operating Model, Debt Schedule and Credit Statistics",
                 "$ in thousands. Year-end timing. Interest on beginning balances, so no circular references.",
                 {"A": 62, **{c: 14 for c in COLS}})
    b.header(ws, 4, ["", *range(0, YEARS + 1)])
    ws["B4"].number_format = '"Close"'
    row = MODEL_FIRST
    for s in SPEC:
        if s[0] == "sec":
            b.section(ws, row, s[1], len(COLS) + 1)
        else:
            key, label, fmt, close, yr, bold = s
            b.label(ws, f"A{row}", label, bold=bold, indent=0 if bold else 1)
            if close:
                b.calc(ws, f"B{row}", close(), fmt, bold=bold)
            for i in range(1, YEARS + 1):
                b.calc(ws, f"{COLS[i]}{row}", yr(COLS[i], COLS[i - 1]), fmt, bold=bold)
        row += 1
    ws.freeze_panes = "B5"


def _returns(b):
    ws = b.sheet("Returns", "Exit and Sponsor Returns",
                 "Single equity outflow at close, single inflow at exit, no interim distributions.",
                 {"A": 58, "B": 16, "C": 18})
    b.header(ws, 4, ["", "Value"])
    last = COLS[-1]
    rows = [
        (5, "Exit Year", f"=Model!{last}4", '0', "Exit_Year", False),
        (6, "Exit-Year EBITDA", f"=Model!{last}{R['ebitda']}", USD, "Exit_EBITDA", False),
        (7, "Exit Enterprise Value", "=Exit_Multiple*B6", USD, "Exit_EV", False),
        (8, "Less: Senior Debt", f"=Model!{last}{R['s_end']}", USD, None, False),
        (9, "Less: Mezzanine Notes (Including PIK)", f"=Model!{last}{R['m_end']}", USD, None, False),
        (10, "Less: Revolver", f"=Model!{last}{R['r_end']}", USD, None, False),
        (11, "Plus: Cash", f"=Model!{last}{R['cash_end']}", USD, None, False),
        (12, "Exit Equity Value", "=B7-B8-B9-B10+B11", USD, "Exit_Equity", True),
        (13, "Less: Management Option Pool", "=Exit_Equity*Option_Pool", USD, None, False),
        (14, "Sponsor Share of Equity (1 Less Rollover)", "=1-Mgmt_Rollover", PCT, "Sponsor_Share", False),
        (15, "Sponsor Exit Proceeds", "=(B12-B13)*Sponsor_Share", USD, "Sponsor_Proceeds", True),
        (16, "Sponsor Equity Invested", "=Total_Equity*Sponsor_Share", USD, "Sponsor_Equity", False),
        (17, "Sponsor MOIC", "=B15/B16", MULT2, "Sponsor_MOIC", True),
        (18, "Sponsor IRR", "=IF(B17>0,B17^(1/B5)-1,-1)", PCT, "Sponsor_IRR", True),
        (20, "Minimum Year-End Cash Balance (Negative Means a Funding Gap)",
         f"=MIN(Model!C{R['cash_end']}:{last}{R['cash_end']})", USD, "Min_Cash", False),
        (21, "Peak Year-End Revolver Balance", f"=MAX(Model!B{R['r_end']}:{last}{R['r_end']})", USD,
         "Peak_Revolver", False),
        (22, "Covenant Tests Failed (Leverage and Coverage, All Years)",
         (f"=(Exit_Year-SUM(Model!C{R['lev_ok']}:{last}{R['lev_ok']}))"
          f"+(Exit_Year-SUM(Model!C{R['cov_ok']}:{last}{R['cov_ok']}))"), '0', "Covenant_Fails", False),
        (25, "EBITDA Growth (Change in EBITDA x Entry Multiple)", "=(Exit_EBITDA-LTM_EBITDA)*Entry_Multiple", USD,
         None, False),
        (26, "Multiple Expansion (Change in Multiple x Exit EBITDA)", "=(Exit_Multiple-Entry_Multiple)*Exit_EBITDA",
         USD, None, False),
        (27, "Debt Paydown and Cash Build (Net Debt at Close Less at Exit)",
         "=(Senior_Debt_0+Mezz_Debt_0-Cash_To_BS)-(B8+B9+B10-B11)", USD, None, False),
        (28, "Less: Transaction and Financing Fees", "=-(Total_Uses-Purchase_Price-Cash_To_BS)", USD, None, False),
        (29, "Equity Value Created (Exit Less Entry Equity)", "=SUM(B25:B28)", USD, "Equity_Gain", True),
    ]
    b.section(ws, 24, "Value Creation Bridge (Total Equity, Before Option Pool)", 3)
    ws["C24"] = "% of Value Created"
    for r in range(25, 30):
        b.calc(ws, f"C{r}", f"=IF(Equity_Gain<>0,B{r}/Equity_Gain,0)", PCT)
    for r, label, formula, fmt, name, bold in rows:
        b.label(ws, f"A{r}", label, bold=bold)
        b.calc(ws, f"B{r}", formula, fmt, name=name, bold=bold)
    ws.freeze_panes = "B5"


GRID_TOPS = (4, 13)
GRID_COLS = "BCDEF"


def _sensitivity(b, case):
    s = sensitivities(case)
    ws = b.sheet("Sensitivity", "Sponsor IRR Sensitivities",
                 "Grid 1 is live formulas (debt does not depend on entry multiple, and exit equity is linear in "
                 "exit multiple). Grid 2 is static Python values; rerun the CLI to refresh. "
                 "Axes are the base case plus or minus fixed steps.",
                 {"A": 34, **{c: 12 for c in GRID_COLS}})
    # Grid 1, live: entry multiple down, exit multiple across. Axes chain off the base case.
    top = GRID_TOPS[0]
    b.section(ws, top, "Grid 1, Live Formulas: Entry Multiple (Down) by Exit Multiple (Across)", 6)
    ax = top + 1
    b.axis(ws, [f"{c}{ax}" for c in GRID_COLS], "Exit_Multiple", "Mult_Step", MULT)
    b.axis(ws, [f"A{r}" for r in range(top + 2, top + 7)], "Entry_Multiple", "Mult_Step", MULT)
    for r in range(top + 2, top + 7):
        for c in GRID_COLS:
            # Rollover is pro rata, so it cancels out of MOIC; only the option pool dilutes the sponsor.
            moic = (f"((Exit_Equity+({c}${ax}-Exit_Multiple)*Exit_EBITDA)*(1-Option_Pool)/"
                    f"(Total_Equity+($A{r}-Entry_Multiple)*LTM_EBITDA*(1+Advisory_Fee_Pct)))")
            b.calc(ws, f"{c}{r}", f"=IF({moic}>0,{moic}^(1/Exit_Year)-1,-1)", PCT)
    b.base(ws, f"D{top + 4}")
    # Grid 2, static: senior leverage changes the whole debt schedule, so it stays in Python.
    top = GRID_TOPS[1]
    b.section(ws, top, "Grid 2, Static Python Values: Senior Leverage (Down) by Exit Multiple (Across)", 6)
    for j, x in enumerate(s["exit_axis"]):
        b.static(ws, f"{GRID_COLS[j]}{top + 1}", x, MULT)
    for i, x in enumerate(s["leverage_axis"]):
        b.static(ws, f"A{top + 2 + i}", x, MULT)
        for j, v in enumerate(s["irr_leverage_exit"][i]):
            b.static(ws, f"{GRID_COLS[j]}{top + 2 + i}", v, PCT)
    b.base(ws, f"D{top + 4}")
    ws.freeze_panes = "B4"


def _checks(b):
    def rng(key):
        return f"Model!{COLS[1]}{R[key]}:{COLS[-1]}{R[key]}"

    def last(key):
        return f"Model!{COLS[-1]}{R[key]}"

    b.checks_sheet([
        ("Sources equal uses", "ABS(Total_Sources-Total_Uses)>Check_Tol"),
        ("Sponsor equity is positive", "Sponsor_Equity<=0"),
        ("Value creation bridge ties to exit equity less entry equity",
         "ABS(Equity_Gain-(Exit_Equity-Total_Equity))>Check_Tol"),
        ("Senior debt never negative", f"MIN(Model!B{R['s_end']}:{COLS[-1]}{R['s_end']})<-Check_Tol"),
        ("Mezzanine debt never negative", f"MIN(Model!B{R['m_end']}:{COLS[-1]}{R['m_end']})<-Check_Tol"),
        ("Revolver never negative or above its commitment",
         (f"(MIN(Model!B{R['r_end']}:{COLS[-1]}{R['r_end']})<-Check_Tol)"
          f"+(MAX(Model!B{R['r_end']}:{COLS[-1]}{R['r_end']})>Revolver_Commit+Check_Tol)>0")),
        ("Senior debt rolls: opening less repayments equals ending",
         f"ABS({last('s_end')}-(Senior_Debt_0-SUM({rng('s_mand')})-SUM({rng('s_sweep')})))>Check_Tol"),
        ("Revolver rolls: draws less repayments equals ending balance",
         f"ABS({last('r_end')}-(SUM({rng('r_draw')})-SUM({rng('r_repay')})))>Check_Tol"),
        ("Cash ties: opening plus free cash flow less debt service plus net revolver equals ending",
         (f"ABS({last('cash_end')}-(Cash_To_BS+SUM({rng('fcf')})-SUM({rng('s_mand')})-SUM({rng('s_sweep')})"
          f"+SUM({rng('r_draw')})-SUM({rng('r_repay')})))>Check_Tol")),
        ("Financing fees: capitalized less amortization equals ending balance, never negative",
         (f"(ABS({last('fee_end')}-(Financing_Fees-SUM({rng('fee_amort')})))>Check_Tol)"
          f"+(MIN(Model!B{R['fee_end']}:{COLS[-1]}{R['fee_end']})<-Check_Tol)>0")),
        ("Year-end cash never below the minimum balance (revolver is enough)",
         "Min_Cash<Min_Cash_Balance-Check_Tol"),
        ("Covenants: every leverage and coverage test passes", "Covenant_Fails>0"),
        ("Entry and exit multiple grid centre matches sponsor IRR",
         f"ABS(Sensitivity!D{GRID_TOPS[0] + 4}-Sponsor_IRR)>Check_Tol"),
        ("Leverage grid centre matches sponsor IRR (rerun the CLI if not)",
         f"ABS(Sensitivity!D{GRID_TOPS[1] + 4}-Sponsor_IRR)>Check_Tol"),
    ])


def _summary(b, case):
    ws = b.sheet("Summary", "LBO Model Summary", "$ in thousands", {"A": 40, "B": 18, "C": 60})
    meta = case["meta"]
    ws["A3"] = meta.get("name", "LBO Case")
    ws["A3"].font = Font(bold=True, size=12)
    if meta.get("illustrative"):
        ws["A4"] = "ILLUSTRATIVE CASE: round numbers, not a real company, not market data."
        ws["A4"].font = Font(bold=True, color="C00000")
    b.master_check(ws)
    b.header(ws, 6, ["Key Outputs", "Value"])
    items = [
        ("Purchase Price", "=Purchase_Price", USD),
        ("Entry Multiple", "=Entry_Multiple", MULT),
        ("Total Debt / LTM EBITDA at Close", f"=Model!B{R['lev_tot']}", MULT),
        ("Sponsor Equity", "=Sponsor_Equity", USD),
        ("Exit Enterprise Value", "=Exit_EV", USD),
        ("Exit Equity Value", "=Exit_Equity", USD),
        ("Sponsor MOIC", "=Sponsor_MOIC", MULT2),
        ("Sponsor IRR", "=Sponsor_IRR", PCT),
        ("Minimum Year-End Cash", "=Min_Cash", USD),
        ("Peak Revolver Balance", "=Peak_Revolver", USD),
        ("Covenant Tests Failed", "=Covenant_Fails", '0'),
    ]
    for i, (label, formula, fmt) in enumerate(items):
        b.label(ws, f"A{7 + i}", label)
        b.calc(ws, f"B{7 + i}", formula, fmt, bold=label.startswith("Sponsor"))
    r = 7 + len(items) + 1
    r = b.color_key(ws, r, static=True)
    b.header(ws, r, ["Sheets", "", ""])
    for i, (n, d) in enumerate([("Inputs", "All hard-coded assumptions"),
                                ("Sources_Uses", "Purchase price, fees, debt and sponsor equity"),
                                ("Model", "Operating build, debt schedule, credit statistics"),
                                ("Returns", "Exit value, rollover and option pool, MOIC, IRR, value creation bridge"),
                                ("Sensitivity", "IRR by entry and exit multiple (live), leverage grid (static)"),
                                ("Checks", "Live integrity checks, 0 means OK")]):
        b.label(ws, f"A{r + 1 + i}", n)
        b.label(ws, f"C{r + 1 + i}", d)


def build(case, path):
    b = Book()
    _summary(b, case)
    _inputs(b, case)
    _sources_uses(b)
    _model(b)
    _returns(b)
    _sensitivity(b, case)
    _checks(b)
    return b.save(path)
