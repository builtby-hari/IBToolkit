"""Writes the bank merger workbook: Summary, Inputs, Purchase_Accounting, Pro_Forma,
Earnback, Sensitivity, Contribution, Breakeven.

Every calculated cell is a live formula. Hard-coded inputs live only on Inputs.
"""
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter as L

from .excel import MULT2, PCT, USD, Book
from .merger import CONTRIB, GRID_PHASES, GRID_STEP, HORIZON, MIX_AXIS, SAVES_STEP, YEARS

PS = '$#,##0.00_);($#,##0.00)'
NUM = '#,##0_);(#,##0)'
RATIO = '0.0000"x"'

# Inputs: (name, label, (section, field, index or None), fmt)
def _s(name, label, sec, field, fmt, i=None):
    return (name, label, (sec, field, i), fmt)


SCALARS = [
    _s("Acq_NI_1", "Acquirer Net Income, Year 1", "acquirer", "net_income", USD, 0),
    _s("Acq_NI_2", "Acquirer Net Income, Year 2", "acquirer", "net_income", USD, 1),
    _s("Acq_Shares", "Acquirer Shares (Thousands)", "acquirer", "shares", NUM),
    _s("Acq_Price", "Acquirer Share Price", "acquirer", "share_price", PS),
    _s("Acq_TBV", "Acquirer Tangible Book Value", "acquirer", "tbv", USD),
    _s("Acq_TA", "Acquirer Tangible Assets", "acquirer", "tangible_assets", USD),
    _s("Tgt_NI_1", "Target Net Income, Year 1", "target", "net_income", USD, 0),
    _s("Tgt_NI_2", "Target Net Income, Year 2", "target", "net_income", USD, 1),
    _s("Tgt_Shares", "Target Shares (Thousands)", "target", "shares", NUM),
    _s("Tgt_Price", "Target Share Price (Unaffected)", "target", "share_price", PS),
    _s("Tgt_TBV", "Target Tangible Book Value", "target", "tbv", USD),
    _s("Tgt_TA", "Target Tangible Assets", "target", "tangible_assets", USD),
    _s("Tgt_Nonint", "Target Noninterest Expense", "target", "noninterest_expense", USD),
    _s("Tgt_Core_Dep", "Target Core Deposits", "target", "core_deposits", USD),
    _s("Tgt_Loans", "Target Loans", "target", "loans", USD),
    _s("Tgt_Secs", "Target Securities", "target", "securities", USD),
    # The offer price row is inserted here by _offer_row (per share or P/TBV).
    _s("Stock_Pct", "Stock Consideration (% of Price)", "deal", "stock_pct", PCT),
    _s("Cost_Of_Cash", "Pre-Tax Cost of Cash Consideration", "deal", "cost_of_cash", PCT),
    _s("Saves_Pct", "Cost Saves (% of Target Noninterest Expense)", "deal", "cost_saves_pct", PCT),
    _s("Phase_1", "Cost Saves Phase-In, Year 1", "deal", "phase_in", PCT, 0),
    _s("Phase_2", "Cost Saves Phase-In, Year 2", "deal", "phase_in", PCT, 1),
    _s("Charges", "One-Time Merger Charges (Pre-Tax)", "deal", "merger_charges", USD),
    _s("CDI_Pct", "Core Deposit Intangible (% of Core Deposits)", "deal", "cdi_pct", PCT),
    _s("CDI_Years", "CDI Amortization Years", "deal", "cdi_years", '0.0'),
    _s("Tax_Rate", "Tax Rate", "deal", "tax_rate", PCT),
    _s("Loan_Dur", "Loan Portfolio Duration (Years)", "marks", "loan_duration", '0.0'),
    _s("Loan_DRate", "Loan Rate Change vs Book Yield", "marks", "loan_rate_change", '0.00%'),
    _s("Loan_Life", "Loan Mark Accretion Life (Years)", "marks", "loan_life", '0.0'),
    _s("Sec_Dur", "Securities Portfolio Duration (Years)", "marks", "securities_duration", '0.0'),
    _s("Sec_DRate", "Securities Rate Change vs Book Yield", "marks", "securities_rate_change", '0.00%'),
    _s("Sec_Life", "Securities Mark Accretion Life (Years)", "marks", "securities_life", '0.0'),
    _s("Day2_Reserve", "CECL Day 2 Reserve on Non-PCD Loans (Pre-Tax, One-Time)", "deal", "day2_reserve", USD),
    _s("Dissyn", "Revenue Dis-Synergies (Pre-Tax, Annual)", "deal", "revenue_dissynergies", USD),
    _s("CDI_SYD", "CDI Method (1 = Sum of Years Digits, 0 = Straight Line)", "deal", "cdi_syd", '0'),
    _s("CDI_Gross", "CDI Tax Treatment in TBV (1 = Gross, 0 = Net of Deferred Tax)", "deal", "cdi_gross", '0'),
    _s("Restr_Sold", "Restructuring: Target Securities Sold", "restructuring", "securities_sold", USD),
    _s("Restr_Yield", "Restructuring: Yield Given Up on Securities", "restructuring", "securities_yield", '0.00%'),
    _s("Restr_Rate", "Restructuring: Rate on Borrowings Repaid", "restructuring", "borrowing_rate", '0.00%'),
    _s("Credit_Total", "Gross Credit Mark (Total)", "credit_mark", "total", USD),
    _s("Credit_PCD", "Credit Mark: PCD Share", "credit_mark", "pcd_share", PCT),
    _s("Credit_Life", "Non-PCD Credit Mark Accretion Life (Years)", "credit_mark", "life", '0.0'),
    _s("Dep_Mark", "Deposit Mark (Positive = Liability Written Down)", "marks", "deposit_mark", USD),
    _s("Dep_Life", "Deposit Mark Amortization Life (Years)", "marks", "deposit_life", '0.0'),
    _s("Borr_Mark", "Borrowings Mark (Positive = Liability Written Down)", "marks", "borrowings_mark", USD),
    _s("Borr_Life", "Borrowings Mark Amortization Life (Years)", "marks", "borrowings_life", '0.0'),
    _s("Exch_Ratio_In", "Announced Exchange Ratio, Stock Election (0 = Offer Price / Acquirer Price)",
       "deal", "exchange_ratio", RATIO),
    _s("NonPCD_GrossUp", "Non-PCD Method (1 = ASU 2025-08 Gross-Up, 0 = Day 2 Reserve Expensed)",
       "credit_mark", "nonpcd_gross_up", '0'),
]
OFFER_AFTER = "Tgt_Secs"
IN_ROW = {}
_r = 5
for _n, *_ in SCALARS:
    IN_ROW[_n] = _r
    _r += 1
    if _n == OFFER_AFTER:
        IN_ROW["Offer"] = _r
        _r += 1

# Pro_Forma rows (columns B, C = Year 1, Year 2).
PF = dict(acq=5, tgt=6, saves=7, dis=8, fund=9, accr=10, restr=11, credit=12, depam=13, cdi=14,
          adj_pre=15, adj_at=16, ni=17, shares=19, eps=20, sa_eps=21, acc_d=22, acc_pct=23, tang_eps=25)
CLOSE = 27  # first row of the At Close block header
YC = {1: "B", 2: "C"}
EB = dict(sa_eps=5, pf_eps=6, sa_tbv=7, pf_tbv=8, gap=9, step=10, result=12)
EBC = [L(i) for i in range(2, 3 + HORIZON)]  # B = Year 0 ... L = Year 10


def _rows(b, ws, rows):
    for r, label, formula, fmt, name, bold in rows:
        b.label(ws, f"A{r}", label, bold=bold, indent=0 if bold else 1)
        b.calc(ws, f"B{r}", formula, fmt, name=name, bold=bold)


def _inputs(b, case):
    ws = b.sheet("Inputs", "Inputs", "Blue cells are hard-coded inputs from the case file. $ in thousands.",
                 {"A": 56, "B": 16})
    b.header(ws, 4, ["Input", "Value"])
    for name, label, (sec, field, i), fmt in SCALARS:
        r = IN_ROW[name]
        derived = {"cdi_syd": int(case["deal"]["cdi_method"] == "syd"),
                   "cdi_gross": int(case["deal"]["cdi_tax_treatment"] == "gross"),
                   "nonpcd_gross_up": int(case["credit_mark"].get("non_pcd_method") == "gross_up")}
        v = derived[field] if field in derived else case[sec][field]
        b.label(ws, f"A{r}", label)
        b.inp(ws, f"B{r}", v if i is None else v[i], fmt, name=name)
    d, r = case["deal"], IN_ROW["Offer"]
    if "price_per_share" in d:
        b.label(ws, f"A{r}", "Offer Price per Target Share")
        b.inp(ws, f"B{r}", d["price_per_share"], PS, name="Offer_In")
    else:
        b.label(ws, f"A{r}", "Offer Price (x Target TBV)")
        b.inp(ws, f"B{r}", d["p_tbv"], MULT2, name="Offer_In")
    ws.freeze_panes = "B5"


def _purchase(b, case):
    ws = b.sheet("Purchase_Accounting", "Price, Consideration and Purchase Accounting",
                 "$ in thousands. Rate mark = -duration x rate change x balance (simplified: ignores convexity "
                 "and cash flow timing).", {"A": 58, "B": 16})
    b.header(ws, 4, ["", "Value"])
    offer = ("=Offer_In" if "price_per_share" in case["deal"]
             else "=Offer_In*Tgt_TBV/Tgt_Shares")
    sections = [
        (5, "Price and Consideration"), (19, "Fair Value Marks and Intangibles"),
        (32, "Goodwill"),
    ]
    for r, t in sections:
        b.section(ws, r, t, 2)
    _rows(b, ws, [
        (6, "Offer Price per Target Share", offer, PS, "Offer_PPS", False),
        (7, "Premium to Unaffected Target Price", "=Offer_PPS/Tgt_Price-1", PCT, "Premium", False),
        (8, "Aggregate Price Paid", "=Offer_PPS*Tgt_Shares", USD, "Deal_Price", True),
        (9, "Price / Tangible Book Value", "=Deal_Price/Tgt_TBV", MULT2, "Price_TBV", False),
        (10, "Price / Year 1 Earnings Paid", "=Deal_Price/Tgt_NI_1", '0.0"x"', "Price_PE", False),
        (11, "Stock Consideration", "=Stock_Pct*Deal_Price", USD, "Stock_Cons", False),
        (12, "Cash Consideration", "=Deal_Price-Stock_Cons", USD, "Cash_Cons", False),
        (13, "Exchange Ratio (Stock Election, Acquirer Shares per Target Share)",
         "=IF(Exch_Ratio_In>0,Exch_Ratio_In,Offer_PPS/Acq_Price)", RATIO, "Exch_Ratio", False),
        (14, "New Acquirer Shares Issued (Thousands)", "=Stock_Cons/Acq_Price", NUM, "New_Shares", False),
        (15, "Blended Acquirer Shares Issued per Target Share", "=New_Shares/Tgt_Shares", RATIO, "Blend_Ratio", False),
        (16, "Consideration Mix: Stock (% of Price)", "=Stock_Cons/Deal_Price", PCT, None, False),
        (17, "Consideration Mix: Cash (% of Price)", "=Cash_Cons/Deal_Price", PCT, None, False),
        (20, "Loan Mark (Negative = Write-Down)", "=-Loan_Dur*Loan_DRate*Tgt_Loans", USD, "Loan_Mark", False),
        (21, "Securities Mark (Negative = Write-Down)", "=-Sec_Dur*Sec_DRate*Tgt_Secs", USD, "Sec_Mark", False),
        (22, "Net Fair Value Marks (Incl. Non-PCD Credit Mark)", "=Loan_Mark+Sec_Mark+Dep_Mark+Borr_Mark-NonPCD_Mark",
         USD, "Net_Marks", True),
        (23, "Core Deposit Intangible Created", "=CDI_Pct*Tgt_Core_Dep", USD, "CDI", False),
        (24, "Net Deferred Tax Asset / (Liability) on Marks and CDI", "=-Tax_Rate*(Net_Marks+CDI)", USD, "Net_DTA", False),
        (25, "After-Tax Merger Charges and Day 2 Reserve (Reserve Zero Under Gross-Up)",
         "=(Charges+Day2_Reserve*(1-NonPCD_GrossUp))*(1-Tax_Rate)", USD, "Charges_AT", False),
        (26, "Deposit Mark (Positive = Liability Written Down)", "=Dep_Mark", USD, None, False),
        (27, "Borrowings Mark (Positive = Liability Written Down)", "=Borr_Mark", USD, None, False),
        (28, "PCD Credit Mark (Allowance Gross-Up, No Income)", "=Credit_Total*Credit_PCD", USD, "PCD_Mark", False),
        (29, "Non-PCD Credit Mark (Loan Write-Down at Close, Accreted Into Income)", "=Credit_Total*(1-Credit_PCD)",
         USD, "NonPCD_Mark", False),
        (30, "CDI Deferred Tax Liability Deducted From TBV (Gross Treatment Only)",
         "=IF(CDI_Gross=1,Tax_Rate*CDI,0)", USD, "CDI_DTL_Ded", False),
        (33, "Target Tangible Book Value", "=Tgt_TBV", USD, None, False),
        (34, "Plus: Net Fair Value Marks", "=Net_Marks", USD, None, False),
        (35, "Plus: Core Deposit Intangible", "=CDI", USD, None, False),
        (36, "Plus: Net Deferred Tax Asset / (Liability)", "=Net_DTA", USD, None, False),
        (37, "Fair Value of Net Identifiable Assets", "=B33+B34+B35+B36", USD, "FV_Net_Assets", True),
        (38, "Goodwill (Price Less Fair Value of Net Assets)", "=Deal_Price-FV_Net_Assets", USD, "Goodwill", True),
    ])
    ws.freeze_panes = "B5"


def _pro_forma(b):
    ws = b.sheet("Pro_Forma", "Pro Forma Earnings, Tangible Book Value and Capital",
                 "$ in thousands except per share. One-time merger charges are excluded from EPS and "
                 "deducted from tangible book value at close.",
                 {"A": 58, "B": 16, "C": 16})
    b.header(ws, 4, ["", *range(1, YEARS + 1)])
    b.section(ws, PF["shares"] - 1, "Per Share", 3)
    b.section(ws, PF["tang_eps"] - 1, "Tangible Earnings (For Earnback)", 3)
    spec = [
        ("acq", "Acquirer Standalone Net Income", lambda y: f"=Acq_NI_{y}", USD, False),
        ("tgt", "Plus: Target Net Income", lambda y: f"=Tgt_NI_{y}", USD, False),
        ("saves", "Plus: Cost Saves (Pre-Tax, Phased)", lambda y: f"=Saves_Pct*Tgt_Nonint*Phase_{y}", USD, False),
        ("dis", "Less: Revenue Dis-Synergies (Pre-Tax)", lambda y: "=Dissyn", USD, False),
        ("fund", "Less: Cost of Cash Consideration (Pre-Tax)", lambda y: "=Cost_Of_Cash*Cash_Cons", USD, False),
        ("accr", "Plus: Accretion of Fair Value Marks (Pre-Tax)",
         lambda y: (f"=IF({YC[y]}$4<=Loan_Life,-Loan_Mark/Loan_Life,0)"
                    f"+IF({YC[y]}$4<=Sec_Life,-Sec_Mark/Sec_Life,0)"), USD, False),
        ("restr", "Plus: Balance Sheet Restructuring Pickup (Pre-Tax)", lambda y: "=Restr_Sold*(Restr_Rate-Restr_Yield)", USD, False),
        ("credit", "Plus: Accretion of Non-PCD Credit Mark (Pre-Tax)",
         lambda y: f"=IF({YC[y]}$4<=Credit_Life,(NonPCD_Mark-Day2_Reserve*NonPCD_GrossUp)/Credit_Life,0)", USD, False),
        ("depam", "Less: Amortization of Deposit and Borrowings Marks (Pre-Tax)",
         lambda y: (f"=IF({YC[y]}$4<=Dep_Life,Dep_Mark/Dep_Life,0)"
                    f"+IF({YC[y]}$4<=Borr_Life,Borr_Mark/Borr_Life,0)"), USD, False),
        ("cdi", "Less: CDI Amortization (Pre-Tax)",
         lambda y: (f"=IF({YC[y]}$4<=CDI_Years,CDI*IF(CDI_SYD=1,"
                    f"(CDI_Years-{YC[y]}$4+1)/(CDI_Years*(CDI_Years+1)/(1+1)),1/CDI_Years),0)"), USD, False),
        ("adj_pre", "Pre-Tax Deal Adjustments",
         lambda y: (f"={YC[y]}{PF['saves']}-{YC[y]}{PF['dis']}-{YC[y]}{PF['fund']}+{YC[y]}{PF['accr']}"
                             f"+{YC[y]}{PF['restr']}+{YC[y]}{PF['credit']}-{YC[y]}{PF['depam']}-{YC[y]}{PF['cdi']}"), USD, False),
        ("adj_at", "After-Tax Deal Adjustments", lambda y: f"={YC[y]}{PF['adj_pre']}*(1-Tax_Rate)", USD, False),
        ("ni", "Pro Forma Net Income",
         lambda y: f"={YC[y]}{PF['acq']}+{YC[y]}{PF['tgt']}+{YC[y]}{PF['adj_at']}", USD, True),
        ("shares", "Pro Forma Shares (Thousands)", lambda y: "=Acq_Shares+New_Shares", NUM, False),
        ("eps", "Pro Forma EPS", lambda y: f"={YC[y]}{PF['ni']}/{YC[y]}{PF['shares']}", PS, True),
        ("sa_eps", "Acquirer Standalone EPS", lambda y: f"={YC[y]}{PF['acq']}/Acq_Shares", PS, False),
        ("acc_d", "Accretion / (Dilution) per Share", lambda y: f"={YC[y]}{PF['eps']}-{YC[y]}{PF['sa_eps']}", PS, False),
        ("acc_pct", "Accretion / (Dilution) %", lambda y: f"={YC[y]}{PF['eps']}/{YC[y]}{PF['sa_eps']}-1", PCT, True),
        ("tang_eps", "Pro Forma Tangible EPS (Adds Back CDI Amortization; Pre-Tax if Gross, After-Tax if Net)",
         lambda y: f"=({YC[y]}{PF['ni']}+{YC[y]}{PF['cdi']}*IF(CDI_Gross=1,1,1-Tax_Rate))/{YC[y]}{PF['shares']}",
         PS, False),
    ]
    for key, label, fn, fmt, bold in spec:
        r = PF[key]
        b.label(ws, f"A{r}", label, bold=bold, indent=0 if bold else 1)
        for y in (1, 2):
            b.calc(ws, f"{YC[y]}{r}", fn(y), fmt, bold=bold, name=f"PF_{key}_{y}" if key in ("eps", "acc_pct") else None)
    b.section(ws, CLOSE, "At Close", 3)
    _rows(b, ws, [
        (28, "Pro Forma Tangible Book Value", "=Acq_TBV+Tgt_TBV+Net_Marks*(1-Tax_Rate)-CDI_DTL_Ded-Cash_Cons-Charges_AT",
         USD, "PF_TBV", True),
        (29, "Pro Forma Tangible Assets", "=Acq_TA+Tgt_TA+Net_Marks*(1-Tax_Rate)-CDI_DTL_Ded-Cash_Cons-Charges_AT-Restr_Sold",
         USD, "PF_TA", False),
        (30, "Pro Forma TCE / Tangible Assets", "=PF_TBV/PF_TA", PCT, "PF_TCE", True),
        (31, "Acquirer Standalone TCE / Tangible Assets", "=Acq_TBV/Acq_TA", PCT, "SA_TCE", False),
        (32, "Acquirer Standalone TBV per Share", "=Acq_TBV/Acq_Shares", PS, "SA_TBVPS", False),
        (33, "Pro Forma TBV per Share", "=PF_TBV/(Acq_Shares+New_Shares)", PS, "PF_TBVPS", True),
        (34, "TBV per Share Accretion / (Dilution) at Close", "=PF_TBVPS-SA_TBVPS", PS, "TBV_Dil_D", False),
        (35, "TBV per Share Accretion / (Dilution) %", "=PF_TBVPS/SA_TBVPS-1", PCT, "TBV_Dil_Pct", True),
        (36, "Ownership: Acquirer Shareholders", "=Acq_Shares/(Acq_Shares+New_Shares)", PCT, "Own_Acq", False),
        (37, "Ownership: Target Shareholders", "=New_Shares/(Acq_Shares+New_Shares)", PCT, "Own_Tgt", False),
    ])
    ws.freeze_panes = "B5"


def _earnback(b):
    ws = b.sheet("Earnback", "TBV per Share Earnback (Simple Crossover)",
                 "Each side's TBV per share grows by its own EPS, no dividends. Years after 2 hold Year 2 EPS "
                 "flat. Pro forma EPS adds back CDI amortization (a non-tangible cost): pre-tax under the gross CDI "
                 "treatment, after tax under net.",
                 {"A": 52, **{c: 12 for c in EBC}})
    b.header(ws, 4, ["", *range(0, HORIZON + 1)])
    e = EB
    labels = {"sa_eps": "Acquirer Standalone EPS", "pf_eps": "Pro Forma Tangible EPS",
              "sa_tbv": "Standalone TBV per Share", "pf_tbv": "Pro Forma TBV per Share",
              "gap": "Gap: Standalone Less Pro Forma", "step": "Crossover Year (Interpolated)"}
    for k, t in labels.items():
        b.label(ws, f"A{e[k]}", t, indent=1)
    b.calc(ws, f"B{e['sa_tbv']}", "=SA_TBVPS", PS)
    b.calc(ws, f"B{e['pf_tbv']}", "=PF_TBVPS", PS)
    b.calc(ws, f"B{e['gap']}", f"=B{e['sa_tbv']}-B{e['pf_tbv']}", PS)
    for i in range(1, HORIZON + 1):
        c, p = EBC[i], EBC[i - 1]
        if i <= YEARS:
            b.calc(ws, f"{c}{e['sa_eps']}", f"=Pro_Forma!{YC[i]}{PF['sa_eps']}", PS)
            b.calc(ws, f"{c}{e['pf_eps']}", f"=Pro_Forma!{YC[i]}{PF['tang_eps']}", PS)
        else:
            b.calc(ws, f"{c}{e['sa_eps']}", f"={p}{e['sa_eps']}", PS)
            b.calc(ws, f"{c}{e['pf_eps']}", f"={p}{e['pf_eps']}", PS)
        b.calc(ws, f"{c}{e['sa_tbv']}", f"={p}{e['sa_tbv']}+{c}{e['sa_eps']}", PS)
        b.calc(ws, f"{c}{e['pf_tbv']}", f"={p}{e['pf_tbv']}+{c}{e['pf_eps']}", PS)
        b.calc(ws, f"{c}{e['gap']}", f"={c}{e['sa_tbv']}-{c}{e['pf_tbv']}", PS)
        first = f"*(SUM(C{e['step']}:{p}{e['step']})=0)" if i > 1 else ""
        b.calc(ws, f"{c}{e['step']}",
               f"=IF(({p}{e['gap']}>0)*({c}{e['gap']}<=0){first},"
               f"({c}$4-1)+{p}{e['gap']}/({p}{e['gap']}-{c}{e['gap']}),0)", '0.00')
    rng = f"C{e['step']}:{EBC[-1]}{e['step']}"
    b.label(ws, f"A{e['result']}", "TBV Earnback Period in Years (0 = None Needed, -1 = Not Within 10 Years)", bold=True)
    b.calc(ws, f"B{e['result']}", f"=IF(B{e['gap']}<=0,0,IF(SUM({rng})>0,SUM({rng}),-1))", '0.0',
           name="Earnback_Years", bold=True)
    ws.freeze_panes = "B5"


MIX_TOP = 22  # consideration mix grid title row


def _sensitivity(b):
    ws = b.sheet("Sensitivity", "EPS Accretion / (Dilution) Sensitivities",
                 "Live formulas: offer price and cost saves only move cost saves, the funding cost of cash and "
                 "the shares issued, so each cell re-prices Pro_Forma net income. Axes are the base case plus "
                 "or minus the steps on Inputs; the shaded centre is the base case.",
                 {"A": 34, **{c: 12 for c in "BCDEFG"}})
    for y, top in ((1, 4), (2, 13)):
        pf = {k: f"Pro_Forma!${YC[y]}${PF[k]}" for k in ("acq", "tgt", "saves", "fund", "adj_pre", "sa_eps")}
        b.section(ws, top, f"Year {y}: Offer Price per Share (Down) by Cost Saves % (Across)", 6)
        b.axis(ws, [f"{c}{top + 1}" for c in "BCDEF"], "Saves_Pct", "Saves_Step", PCT, hi=1)
        b.axis(ws, [f"A{top + 2 + i}" for i in range(5)], "Offer_PPS", "Offer_PPS*Grid_Price_Step", PS)
        other = f"{pf['adj_pre']}-{pf['saves']}+{pf['fund']}"
        for i in range(5):
            r = top + 2 + i
            for c in "BCDEF":
                b.calc(ws, f"{c}{r}",
                       f"=({pf['acq']}+{pf['tgt']}+({other}+{c}${top + 1}*Tgt_Nonint*Phase_{y}"
                       f"-Cost_Of_Cash*(1-Stock_Pct)*$A{r}*Tgt_Shares)*(1-Tax_Rate))"
                       f"/(Acq_Shares+Stock_Pct*$A{r}*Tgt_Shares/Acq_Price)/{pf['sa_eps']}-1", PCT)
        b.base(ws, f"D{top + 4}")
    t = MIX_TOP
    b.section(ws, t, "EPS Accretion / (Dilution) by Consideration Mix: Stock % of Price (Across; Last Column = Base)", 7)
    for c, ref in zip("BCDEFG", [f"Mix_{j + 1}" for j in range(len(MIX_AXIS))] + ["Stock_Pct"]):
        b.calc(ws, f"{c}{t + 1}", f"={ref}", PCT)
    for y in (1, 2):
        pf = {k: f"Pro_Forma!${YC[y]}${PF[k]}" for k in ("acq", "tgt", "fund", "adj_pre", "sa_eps")}
        r = t + 1 + y
        b.label(ws, f"A{r}", f"Year {y}", indent=1)
        for c in "BCDEFG":
            b.calc(ws, f"{c}{r}",
                   f"=({pf['acq']}+{pf['tgt']}+({pf['adj_pre']}+{pf['fund']}-Cost_Of_Cash*(1-{c}${t + 1})*Deal_Price)"
                   f"*(1-Tax_Rate))/(Acq_Shares+{c}${t + 1}*Deal_Price/Acq_Price)/{pf['sa_eps']}-1", PCT)
        b.base(ws, f"G{r}")
    ws.freeze_panes = "B4"
    return [(f"Accretion grid centre matches Year {y} accretion (grid wiring)",
             f"ABS(Sensitivity!D{top + 4}-PF_acc_pct_{y})>Check_Tol") for y, top in ((1, 4), (2, 13))] + [
            (f"Consideration mix grid at the base mix matches Year {y} accretion (grid wiring)",
             f"ABS(Sensitivity!G{t + 1 + y}-PF_acc_pct_{y})>Check_Tol") for y in (1, 2)]


# Contribution and breakeven inputs that are not in SCALARS: (name, label, (section, field), fmt).
EXTRA_INPUTS = [
    ("Acq_LTM_NI", "Acquirer Net Income, LTM", ("acquirer", "ltm_net_income"), USD),
    ("Tgt_LTM_NI", "Target Net Income, LTM", ("target", "ltm_net_income"), USD),
    ("Acq_Assets", "Acquirer Total Assets", ("acquirer", "total_assets"), USD),
    ("Tgt_Assets", "Target Total Assets", ("target", "total_assets"), USD),
    ("Acq_Deposits", "Acquirer Deposits", ("acquirer", "deposits"), USD),
    ("Tgt_Deposits", "Target Deposits", ("target", "deposits"), USD),
    ("Acq_Loans", "Acquirer Loans", ("acquirer", "loans"), USD),
]
# Contribution sheet cells per CONTRIB key: (acquirer formula, target formula).
CONTRIB_XL = {"ni_ltm": ("Acq_LTM_NI", "Tgt_LTM_NI"), "ni_y1": ("Acq_NI_1", "Tgt_NI_1"),
              "tce": ("Acq_TBV", "Tgt_TBV"), "assets": ("Acq_Assets", "Tgt_Assets"),
              "deposits": ("Acq_Deposits", "Tgt_Deposits"), "loans": ("Acq_Loans", "Tgt_Loans"),
              "mcap": ("Acq_Shares*Acq_Price", "Tgt_Shares*Tgt_Price")}
CT_TOP = 5  # first metric row on Contribution
BE_GRID = 16  # Breakeven grid title row: axis on the next row, five offer prices below


def _extra_inputs(b, case):
    ws = b.wb["Inputs"]
    r = ws.max_row + 2
    b.section(ws, r, "Contribution Analysis (0 = Not Entered, Metric Left Out)", 2)
    for i, (name, label, (sec, field), fmt) in enumerate(EXTRA_INPUTS, start=r + 1):
        b.label(ws, f"A{i}", label)
        b.inp(ws, f"B{i}", case[sec][field], fmt, name=name)
    r = ws.max_row + 2
    b.section(ws, r, "Breakeven Accretion Grid Axes", 2)
    grid = [("Grid_Price_Step", "Offer Price Step (% of Base Offer)", GRID_STEP)] + [
        (f"Grid_Phase_{j + 1}", f"Year 1 Cost Saves Realized, Column {j + 1} (% of Run-Rate)", v)
        for j, v in enumerate(GRID_PHASES)]
    for i, (name, label, v) in enumerate(grid, start=r + 1):
        b.label(ws, f"A{i}", label)
        b.inp(ws, f"B{i}", v, PCT, name=name)
    r = ws.max_row + 2
    b.section(ws, r, "Sensitivity Grid Axes", 2)
    sens = [("Saves_Step", "Cost Saves Step (Points of Noninterest Expense)", SAVES_STEP)] + [
        (f"Mix_{j + 1}", f"Stock Consideration, Mix Column {j + 1} (% of Price)", v) for j, v in enumerate(MIX_AXIS)]
    for i, (name, label, v) in enumerate(sens, start=r + 1):
        b.label(ws, f"A{i}", label)
        b.inp(ws, f"B{i}", v, PCT, name=name)


def _contribution(b):
    ws = b.sheet("Contribution", "Contribution Analysis",
                 "$ in thousands. Implied exchange ratio = all-stock ratio that gives target holders their share "
                 "of the metric: (target / acquirer) x acquirer shares / target shares. With cash in the mix, "
                 "pro forma ownership sits below the target's contribution by design.",
                 {"A": 58, **{c: 15 for c in "BCDEFG"}})
    b.header(ws, 4, ["Metric", "Acquirer", "Target", "Combined", "Acquirer %", "Target %", "Implied Exchange Ratio"])
    last = CT_TOP + len(CONTRIB) - 1
    for r, (key, label, _) in enumerate(CONTRIB, start=CT_TOP):
        acq, tgt = CONTRIB_XL[key]
        inc = f"(B{r}>0)*(C{r}>0)"  # 0 = not entered: blank shares and ratio, left out of the range
        b.label(ws, f"A{r}", label, indent=1)
        b.calc(ws, f"B{r}", f"={acq}", USD)
        b.calc(ws, f"C{r}", f"={tgt}", USD)
        b.calc(ws, f"D{r}", f"=B{r}+C{r}", USD)
        b.calc(ws, f"E{r}", f'=IF({inc},B{r}/D{r},"")', PCT)
        b.calc(ws, f"F{r}", f'=IF({inc},C{r}/D{r},"")', PCT)
        b.calc(ws, f"G{r}", f'=IF({inc},C{r}/B{r}*Acq_Shares/Tgt_Shares,"")', RATIO)
    g, f = f"G{CT_TOP}:G{last}", f"F{CT_TOP}:F{last}"
    top = last + 2
    b.section(ws, top, "Range and Where the Deal Sits", 7)
    _rows(b, ws, [
        (top + 1, "Implied Exchange Ratio: Minimum", f"=MIN({g})", RATIO, "Contrib_Ratio_Min", False),
        (top + 2, "Implied Exchange Ratio: Maximum", f"=MAX({g})", RATIO, "Contrib_Ratio_Max", False),
        (top + 3, "Announced Exchange Ratio (Stock Election)", "=Exch_Ratio", RATIO, None, True),
        (top + 4, "Announced Ratio Position in Range (0% = Minimum, 100% = Maximum)",
         "=IF(Contrib_Ratio_Max>Contrib_Ratio_Min,(Exch_Ratio-Contrib_Ratio_Min)/(Contrib_Ratio_Max-Contrib_Ratio_Min),0)",
         PCT, "Contrib_Ratio_Pos", False),
        (top + 5, "Target Contribution: Minimum", f"=MIN({f})", PCT, "Contrib_Tgt_Min", False),
        (top + 6, "Target Contribution: Maximum", f"=MAX({f})", PCT, "Contrib_Tgt_Max", False),
        (top + 7, "Target Pro Forma Ownership", "=Own_Tgt", PCT, None, True),
        (top + 8, "Ownership Position in Range (0% = Minimum, 100% = Maximum)",
         "=IF(Contrib_Tgt_Max>Contrib_Tgt_Min,(Own_Tgt-Contrib_Tgt_Min)/(Contrib_Tgt_Max-Contrib_Tgt_Min),0)",
         PCT, "Contrib_Own_Pos", False),
    ])
    ws.freeze_panes = "B5"
    rng = f"Contribution!E{CT_TOP}:F{last}"
    return [("Contribution shares sum to 100% on every included metric",
             f"ABS(SUM({rng})-COUNT(Contribution!E{CT_TOP}:E{last}))>Check_Tol")]


def _breakeven(b):
    ws = b.sheet("Breakeven", "Breakeven Cost Saves and Year 1 Accretion Grid",
                 "$ in thousands. Saves only move pro forma net income, after tax, so the breakeven is closed form: "
                 "modeled saves less (pro forma EPS less standalone EPS) x pro forma shares / (1 - tax rate). "
                 "The grid is live formulas.",
                 {"A": 62, **{c: 14 for c in "BCDE"}})
    b.header(ws, 4, ["", "Value"])
    b.section(ws, 5, "Breakeven Cost Saves for 0% Year 1 EPS Accretion", 2)
    pf = {k: f"Pro_Forma!$B${PF[k]}" for k in ("acq", "tgt", "saves", "fund", "adj_pre", "acc_d", "sa_eps")}
    _rows(b, ws, [
        (6, "Modeled Year 1 Cost Saves (Pre-Tax, as Realized)", f"={pf['saves']}", USD, "BE_Modeled", False),
        (7, "Year 1 Accretion / (Dilution) per Share", f"={pf['acc_d']}", PS, None, False),
        (8, "Pro Forma Shares (Thousands)", "=Acq_Shares+New_Shares", NUM, None, False),
        (9, "Breakeven Year 1 Cost Saves (Pre-Tax, as Realized)", "=B6-B7*B8/(1-Tax_Rate)", USD, "BE_Saves", True),
        (10, "Breakeven Saves as % of Target Noninterest Expense", "=BE_Saves/Tgt_Nonint", PCT, "BE_Saves_Pct", False),
        (11, "Breakeven Run-Rate Saves % at the Modeled Year 1 Phase-In",
         '=IF(Phase_1>0,BE_Saves/(Tgt_Nonint*Phase_1),"n/a")', PCT, "BE_Run_Rate", True),
        (12, "Modeled Run-Rate Cost Saves (% of Target Noninterest Expense)", "=Saves_Pct", PCT, None, False),
        (13, "Cushion: Modeled Less Breakeven Year 1 Saves (Pre-Tax)", "=BE_Modeled-BE_Saves", USD, "BE_Cushion", False),
        (14, "Year 1 EPS Accretion at Breakeven Saves (Should Be 0%)",
         f"=({pf['acq']}+{pf['tgt']}+({pf['adj_pre']}-BE_Modeled+BE_Saves)*(1-Tax_Rate))/B8/{pf['sa_eps']}-1",
         PCT, "BE_Acc_Check", False),
    ])
    t = BE_GRID
    b.section(ws, t, "Year 1 EPS Accretion / (Dilution): Offer Price per Share (Down) by Year 1 Saves Realized, "
                     "% of Run-Rate (Across; Last Column = Modeled Phase-In)", 5)
    b.label(ws, f"A{t + 1}", "Offer Price per Target Share", indent=1)
    for c, ref in zip("BCDE", [f"Grid_Phase_{j + 1}" for j in range(len(GRID_PHASES))] + ["Phase_1"]):
        b.calc(ws, f"{c}{t + 1}", f"={ref}", PCT)
    # Only the offer price and Year 1 realization change; every other pre-tax adjustment is price independent.
    other = f"{pf['adj_pre']}-{pf['saves']}+{pf['fund']}"
    for i, k in enumerate(range(-2, 3)):
        r = t + 2 + i
        # Base offer in the middle row; each row out adds or takes one step.
        step = "" if k == 0 else f"{'+' if k > 0 else '-'}Offer_PPS*Grid_Price_Step"
        b.calc(ws, f"A{r}", f"={'Offer_PPS' if k == 0 else f'A{r - 1 if k > 0 else r + 1}'}{step}", PS)
        for c in "BCDE":
            b.calc(ws, f"{c}{r}",
                   f"=({pf['acq']}+{pf['tgt']}+({other}+Saves_Pct*Tgt_Nonint*{c}${t + 1}"
                   f"-Cost_Of_Cash*(1-Stock_Pct)*$A{r}*Tgt_Shares)*(1-Tax_Rate))"
                   f"/(Acq_Shares+Stock_Pct*$A{r}*Tgt_Shares/Acq_Price)/{pf['sa_eps']}-1", PCT)
    ws.freeze_panes = "B5"
    return [("Year 1 EPS accretion at breakeven cost saves is zero", "ABS(BE_Acc_Check)>Check_Tol"),
            ("Accretion grid at the base offer and modeled phase-in equals Year 1 accretion",
             f"ABS(Breakeven!E{t + 4}-PF_acc_pct_1)>Check_Tol")]


def _checks(b, extra):
    b.checks_sheet([
        ("Stock plus cash consideration equals aggregate price", "ABS(Stock_Cons+Cash_Cons-Deal_Price)>Check_Tol"),
        ("Ownership split sums to 100%", "ABS(Own_Acq+Own_Tgt-1)>Check_Tol"),
        ("Blended shares per target share times target shares equals new shares issued",
         "ABS(Blend_Ratio*Tgt_Shares-New_Shares)>Check_Tol"),
        ("Goodwill ties to price less TBV, after-tax marks and after-tax CDI",
         "ABS(Goodwill-(Deal_Price-Tgt_TBV-(Net_Marks+CDI)*(1-Tax_Rate)))>Check_Tol"),
        ("Goodwill is not negative (negative means a bargain purchase)", "Goodwill<0"),
        ("Restructuring securities sold do not exceed target securities", "Restr_Sold>Tgt_Secs"),
        ("PCD plus non-PCD credit mark equals gross credit mark", "ABS(PCD_Mark+NonPCD_Mark-Credit_Total)>Check_Tol"),
        ("Pro forma TCE ratio is between 0% and 100%", "(PF_TCE<=0)+(PF_TCE>=1)>0"),
        ("Pro forma TBV per share times shares equals pro forma TBV",
         "ABS(PF_TBVPS*(Acq_Shares+New_Shares)-PF_TBV)>Check_Tol"),
    ] + extra)


def _summary(b, case):
    ws = b.sheet("Summary", "Bank Merger Model Summary", "$ in thousands except per share", {"A": 44, "B": 18, "C": 60})
    meta = case["meta"]
    ws["A3"] = meta.get("name", "Merger Case")
    ws["A3"].font = Font(bold=True, size=12)
    if meta.get("illustrative"):
        ws["A4"] = "ILLUSTRATIVE CASE: made-up banks and round numbers, not real companies, not market data."
        ws["A4"].font = Font(bold=True, color="C00000")
    elif meta.get("source"):
        ws["A4"] = "Sources: " + meta["source"]
    b.master_check(ws)
    b.header(ws, 6, ["Key Outputs", "Value"])
    items = [
        ("Aggregate Price Paid", "=Deal_Price", USD), ("Offer Price per Target Share", "=Offer_PPS", PS),
        ("Price / Tangible Book Value", "=Price_TBV", MULT2), ("Price / Year 1 Earnings", "=Price_PE", '0.0"x"'),
        ("Goodwill Created", "=Goodwill", USD), ("Core Deposit Intangible", "=CDI", USD),
        ("Year 1 EPS Accretion / (Dilution)", "=PF_acc_pct_1", PCT),
        ("Year 2 EPS Accretion / (Dilution)", "=PF_acc_pct_2", PCT),
        ("TBV per Share Accretion / (Dilution) at Close", "=TBV_Dil_Pct", PCT),
        ("TBV Earnback (Years, -1 = Not Within 10)", "=Earnback_Years", '0.0'),
        ("Pro Forma TCE Ratio", "=PF_TCE", PCT),
        ("Ownership: Acquirer / Target", "=Own_Acq", PCT),
    ]
    for i, (label, formula, fmt) in enumerate(items):
        b.label(ws, f"A{7 + i}", label)
        b.calc(ws, f"B{7 + i}", formula, fmt, bold="Accretion" in label)
    b.calc(ws, f"C{7 + len(items) - 1}", "=Own_Tgt", PCT)
    r = 7 + len(items) + 1
    r = b.color_key(ws, r)
    b.header(ws, r, ["Sheets", "", ""])
    for i, (n, d) in enumerate([("Inputs", "All hard-coded assumptions"),
                                ("Purchase_Accounting", "Price, consideration, marks, CDI, goodwill"),
                                ("Pro_Forma", "EPS accretion, TBV per share, TCE ratio, ownership"),
                                ("Earnback", "TBV per share crossover"),
                                ("Sensitivity", "Accretion grids by price, cost saves and consideration mix, live formulas"),
                                ("Contribution", "Each side's share of earnings, capital, balance sheet and market cap"),
                                ("Breakeven", "Breakeven cost saves and live accretion grid by price and phase-in"),
                                ("Checks", "Live integrity checks, 0 means OK")]):
        b.label(ws, f"A{r + 1 + i}", n)
        b.label(ws, f"C{r + 1 + i}", d)


def build(case, path):
    b = Book()
    _summary(b, case)
    _inputs(b, case)
    _purchase(b, case)
    _pro_forma(b)
    _earnback(b)
    sens = _sensitivity(b)
    _extra_inputs(b, case)
    _checks(b, sens + _contribution(b) + _breakeven(b))
    return b.save(path)
