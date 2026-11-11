"""Precedent transactions: deal rows, statistics, recency filter and implied target value.

Money is in $ millions. Two kinds of deal set: "corporate" (EV / LTM revenue, EV / LTM EBITDA) and
"bank" (P / TBV paid, P / LTM EPS paid, core deposit premium). The Precedents sheet mirrors the
Python here with live formulas, so both give the same numbers.

Core deposit premium = (price paid less tangible book value) / core deposits, as a decimal.
Multiples are inputs as reported by the source (press release, 8-K deck or proxy fairness
summary). A deal with no reported figure for a metric is left out of that metric.
"""
import datetime as dt
from statistics import mean, median

from openpyxl.styles import Alignment, Font

from .comps import implied, percentile
from .excel import MULT, MULT2, PCT, Book
from .lbo import CaseError, _check

# (key, label, check kind, number format)
KINDS = {
    "corporate": [("ev_rev_ltm", "EV / LTM Revenue", "pos", MULT2),
                  ("ev_ebitda_ltm", "EV / LTM EBITDA", "pos", MULT)],
    "bank": [("ptbv", "P / TBV Paid", "pos", MULT2),
             ("pe_ltm", "P / LTM EPS Paid", "pos", MULT),
             ("cdp", "Core Deposit Premium", "num", PCT)],
}
MIN_DEALS = 3
NA = "n/a"
DATE = "yyyy-mm-dd"
NUM1 = "#,##0.0"
STATS = [("mean", "Mean", "AVERAGE({})"), ("median", "Median", "MEDIAN({})"),
         ("p25", "25th Percentile", "PERCENTILE({},0.25)"), ("p75", "75th Percentile", "PERCENTILE({},0.75)"),
         ("high", "High", "MAX({})"), ("low", "Low", "MIN({})")]


def _date(v, path):
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    try:
        return dt.date.fromisoformat(str(v))
    except ValueError:
        raise CaseError(f"Invalid input {path}: must be a date like 2025-07-18 (got {v!r})") from None


def edate(d, months):
    """Same as Excel EDATE: months are truncated to a whole number, the day is clamped to month end."""
    m = d.year * 12 + d.month - 1 + int(months)
    y, mo = divmod(m, 12)
    mo += 1
    nxt = dt.date(y + (mo == 12), mo % 12 + 1, 1)
    return dt.date(y, mo, min(d.day, (nxt - dt.timedelta(days=1)).day))


def cutoff(prec):
    """Earliest included announce date, or None when the recency filter is off."""
    return edate(prec["as_of"], -12 * prec["max_age_years"]) if prec["max_age_years"] else None


def included(prec):
    c = cutoff(prec)
    return [d for d in prec["deals"] if c is None or d["date"] >= c]


def values(prec, key):
    return [d[key] for d in included(prec) if d.get(key) is not None]


def validate(raw, kind):
    """Clean [precedents] section, or a CaseError naming the field."""
    if not isinstance(raw, dict) or not isinstance(raw.get("deals"), list):
        raise CaseError("Missing required input: precedents.deals")
    if "as_of" not in raw:
        raise CaseError("Missing required input: precedents.as_of")
    spec = KINDS[kind]
    p = {"as_of": _date(raw["as_of"], "precedents.as_of"),
         "max_age_years": _check("precedents.max_age_years", raw.get("max_age_years", 0), "nonneg"),
         "note": str(raw.get("note", "")), "deals": []}
    cd = raw.get("target_core_deposits")
    p["target_core_deposits"] = None if cd is None else _check("precedents.target_core_deposits", cd, "pos")
    for i, d in enumerate(raw["deals"]):
        path = f"precedents.deals[{i}]"
        for f in ("date", "acquirer", "target", "deal_value"):
            if f not in d:
                raise CaseError(f"Missing required input: {path}.{f}")
        row = {"date": _date(d["date"], f"{path}.date"), "acquirer": str(d["acquirer"]), "target": str(d["target"]),
               "deal_value": _check(f"{path}.deal_value", d["deal_value"], "pos"), "source": str(d.get("source", ""))}
        if row["date"] > p["as_of"]:
            raise CaseError(f"Invalid input {path}.date: after precedents.as_of")
        for key, _, ck, _ in spec:
            row[key] = None if d.get(key) is None else _check(f"{path}.{key}", d[key], ck)
        p["deals"].append(row)
    p["metrics"], p["skipped"] = [], []
    for key, label, _, _ in spec:
        n = len(values(p, key))
        if n < MIN_DEALS:
            p["skipped"].append(f"{label}: {n} deal(s) with a figure, need {MIN_DEALS}")
        elif key == "cdp" and p["target_core_deposits"] is None:
            p["skipped"].append(f"{label}: needs precedents.target_core_deposits")
        else:
            p["metrics"].append(key)
    if not p["metrics"]:
        raise CaseError("Invalid input precedents.deals: no multiple has enough deals in the recency window "
                        f"({'; '.join(p['skipped'])})")
    return p


def run(prec, kind, t):
    """Stats and implied target value per active metric. t is the target dict from the case."""
    out = {}
    for key, label, _, _ in KINDS[kind]:
        if key not in prec["metrics"]:
            continue
        xs = values(prec, key)
        st = dict(mean=mean(xs), median=median(xs), p25=percentile(xs, 0.25), p75=percentile(xs, 0.75),
                  high=max(xs), low=min(xs))
        imp = {}
        for q in ("p25", "median", "p75"):
            m = st[q]
            if kind == "corporate":
                f = "ltm_revenue" if key == "ev_rev_ltm" else "ltm_ebitda"
                imp[q] = implied("ev", m, t[f], t["net_debt"], t["diluted_shares"])
            else:
                if key == "cdp":
                    eq = t["tce"] + m * prec["target_core_deposits"]
                    px = eq / t["shares"]
                else:
                    px = m * (t["tce"] if key == "ptbv" else t["net_income"]) / t["shares"]
                imp[q] = (px * t["shares"], px)
        out[key] = dict(label=label, n=len(xs), stats=st, implied=imp)
    return out


def football(res):
    """(label, low, high) per metric, 25th to 75th percentile implied price. Mid is res[key]['implied']['median']."""
    return [(f"Precedents: {r['label']}", r["implied"]["p25"][-1], r["implied"]["p75"][-1]) for r in res.values()]


# ---- workbook ---------------------------------------------------------------------

def add_sheet(b, prec, kind):
    """Add the deal inputs to Inputs and build the Precedents sheet. Call after Inputs exists and
    before checks_sheet. Returns a layout dict for the football field and Checks."""
    spec = KINDS[kind]
    active = [s for s in spec if s[0] in prec["metrics"]]
    n = len(prec["deals"])
    inp = b.wb["Inputs"]
    r = inp.max_row + 2
    b.header(inp, r, ["Precedent Transaction Settings", "Value"])
    for lab, val, fmt, name in [("As-Of Date", prec["as_of"], DATE, "Prec_As_Of"),
                                ("Recency Filter: Deals Within N Years of As-Of (0 = Off)",
                                 prec["max_age_years"], "0.0", "Prec_Max_Age"),
                                ("Minimum Deals per Multiple", MIN_DEALS, "0", "Prec_Min_Deals")] + (
            [("Target Core Deposits ($M)", prec["target_core_deposits"], NUM1, "Target_Core_Deposits")]
            if prec["target_core_deposits"] is not None else []):
        r += 1
        b.label(inp, f"A{r}", lab)
        b.inp(inp, f"B{r}", val, fmt, name=name)
    mcol = {k: chr(ord("D") + i) for i, (k, *_) in enumerate(spec)}  # Inputs metric columns
    acq, src = chr(ord("D") + len(spec)), chr(ord("E") + len(spec))
    r += 2
    b.header(inp, r, ["Precedent Deals: Target", "Announce Date", "Deal Value ($M)"] + [s[1] for s in spec]
             + ["Acquirer", "Source (Public Filing or Press Release)"])
    inp.column_dimensions[acq].width = 30
    ir0 = r + 1
    for i, d in enumerate(prec["deals"]):
        ri = ir0 + i
        b.inp(inp, f"A{ri}", d["target"], "@").alignment = Alignment(horizontal="left")
        b.inp(inp, f"B{ri}", d["date"], DATE)
        b.inp(inp, f"C{ri}", d["deal_value"], NUM1)
        for key, _, _, fmt in spec:
            v = d[key]
            b.inp(inp, f"{mcol[key]}{ri}", NA if v is None else v, fmt)
        for c, txt in ((acq, d["acquirer"]), (src, d["source"])):
            b.inp(inp, f"{c}{ri}", txt, "@").alignment = Alignment(horizontal="left")

    ws = b.sheet("Precedents", "Precedent Transactions",
                 (prec["note"] + " " if prec["note"] else "") +
                 "$ in millions. Deals before the recency cutoff are left out of every statistic.",
                 {"A": 36, "B": 30, "C": 14, "D": 16, "E": 12, **{chr(ord("F") + i): 16 for i in range(len(active))}})
    b.header(ws, 4, ["Target", "Acquirer", "Announce Date", "Deal Value", "Included"] + [s[1] for s in active])
    first, last = 5, 4 + n
    pc = {s[0]: chr(ord("F") + i) for i, s in enumerate(active)}
    for i in range(n):
        row, ri = first + i, ir0 + i
        b.calc(ws, f"A{row}", f"=Inputs!A{ri}", "@").alignment = Alignment(horizontal="left")
        b.calc(ws, f"B{row}", f"=Inputs!{acq}{ri}", "@").alignment = Alignment(horizontal="left")
        b.calc(ws, f"C{row}", f"=Inputs!B{ri}", DATE)
        b.calc(ws, f"D{row}", f"=Inputs!C{ri}", NUM1)
        b.calc(ws, f"E{row}", f"=IF(C{row}>=Prec_Cutoff,1,0)", "0")
        for key, _, _, fmt in active:
            src_ref = f"Inputs!{mcol[key]}{ri}"
            b.calc(ws, f"{pc[key]}{row}", f'=IF(E{row}=0,"",IF({src_ref}="{NA}","",{src_ref}))', fmt)
    st = {k: last + 2 + i for i, (k, *_) in enumerate(STATS)}
    for k, label, fn in STATS:
        b.label(ws, f"A{st[k]}", label, bold=True)
        for key, _, _, fmt in active:
            c = pc[key]
            b.calc(ws, f"{c}{st[k]}", "=" + fn.format(f"{c}{first}:{c}{last}"), fmt, bold=True, total=(k == "mean"))
    nrow = last + 2 + len(STATS)
    b.label(ws, f"A{nrow}", "Deals Included", bold=True)
    for key, *_ in active:
        b.calc(ws, f"{pc[key]}{nrow}", f"=COUNT({pc[key]}{first}:{pc[key]}{last})", "0", bold=True)
    crow = nrow + 1
    b.label(ws, f"A{crow}", "Recency Cutoff (Deals On or After This Date)", bold=True)
    b.calc(ws, f"B{crow}", "=IF(Prec_Max_Age=0,0,EDATE(Prec_As_Of,-12*Prec_Max_Age))", DATE, name="Prec_Cutoff")

    h = crow + 3
    b.section(ws, h - 1, "Implied Target Valuation (25th Percentile, Median, 75th Percentile)", 12)
    if kind == "corporate":
        b.header(ws, h, ["Method", "Target Metric", "Multiple: 25th", "Multiple: Median", "Multiple: 75th",
                         "EV: 25th", "EV: Median", "EV: 75th", "Equity: 25th", "Equity: Median", "Equity: 75th",
                         "Price: 25th", "Price: Median", "Price: 75th", "Spread"])
        price, spread = "LMN", "O"
    else:
        b.header(ws, h, ["Method", "Target Metric", "Multiple: 25th", "Multiple: Median", "Multiple: 75th",
                         "Equity: 25th", "Equity: Median", "Equity: 75th", "Price: 25th", "Price: Median",
                         "Price: 75th", "Spread"])
        price, spread = "IJK", "L"
    imp = {}
    for i, (key, label, _, _) in enumerate(active):
        row = h + 1 + i
        imp[key] = row
        b.label(ws, f"A{row}", label)
        if kind == "corporate":
            tm = "Target_Rev_LTM" if key == "ev_rev_ltm" else "Target_EBITDA_LTM"
            tf = NUM1
        else:
            tm, tf = {"ptbv": ("TBVPS", PS), "pe_ltm": ("NI_LTM/Shares", PS), "cdp": ("Target_Core_Deposits", NUM1)}[key]
        b.calc(ws, f"B{row}", f"={tm}", tf)
        for k, stat in enumerate(("p25", "median", "p75")):
            mult = "CDE"[k]
            b.calc(ws, f"{mult}{row}", f"={pc[key]}{st[stat]}", spec_fmt(spec, key))
            px = price[k]
            if kind == "corporate":
                ev, eq = "FGH"[k], "IJK"[k]
                b.calc(ws, f"{ev}{row}", f"={mult}{row}*$B{row}", NUM1)
                b.calc(ws, f"{eq}{row}", f"={ev}{row}-Net_Debt", NUM1)
                b.calc(ws, f"{px}{row}", f"={eq}{row}/Diluted_Shares", PS, bold=True)
            else:
                eq = "FGH"[k]
                if key == "cdp":
                    b.calc(ws, f"{eq}{row}", f"=TCE+{mult}{row}*$B{row}", NUM1)
                    b.calc(ws, f"{px}{row}", f"={eq}{row}/Shares", PS, bold=True)
                else:
                    b.calc(ws, f"{px}{row}", f"={mult}{row}*$B{row}", PS, bold=True)
                    b.calc(ws, f"{eq}{row}", f"={px}{row}*Shares", NUM1)
        b.calc(ws, f"{spread}{row}", f"={price[2]}{row}-{price[0]}{row}", PS)
    ws.freeze_panes = "B5"
    return dict(price=price, spread=spread, imp=imp, active=[s[1] for s in active],
                count_row=nrow, cols=(pc[active[0][0]], pc[active[-1][0]]))


PS = '$#,##0.00_);($#,##0.00);"-"_)'


def spec_fmt(spec, key):
    return next(s[3] for s in spec if s[0] == key)


def football_rows(lay):
    """(label, low formula, mid formula, high formula) for each active metric, from the Precedents sheet."""
    lo, mid, hi = lay["price"]
    return [(f"Precedents: {lab}", f"=Precedents!{lo}{r}", f"=Precedents!{mid}{r}", f"=Precedents!{hi}{r}")
            for lab, r in zip(lay["active"], lay["imp"].values())]


def checks(lay):
    r0, r1 = min(lay["imp"].values()), max(lay["imp"].values())
    c0, c1 = lay["cols"]
    return [("Precedents: implied value at the 25th percentile is at most the 75th percentile, every method",
             f"MIN(Precedents!{lay['spread']}{r0}:{lay['spread']}{r1})<-Check_Tol"),
            ("Precedents: every multiple has at least the minimum number of deals after the recency filter",
             f"MIN(Precedents!{c0}{lay['count_row']}:{c1}{lay['count_row']})<Prec_Min_Deals")]
