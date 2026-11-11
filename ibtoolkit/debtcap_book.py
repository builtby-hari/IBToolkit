"""Writes the debt capacity workbook: Summary, Inputs, Covenant, Capacity, Structure, Model, Rating,
Sensitivity, Checks.

Every calculated cell is a live formula. Hard-coded inputs live only on Inputs.
"""
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter as L

from .debtcap import NAMES, sensitivities
from .excel import MULT, MULT2, PCT, USD, Book
from .lbo import YEARS

PASS = '[=1]"Pass";[=0]"Fail"'
RATE = '0.00%'
COLS = [L(i) for i in range(2, 2 + YEARS + 1)]  # B = close, C..G = years 1..5

# Inputs: (name, label, (section, field), fmt)
SCALARS = [
    ("LTM_EBITDA", "LTM EBITDA", ("company", "ltm_ebitda"), USD),
    ("Max_Total_Lev", "Maximum Total Debt / EBITDA", ("limits", "max_total_leverage"), MULT),
    ("Max_Senior_Lev", "Maximum Senior Secured Debt / EBITDA (Term Loan B Plus Second Lien)",
     ("limits", "max_senior_leverage"), MULT),
    ("Min_Coverage", "Minimum EBITDA / Cash Interest", ("limits", "min_interest_coverage"), MULT),
    ("Min_FCF_Debt", "Minimum Cash Flow After Interest / Debt", ("limits", "min_fcf_to_debt"), PCT),
    ("Cushion", "Sizing Cushion (% Below the Binding Maximum)", ("limits", "cushion_pct"), PCT),
    ("TLB_Share", "Term Loan B (% of Total Debt)", ("term_loan_b", "share"), PCT),
    ("TLB_Rate", "Term Loan B All-In Interest Rate", ("term_loan_b", "rate"), RATE),
    ("TLB_Amort_Pct", "Term Loan B Mandatory Amortization (% of Original per Year)", ("term_loan_b", "amort_pct"), PCT),
    ("Sweep_Pct", "Term Loan B Cash Sweep (% of Cash Flow After Mandatory Amortization)",
     ("term_loan_b", "sweep_pct"), PCT),
    ("Notes_Share", "Senior Notes (% of Total Debt, Bullet)", ("senior_notes", "share"), PCT),
    ("Notes_Rate", "Senior Notes Interest Rate", ("senior_notes", "rate"), RATE),
    ("SL_Share", "Second Lien (% of Total Debt, Bullet)", ("second_lien", "share"), PCT),
    ("SL_Rate", "Second Lien Interest Rate", ("second_lien", "rate"), RATE),
    ("Haircut_Step", "Sensitivity Step for EBITDA Haircut", ("sensitivity", "haircut_step"), PCT),
    ("Rate_Step", "Sensitivity Step for Interest Rate Shift", ("sensitivity", "rate_step"), RATE),
    ("AB_Synergies", "Add-Back: Run-Rate Cost Synergies", ("covenant_ebitda", "synergies"), USD),
    ("AB_Restructuring", "Add-Back: Restructuring Charges", ("covenant_ebitda", "restructuring"), USD),
    ("AB_NonRecurring", "Add-Back: Non-Recurring Items", ("covenant_ebitda", "non_recurring"), USD),
    ("AB_ProForma", "Add-Back: Pro Forma Acquired EBITDA", ("covenant_ebitda", "pro_forma_acquisitions"), USD),
    ("AB_Other", "Add-Back: Other", ("covenant_ebitda", "other"), USD),
    ("Addback_Cap_Pct", "Cap on Total Add-Backs (% of Reported LTM EBITDA, Before Add-Backs)",
     ("covenant_ebitda", "cap_pct"), PCT),
    ("FC_Amount", "Free-and-Clear Basket: Fixed Amount", ("free_and_clear", "amount"), USD),
    ("FC_Pct", "Free-and-Clear Basket: % of Covenant EBITDA (Greater of the Two Applies)",
     ("free_and_clear", "pct_ebitda"), PCT),
]
AB_NAMES = [("AB_Synergies", "Run-Rate Cost Synergies"), ("AB_Restructuring", "Restructuring Charges"),
            ("AB_NonRecurring", "Non-Recurring Items"), ("AB_ProForma", "Pro Forma Acquired EBITDA"),
            ("AB_Other", "Other Add-Backs")]
SERIES = [
    ("ebitda", "Projected EBITDA", ("projections", "ebitda"), USD),
    ("capex", "Capex", ("projections", "capex"), USD),
    ("taxes", "Cash Taxes (Held Fixed, Not Re-Computed for Interest)", ("projections", "cash_taxes"), USD),
    ("nwc", "Increase in Net Working Capital", ("projections", "nwc_increase"), USD),
]
IN_FIRST = 5
IN_ROW = {s[0]: IN_FIRST + i for i, s in enumerate(SCALARS)}
IN_SERIES = IN_FIRST + len(SCALARS) + 2
IN_SROW = {s[0]: IN_SERIES + 1 + i for i, s in enumerate(SERIES)}
IN_GRID = IN_SERIES + len(SERIES) + 3  # header row; bands start on the next row

CAP_ROWS = {"total": 12, "senior": 13, "cov": 14, "fcf": 15}

R = {}


def _f(key, c):
    return f"{c}{R[key]}"


def _spec():
    f = _f

    def inp(k, c):
        return f"=Inputs!{c}{IN_SROW[k]}"

    return [
        ("sec", "Operating Cash Flow Build"),
        ("ebitda", "EBITDA", USD, lambda: "=LTM_EBITDA", lambda c, p: inp("ebitda", c), True),
        ("capex", "Less: Capex", USD, None, lambda c, p: inp("capex", c), False),
        ("taxes", "Less: Cash Taxes", USD, None, lambda c, p: inp("taxes", c), False),
        ("dnwc", "Less: Increase in NWC", USD, None, lambda c, p: inp("nwc", c), False),
        ("ufcf", "Cash Flow Before Debt Service", USD, None,
         lambda c, p: f"={f('ebitda', c)}-{f('capex', c)}-{f('taxes', c)}-{f('dnwc', c)}", True),
        ("sec", "Term Loan B Schedule"),
        ("t_beg", "Beginning Balance", USD, None, lambda c, p: f"={f('t_end', p)}", False),
        ("t_int", "Interest (on Beginning Balance)", USD, None, lambda c, p: f"={f('t_beg', c)}*TLB_Rate", False),
        ("t_mand", "Less: Mandatory Amortization", USD, None,
         lambda c, p: f"=MIN({f('t_beg', c)},TLB_Amort_Pct*TLB_0)", False),
        ("t_sweep", "Less: Cash Sweep", USD, None,
         lambda c, p: (f"=MIN({f('t_beg', c)}-{f('t_mand', c)},"
                       f"Sweep_Pct*MAX(0,{f('fcf', c)}-{f('t_mand', c)}))"), False),
        ("t_end", "Ending Balance", USD, lambda: "=TLB_0",
         lambda c, p: f"={f('t_beg', c)}-{f('t_mand', c)}-{f('t_sweep', c)}", True),
        ("sec", "Senior Notes Schedule (Bullet)"),
        ("n_beg", "Beginning Balance", USD, None, lambda c, p: f"={f('n_end', p)}", False),
        ("n_int", "Interest (on Beginning Balance)", USD, None, lambda c, p: f"={f('n_beg', c)}*Notes_Rate", False),
        ("n_end", "Ending Balance", USD, lambda: "=Notes_0", lambda c, p: f"={f('n_beg', c)}", True),
        ("sec", "Second Lien Schedule (Bullet)"),
        ("s_beg", "Beginning Balance", USD, None, lambda c, p: f"={f('s_end', p)}", False),
        ("s_int", "Interest (on Beginning Balance)", USD, None, lambda c, p: f"={f('s_beg', c)}*SL_Rate", False),
        ("s_end", "Ending Balance", USD, lambda: "=SL_0", lambda c, p: f"={f('s_beg', c)}", True),
        ("sec", "Cash Flow After Debt Service (Close Column Shows Pro Forma Annual Interest)"),
        ("int_tot", "Total Cash Interest", USD,
         lambda: f"={f('t_end', 'B')}*TLB_Rate+{f('n_end', 'B')}*Notes_Rate+{f('s_end', 'B')}*SL_Rate",
         lambda c, p: f"={f('t_int', c)}+{f('n_int', c)}+{f('s_int', c)}", False),
        ("fcf", "Cash Flow After Interest", USD, None,
         lambda c, p: f"={f('ufcf', c)}-{f('int_tot', c)}", True),
        ("retained", "Cash Flow Retained After Mandatory Amortization and Sweep", USD, None,
         lambda c, p: f"={f('fcf', c)}-{f('t_mand', c)}-{f('t_sweep', c)}", False),
        ("cum_cash", "Cumulative Cash Retained (Not Applied to Debt)", USD, lambda: "=0",
         lambda c, p: f"={f('cum_cash', p)}+{f('retained', c)}", False),
        ("sec", "Credit Statistics"),
        ("debt_tot", "Total Debt", USD,
         lambda: f"={f('t_end', 'B')}+{f('n_end', 'B')}+{f('s_end', 'B')}",
         lambda c, p: f"={f('t_end', c)}+{f('n_end', c)}+{f('s_end', c)}", True),
        ("sec_tot", "Senior Secured Debt (Term Loan B and Second Lien)", USD,
         lambda: f"={f('t_end', 'B')}+{f('s_end', 'B')}",
         lambda c, p: f"={f('t_end', c)}+{f('s_end', c)}", False),
        ("lev_tot", "Total Debt / EBITDA", MULT, lambda: f"={f('debt_tot', 'B')}/{f('ebitda', 'B')}",
         lambda c, p: f"={f('debt_tot', c)}/{f('ebitda', c)}", False),
        ("lev_sen", "Senior Secured Debt / EBITDA", MULT, lambda: f"={f('sec_tot', 'B')}/{f('ebitda', 'B')}",
         lambda c, p: f"={f('sec_tot', c)}/{f('ebitda', c)}", False),
        ("cov_ebitda", "Covenant EBITDA (Close: Capped Adjusted LTM; Years: Projected)", USD,
         lambda: "=Covenant_EBITDA", lambda c, p: f"={f('ebitda', c)}", False),
        ("lev_cov", "Total Debt / Covenant EBITDA (Leverage Test Basis)", MULT,
         lambda: f"={f('debt_tot', 'B')}/{f('cov_ebitda', 'B')}",
         lambda c, p: f"={f('debt_tot', c)}/{f('cov_ebitda', c)}", False),
        ("sen_cov", "Senior Secured Debt / Covenant EBITDA (Leverage Test Basis)", MULT,
         lambda: f"={f('sec_tot', 'B')}/{f('cov_ebitda', 'B')}",
         lambda c, p: f"={f('sec_tot', c)}/{f('cov_ebitda', c)}", False),
        ("cov", "EBITDA / Cash Interest", MULT,
         lambda: f"=IF({f('int_tot', 'B')}>0,{f('ebitda', 'B')}/{f('int_tot', 'B')},0)",
         lambda c, p: f"=IF({f('int_tot', c)}>0,{f('ebitda', c)}/{f('int_tot', c)},0)", False),
        ("cov_capex", "(EBITDA - Capex) / Cash Interest", MULT, None,
         lambda c, p: f"=IF({f('int_tot', c)}>0,({f('ebitda', c)}-{f('capex', c)})/{f('int_tot', c)},0)", False),
        ("fcf_debt", "Cash Flow After Interest / Beginning Debt (Close Column Shows Year 1)", PCT,
         lambda: f"={f('fcf_debt', 'C')}",
         lambda c, p: f"=IF({f('debt_tot', p)}>0,{f('fcf', c)}/{f('debt_tot', p)},0)", False),
        ("sec", "Limit Tests (Binding Constraint Respected When All Pass)"),
        ("lev_ok", "Total Leverage Within Limit", PASS,
         lambda: f"=IF({f('lev_cov', 'B')}<=Max_Total_Lev+Check_Tol,1,0)",
         lambda c, p: f"=IF({f('lev_cov', c)}<=Max_Total_Lev+Check_Tol,1,0)", False),
        ("sen_ok", "Senior Secured Leverage Within Limit", PASS,
         lambda: f"=IF({f('sen_cov', 'B')}<=Max_Senior_Lev+Check_Tol,1,0)",
         lambda c, p: f"=IF({f('sen_cov', c)}<=Max_Senior_Lev+Check_Tol,1,0)", False),
        ("cov_ok", "Interest Coverage Within Limit", PASS,
         lambda: f"=IF({f('int_tot', 'B')}>0,IF({f('cov', 'B')}>=Min_Coverage-Check_Tol,1,0),1)",
         lambda c, p: f"=IF({f('int_tot', c)}>0,IF({f('cov', c)}>=Min_Coverage-Check_Tol,1,0),1)", False),
        ("fcf_ok", "FCF / Debt Within Limit", PASS, lambda: f"={f('fcf_ok', 'C')}",
         lambda c, p: f"=IF({f('debt_tot', p)}>0,IF({f('fcf_debt', c)}>=Min_FCF_Debt-Check_Tol,1,0),1)", False),
        ("all_ok", "All Limits Met", PASS,
         lambda: f"={f('lev_ok', 'B')}*{f('sen_ok', 'B')}*{f('cov_ok', 'B')}*{f('fcf_ok', 'B')}",
         lambda c, p: f"={f('lev_ok', c)}*{f('sen_ok', c)}*{f('cov_ok', c)}*{f('fcf_ok', c)}", True),
        ("fail_any", "Any Limit Failed (1 = Yes)", "0", None, lambda c, p: f"=1-{f('all_ok', c)}", False),
        ("sec", "Deleveraging Path"),
        ("paid", "Cumulative Debt Repaid", USD, None, lambda c, p: f"={f('debt_tot', 'B')}-{f('debt_tot', c)}", False),
        ("pct_paid", "Debt Repaid (% of Closing Debt)", PCT, None,
         lambda c, p: f"=IF({f('debt_tot', 'B')}>0,{f('paid', c)}/{f('debt_tot', 'B')},0)", False),
        ("turns", "Turns of Leverage Removed Since Close", MULT, None,
         lambda c, p: f"={f('lev_tot', 'B')}-{f('lev_tot', c)}", False),
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
                 {"A": 62, **{c: 14 for c in COLS}})
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
    b.header(ws, IN_GRID, ["Illustrative Rating Grid (Best Band First)", "Max Debt / EBITDA", "Min EBITDA / Interest"])
    for i, g in enumerate(case["rating_grid"]):
        r = IN_GRID + 1 + i
        b.inp(ws, f"A{r}", g["rating"], "@")
        ws[f"A{r}"].alignment = Alignment(horizontal="left")
        b.inp(ws, f"B{r}", g["max_leverage"], MULT2)
        b.inp(ws, f"C{r}", g["min_coverage"], MULT2)
    ws.freeze_panes = "B5"


def _capacity(b):
    ws = b.sheet("Capacity", "Debt Capacity at Close",
                 "$ in thousands. Each constraint is solved for total debt, then the lowest one binds.",
                 {"A": 78, "B": 16, "C": 16, "D": 18})
    b.section(ws, 5, "Sizing Drivers", 4)
    drivers = [
        (6, "LTM EBITDA", "=LTM_EBITDA", USD, None),
        (7, "Year 1 Cash Flow Before Debt Service", f"=Model!C{R['ufcf']}", USD, "Y1_CF"),
        (8, "Blended Interest Rate (Weighted by Share of Debt)",
         "=TLB_Share*TLB_Rate+Notes_Share*Notes_Rate+SL_Share*SL_Rate", RATE, "Blended_Rate"),
        (9, "Senior Secured Share of Debt (Term Loan B Plus Second Lien)", "=TLB_Share+SL_Share", PCT, "Secured_Share"),
    ]
    for r, label, formula, fmt, name in drivers:
        b.label(ws, f"A{r}", label, indent=1)
        b.calc(ws, f"B{r}", formula, fmt, name=name)
    b.section(ws, 10, "Maximum Total Debt by Constraint", 4)
    b.header(ws, 11, ["Constraint", "Maximum Debt", "x LTM EBITDA", "Lowest (1 = Yes)"])
    rows = [
        ("total", "Total Leverage: Maximum Debt / EBITDA Times Covenant EBITDA", "=Max_Total_Lev*Covenant_EBITDA",
         "Max_By_Total"),
        ("senior", "Senior Secured Leverage: Maximum Senior / EBITDA Times Covenant EBITDA Over Secured Share",
         "=Max_Senior_Lev*Covenant_EBITDA/Secured_Share", "Max_By_Senior"),
        ("cov", "Interest Coverage: Reported (Cash) LTM EBITDA Over Minimum Coverage Times Blended Rate",
         "=LTM_EBITDA/(Min_Coverage*Blended_Rate)", "Max_By_Coverage"),
        ("fcf", "FCF / Debt: Year 1 Cash Flow Over Minimum Ratio Plus Blended Rate",
         "=MAX(0,Y1_CF)/(Min_FCF_Debt+Blended_Rate)", "Max_By_FCF"),
    ]
    for key, label, formula, name in rows:
        r = CAP_ROWS[key]
        b.label(ws, f"A{r}", label, indent=1)
        b.calc(ws, f"B{r}", formula, USD, name=name)
        b.calc(ws, f"C{r}", f"=B{r}/LTM_EBITDA", MULT2)
        b.calc(ws, f"D{r}", f"=IF(B{r}=Max_Debt,1,0)", "0")
    first, last = CAP_ROWS["total"], CAP_ROWS["fcf"]
    out = [
        (17, "Maximum Total Debt (Lowest of the Four)", f"=MIN(B{first}:B{last})", USD, "Max_Debt", True),
        (18, "Binding Constraint",
         (f'=IF(B{first}=Max_Debt,"{NAMES[0]}",IF(B{first + 1}=Max_Debt,"{NAMES[1]}",'
          f'IF(B{first + 2}=Max_Debt,"{NAMES[2]}","{NAMES[3]}")))'), "@", "Binding_Name", True),
        (19, "Maximum Debt at the Named Binding Constraint",
         (f'=IF(Binding_Name="{NAMES[0]}",B{first},IF(Binding_Name="{NAMES[1]}",B{first + 1},'
          f'IF(Binding_Name="{NAMES[2]}",B{first + 2},B{last})))'), USD, "Binding_Max", False),
        (20, "Sizing Cushion (% Below the Binding Maximum)", "=Cushion", PCT, None, False),
        (21, "Proposed Total Debt", "=Max_Debt*(1-Cushion)", USD, "Proposed_Debt", True),
        (22, "Proposed Total Debt / LTM EBITDA", "=Proposed_Debt/LTM_EBITDA", MULT2, None, False),
    ]
    for r, label, formula, fmt, name, bold in out:
        b.label(ws, f"A{r}", label, bold=bold)
        b.calc(ws, f"B{r}", formula, fmt, name=name, bold=bold, total=(r in (17, 21)))
    ws.freeze_panes = "B5"


def _covenant(b):
    ws = b.sheet("Covenant", "Covenant EBITDA Bridge and Test Basis",
                 "$ in thousands. Add-backs are capped at a % of reported LTM EBITDA. Leverage tests use the "
                 "capped figure; coverage and FCF tests use cash EBITDA.",
                 {"A": 78, "B": 18, "C": 18, "D": 16})
    b.header(ws, 4, ["Covenant EBITDA Bridge", "Amount", "% of Reported EBITDA"])
    rows = [(5, "Reported (Unadjusted) LTM EBITDA", "=LTM_EBITDA", None, True)]
    rows += [(6 + i, f"Add: {label}", f"={n}", None, False) for i, (n, label) in enumerate(AB_NAMES)]
    rows += [
        (11, "Total Add-Backs Before Cap", "=SUM(B6:B10)", "Addbacks_Total", False),
        (12, "Adjusted EBITDA Before Cap (Uncapped)", "=B5+B11", "Uncapped_EBITDA", True),
        (13, "Add-Back Cap: Cap % Times Reported LTM EBITDA", "=Addback_Cap_Pct*LTM_EBITDA", "Addback_Cap", False),
        (14, "Add-Backs Allowed (Lower of Total and Cap)", "=MIN(Addbacks_Total,Addback_Cap)", "Addbacks_Allowed",
         False),
        (15, "Add-Backs Excluded by the Cap", "=Addbacks_Total-Addbacks_Allowed", None, False),
        (16, "Covenant EBITDA (Capped Adjusted)", "=LTM_EBITDA+Addbacks_Allowed", "Covenant_EBITDA", True),
    ]
    for r, label, formula, name, bold in rows:
        b.label(ws, f"A{r}", label, bold=bold, indent=0 if bold else 1)
        b.calc(ws, f"B{r}", formula, USD, name=name, bold=bold, total=r in (12, 16))
        b.calc(ws, f"C{r}", f"=B{r}/LTM_EBITDA", PCT, bold=bold)
    b.label(ws, "A17", "Cap Binds (1 = Yes)", indent=1)
    b.calc(ws, "B17", "=IF(Addbacks_Total>Addback_Cap,1,0)", "0")
    b.section(ws, 19, "EBITDA Basis by Test (Leverage on Covenant EBITDA, Cash Tests on Cash EBITDA)", 4)
    for r, label, formula in [(20, "Leverage Tests (Total and Senior Secured): Covenant EBITDA", "=Covenant_EBITDA"),
                              (21, "Interest Coverage Test: Reported (Cash) LTM EBITDA", "=LTM_EBITDA"),
                              (22, "FCF / Debt Test: Year 1 Cash Flow From Projected (Cash) EBITDA", "=Y1_CF")]:
        b.label(ws, f"A{r}", label, indent=1)
        b.calc(ws, f"B{r}", formula, USD)
    b.section(ws, 24, "Maximum Debt: Reported EBITDA vs Covenant EBITDA", 4)
    b.header(ws, 25, ["Constraint", "On Reported EBITDA", "On Covenant EBITDA", "Change"])
    cmp_rows = [(26, NAMES[0], "=Max_Total_Lev*LTM_EBITDA", "=Max_By_Total"),
                (27, NAMES[1], "=Max_Senior_Lev*LTM_EBITDA/Secured_Share", "=Max_By_Senior"),
                (28, NAMES[2], "=Max_By_Coverage", "=Max_By_Coverage"),
                (29, NAMES[3], "=Max_By_FCF", "=Max_By_FCF")]
    for r, label, rep_f, cov_f in cmp_rows:
        b.label(ws, f"A{r}", label, indent=1)
        b.calc(ws, f"B{r}", rep_f, USD)
        b.calc(ws, f"C{r}", cov_f, USD)
        b.calc(ws, f"D{r}", f"=C{r}-B{r}", USD)
    b.label(ws, "A30", "Maximum Total Debt (Lowest of the Four)", bold=True)
    b.calc(ws, "B30", "=MIN(B26:B29)", USD, name="Max_Debt_Reported", bold=True, total=True)
    b.calc(ws, "C30", "=Max_Debt", USD, bold=True, total=True)
    b.calc(ws, "D30", "=C30-B30", USD, name="Addback_Debt_Change", bold=True, total=True)
    b.section(ws, 32, "Free-and-Clear Basket (Incremental Debt Permitted Regardless of Leverage)", 4)
    fc = [(33, "Fixed Amount", "=FC_Amount", None, False),
          (34, "% of Covenant EBITDA Times Covenant EBITDA", "=FC_Pct*Covenant_EBITDA", None, False),
          (35, "Free-and-Clear Basket (Greater of the Two)", "=MAX(B33,B34)", "Free_Clear", True),
          (36, "Maximum Debt Plus Free-and-Clear Basket (Cash Tests Not Re-Run; Not in Proposed Debt)",
           "=Max_Debt+Free_Clear", "Max_Debt_With_FC", True)]
    for r, label, formula, name, bold in fc:
        b.label(ws, f"A{r}", label, bold=bold, indent=0 if bold else 1)
        b.calc(ws, f"B{r}", formula, USD, name=name, bold=bold, total=r == 35)
    ws.freeze_panes = "B5"


def _structure(b):
    ws = b.sheet("Structure", "Proposed Capital Structure at Close",
                 "$ in thousands. Each tranche is its input share of the proposed total debt.",
                 {"A": 34, "B": 14, "C": 14, "D": 14, "E": 14, "F": 16, "G": 20})
    b.header(ws, 4, ["Tranche", "Amount", "x LTM EBITDA", "% of Total", "Interest Rate", "Annual Interest",
                     "Cumulative x EBITDA"])
    tr = [("Term Loan B", "=TLB_Share*Proposed_Debt", "TLB_0", "TLB_Rate"),
          ("Senior Notes", "=Notes_Share*Proposed_Debt", "Notes_0", "Notes_Rate"),
          ("Second Lien", "=SL_Share*Proposed_Debt", "SL_0", "SL_Rate")]
    for i, (label, formula, name, rate) in enumerate(tr):
        r = 5 + i
        b.label(ws, f"A{r}", label, indent=1)
        b.calc(ws, f"B{r}", formula, USD, name=name)
        b.calc(ws, f"C{r}", f"=B{r}/LTM_EBITDA", MULT2)
        b.calc(ws, f"D{r}", f"=IF(Total_Debt_0>0,B{r}/Total_Debt_0,0)", PCT)
        b.calc(ws, f"E{r}", f"={rate}", RATE)
        b.calc(ws, f"F{r}", f"=B{r}*E{r}", USD)
        b.calc(ws, f"G{r}", f"=SUM(B$5:B{r})/LTM_EBITDA", MULT2)
    b.label(ws, "A8", "Total Debt", bold=True)
    b.calc(ws, "B8", "=SUM(B5:B7)", USD, name="Total_Debt_0", bold=True, total=True)
    b.calc(ws, "C8", "=B8/LTM_EBITDA", MULT2, bold=True, total=True)
    b.calc(ws, "D8", "=SUM(D5:D7)", PCT, bold=True, total=True)
    b.calc(ws, "E8", "=IF(B8>0,F8/B8,0)", RATE, bold=True, total=True)
    b.calc(ws, "F8", "=SUM(F5:F7)", USD, bold=True, total=True)
    ws.freeze_panes = "B5"


def _model(b):
    ws = b.sheet("Model", "Five-Year Debt Schedule, Credit Statistics and Deleveraging",
                 "$ in thousands. Year-end timing. Interest on beginning balances, so no circular references.",
                 {"A": 70, **{c: 14 for c in COLS}})
    b.header(ws, 4, ["", *range(YEARS + 1)])
    ws["B4"].number_format = '"Close"'
    row = MODEL_FIRST
    for s in SPEC:
        if s[0] == "sec":
            b.section(ws, row, s[1], len(COLS) + 1)
        else:
            _, label, fmt, close, yr, bold = s
            b.label(ws, f"A{row}", label, bold=bold, indent=0 if bold else 1)
            if close:
                b.calc(ws, f"B{row}", close(), fmt, bold=bold)
            if yr:
                for i in range(1, YEARS + 1):
                    b.calc(ws, f"{COLS[i]}{row}", yr(COLS[i], COLS[i - 1]), fmt, bold=bold)
        row += 1
    ws.freeze_panes = "B5"


def _chain(flags, names, last):
    """Nested IF that returns the first name whose flag is 0, else the last label."""
    out = f'"{last}"'
    for fl, nm in reversed(list(zip(flags, names))):
        out = f"IF({fl}=0,{nm},{out})"
    return out


def _rating(b, case):
    n = len(case["rating_grid"])
    ws = b.sheet("Rating", "Indicative Rating Band",
                 "Illustrative leverage and coverage bands from Inputs. A band is met when both tests pass; "
                 "the indicative rating is the best band met. Not a rating agency methodology.",
                 {"A": 70, **{c: 14 for c in COLS}})
    b.header(ws, 4, ["", *range(YEARS + 1)])
    ws["B4"].number_format = '"Close"'
    for r, label, key, fmt in [(5, "Total Debt / EBITDA", "lev_tot", MULT), (6, "EBITDA / Cash Interest", "cov", MULT),
                               (7, "Total Cash Interest", "int_tot", USD)]:
        b.label(ws, f"A{r}", label, indent=1)
        for c in COLS:
            b.calc(ws, f"{c}{r}", f"=Model!{c}{R[key]}", fmt)
    lf0 = 9
    cf0 = lf0 + n + 1
    out0 = cf0 + n + 1
    b.section(ws, lf0 - 1, "Leverage Test Fails by Band (1 = Debt / EBITDA Above the Band Maximum)", len(COLS) + 1)
    b.section(ws, cf0 - 1, "Coverage Test Fails by Band (1 = Coverage Below the Band Minimum)", len(COLS) + 1)
    b.section(ws, out0 - 1, "Indicative Rating", len(COLS) + 1)
    for i in range(n):
        ir = IN_GRID + 1 + i
        b.label(ws, f"A{lf0 + i}", f"Band {i + 1}: Leverage Test Fails", indent=1)
        b.label(ws, f"A{cf0 + i}", f"Band {i + 1}: Coverage Test Fails", indent=1)
        for c in COLS:
            b.calc(ws, f"{c}{lf0 + i}", f"=IF({c}$5>Inputs!$B${ir},1,0)", "0")
            b.calc(ws, f"{c}{cf0 + i}", f"=IF({c}$7>0,IF({c}$6<Inputs!$C${ir},1,0),0)", "0")
    names = [f"Inputs!$A${IN_GRID + 1 + i}" for i in range(n)]
    last = f"Below {case['rating_grid'][-1]['rating']}"
    kinds = [("Leverage-Implied Rating", lambda c: [f"{c}{lf0 + i}" for i in range(n)]),
             ("Coverage-Implied Rating", lambda c: [f"{c}{cf0 + i}" for i in range(n)]),
             ("Indicative Rating (Best Band Where Both Tests Pass)",
              lambda c: [f"MAX({c}{lf0 + i},{c}{cf0 + i})" for i in range(n)])]
    for k, (label, flags) in enumerate(kinds):
        r = out0 + k
        b.label(ws, f"A{r}", label, bold=(k == 2))
        for c in COLS:
            b.calc(ws, f"{c}{r}", "=" + _chain(flags(c), names, last), "@", bold=(k == 2))
    b.name(ws, f"B{out0 + 2}", "Rating_Close")
    b.name(ws, f"{COLS[-1]}{out0 + 2}", "Rating_Final")
    ws.freeze_panes = "B5"


GRID_TOPS = (4, 13)
GRID_COLS = "BCDEF"
SHIFT_FMT = '0.00%;-0.00%;0.00%'


def _sensitivity(b, case):
    s = sensitivities(case)
    ws = b.sheet("Sensitivity", "Maximum Debt Sensitivities",
                 "Grid 1 is live formulas. Grid 2 is static Python values; rerun the CLI to refresh. "
                 "Haircuts cut LTM and Year 1 EBITDA only; capex, taxes and NWC stay as input. "
                 "Rate shifts move every tranche. Axes are the base case plus fixed steps, not market views.",
                 {"A": 34, **{c: 24 for c in GRID_COLS}})
    top = GRID_TOPS[0]
    b.section(ws, top, "Grid 1, Live Formulas: Maximum Debt, EBITDA Haircut (Down) by Interest Rate Shift (Across)", 6)
    ax = top + 1
    b.calc(ws, f"D{ax}", "=0", SHIFT_FMT)
    b.calc(ws, f"C{ax}", f"=D{ax}-Rate_Step", SHIFT_FMT)
    b.calc(ws, f"B{ax}", f"=C{ax}-Rate_Step", SHIFT_FMT)
    b.calc(ws, f"E{ax}", f"=D{ax}+Rate_Step", SHIFT_FMT)
    b.calc(ws, f"F{ax}", f"=E{ax}+Rate_Step", SHIFT_FMT)
    first = top + 2
    b.calc(ws, f"A{first}", "=0", '0.0%')
    for r in range(first + 1, first + 5):
        b.calc(ws, f"A{r}", f"=A{r - 1}+Haircut_Step", '0.0%')
    for r in range(first, first + 5):
        for c in GRID_COLS:
            e = f"LTM_EBITDA*(1-$A{r})"
            el = f"Covenant_EBITDA*(1-$A{r})"
            rate = f"(Blended_Rate+{c}${ax})"
            cf = f"MAX(0,Y1_CF-$A{r}*Model!$C${R['ebitda']})"
            b.calc(ws, f"{c}{r}",
                   (f"=MAX(0,MIN(Max_Total_Lev*{el},Max_Senior_Lev*{el}/Secured_Share,"
                    f"{e}/(Min_Coverage*{rate}),{cf}/(Min_FCF_Debt+{rate})))"), USD)
    top = GRID_TOPS[1]
    b.section(ws, top, "Grid 2, Static Python Values: Binding Constraint, EBITDA Haircut (Down) by "
                       "Interest Rate Shift (Across)", 6)
    for j, x in enumerate(s["shift_axis"]):
        b.static(ws, f"{GRID_COLS[j]}{top + 1}", x, SHIFT_FMT)
    for i, x in enumerate(s["haircut_axis"]):
        b.static(ws, f"A{top + 2 + i}", x, '0.0%')
        for j, v in enumerate(s["binding"][i]):
            b.static(ws, f"{GRID_COLS[j]}{top + 2 + i}", v, "@")
    ws.freeze_panes = "B4"


def _checks(b):
    def rng(key):
        return f"Model!{COLS[1]}{R[key]}:{COLS[-1]}{R[key]}"

    cap = [f"Max_By_{k}" for k in ("Total", "Senior", "Coverage", "FCF")]
    g1 = GRID_TOPS[0] + 2
    g2 = GRID_TOPS[1] + 2
    b.checks_sheet([
        ("Tranches sum to proposed total debt", "ABS(Total_Debt_0-Proposed_Debt)>Check_Tol"),
        ("Tranche shares sum to 100%", "ABS(TLB_Share+Notes_Share+SL_Share-1)>Check_Tol"),
        ("Proposed debt is within every constraint maximum",
         "(" + ")+(".join(f"Proposed_Debt>{n}+Check_Tol" for n in cap) + ")>0"),
        ("Named binding constraint is the lowest maximum", "ABS(Binding_Max-Max_Debt)>Check_Tol"),
        ("Total debt never negative", f"MIN(Model!B{R['debt_tot']}:{COLS[-1]}{R['debt_tot']})<-Check_Tol"),
        ("Term loan rolls: opening less repayments equals ending",
         f"ABS(Model!{COLS[-1]}{R['t_end']}-(TLB_0-SUM({rng('t_mand')})-SUM({rng('t_sweep')})))>Check_Tol"),
        ("Cash flow after interest covers mandatory amortization every year",
         f"MIN({rng('retained')})<-Check_Tol"),
        ("Binding constraint respected at close: all four limit tests pass", f"Model!B{R['all_ok']}=0"),
        ("Binding constraint respected in each of the five years: all four limit tests pass",
         f"SUM({rng('fail_any')})>0"),
        ("Maximum debt grid base cell matches maximum debt", f"ABS(Sensitivity!D{g1}-Max_Debt)>Check_Tol"),
        ("Binding constraint grid base cell matches the binding constraint (rerun the CLI if not)",
         f"Sensitivity!D{g2}<>Binding_Name"),
        ("Allowed add-backs within the cap and within total add-backs",
         "(Addbacks_Allowed>Addback_Cap+Check_Tol)+(Addbacks_Allowed>Addbacks_Total+Check_Tol)>0"),
        ("Covenant EBITDA between reported and uncapped adjusted EBITDA",
         "(Covenant_EBITDA<LTM_EBITDA-Check_Tol)+(Covenant_EBITDA>Uncapped_EBITDA+Check_Tol)>0"),
        ("Add-backs never lower maximum debt (reported basis at or below covenant basis)",
         "Max_Debt_Reported>Max_Debt+Check_Tol"),
    ])


def _summary(b, case):
    ws = b.sheet("Summary", "Debt Capacity Summary", "$ in thousands", {"A": 44, "B": 24, "C": 60})
    meta = case["meta"]
    ws["A3"] = meta.get("name", "Debt Capacity Case")
    ws["A3"].font = Font(bold=True, size=12)
    if meta.get("illustrative"):
        ws["A4"] = "ILLUSTRATIVE CASE: round numbers, not a real company, not market data."
        ws["A4"].font = Font(bold=True, color="C00000")
    b.master_check(ws)
    b.header(ws, 6, ["Key Outputs", "Value"])
    last = COLS[-1]
    items = [
        ("Reported LTM EBITDA", "=LTM_EBITDA", USD),
        ("Covenant EBITDA (Capped Adjusted)", "=Covenant_EBITDA", USD),
        ("Maximum Total Debt on Reported EBITDA", "=Max_Debt_Reported", USD),
        ("Maximum Total Debt", "=Max_Debt", USD),
        ("Change in Maximum Debt From Add-Backs", "=Addback_Debt_Change", USD),
        ("Free-and-Clear Basket", "=Free_Clear", USD),
        ("Binding Constraint", "=Binding_Name", "@"),
        ("Proposed Total Debt", "=Proposed_Debt", USD),
        ("Total Debt / LTM EBITDA at Close", f"=Model!B{R['lev_tot']}", MULT2),
        ("Senior Secured Debt / LTM EBITDA at Close", f"=Model!B{R['lev_sen']}", MULT2),
        ("EBITDA / Cash Interest at Close", f"=Model!B{R['cov']}", MULT2),
        ("Indicative Rating at Close", "=Rating_Close", "@"),
        ("Indicative Rating in Year 5", "=Rating_Final", "@"),
        ("Total Debt / EBITDA in Year 5", f"=Model!{last}{R['lev_tot']}", MULT2),
        ("Debt Repaid by Year 5 (% of Closing Debt)", f"=Model!{last}{R['pct_paid']}", PCT),
        ("Limit Tests Failed (Years 1 to 5)", f"=SUM(Model!C{R['fail_any']}:{last}{R['fail_any']})", '0'),
    ]
    for i, (label, formula, fmt) in enumerate(items):
        b.label(ws, f"A{7 + i}", label)
        b.calc(ws, f"B{7 + i}", formula, fmt, bold=label.startswith("Proposed"))
    r = 7 + len(items) + 1
    r = b.color_key(ws, r, static=True)
    b.header(ws, r, ["Sheets", "", ""])
    for i, (n, d) in enumerate([("Inputs", "All hard-coded assumptions, including the illustrative rating grid"),
                                ("Covenant", "Covenant EBITDA bridge, test basis, reported vs adjusted capacity"),
                                ("Capacity", "Maximum debt by constraint and the binding one"),
                                ("Structure", "Proposed debt by tranche"),
                                ("Model", "Five-year debt schedule, credit statistics, limit tests, deleveraging"),
                                ("Rating", "Indicative rating band by year"),
                                ("Sensitivity", "Maximum debt by EBITDA haircut and rate shift"),
                                ("Checks", "Live integrity checks, 0 means OK")]):
        b.label(ws, f"A{r + 1 + i}", n)
        b.label(ws, f"C{r + 1 + i}", d)


def build(case, path):
    b = Book()
    _summary(b, case)
    _inputs(b, case)
    _covenant(b)
    _capacity(b)
    _structure(b)
    _model(b)
    _rating(b, case)
    _sensitivity(b, case)
    _checks(b)
    return b.save(path)
