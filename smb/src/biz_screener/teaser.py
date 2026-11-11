"""One-page sell-side style teaser per deal, as a self-contained HTML page.

Inputs: a Result, its Listing, periods, add-backs, Valuation, DebtRun and settings.
Outputs: HTML with inline style only, all text escaped, print CSS for one page.
Every figure is already computed elsewhere; a missing input shows as Not provided.
"""
import os
import re
from html import escape
from typing import List, Optional

from . import multiples, normalize, returns
from .models import AddBack, DebtRun, FinancialPeriod, Listing, Result, Valuation
from .pipeline import cagr_of
from .report import NOTE, TITLES, blocked_reasons, write_report

FOOTER = "Illustrative analysis, not advice. " + NOTE
NA = "Not provided"


def _usd(x: Optional[float]) -> str:
    return NA if x is None else "${:,.0f}".format(x)


def _pct(x: Optional[float]) -> str:
    return NA if x is None else "%.1f%%" % (x * 100)


def _mult(x: float) -> str:
    return "n/a" if x == float("inf") else "%.2fx" % x


def _table(rows: List[tuple]) -> str:
    return "<table>%s</table>" % "".join(
        "<tr><th>%s</th><td>%s</td></tr>" % (escape(k), escape(v)) for k, v in rows)


def render_teaser(r: Result, listing: Listing, periods: List[FinancialPeriod],
                  adds: List[AddBack], val: Valuation, debt: Optional[DebtRun],
                  cfg: dict) -> str:
    ind = cfg["industries"][listing.category]
    norm = normalize.normalize_periods(periods, adds, ind["manager_salary_default"])[-1]
    rev = max(periods, key=lambda p: p.fiscal_year).revenue
    p_sde, p_ebitda = multiples.asking_multiples(listing.asking_price, norm.sde, norm.ebitda)
    margin = lambda x: _pct(x / rev) if rev > 0 else NA
    need = cfg["sba"]["min_dscr_lender"]
    lo, hi = sorted((val.sde_value, val.ebitda_value, val.dcf_value))[::2]
    business = [
        ("Category", listing.category.replace("_", " ").title()),
        ("County FIPS", listing.county_fips or NA),
        ("Lease years remaining", NA if listing.lease_years_remaining is None
         else "%g" % listing.lease_years_remaining),
        ("Top customer share", _pct(listing.top_customer_share)),
        ("Listing source", listing.source),
    ]
    fin = [
        ("Revenue (FY%d)" % norm.fiscal_year, _usd(rev)),
        ("SDE", "%s (%s margin)" % (_usd(norm.sde), margin(norm.sde))),
        ("EBITDA", "%s (%s margin)" % (_usd(norm.ebitda), margin(norm.ebitda))),
        ("Revenue growth (CAGR)", _pct(cagr_of(periods))),
        ("Financials", "Seller-stated" if all(p.is_stated for p in periods) else "Includes estimates"),
    ]
    ask = [
        ("Asking price", _usd(listing.asking_price)),
        ("Price / SDE", _mult(p_sde)),
        ("Price / EBITDA", _mult(p_ebitda)),
        ("Valuation range (SDE, EBITDA, DCF methods)", "%s to %s" % (_usd(lo), _usd(hi))),
        ("Blended value", _usd(val.blended_value)),
    ]
    if debt:
        dscr = [
            ("SBA loan", _usd(debt.loan_amount)),
            ("Rate and term", "%.2f%% over %d years" % (debt.rate * 100, debt.term_years)),
            ("Annual debt service", _usd(debt.annual_payment)),
            ("Lender DSCR", "%.2fx against %.2fx required (%s)" % (
                debt.dscr_lender, need, "meets" if debt.dscr_lender >= need else "below")),
        ]
    else:
        dscr = [("SBA loan", "Not computed")]
    latest = max(periods, key=lambda p: p.fiscal_year)
    ret = debt and returns.equity_returns(listing.asking_price, norm.ebitda,
                                          latest.depreciation + latest.amortization, debt, cfg)
    if ret:
        lbo = [
            ("Equity invested (cash plus SBA fee)", _usd(ret["invested"])),
            ("Year 1 cash to equity (after debt service)", _usd(ret["year1_cash"])),
            ("Exit value, year %d (entry EBITDA multiple)" % ret["years"], _usd(ret["exit_ev"])),
            ("Less: SBA balance and seller note at exit", _usd(ret["payoff"])),
            ("Exit equity", _usd(ret["exit_equity"])),
            ("Equity MOIC", _mult(ret["moic"])),
            ("Equity IRR", _pct(ret["irr"])),
        ]
    else:
        lbo = [("Equity returns", "Not computed")]
    items = ["%s (%s)" % (TITLES.get(f.code, f.code), f.evidence) for f in r.flags
             if f.severity != "high"] + blocked_reasons(r) + r.notes
    flags = "<ul>%s</ul>" % "".join("<li>%s</li>" % escape(x) for x in items) if items \
        else "<p>None</p>"
    title = "Deal Teaser %s" % listing.external_ref
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>%s</title><style>'
        "body{font-family:system-ui,sans-serif;margin:1.5rem;color:#1a1a1a;font-size:13px}"
        "h1{font-size:1.4rem;margin:0}h2{font-size:1rem;margin:.8rem 0 .2rem;border-bottom:1px solid #999}"
        "table{border-collapse:collapse;width:100%%}th,td{padding:.15rem .4rem;text-align:left;"
        "vertical-align:top}th{width:45%%;font-weight:600}ul{margin:.2rem 0;padding-left:1.2rem}"
        ".cols{display:grid;grid-template-columns:1fr 1fr;gap:0 1.5rem}"
        "footer{margin-top:1rem;border-top:1px solid #999;padding-top:.4rem;font-style:italic}"
        "@media print{@page{size:letter;margin:.5in}body{margin:0;font-size:11px}"
        "h2,table,ul{break-inside:avoid}}"
        "</style></head><body><h1>%s</h1><p>%s. Score %.1f, %s.</p>"
        '<div class="cols"><div><h2>Business</h2>%s<h2>Key Financials</h2>%s</div>'
        "<div><h2>Price and Valuation</h2>%s<h2>Debt Sizing (SBA 7(a))</h2>%s</div></div>"
        "<h2>Buyer Returns (Hold %s Years, Exit at Entry Multiple)</h2>%s"
        "<h2>Red Flags and Notes</h2>%s<footer>%s</footer></body></html>" % (
            escape(title), escape(title), escape(listing.category.replace("_", " ").title()),
            r.total, "Passes screening" if r.passes else "Blocked",
            _table(business), _table(fin), _table(ask), _table(dscr), cfg["dcf"]["forecast_years"],
            _table(lbo), flags, escape(FOOTER)))


def write_teaser(text: str, directory: str, rank: int, ref: str) -> str:
    """File name is rank plus a safe ref, so odd refs cannot escape the folder or collide."""
    path = os.path.join(directory, "%02d-%s.html" % (rank, re.sub(r"[^A-Za-z0-9_-]+", "_", ref)))
    write_report(text, path)
    return path
