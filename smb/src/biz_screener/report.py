"""HTML and CSV reports of ranked deals.

Inputs: Result records (ranked), a title.
Outputs: one self-contained HTML page (inline style, no external resources, all text escaped)
and a CSV. Each deal is marked Passes or Blocked; a blocked deal lists why in plain words.
"""
import csv
import io
import os
from html import escape
from typing import List

from .models import Result

NOTE = "Screening aid built on seller-stated, unaudited numbers. Research estimate, not advice."
TITLES = {
    "missing_financials": "Financials are missing or only estimates",
    "addback_ratio": "Add-backs are too large a share of profit",
    "nonpositive_sde": "The business earns nothing for an owner",
    "declining_revenue": "Revenue keeps falling",
    "concentration": "Too much revenue from one customer",
    "low_dscr": "Cash flow is too thin to cover the SBA loan",
    "equity_shortfall": "Cash on hand does not cover the required equity",
}


def blocked_reasons(r: Result) -> List[str]:
    """Plain-words reasons a deal is blocked; empty when it passes."""
    out = ["%s (%s)" % (TITLES.get(f.code, f.code), f.evidence) for f in r.blockers]
    if r.dscr is None and not any(f.code == "equity_shortfall" for f in r.blockers):
        out.append("No loan coverage figure could be computed, so the deal cannot be cleared")
    return out


def _money(x: float) -> str:
    return "${:,.0f}".format(x)


def _safe_cell(text: str) -> str:
    """Stop spreadsheets from running text that starts with a formula character."""
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


def render_csv(results: List[Result]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["rank", "ref", "category", "county_fips", "asking_price", "blended_value",
                "dscr", "score", "status", "blocked_because", "other_flags", "notes"])
    for r in results:
        why = blocked_reasons(r)
        w.writerow([r.rank, _safe_cell(r.ref), r.category, r.county_fips, round(r.asking_price),
                    round(r.blended_value), "" if r.dscr is None else "%.2f" % r.dscr,
                    "%.1f" % r.total, "Blocked" if why else "Passes",
                    _safe_cell("; ".join(why)),
                    "; ".join(f.code for f in r.flags if f.severity != "high"),
                    "; ".join(r.notes)])
    return buf.getvalue()


def render_html(results: List[Result], title: str = "Deal Screening Report") -> str:
    rows = []
    for r in results:
        why = blocked_reasons(r)
        status = ('<td class="bad">Blocked<ul>%s</ul></td>'
                  % "".join("<li>%s</li>" % escape(x) for x in why)) if why \
            else '<td class="ok">Passes</td>'
        watch = escape(", ".join([f.evidence for f in r.flags if f.severity != "high"]
                                 + r.notes)) or "-"
        rows.append("<tr><td>%d</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
                    "<td>%s</td><td>%.1f</td>%s<td>%s</td></tr>" % (
                        r.rank, escape(r.ref), escape(r.category), escape(r.county_fips),
                        _money(r.asking_price), _money(r.blended_value),
                        "n/a" if r.dscr is None else "%.2fx" % r.dscr, r.total, status, watch))
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        "<title>%s</title><style>"
        "body{font-family:system-ui,sans-serif;margin:2rem;color:#1a1a1a}"
        "table{border-collapse:collapse;width:100%%}"
        "th,td{border:1px solid #ccc;padding:.4rem .6rem;text-align:left;vertical-align:top}"
        "th{background:#f0f0f0}.ok{color:#0a6b2b;font-weight:600}.bad{color:#a11}"
        "ul{margin:.2rem 0 0 1rem;padding:0;font-weight:400}"
        "</style></head><body><h1>%s</h1><p>%s</p><table><thead><tr><th>Rank</th><th>Ref</th>"
        "<th>Category</th><th>County</th><th>Asking</th><th>Blended Value</th><th>DSCR</th>"
        "<th>Score</th><th>Status</th><th>Watch Items</th></tr></thead><tbody>%s</tbody></table>"
        "</body></html>" % (escape(title), escape(title), escape(NOTE), "".join(rows)))


def write_report(text: str, path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
