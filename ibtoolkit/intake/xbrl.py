"""Turn an SEC XBRL companyfacts JSON into a list of SourcedValue.

Flow fields (income statement, cash flow) come out as FY (10-K), the latest YTD and quarter (10-Q) and
LTM = latest FY + current YTD - prior-year YTD. Balance sheet fields come out as instants at their
latest period end. Money stays in raw USD as filed; the draft writer converts to $ millions.

Rules for picking a row:
- Only 10-K and 10-Q rows (and their amendments). Proxy statements and 8-Ks are ignored.
- The same period shows up again as a comparative in later filings. For one period the latest filed
  row wins (it carries any restatement); a note records it when the number changed.
- For each field the tag with the most recent fiscal-year end (or balance date) wins, ties go to the
  tag listed first. The same tag is used for all three pieces of an LTM.
- Exception, revenue: when two tags report the same latest fiscal year, the larger value wins (a
  holding company can report a narrow contract-revenue tag next to a total Revenues tag) and a note
  records the gap, so revenue is never silently understated.
"""
import json
import urllib.request
from datetime import date

from .. import edgar
from .fields import FIELDS, FY, INSTANT, LTM, QTR, XBRL, YTD, SourcedValue

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FORMS = ("10-K", "10-K/A", "10-Q", "10-Q/A")

# field -> us-gaap tags in order of preference.
FLOW_TAGS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax",
                "RevenueFromContractWithCustomerIncludingAssessedTax", "Revenues", "SalesRevenueNet",
                "SalesRevenueGoodsNet"],
    "operating_income": ["OperatingIncomeLoss"],
    "d_and_a": ["DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet",
                "DepreciationAndAmortization", "Depreciation"],
    "interest_expense": ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt"],
    "income_tax": ["IncomeTaxExpenseBenefit"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "diluted_eps": ["EarningsPerShareDiluted"],
    "diluted_shares": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
}
INSTANT_TAGS = {
    "cash": ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
    "current_assets": ["AssetsCurrent"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "total_assets": ["Assets"],
    "liabilities_and_equity": ["LiabilitiesAndStockholdersEquity"],
    "total_equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "goodwill": ["Goodwill"],
    "intangibles": ["IntangibleAssetsNetExcludingGoodwill", "FiniteLivedIntangibleAssetsNet"],
    "shares_outstanding": ["CommonStockSharesOutstanding"],
}
# Debt is built from parts: the long-term (noncurrent) piece plus the current piece.
DEBT_NONCURRENT = ["LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations"]
DEBT_CURRENT_TOTAL = ["DebtCurrent"]
DEBT_CURRENT_PARTS = [["LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent"],
                      ["CommercialPaper"], ["ShortTermBorrowings"]]
STALE_TAG_DAYS = 400
LARGER_WINS = ("revenue",)  # fields where tags tied on the latest year are compared by value
NOT_ADDITIVE = ("diluted_shares",)  # weighted share counts are not summed into an LTM


class XbrlError(RuntimeError):
    pass


# ---- ticker to CIK -------------------------------------------------------------------------------

def load_tickers(opener=urllib.request.urlopen):
    """Download SEC's company_tickers.json (needs SEC_USER_AGENT)."""
    req = urllib.request.Request(TICKERS_URL, headers={"User-Agent": edgar.user_agent(), "Accept": "application/json"})
    with opener(req) as resp:
        return json.loads(resp.read())


def cik_for_ticker(ticker, tickers):
    """CIK (as a string of digits) for a ticker, from a company_tickers.json dict."""
    want = ticker.strip().upper().replace(".", "-")
    for row in tickers.values():
        if row.get("ticker", "").upper() == want:
            return str(row["cik_str"])
    raise XbrlError(f"Ticker {ticker!r} not found in SEC company_tickers.json")


# ---- row helpers ---------------------------------------------------------------------------------

def _d(s):
    return date.fromisoformat(s)


def _rows(facts, tag, unit, ns="us-gaap"):
    """Rows of one tag and unit from 10-K / 10-Q filings, deduplicated by period.

    Returns {period key: (latest filed row, first filed row)}. The key is (start, end) for flows and
    ("", end) for instants.
    """
    raw = facts.get("facts", {}).get(ns, {}).get(tag, {}).get("units", {}).get(unit, [])
    groups = {}
    for r in raw:
        if r.get("form") in FORMS and "end" in r and "val" in r:
            groups.setdefault((r.get("start", ""), r["end"]), []).append(r)
    out = {}
    for key, rs in groups.items():
        rs.sort(key=lambda r: r.get("filed", ""))
        out[key] = (rs[-1], rs[0])
    return out


def _days(key):
    return (_d(key[1]) - _d(key[0])).days


def _is_annual(key, row):
    return 350 <= _days(key) <= 380 and row["form"].startswith("10-K")


def _year_back(iso):
    d = _d(iso)
    try:
        return d.replace(year=d.year - 1)
    except ValueError:  # Feb 29
        return d.replace(year=d.year - 1, day=28)


def _label(row, first, key, kind):
    """Human label for a period: '10-K FY2025' or '10-Q Q2 FY2026 (YTD to 2026-08-02)'."""
    fy = first.get("fy", row.get("fy"))
    base = f"{row['form']} FY{fy}" if row["form"].startswith("10-K") else f"{row['form']} {row.get('fp')} FY{fy}"
    if kind == "FY":
        return base
    return f"{base} (at {key[1]})" if kind == "instant" else f"{base} ({kind} to {key[1]})"


def _piece(row, first, key, tag, kind, field):
    """One extracted number with its citation. Capex is made positive here."""
    val, notes = row["val"], []
    if field == "capex" and val < 0:
        val = -val
        notes.append("capex reported negative; sign flipped to positive")
    if first is not row and first["val"] != row["val"]:
        notes.append(f"restated: first filed as {first['val']} in accn {first['accn']}")
    return dict(val=val, row=row, key=key, tag=tag, notes=notes, kind=kind,
                ref=f"{_label(row, first, key, kind)} accn {row['accn']} tag {tag}")


# ---- flows ---------------------------------------------------------------------------------------

def _best_flow_tag(facts, tags, unit, field=""):
    """(tag, periods, notes) for the tag whose latest fiscal year ends last; ties go to the earlier tag.

    For fields in LARGER_WINS a tie on the latest year goes to the tag with the larger value, and the
    notes say which smaller value was passed over.
    """
    cands = []
    for tag in tags:
        periods = {k: v for k, v in _rows(facts, tag, unit).items() if k[0]}  # flows need a start date
        annual = {k: v for k, v in periods.items() if _is_annual(k, v[0])}
        if annual:
            key = max(annual, key=lambda k: k[1])
            cands.append((key[1], tag, periods, annual[key][0]["val"]))
    if not cands:
        return None, None, []
    top = max(c[0] for c in cands)
    tied = [c for c in cands if c[0] == top]
    best = tied[0]
    notes = []
    if field in LARGER_WINS and len(tied) > 1:
        best = max(tied, key=lambda c: c[3])  # max keeps the first of equals, so list order breaks ties
        for c in tied:
            if c[1] != best[1] and c[3] != best[3]:
                notes.append(f"tag {c[1]} also reports {c[3]:,.0f} for the fiscal year ending {top}; "
                             f"used the larger tag {best[1]} ({best[3]:,.0f})")
    return best[1], best[2], notes


def _flow_pieces(periods, tag, field):
    """FY, current YTD, current quarter and prior-year YTD pieces for one tag."""
    annual = {k: v for k, v in periods.items() if _is_annual(k, v[0])}
    fy_key = max(annual, key=lambda k: k[1])
    fy = _piece(*annual[fy_key], fy_key, tag, "FY", field)
    later = {k: v for k, v in periods.items() if k[1] > fy_key[1] and v[0]["form"].startswith("10-Q")}
    ytd = qtr = prior = None
    if later:
        end = max(k[1] for k in later)
        same_end = {k: v for k, v in later.items() if k[1] == end}
        ytd_keys = [k for k in same_end if _days(k) <= 290]
        if ytd_keys:
            k = max(ytd_keys, key=_days)
            ytd = _piece(same_end[k][0], same_end[k][1], k, tag, "YTD", field)
            qk = [q for q in same_end if _days(q) <= 100]
            if qk:
                q = max(qk, key=_days)
                qtr = _piece(same_end[q][0], same_end[q][1], q, tag, "quarter", field)
            target_end = _year_back(end)
            cands = [(abs((_d(p[1]) - target_end).days), p) for p in periods
                     if abs(_days(p) - _days(k)) <= 7 and abs((_d(p[1]) - target_end).days) <= 10
                     and periods[p][0]["form"].startswith("10-Q")]
            if cands:
                p = min(cands)[1]
                prior = _piece(periods[p][0], periods[p][1], p, tag, "YTD", field)
    return fy, ytd, qtr, prior


def _sv(field, value, ptype, p, ref, notes, start=""):
    row = p["row"]
    return SourcedValue(field=field, value=value, unit=FIELDS[field][0], period_type=ptype,
                        period_end=p["key"][1], source_kind=XBRL, source_ref=ref,
                        period_start=start or p["key"][0], form=row["form"], filed=row.get("filed", ""),
                        notes=list(notes))


def _latest_10q_end(facts, after, ns="us-gaap"):
    """Latest period end among any tag's 10-Q rows after a date, or '' when there is none."""
    best = ""
    for tag in facts.get("facts", {}).get(ns, {}).values():
        for rows in tag.get("units", {}).values():
            for r in rows:
                if r.get("form") in ("10-Q", "10-Q/A") and r.get("end", "") > max(after, best):
                    best = r["end"]
    return best


def _flow_values(facts, field, tags):
    unit = FIELDS[field][0]
    tag, periods, tag_notes = _best_flow_tag(facts, tags, unit, field)
    if tag is None:
        return []
    fy, ytd, qtr, prior = _flow_pieces(periods, tag, field)
    for p in (fy, ytd, qtr, prior):
        if p:
            p["notes"] = p["notes"] + tag_notes
    out = [_sv(field, fy["val"], FY, fy, fy["ref"], fy["notes"])]
    if ytd:
        out.append(_sv(field, ytd["val"], YTD, ytd, ytd["ref"], ytd["notes"]))
    if qtr:
        out.append(_sv(field, qtr["val"], QTR, qtr, qtr["ref"], qtr["notes"]))
    if field in NOT_ADDITIVE:
        return out
    if ytd is None:
        later = _latest_10q_end(facts, fy["key"][1])
        if later:
            msg = (f"LTM = {fy['ref']} (fiscal year only: a 10-Q for the period ending {later} exists in the facts "
                   f"but does not report this tag as year to date)")
        else:
            msg = f"LTM = {fy['ref']} (latest period is the fiscal year; no later 10-Q in the facts)"
        sv = _sv(field, fy["val"], LTM, fy, msg, fy["notes"], fy["key"][0])
        if later:
            sv.flag(f"LTM is only the fiscal year ending {fy['key'][1]}; a later 10-Q (period ending {later}) exists "
                    "but does not report this tag, so the figure may be stale")
        out.append(sv)
    elif prior:
        val = round(fy["val"] + ytd["val"] - prior["val"], 6)
        ref = f"LTM to {ytd['key'][1]} = {fy['ref']} + {ytd['ref']} - {prior['ref']}"
        notes = fy["notes"] + ytd["notes"] + prior["notes"]
        if field == "diluted_eps":
            notes.append("sum of reported per-share amounts; approximate")
        out.append(_sv(field, val, LTM, ytd, ref, notes, prior["key"][1]))
    else:
        out[0].flag(f"year to date to {ytd['key'][1]} exists but there is no prior-year year to date, so no LTM "
                    "could be built; the fiscal year figure is used instead and may be stale")
    return out


# ---- balance sheet -------------------------------------------------------------------------------

def _instant_pick(facts, tags, unit, ns="us-gaap"):
    """(tag, key, (row, first)) for the tag with the latest balance date."""
    best = None
    for tag in tags:
        periods = _rows(facts, tag, unit, ns)
        if periods:
            key = max(periods, key=lambda k: k[1])
            if best is None or key[1] > best[1][1]:
                best = (tag, key, periods[key])
    return best


def _instant_sv(field, tag, key, pair, notes=(), ref=None):
    row, first = pair
    p = _piece(row, first, key, tag, "instant", field)
    label = _label(row, first, key, "instant")
    return SourcedValue(field=field, value=row["val"], unit=FIELDS[field][0], period_type=INSTANT,
                        period_end=key[1], source_kind=XBRL, source_ref=ref or f"{label} accn {row['accn']} tag {tag}",
                        form=row["form"], filed=row.get("filed", ""), notes=p["notes"] + list(notes))


def _debt_value(facts):
    """Total debt = noncurrent debt + current debt, all at the noncurrent piece's balance date."""
    nc = _instant_pick(facts, DEBT_NONCURRENT, "USD")
    if nc is None:
        return None
    tag, key, pair = nc
    end = key[1]
    parts = [("noncurrent", _piece(*pair, key, tag, "instant", "debt"))]
    cur = _instant_pick(facts, DEBT_CURRENT_TOTAL, "USD")
    if cur and cur[1][1] == end:
        parts.append(("current", _piece(*cur[2], cur[1], cur[0], "instant", "debt")))
    else:
        for group in DEBT_CURRENT_PARTS:
            hit = _instant_pick(facts, group, "USD")
            if hit and hit[1][1] == end:
                parts.append(("current", _piece(*hit[2], hit[1], hit[0], "instant", "debt")))
    only_noncurrent = len(parts) == 1
    total = sum(p["val"] for _, p in parts)
    row = pair[0]
    ref = " + ".join(f"{p['ref']}" for _, p in parts)
    notes = ["debt = " + " + ".join(p["tag"] for _, p in parts)
             + "; may include finance lease obligations; excludes operating leases"]
    sv = SourcedValue(field="debt", value=total, unit="USD", period_type=INSTANT, period_end=end,
                      source_kind=XBRL, source_ref=ref, form=row["form"], filed=row.get("filed", ""),
                      notes=notes)
    if only_noncurrent:
        sv.flag(f"only noncurrent debt found at {end}; no current portion tagged for that date, so total debt "
                "may be understated")
    return sv


def _instant_values(facts):
    out = []
    for field, tags in INSTANT_TAGS.items():
        unit = FIELDS[field][0]
        hit = _instant_pick(facts, tags, unit)
        if hit:
            out.append(_instant_sv(field, *hit))
        elif field == "shares_outstanding":
            dei = _instant_pick(facts, ["EntityCommonStockSharesOutstanding"], unit, "dei")
            if dei:
                out.append(_instant_sv(field, *dei, notes=["cover page share count (dei), dated after the balance sheet"]))
    debt = _debt_value(facts)
    if debt:
        out.append(debt)
    return out


def _flag_stale_tags(values):
    """Flag values whose tag stopped being reported long before the newest period (company changed tags)."""
    newest = max((v.period_end for v in values), default="")
    for v in values:
        if newest and (_d(newest) - _d(v.period_end)).days > STALE_TAG_DAYS:
            v.flag(f"tag last reported for period ending {v.period_end}, over a year before {newest}; "
                   "the company may use a different tag now")
    return values


def extract(facts):
    """Every FIELDS entry the companyfacts JSON can supply, as a list of SourcedValue."""
    out = []
    for field, tags in FLOW_TAGS.items():
        out.extend(_flow_values(facts, field, tags))
    out.extend(_instant_values(facts))
    return _flag_stale_tags(out)
