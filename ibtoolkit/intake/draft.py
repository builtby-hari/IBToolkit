"""Write a draft DCF case TOML from SourcedValue lists.

Money is converted to $ millions and shares to millions. Every number gets a source comment. Anything
the filings cannot give (next-twelve-month figures, DCF assumptions, peers) is written as a TODO
comment, never invented. The file carries [meta] draft = true until the review step approves it, and
a [[intake.values]] block per value so the review step can re-check the sources.
"""
import json
from datetime import date

from . import xbrl
from .fields import FIELDS, FLAG, FY, LTM, QTR, YTD

MILLION = 1_000_000
STALE_NOTE = "tag last reported"  # start of the note xbrl adds to a stale-tag value
PERIOD_RANK = {QTR: 3, YTD: 2, FY: 1}  # for share counts: prefer the latest quarter

# target key -> (kind, fields it needs). The DCF engine needs all of these.
TARGET_KEYS = ["net_debt", "diluted_shares", "ltm_revenue", "ntm_revenue", "ltm_ebitda", "ntm_ebitda",
               "ltm_eps", "ntm_eps"]
DCF_TODO = [
    ("revenue_growth", "list of 5 yearly growth rates"),
    ("ebitda_margin", "list of 5 yearly EBITDA margins"),
    ("da_pct_revenue", "D&A as a share of revenue"),
    ("capex_pct_revenue", "capex as a share of revenue"),
    ("nwc_pct_revenue_change", "NWC investment as a share of the change in revenue"),
    ("tax_rate", "forecast tax rate"),
    ("risk_free", "risk-free rate (market data, with a date and source)"),
    ("equity_risk_premium", "equity risk premium"),
    ("beta", "beta"),
    ("pre_tax_cost_of_debt", "pre-tax cost of debt"),
    ("debt_to_capital", "target debt to capital"),
    ("terminal_growth", "terminal growth rate"),
    ("exit_multiple", "exit EV / EBITDA multiple"),
    ("mid_year", "true or false"),
]


def select(values):
    """One value per field for the draft: LTM for flows (FY only when no LTM exists), the latest period
    for weighted share counts, the latest balance date for the balance sheet. Whole company only."""
    chosen = {}
    for v in values:
        if v.segment:
            continue
        if v.field == "diluted_shares":
            rank = (v.period_end, PERIOD_RANK.get(v.period_type, 0))
        elif FIELDS[v.field][1] == "flow":
            if v.period_type not in (LTM, FY):
                continue
            rank = (v.period_end, 1 if v.period_type == LTM else 0)
        else:
            rank = (v.period_end, 0)
        cur = chosen.get(v.field)
        if cur is None or rank > cur[0]:
            chosen[v.field] = (rank, v)
    return {f: v for f, (_, v) in chosen.items()}


def _mismatch(*vals):
    """Why these values cannot be combined into one number, or '' when they can."""
    if len({(v.period_type, v.period_end) for v in vals}) > 1:
        return "inputs are from different periods (" + "; ".join(
            f"{v.field} {v.period_type} {v.period_end}" for v in vals) + ")"
    stale = [v.field for v in vals if any(n.startswith(STALE_NOTE) for n in v.notes)]
    if stale:
        return f"stale tag for {', '.join(stale)} (last reported long before the newest period)"
    return ""


def target_gaps(sel):
    """{target key: reason} for numbers that have all their inputs but cannot be combined safely."""
    gaps = {}
    for key, names in (("ltm_ebitda", ("operating_income", "d_and_a")), ("net_debt", ("debt", "cash"))):
        if all(n in sel for n in names):
            why = _mismatch(*(sel[n] for n in names))
            if why:
                gaps[key] = why
    return gaps


def derive_target(sel):
    """Expected [target] numbers ($M, shares in M) from the selected values. Missing keys are absent.

    A combined number (EBITDA, net debt) is left out when its inputs are from different dates or carry
    a stale-tag flag; target_gaps says why.
    """
    t = {}
    gaps = target_gaps(sel)
    if "revenue" in sel:
        t["ltm_revenue"] = sel["revenue"].value / MILLION
    if "operating_income" in sel and "d_and_a" in sel and "ltm_ebitda" not in gaps:
        t["ltm_ebitda"] = (sel["operating_income"].value + sel["d_and_a"].value) / MILLION
    if "diluted_eps" in sel:
        t["ltm_eps"] = sel["diluted_eps"].value
    if "diluted_shares" in sel:
        t["diluted_shares"] = sel["diluted_shares"].value / MILLION
    if "debt" in sel and "cash" in sel and "net_debt" not in gaps:
        t["net_debt"] = (sel["debt"].value - sel["cash"].value) / MILLION
    return t


# TOML helpers -------------------------------------------------------------------------------------

def _num(x):
    s = f"{x:.6f}".rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def _str(s):
    return json.dumps(s)


def _raw(x):
    return str(int(x)) if float(x).is_integer() else repr(round(x, 6))


def _m(v):
    return f"{v / MILLION:,.1f}"


def _src(v):
    return f"{v.source_ref}"


def _lines(prefix, text, width=118):
    """Wrap text into comment lines; continuation lines start with a plain '#' so only the first line
    carries a marker such as TODO."""
    out, line = [], prefix
    for w in text.split():
        if len(line) + len(w) + 1 > width and line.strip("# ").strip():
            out.append(line)
            line = "#    "
        line += w if line.endswith(" ") else " " + w
    out.append(line)
    return out


def _target_block(sel, derived):
    out = ["[target]"]
    gaps = target_gaps(sel)
    def put(key, comment, sources):
        out.extend(_lines("#", comment))
        for s in sources:
            out.extend(_lines("#   Source:", s))
        out.append(f"{key} = {_num(derived[key])}")
        out.append("")
    def todo(key, why):
        out.extend(_lines("# TODO", f"target.{key}: {why}"))
        out.append("")
    if "net_debt" in derived:
        d, c = sel["debt"], sel["cash"]
        put("net_debt", f"Total debt {_m(d.value)} less cash and equivalents {_m(c.value)} ($M) at {d.period_end}. "
            f"{d.notes[0] if d.notes else ''}", [f"debt: {_src(d)}", f"cash: {_src(c)}"])
    else:
        todo("net_debt", f"not written, {gaps['net_debt']}; pick debt and cash from the same balance sheet date"
             if "net_debt" in gaps else "needs total debt and cash from a balance sheet; not found in the XBRL facts")
    if "diluted_shares" in derived:
        s = sel["diluted_shares"]
        put("diluted_shares", f"Weighted average diluted shares, millions, for the period ending {s.period_end} "
            "(a weighted average, not a period-end count).", [_src(s)])
    else:
        todo("diluted_shares", "weighted average diluted shares not found")
    if "ltm_revenue" in derived:
        r = sel["revenue"]
        put("ltm_revenue", f"Revenue, last twelve months to {r.period_end}, $M.", [_src(r)])
    else:
        todo("ltm_revenue", "revenue not found")
    todo("ntm_revenue", "next-twelve-month revenue needs consensus or management guidance; none in the filings")
    if "ltm_ebitda" in derived:
        o, a = sel["operating_income"], sel["d_and_a"]
        put("ltm_ebitda", f"EBITDA = operating income {_m(o.value)} + D&A {_m(a.value)} ($M), last twelve months "
            f"to {o.period_end}. Built from the filing, not a reported EBITDA figure.",
            [f"operating income: {_src(o)}", f"D&A: {_src(a)}"])
    else:
        todo("ltm_ebitda", f"not written, {gaps['ltm_ebitda']}; EBITDA needs operating income and D&A for the same period"
             if "ltm_ebitda" in gaps else "needs both operating income and D&A (EBITDA = operating income + D&A); one is missing")
    todo("ntm_ebitda", "next-twelve-month EBITDA needs consensus or guidance; none in the filings")
    if "ltm_eps" in derived:
        e = sel["diluted_eps"]
        put("ltm_eps", f"Diluted EPS, last twelve months to {e.period_end}, dollars.", [_src(e)])
    else:
        todo("ltm_eps", "diluted EPS not found")
    todo("ntm_eps", "next-twelve-month EPS needs consensus or guidance; none in the filings")
    return out


def _ratio(sel, num, den):
    if num in sel and den in sel and sel[den].value:
        return sel[num].value / sel[den].value
    return None


def _dcf_block(sel):
    out = ["[dcf]", "# Every line below is an assumption the filings cannot give. Fill each one in with its own source or",
           "# an ASSUMPTION label. Reference ratios from the filings are shown where they exist."]
    hints = {"da_pct_revenue": _ratio(sel, "d_and_a", "revenue"), "capex_pct_revenue": _ratio(sel, "capex", "revenue")}
    if "income_tax" in sel and "net_income" in sel and sel["net_income"].value + sel["income_tax"].value:
        hints["tax_rate"] = sel["income_tax"].value / (sel["net_income"].value + sel["income_tax"].value)
    for key, what in DCF_TODO:
        hint = hints.get(key)
        extra = f" Reference only: LTM {hint:.1%} from the filings above (not a forecast)." if hint is not None else ""
        if key == "tax_rate" and hint is not None:
            extra = f" Reference only: LTM tax / (net income + tax) = {hint:.1%} (effective rate, not a forecast)."
        out.extend(_lines("# TODO", f"dcf.{key}: {what}.{extra}"))
    out.append("")
    return out


def _intake_blocks(sel):
    out = ["# Machine-readable record of every sourced value above (used by `intake --review`). Raw USD as filed."]
    for f in sorted(sel):
        v = sel[f]
        out += ["", "[[intake.values]]", f"field = {_str(v.field)}", f"value = {_raw(v.value)}",
                f"unit = {_str(v.unit)}", f"period_type = {_str(v.period_type)}", f"period_start = {_str(v.period_start)}",
                f"period_end = {_str(v.period_end)}", f"source_kind = {_str(v.source_kind)}",
                f"source_ref = {_str(v.source_ref)}", f"form = {_str(v.form)}", f"filed = {_str(v.filed)}",
                f"segment = {_str(v.segment)}", f"status = {_str(v.status)}", f"notes = {json.dumps(v.notes)}"]
    return out


def build_draft(values, entity, ticker="", cik="", today=None):
    """Return the draft DCF case as TOML text."""
    today = today or date.today().isoformat()
    sel = select(values)
    derived = derive_target(sel)
    flagged = sorted(f for f, v in sel.items() if v.status == FLAG)
    out = [f"# DRAFT DCF CASE for {entity}, built from SEC XBRL company facts on {today}.",
           "# Not ready to run: the dcf command refuses it while [meta] draft = true.",
           "# Money is in $ millions, shares in millions, per-share values in dollars. Every number cites its filing;",
           "# lines marked TODO still need a sourced value. Then run:",
           "#   python -m ibtoolkit intake --review <this file>   (and --approve when clean)",
           ""]
    if flagged:
        out += [f"# FLAGGED on extraction: {', '.join(flagged)} (see notes in the [[intake.values]] blocks).", ""]
    out += ["[meta]", f"name = {_str(entity + ' (' + ticker + '), draft DCF' if ticker else entity + ', draft DCF')}",
            "draft = true", "illustrative = false",
            f"source = {_str('SEC EDGAR XBRL companyfacts' + (', CIK ' + cik if cik else '') + ', retrieved ' + today)}", ""]
    out += _target_block(sel, derived)
    out += _dcf_block(sel)
    out += ["# TODO peers: add at least 3 [[peers]] tables (name, price, shares, net_debt, revenue_ltm, revenue_ntm, ebitda_ltm,",
            "# ebitda_ntm, eps_ltm, eps_ntm), each sourced. Peer data is not in this company's own filings.", ""]
    out += _intake_blocks(sel)
    return "\n".join(out) + "\n"
